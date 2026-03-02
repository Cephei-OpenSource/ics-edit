#!/usr/bin/env python3

import argparse
import csv
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone as utc_timezone
from pathlib import Path

from dateutil.rrule import rrulestr
from icalendar import Calendar
from pytz import UnknownTimeZoneError, timezone

DEFAULT_TIMEZONE = "Europe/Berlin"

REASON_REMOVED_SINGLE_ENDED_BEFORE_CUTOFF = "removed_single_ended_before_cutoff"
REASON_REMOVED_FINITE_RECURRENCE_ENDED_BEFORE_CUTOFF = (
    "removed_finite_recurrence_ended_before_cutoff"
)
REASON_KEPT_END_ON_OR_AFTER_CUTOFF = "kept_end_on_or_after_cutoff"
REASON_KEPT_MISSING_END = "kept_missing_end"
REASON_KEPT_OPEN_RECURRENCE = "kept_open_recurrence"
REASON_KEPT_MALFORMED = "kept_malformed"


def to_aware_datetime(value, fallback_tz):
    if isinstance(value, datetime):
        return fallback_tz.localize(value) if value.tzinfo is None else value

    if isinstance(value, date):
        return fallback_tz.localize(datetime.combine(value, datetime.min.time()))

    raise ValueError(f"Unsupported date value type: {type(value).__name__}")


def canonical_datetime(value):
    return value.astimezone(utc_timezone.utc)


def event_uid(component):
    uid = component.get("UID")
    return str(uid) if uid is not None else "<missing UID>"


def warn_event(component, message):
    sys.stderr.write(f"warning: VEVENT {event_uid(component)}: {message}\n")


def get_event_start(component, fallback_tz):
    dtstart_property = component.get("DTSTART")
    if dtstart_property is None:
        raise ValueError("Missing DTSTART")

    return to_aware_datetime(dtstart_property.dt, fallback_tz)


def get_event_duration(component, event_start, fallback_tz):
    duration_property = component.get("DURATION")
    if duration_property is not None:
        duration = duration_property.dt
        if not isinstance(duration, timedelta):
            raise ValueError("Unsupported DURATION value")
        if duration < timedelta(0):
            raise ValueError("DURATION must not be negative")
        return duration

    dtend_property = component.get("DTEND")
    if dtend_property is None:
        return None

    event_end = to_aware_datetime(dtend_property.dt, fallback_tz)
    duration = event_end - event_start
    if duration < timedelta(0):
        raise ValueError("DTEND is before DTSTART")
    return duration


def parse_rrule(rrule_component, event_start):
    rrule_string = str(rrule_component.to_ical(), "utf-8")

    try:
        return rrulestr(rrule_string, dtstart=event_start)
    except ValueError as exc:
        message = str(exc)
        if "UNTIL values must be specified in UTC when DTSTART is timezone-aware" not in message:
            raise

        # Fallback for non-compliant ICS input where DTSTART is timezone-aware
        # but UNTIL is not expressed in UTC.
        naive_start = event_start.replace(tzinfo=None)
        return rrulestr(rrule_string, dtstart=naive_start)


def iter_property_datetimes(component, property_name, fallback_tz):
    properties = component.get(property_name)
    if properties is None:
        return

    if not isinstance(properties, list):
        properties = [properties]

    for prop in properties:
        if hasattr(prop, "dts"):
            for entry in prop.dts:
                yield to_aware_datetime(entry.dt, fallback_tz)
        elif hasattr(prop, "dt"):
            yield to_aware_datetime(prop.dt, fallback_tz)


def get_last_occurrence_start(component, event_start, fallback_tz):
    rrule_component = component.get("RRULE")
    if rrule_component is None:
        return None

    has_until = "UNTIL" in rrule_component
    has_count = "COUNT" in rrule_component
    if not (has_until or has_count):
        return None

    rule = parse_rrule(rrule_component, event_start)

    try:
        last_occurrence = rule[-1]
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not determine last recurrence: {exc}") from exc

    if last_occurrence is not None:
        last_occurrence = to_aware_datetime(last_occurrence, fallback_tz)

    excluded = {
        canonical_datetime(value)
        for value in iter_property_datetimes(component, "EXDATE", fallback_tz)
    }

    while last_occurrence is not None and canonical_datetime(last_occurrence) in excluded:
        try:
            previous = rule.before(last_occurrence, inc=False)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"Could not walk recurrence backwards after EXDATE: {exc}"
            ) from exc
        if previous is None:
            last_occurrence = None
        else:
            last_occurrence = to_aware_datetime(previous, fallback_tz)

    rdates = [
        value
        for value in iter_property_datetimes(component, "RDATE", fallback_tz)
        if canonical_datetime(value) not in excluded
    ]

    if rdates:
        latest_rdate = max(rdates, key=canonical_datetime)
        if last_occurrence is None or canonical_datetime(latest_rdate) > canonical_datetime(
            last_occurrence
        ):
            last_occurrence = latest_rdate

    return last_occurrence


def classify_event(component, cutoff_date, comparison_tz):
    event_start = get_event_start(component, comparison_tz)
    duration = get_event_duration(component, event_start, comparison_tz)

    # Per project rule: events without DTEND/DURATION are never deleted.
    if duration is None:
        return False, REASON_KEPT_MISSING_END

    rrule_component = component.get("RRULE")
    if rrule_component is not None and (
        "UNTIL" not in rrule_component and "COUNT" not in rrule_component
    ):
        return False, REASON_KEPT_OPEN_RECURRENCE

    last_occurrence_start = get_last_occurrence_start(component, event_start, comparison_tz)
    if last_occurrence_start is None:
        event_end = event_start + duration
        if event_end.astimezone(comparison_tz) < cutoff_date:
            return True, REASON_REMOVED_SINGLE_ENDED_BEFORE_CUTOFF
        return False, REASON_KEPT_END_ON_OR_AFTER_CUTOFF

    last_occurrence_end = last_occurrence_start + duration
    if last_occurrence_end.astimezone(comparison_tz) < cutoff_date:
        return True, REASON_REMOVED_FINITE_RECURRENCE_ENDED_BEFORE_CUTOFF

    return False, REASON_KEPT_END_ON_OR_AFTER_CUTOFF


def format_component_datetime(component, property_name):
    value = component.get(property_name)
    if value is None:
        return ""

    if isinstance(value, list):
        parts = []
        for item in value:
            if hasattr(item, "dts"):
                parts.extend(str(entry.dt) for entry in item.dts)
            elif hasattr(item, "dt"):
                parts.append(str(item.dt))
            else:
                parts.append(str(item))
        return "; ".join(parts)

    if hasattr(value, "dts"):
        return "; ".join(str(entry.dt) for entry in value.dts)
    if hasattr(value, "dt"):
        return str(value.dt)
    return str(value)


def deleted_event_record(component, reason):
    rrule = component.get("RRULE")
    if rrule is None:
        rrule_value = ""
    else:
        rrule_value = str(rrule.to_ical(), "utf-8")

    recurrence_id = component.get("RECURRENCE-ID")
    recurrence_id_value = ""
    if recurrence_id is not None:
        recurrence_id_value = str(getattr(recurrence_id, "dt", recurrence_id))

    duration_property = component.get("DURATION")
    duration_value = ""
    if duration_property is not None:
        duration_value = str(duration_property.dt)

    summary = component.get("SUMMARY")

    return {
        "uid": event_uid(component),
        "recurrence_id": recurrence_id_value,
        "dtstart": format_component_datetime(component, "DTSTART"),
        "dtend": format_component_datetime(component, "DTEND"),
        "duration": duration_value,
        "rrule": rrule_value,
        "reason": reason,
        "summary": "" if summary is None else str(summary),
    }


def write_deleted_log(log_path, rows):
    with open(log_path, "w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "uid",
                "recurrence_id",
                "dtstart",
                "dtend",
                "duration",
                "rrule",
                "reason",
                "summary",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def print_stats(stats):
    sys.stderr.write("Processing stats:\n")
    sys.stderr.write(f"  VEVENT processed: {stats['total_vevents']}\n")
    sys.stderr.write(f"  VEVENT kept:      {stats['kept_total']}\n")
    sys.stderr.write(f"  VEVENT removed:   {stats['removed_total']}\n")
    sys.stderr.write("  Reasons:\n")
    for reason in sorted(stats["reason_counts"]):
        count = stats["reason_counts"][reason]
        sys.stderr.write(f"    {reason}: {count}\n")


def build_clean_calendar(cal, cutoff_date, comparison_tz):
    new_cal = Calendar()

    # Preserve calendar metadata (PRODID, VERSION, X-WR-*).
    for prop, val in cal.items():
        new_cal.add(prop, val)

    reason_counts = Counter()
    deleted_rows = []
    total_vevents = 0
    kept_total = 0
    removed_total = 0

    for component in cal.subcomponents:
        if component.name != "VEVENT":
            new_cal.add_component(component)
            continue

        total_vevents += 1
        try:
            should_delete, reason = classify_event(component, cutoff_date, comparison_tz)
        except Exception as exc:  # noqa: BLE001
            reason = REASON_KEPT_MALFORMED
            should_delete = False
            warn_event(component, f"{exc}. Keeping event unchanged.")

        reason_counts[reason] += 1

        if should_delete:
            removed_total += 1
            deleted_rows.append(deleted_event_record(component, reason))
            continue

        kept_total += 1
        new_cal.add_component(component)

    stats = {
        "total_vevents": total_vevents,
        "kept_total": kept_total,
        "removed_total": removed_total,
        "reason_counts": reason_counts,
    }
    return new_cal, stats, deleted_rows


def write_calendar_bytes(data, output_target):
    if output_target == sys.stdout:
        sys.stdout.buffer.write(data)
        return

    with open(output_target, "wb") as file_handle:
        file_handle.write(data)


def backup_file(input_path, backup_suffix):
    backup_path = Path(f"{input_path}{backup_suffix}")
    if backup_path.exists():
        index = 1
        while True:
            candidate = Path(f"{input_path}{backup_suffix}.{index}")
            if not candidate.exists():
                backup_path = candidate
                break
            index += 1

    shutil.copy2(input_path, backup_path)
    return str(backup_path)


def write_file_atomic(path, data):
    directory = os.path.dirname(path) or "."
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=directory, prefix=".ics-edit-", delete=False
        ) as temp_file:
            temp_file.write(data)
            temp_path = temp_file.name

        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def remove_old_events(
    ics_file_path,
    cutoff_date,
    output_file_path,
    timezone_name,
    dry_run=False,
    deleted_log_path=None,
):
    with open(ics_file_path, "r", encoding="utf-8") as file_handle:
        cal = Calendar.from_ical(file_handle.read())

    comparison_tz = timezone(timezone_name)
    cutoff_date = comparison_tz.localize(cutoff_date)

    new_cal, stats, deleted_rows = build_clean_calendar(cal, cutoff_date, comparison_tz)

    if deleted_log_path is not None:
        write_deleted_log(deleted_log_path, deleted_rows)

    if not dry_run:
        calendar_bytes = new_cal.to_ical()
        if output_file_path != sys.stdout and os.path.abspath(output_file_path) == os.path.abspath(
            ics_file_path
        ):
            write_file_atomic(output_file_path, calendar_bytes)
        else:
            write_calendar_bytes(calendar_bytes, output_file_path)

    return stats


def valid_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {value}. Use YYYY-MM-DD format."
        ) from exc


def valid_timezone(value):
    try:
        timezone(value)
    except UnknownTimeZoneError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid timezone: {value}. Use an IANA timezone, for example Europe/Berlin or UTC."
        ) from exc
    return value


def check_file_exists(filename):
    if not os.path.exists(filename):
        raise argparse.ArgumentTypeError(f"The file {filename} does not exist.")
    return filename


class MyParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)


def parse_args():
    cutoff_date_default = datetime(datetime.now().year, 1, 1)

    parser = MyParser(description="Old ICS Calendar Entries Cleaner")
    parser.add_argument(
        "input_filename", type=check_file_exists, help="The ICS input filename"
    )
    parser.add_argument(
        "-d",
        "--date",
        type=valid_date,
        default=cutoff_date_default,
        help=(
            "Start date for cleaning (format: YYYY-MM-DD). "
            f"Default: {cutoff_date_default.strftime('%Y-%m-%d')}"
        ),
    )
    parser.add_argument(
        "-t",
        "--timezone",
        type=valid_timezone,
        default=DEFAULT_TIMEZONE,
        help=f"Timezone used for date comparisons (default: {DEFAULT_TIMEZONE})",
    )
    parser.add_argument(
        "-o", "--output", default=sys.stdout, help="Output file name (default: stdout)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only. Do not write cleaned ICS output.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Print keep/remove counts and reason breakdown to stderr.",
    )
    parser.add_argument(
        "--deleted-log",
        help="Write deleted VEVENT entries to a TSV file.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file with the cleaned calendar.",
    )
    parser.add_argument(
        "--backup-suffix",
        default=".bak",
        help="Backup suffix used with --in-place (default: .bak).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Disable backup file creation when using --in-place.",
    )

    args = parser.parse_args()

    if args.in_place and args.output != sys.stdout:
        parser.error("--in-place cannot be combined with --output")

    if args.in_place and args.dry_run:
        parser.error("--in-place cannot be combined with --dry-run")

    if args.no_backup and not args.in_place:
        parser.error("--no-backup requires --in-place")

    if args.backup_suffix == "" and args.in_place and not args.no_backup:
        parser.error("--backup-suffix must not be empty when backup is enabled")

    return args


def main():
    args = parse_args()

    if args.in_place:
        if not args.no_backup:
            backup_path = backup_file(args.input_filename, args.backup_suffix)
            sys.stderr.write(f"Created backup: {backup_path}\n")

        stats = remove_old_events(
            args.input_filename,
            args.date,
            args.input_filename,
            args.timezone,
            dry_run=False,
            deleted_log_path=args.deleted_log,
        )
    else:
        stats = remove_old_events(
            args.input_filename,
            args.date,
            args.output,
            args.timezone,
            dry_run=args.dry_run,
            deleted_log_path=args.deleted_log,
        )

    if args.stats:
        print_stats(stats)


if __name__ == "__main__":
    main()
