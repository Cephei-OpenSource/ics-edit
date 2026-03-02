# ICS-Edit

`ICS-Edit` currently consists of only `remove-old-ics-entries.py`.

The script removes expired calendar entries in an ICS file. Entries are deleted only if they, and possible repetitions, end before a cutoff date passed on the command line (default: beginning of the current year). An entry without an end limit is never deleted.

## Features

- Removes single events before a cutoff date.
- Removes recurring events only when the series has a clear end (`UNTIL` or `COUNT`) and the last occurrence is before cutoff.
- Keeps recurring events without `UNTIL`/`COUNT`.
- Preserves calendar metadata and non-event components (`VTODO`, `VTIMEZONE`, `VJOURNAL`).
- Writes to stdout by default or to an output file.

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
python3 remove-old-ics-entries.py [-h] [-d DATE] [-o OUTPUT] input_filename
```

Arguments:

- `input_filename`: path to input ICS file (required)
- `-d, --date`: cutoff date in format `YYYY-MM-DD`
  - default: `<current-year>-01-01`
- `-o, --output`: output filename
  - default: stdout

## Examples

Write result to a file:

```bash
python3 remove-old-ics-entries.py -d 2025-01-01 -o cleaned.ics calendar.ics
```

Write result to stdout:

```bash
python3 remove-old-ics-entries.py -d 2024-01-01 calendar.ics > cleaned.ics
```

## Current Behavior Notes

- For non-recurring events, the script compares `DTSTART` with the cutoff date.
- For recurring events:
  - with `UNTIL`: deletes if the last computed occurrence is before cutoff.
  - with `COUNT`: deletes if the last computed occurrence is before cutoff.
  - without `UNTIL` and without `COUNT`: kept.
- Dates are evaluated in timezone `Europe/Berlin`.

## Limitations

- The deletion logic is based on event start times and series boundaries, not explicit `DTEND` duration checks.
- Very complex recurrence rules may require additional validation with real data.

## License

No license file is included yet. If you plan to publish publicly, add a `LICENSE` file.
