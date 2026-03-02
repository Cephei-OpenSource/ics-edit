#!/usr/bin/env python3

import argparse
import os
import re
import sys
from datetime import datetime

from dateutil.rrule import rrulestr
from icalendar import Calendar
from pytz import UnknownTimeZoneError, timezone

DEFAULT_TIMEZONE = "Europe/Berlin"


def remove_old_events(ics_file_path, cutoff_date, output_file_path, timezone_name):
    with open(ics_file_path, "r", encoding="utf-8") as f:
        cal = Calendar.from_ical(f.read())

    new_cal = Calendar()

    # Preserve calendar metadata (PRODID, VERSION, X-WR-*).
    for prop, val in cal.items():
        new_cal.add(prop, val)

    tz = timezone(timezone_name)
    cutoff_date = tz.localize(cutoff_date)

    for component in cal.walk():
        if component.name == "VEVENT":
            event_date = component.get("DTSTART").dt

            if isinstance(event_date, datetime) and event_date.tzinfo is not None:
                event_date = event_date.astimezone(tz)
            elif isinstance(event_date, datetime):
                event_date = tz.localize(event_date)
            else:
                event_date = datetime.combine(event_date, datetime.min.time())
                event_date = tz.localize(event_date)

            rrule_component = component.get("RRULE")
            if rrule_component is not None:
                rrule_str = str(rrule_component.to_ical(), "utf-8")

                # Ensure UNTIL in RRULE is timezone-aware for correct parsing.
                def fix_until_tz(match):
                    until_val = match.group(1)
                    if not until_val.endswith("Z"):
                        if len(until_val) == 8:
                            until_val = until_val + "T000000Z"
                        else:
                            until_val = until_val + "Z"
                    return "UNTIL=" + until_val

                rrule_str = re.sub(r"UNTIL=([^;\s]+)", fix_until_tz, rrule_str)
                rrule = rrulestr(rrule_str, dtstart=event_date)

                has_until = "UNTIL" in rrule_component
                has_count = "COUNT" in rrule_component
                last_occurrence = None

                if has_until:
                    last_occurrence = rrule[-1]
                elif has_count:
                    occurrences = list(rrule)
                    last_occurrence = occurrences[-1] if occurrences else None

                if (has_until or has_count) and (last_occurrence < cutoff_date):
                    continue
            else:
                if event_date < cutoff_date:
                    continue

            new_cal.add_component(component)
        elif component.name in ["VTODO", "VTIMEZONE", "VJOURNAL"]:
            new_cal.add_component(component)

    if output_file_path == sys.stdout:
        sys.stdout.buffer.write(new_cal.to_ical())
    else:
        with open(output_file_path, "wb") as f:
            f.write(new_cal.to_ical())


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


if __name__ == "__main__":
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
    parser.add_argument("-o", "--output", default=sys.stdout, help="Output file name (default: stdout)")
    args = parser.parse_args()

    remove_old_events(args.input_filename, args.date, args.output, args.timezone)
