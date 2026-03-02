#!/usr/bin/env python3

# Erfordert diese beiden Nicht-Standard-Bibliotheken
# pip install pytz
# pip install icalendar
# pip install python-dateutil

# usage: remove-old-ics-entries.py [-h] [-d DATE] [-o OUTPUT] input_filename
#
# Old ICS Calendar Entries Cleaner
#
# positional arguments:
#  input_filename        The ICS input filename
#
# options:
#  -h, --help            show this help message and exit
#  -d DATE, --date DATE  Start date for cleaning (format: YYYY-MM-DD). Default:
#                        {lfd.Jahr}-01-01
#  -o OUTPUT, --output OUTPUT
#                        Output file name (default: stdout)

import argparse, sys, os
from icalendar import Calendar
from datetime import datetime
from pytz import timezone
from dateutil.rrule import rrulestr
import re

def remove_old_events(ics_file_path, cutoff_date, output_file_path):
    # Lade den Kalender aus der ICS-Datei
    with open(ics_file_path, 'r', encoding='utf-8') as f:
        cal = Calendar.from_ical(f.read())

    # Neuer Kalender ohne die alten Events
    new_cal = Calendar()

    # Kalender-Metadaten (PRODID, VERSION, X-WR-*) vom Original übernehmen
    for prop, val in cal.items():
        new_cal.add(prop, val)

    # Konvertiere cutoff_date zu einer "aware" datetime mit Zeitzoneninformation
    tz = timezone('Europe/Berlin')
    cutoff_date = tz.localize(cutoff_date)

    for component in cal.walk():
        if component.name == "VEVENT":
            event_date = component.get('DTSTART').dt

            # Prüfen, ob das Datum eine Zeitzone hat, und angleichen
            if isinstance(event_date, datetime) and event_date.tzinfo is not None:
                event_date = event_date.astimezone(tz)
            elif isinstance(event_date, datetime):
                event_date = tz.localize(event_date)
            else:
                event_date = datetime.combine(event_date, datetime.min.time())
                event_date = tz.localize(event_date)

            # Prüfen, ob das Event wiederkehrend ist
            rrule_component = component.get('RRULE')
            if rrule_component is not None:
                # Extrahiere die RRULE und berechne die Wiederholungen
                rrule_str = str(rrule_component.to_ical(), 'utf-8')
                if isinstance(event_date, datetime) and event_date.tzinfo is not None:
                    def fix_until_tz(match):
                        until_val = match.group(1)
                        if not until_val.endswith('Z'):
                            if len(until_val) == 8:
                                # Reines Datum wie 20231231 -> 20231231T000000Z
                                until_val = until_val + 'T000000Z'
                            else:
                                # Datetime ohne Z -> Z anhängen
                                until_val = until_val + 'Z'
                        return 'UNTIL=' + until_val
                    rrule_str = re.sub(r'UNTIL=([^;\s]+)', fix_until_tz, rrule_str)
                rrule = rrulestr(rrule_str, dtstart=event_date)

                # Überprüfe das Enddatum (UNTIL) oder berechne das letzte Vorkommen basierend auf COUNT
                has_until = 'UNTIL' in rrule_component
                has_count = 'COUNT' in rrule_component
                last_occurrence = None

                if has_until:
                    # Berechne das letzte Vorkommen, wenn UNTIL vorhanden ist
                    last_occurrence = rrule[-1]
                elif has_count:
                    # Berechne das letzte Vorkommen basierend auf COUNT
                    occurrences = list(rrule)
                    last_occurrence = occurrences[-1] if occurrences else None

                # Bedingungen für das Nicht-Übernehmen der Serie
                if (has_until or has_count) and (last_occurrence < cutoff_date):
                    continue  # Wenn die Serie ein Enddatum hat und dieses vor cutoff_date liegt, überspringen wir sie
            else:
                # Einzelereignisse, die vor dem cutoff_date liegen, überspringen
                if event_date < cutoff_date:
                    continue

            # Füge das Event zum neuen Kalender hinzu
            new_cal.add_component(component)
        elif component.name in ["VTODO", "VTIMEZONE", "VJOURNAL"]:
            # Füge andere Komponenten ohne Änderung hinzu
            new_cal.add_component(component)

    if output_file_path == sys.stdout:
        sys.stdout.buffer.write(new_cal.to_ical())  # Schreibe binär auf stdout
    else:
        with open(output_file_path, 'wb') as f:
            f.write(new_cal.to_ical())

def valid_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {s}. Use YYYY-MM-DD format.")

def check_file_exists(filename):
    if not os.path.exists(filename):
        raise argparse.ArgumentTypeError(f"The file {filename} does not exist.")
    return filename

# Eine benutzerdefinierte Fehlerklasse, die bei fehlenden Argumenten die Usage ausgibt
class MyParser(argparse.ArgumentParser):
    def error(self, message):
        sys.stderr.write(f"error: {message}\n")
        self.print_help()
        sys.exit(2)

if __name__ == "__main__":
    cutoff_date_default = datetime(datetime.now().year, 1, 1)

    parser = MyParser(description='Old ICS Calendar Entries Cleaner')
    parser.add_argument('input_filename', type=check_file_exists, help='The ICS input filename')  # Verpflichtendes Argument
    parser.add_argument('-d', '--date', type=valid_date, default=cutoff_date_default,
                        help=f'Start date for cleaning (format: YYYY-MM-DD). Default: {cutoff_date_default.strftime("%Y-%m-%d")}')
    parser.add_argument('-o', '--output', default=sys.stdout, help='Output file name (default: stdout)')
    args = parser.parse_args()

    input_filename = args.input_filename
    cutoff_date = args.date
    output_filename = args.output

    remove_old_events(input_filename, cutoff_date, output_filename)
