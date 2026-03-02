import importlib.util
import io
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from datetime import date, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "remove-old-ics-entries.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def load_script_module():
    spec = importlib.util.spec_from_file_location("remove_old_ics_entries", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_MODULE = None
MODULE_LOAD_ERROR = None
try:
    SCRIPT_MODULE = load_script_module()
except ModuleNotFoundError as exc:
    MODULE_LOAD_ERROR = exc


class CoreLogicUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if MODULE_LOAD_ERROR is not None:
            raise unittest.SkipTest(f"Could not import script module: {MODULE_LOAD_ERROR}")

    def setUp(self):
        self.module = SCRIPT_MODULE
        self.utc = self.module.timezone("UTC")
        self.berlin = self.module.timezone("Europe/Berlin")

    def first_vevent(self, ics_text):
        calendar = self.module.Calendar.from_ical(textwrap.dedent(ics_text).strip())
        for component in calendar.subcomponents:
            if component.name == "VEVENT":
                return component
        self.fail("No VEVENT found in test calendar")

    def test_to_aware_datetime_localizes_naive_datetime(self):
        naive_value = datetime(2025, 7, 1, 10, 30)
        aware_value = self.module.to_aware_datetime(naive_value, self.berlin)

        self.assertIsNotNone(aware_value.tzinfo)
        self.assertEqual(aware_value.replace(tzinfo=None), naive_value)

    def test_to_aware_datetime_keeps_aware_datetime_unchanged(self):
        aware_input = self.utc.localize(datetime(2025, 7, 1, 10, 30))
        self.assertIs(self.module.to_aware_datetime(aware_input, self.berlin), aware_input)

    def test_to_aware_datetime_converts_date_to_midnight(self):
        aware_value = self.module.to_aware_datetime(date(2025, 7, 1), self.utc)

        self.assertEqual(aware_value.hour, 0)
        self.assertEqual(aware_value.minute, 0)
        self.assertEqual(aware_value.second, 0)
        self.assertIsNotNone(aware_value.tzinfo)

    def test_parse_rrule_warns_on_until_timezone_mismatch_fallback(self):
        component = self.first_vevent(
            """
            BEGIN:VCALENDAR
            VERSION:2.0
            PRODID:-//ics-edit tests//EN
            BEGIN:VEVENT
            UID:rrule-mismatch@example.com
            DTSTART;TZID=Europe/Berlin:20240601T090000
            DTEND;TZID=Europe/Berlin:20240601T100000
            RRULE:FREQ=DAILY;UNTIL=20240603T090000
            END:VEVENT
            END:VCALENDAR
            """
        )
        event_start = self.module.get_event_start(component, self.berlin)
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            rule = self.module.parse_rrule(component.get("RRULE"), event_start, component)

        self.assertIn(
            "RRULE UNTIL is not UTC while DTSTART is timezone-aware",
            stderr.getvalue(),
        )
        self.assertIsNone(rule[0].tzinfo)
        self.assertIsNone(rule[-1].tzinfo)

    def test_get_last_occurrence_start_uses_count(self):
        component = self.first_vevent(
            """
            BEGIN:VCALENDAR
            VERSION:2.0
            PRODID:-//ics-edit tests//EN
            BEGIN:VEVENT
            UID:count-unit@example.com
            DTSTART:20240601T090000Z
            DTEND:20240601T100000Z
            RRULE:FREQ=DAILY;COUNT=3
            END:VEVENT
            END:VCALENDAR
            """
        )
        event_start = self.module.get_event_start(component, self.utc)

        last_occurrence = self.module.get_last_occurrence_start(component, event_start, self.utc)

        expected = self.utc.localize(datetime(2024, 6, 3, 9, 0))
        self.assertEqual(last_occurrence, expected)

    def test_get_last_occurrence_start_applies_exdate(self):
        component = self.first_vevent(
            """
            BEGIN:VCALENDAR
            VERSION:2.0
            PRODID:-//ics-edit tests//EN
            BEGIN:VEVENT
            UID:exdate-unit@example.com
            DTSTART:20250629T100000Z
            DTEND:20250629T110000Z
            RRULE:FREQ=DAILY;COUNT=3
            EXDATE:20250701T100000Z
            END:VEVENT
            END:VCALENDAR
            """
        )
        event_start = self.module.get_event_start(component, self.utc)

        last_occurrence = self.module.get_last_occurrence_start(component, event_start, self.utc)

        expected = self.utc.localize(datetime(2025, 6, 30, 10, 0))
        self.assertEqual(last_occurrence, expected)

    def test_get_last_occurrence_start_returns_none_for_open_recurrence(self):
        component = self.first_vevent(
            """
            BEGIN:VCALENDAR
            VERSION:2.0
            PRODID:-//ics-edit tests//EN
            BEGIN:VEVENT
            UID:open-recurrence@example.com
            DTSTART:20240601T090000Z
            DTEND:20240601T100000Z
            RRULE:FREQ=DAILY
            END:VEVENT
            END:VCALENDAR
            """
        )
        event_start = self.module.get_event_start(component, self.utc)
        self.assertIsNone(
            self.module.get_last_occurrence_start(component, event_start, self.utc)
        )


class RemoveOldIcsEntriesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ics-edit-tests-")
        self.workdir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def fixture_copy(self, fixture_name, dest_name=None):
        src = FIXTURES / fixture_name
        dest = self.workdir / (dest_name or fixture_name)
        shutil.copy2(src, dest)
        return dest

    def run_script(self, *args):
        cmd = ["python3", str(SCRIPT_PATH), *args]
        return subprocess.run(cmd, capture_output=True, text=True)

    def assert_uid_present(self, path, uid):
        content = path.read_text(encoding="utf-8")
        self.assertIn(uid, content)

    def assert_uid_absent(self, path, uid):
        content = path.read_text(encoding="utf-8")
        self.assertNotIn(uid, content)

    def test_no_dtend_is_kept(self):
        input_file = self.fixture_copy("no-dtend.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_present(output_file, "UID:no-dtend@example.com")

    def test_cross_cutoff_span_is_kept(self):
        input_file = self.fixture_copy("cross-cutoff-span.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_present(output_file, "UID:cross-cutoff@example.com")

    def test_finite_until_recurrence_is_removed(self):
        input_file = self.fixture_copy("until.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_absent(output_file, "UID:until@example.com")

    def test_finite_count_recurrence_is_removed(self):
        input_file = self.fixture_copy("count.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_absent(output_file, "UID:count@example.com")

    def test_exdate_is_considered_for_last_occurrence(self):
        input_file = self.fixture_copy("exdate.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_absent(output_file, "UID:exdate@example.com")

    def test_all_day_event_spanning_cutoff_is_kept(self):
        input_file = self.fixture_copy("all-day.ics")
        output_file = self.workdir / "out.ics"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assert_uid_present(output_file, "UID:all-day@example.com")

    def test_timezone_change_affects_decision(self):
        input_file = self.fixture_copy("timezone-change.ics")
        output_file_utc = self.workdir / "out-utc.ics"
        output_file_lax = self.workdir / "out-lax.ics"

        keep_result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "-o",
            str(output_file_utc),
            str(input_file),
        )
        remove_result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "America/Los_Angeles",
            "-o",
            str(output_file_lax),
            str(input_file),
        )

        self.assertEqual(keep_result.returncode, 0, msg=keep_result.stderr)
        self.assertEqual(remove_result.returncode, 0, msg=remove_result.stderr)
        self.assert_uid_present(output_file_utc, "UID:timezone-change@example.com")
        self.assert_uid_absent(output_file_lax, "UID:timezone-change@example.com")

    def test_dry_run_and_stats_and_deleted_log(self):
        input_file = self.fixture_copy("count.ics")
        original = input_file.read_text(encoding="utf-8")
        deleted_log = self.workdir / "deleted.tsv"

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "--dry-run",
            "--stats",
            "--deleted-log",
            str(deleted_log),
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("Processing stats:", result.stderr)
        self.assertIn("removed_finite_recurrence_ended_before_cutoff", result.stderr)
        self.assertEqual(input_file.read_text(encoding="utf-8"), original)
        log_content = deleted_log.read_text(encoding="utf-8")
        self.assertIn("uid\trecurrence_id\tdtstart", log_content)
        self.assertIn("count@example.com", log_content)

    def test_in_place_creates_backup_and_rewrites_input(self):
        input_file = self.fixture_copy("count.ics", "in-place.ics")

        result = self.run_script(
            "-d",
            "2025-07-01",
            "-t",
            "UTC",
            "--in-place",
            str(input_file),
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        backup = input_file.with_name(input_file.name + ".bak")
        self.assertTrue(backup.exists(), "Expected automatic backup file to exist")
        self.assert_uid_absent(input_file, "UID:count@example.com")
        self.assert_uid_present(backup, "UID:count@example.com")


if __name__ == "__main__":
    unittest.main()
