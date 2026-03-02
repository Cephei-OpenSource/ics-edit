import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "remove-old-ics-entries.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


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
