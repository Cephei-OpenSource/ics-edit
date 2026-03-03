# ICS-Edit

`ICS-Edit` is centered around `remove-old-ics-entries.py`.

The script removes expired calendar entries in an ICS file. Entries are deleted only if they, and possible repetitions, end before a cutoff date passed on the command line (default: beginning of the current year). An entry without an end limit is never deleted.

## Features

- Removes single events whose end (`DTEND` or `DTSTART + DURATION`) is before a cutoff date.
- Removes recurring events only when the series has a clear end (`UNTIL` or `COUNT`) and the last occurrence end is before cutoff.
- Keeps recurring events without `UNTIL`/`COUNT`.
- Optionally shifts open recurring events to the first occurrence on or after cutoff (`--shift-open-recurrence-starts`).
- Keeps events without end information (`DTEND` and `DURATION` both missing).
- Preserves calendar metadata and non-event components.
- Writes to stdout by default or to an output file.
- Supports `--dry-run` and `--stats` to preview changes safely.
- Supports `--in-place` with automatic backup creation.
- Supports `--deleted-log` to export all deleted entries for manual review.
- Supports `--shifted-log` to export all shifted entries for manual review.
- Supports `--prune-old-exceptions` to remove old `EXDATE` exceptions from kept recurring events.

## Requirements

- Python 3
- Packages:
  - `icalendar`
  - `pytz`
  - `python-dateutil`

Install dependencies:

```bash
pip install icalendar pytz python-dateutil
```

## Usage

```bash
python3 remove-old-ics-entries.py [-h] [-d DATE] [-t TIMEZONE] [-o OUTPUT] [--dry-run] [--stats] [--deleted-log FILE] [--shifted-log FILE] [--shift-open-recurrence-starts] [--prune-old-exceptions] [--in-place] [--backup-suffix SUFFIX] [--no-backup] input_filename
```

Arguments:

- `input_filename`: path to input ICS file (required)
- `-d, --date`: cutoff date in format `YYYY-MM-DD`
  - default: `<current-year>-01-01`
- `-t, --timezone`: timezone for date comparisons (IANA format)
  - default: `Europe/Berlin`
- `-o, --output`: output filename
  - default: stdout
- `--dry-run`: analyze only, do not write cleaned ICS output
- `--stats`: print keep/remove counters and reasons to stderr
- `--deleted-log FILE`: write every deleted `VEVENT` and pruned `EXDATE` exception to a TSV file
- `--shifted-log FILE`: write every shifted `VEVENT` to a TSV file
- `--shift-open-recurrence-starts`: for open recurrences (`RRULE` without `UNTIL`/`COUNT`), move `DTSTART`/`DTEND` to first occurrence on or after cutoff
  - why this matters: open recurrences can run for many years with a short ICS representation, but calendar apps still need to evaluate all past virtual occurrences when building recurrence trees. This can make sync/update operations slow because recurrence expansion is often re-run after every calendar change.
  - practical effect: shifting the start to the cutoff removes historical recurrence expansion work while keeping future behavior, which can produce very large performance gains in some calendar clients.
  - safe usage: use when you do not need historical instances before cutoff in the target ICS anymore.
- `--prune-old-exceptions`: remove `EXDATE` values before cutoff from kept recurring events
  - this only changes kept recurring events and only removes exception dates that are already in the past relative to cutoff.
  - useful together with `--shift-open-recurrence-starts` to reduce stale exception history and keep recurring event data compact.
- `--in-place`: overwrite input file with cleaned output
- `--backup-suffix SUFFIX`: backup suffix for `--in-place` (default: `.bak`)
- `--no-backup`: disable backup creation when using `--in-place`

## Examples

Write result to a file:

```bash
python3 remove-old-ics-entries.py -d 2025-01-01 -t UTC -o cleaned.ics calendar.ics
```

Write result to stdout:

```bash
python3 remove-old-ics-entries.py -d 2024-01-01 calendar.ics > cleaned.ics
```

Preview only with stats and deleted entries list:

```bash
python3 remove-old-ics-entries.py -d 2025-07-01 --dry-run --stats --deleted-log deleted.tsv calendar.ics
```

Edit file in place and create automatic backup:

```bash
python3 remove-old-ics-entries.py -d 2025-07-01 --in-place calendar.ics
```

## Current Behavior Notes

- For non-recurring events:
  - with `DTEND` or `DURATION`: compares computed end with cutoff.
  - without `DTEND` and without `DURATION`: always kept.
- For recurring events:
  - with `UNTIL` or `COUNT`: deletes if the last occurrence end is before cutoff.
  - without `UNTIL`/`COUNT`: kept.
  - without `UNTIL`/`COUNT` and `--shift-open-recurrence-starts`: kept, but `DTSTART` (and `DTEND` if present) is moved to the first occurrence on or after cutoff.
    - performance note: this can significantly speed up some ICS calendar apps by avoiding expansion of very long past recurrence history after each calendar change.
  - with `--prune-old-exceptions`: old `EXDATE` values before cutoff are removed from kept events.
    - intent: remove historical exception clutter that no longer affects future scheduling.
  - without event duration/end information: kept.
- `EXDATE` and `RDATE` are considered when determining the last finite recurrence occurrence.
- Dates are evaluated in the timezone passed via `--timezone` (default: `Europe/Berlin`).
- Malformed events are kept and reported as warnings on stderr.

## Tests

Run the test suite:

```bash
python3 -m unittest -v tests/test_remove_old_ics_entries.py
```

## Limitations

- Very complex recurrence rules (especially with `EXDATE`/`RDATE`) may require additional validation with real data.

## License

This project is licensed under the Apache License 2.0.
