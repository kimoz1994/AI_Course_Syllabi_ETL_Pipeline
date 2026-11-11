"""Unit tests at the validation boundary: normalize-then-assert (v1 flow).

``validate_dataset`` consumes the intake's records + extraction log (plain
dicts, no PDFs needed) and returns the report, the normalized records that
will be written, and the updated log.
"""

import unittest
from pathlib import Path

from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

REPO = Path(__file__).resolve().parents[1]


def _fields(**overrides):
    """A known-good 14-field dict (all fields present, contract-valid)."""
    fields = {
        "country": "Narnia",
        "institution": "Mock University",
        "year": "2023-09-01",
        "course_level": "Undergraduate",
        "target_audience": "engineering students",
        "course_title": "Introduction to Artificial Intelligence",
        "prerequisites": "Basic programming",
        "course_description": "An overview of AI.",
        "course_topics": ["Search", "Machine learning", "Ethics"],
        "course_outcomes": ["Apply search algorithms"],
        "tools": ["Python"],
        "textbooks": ["AIMA 4th ed."],
        "teaching_method": ["Lecture based learning"],
        "assessment_methods": ["Short Quizzes", "Final Exam"],
    }
    fields.update(overrides)
    return fields


def _dataset(n=2, **overrides):
    """n records + a matching extraction log (one 'ok' entry per record)."""
    records, log_records = [], []
    for i in range(1, n + 1):
        sid = f"S{i:03d}"
        records.append(
            {
                "syllabus_id": sid,
                "source_file": f"{sid.lower()}_syllabus.pdf",
                "content_hash": f"hash{i}",
                **_fields(**overrides),
            }
        )
        log_records.append(
            {
                "syllabus_id": sid,
                "source_file": f"{sid.lower()}_syllabus.pdf",
                "content_hash": f"hash{i}",
                "status": "ok",
                "warnings": [],
                "issues": [],
            }
        )
    log = {
        "input_folder": "pdfs",
        "files_seen": n,
        "distinct_files": n,
        "dropped_duplicates": [],
        "records": log_records,
    }
    return records, log


class FailModelTests(unittest.TestCase):
    """Failing checks: file-count gate + contract violations."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_clean_dataset_passes_with_no_failures(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset()
        report, out_records, out_log = validate_dataset(records, log, self.contract)
        self.assertEqual(report["overall"], "pass")
        self.assertEqual(
            [c["status"] for c in report["checks"] if c["status"] == "fail"], []
        )
        # The records that will be written are the ones that were asserted.
        self.assertEqual(out_records, records)

    def test_file_count_mismatch_fails_the_run(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(n=2)
        log["distinct_files"] = 3  # one distinct-hash file produced no record
        report, _, _ = validate_dataset(records, log, self.contract)
        gate = next(c for c in report["checks"] if c["name"] == "file_count_gate")
        self.assertEqual(gate["status"], "fail")
        self.assertEqual(report["overall"], "fail")
        self.assertIn("3", gate["detail"])
        self.assertIn("2", gate["detail"])

    def test_unmappable_vocabulary_value_fails_and_names_file_field_value(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(course_level="Narnian")
        report, _, _ = validate_dataset(records, log, self.contract)
        check = next(
            c for c in report["checks"] if c["name"] == "unmappable_vocabulary_values"
        )
        self.assertEqual(check["status"], "fail")
        self.assertEqual(report["overall"], "fail")
        self.assertIn("s001_syllabus.pdf", check["detail"])
        self.assertIn("course_level", check["detail"])
        self.assertIn("Narnian", check["detail"])

    def test_structural_violation_fails_the_run(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(course_topics="Search, ML")  # not an array
        report, _, _ = validate_dataset(records, log, self.contract)
        check = next(c for c in report["checks"] if c["name"] == "record_contract")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(report["overall"], "fail")
        self.assertIn("course_topics", check["detail"])


class WarnModelTests(unittest.TestCase):
    """Warnings never fail the run; the report carries the metrics."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_scan_record_warns_without_failing(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(n=1)
        records[0] = {
            "syllabus_id": "S001",
            "source_file": "s001_syllabus.pdf",
            "content_hash": "hash1",
            **{col: None for col in records[0] if col not in
               ("syllabus_id", "source_file", "content_hash")},
        }
        log["records"][0]["status"] = "scan"
        log["records"][0]["warnings"] = ["no text layer (image-only scan?) - all-null record"]
        report, _, _ = validate_dataset(records, log, self.contract)
        check = next(c for c in report["checks"] if c["name"] == "scan_or_failed_records")
        self.assertEqual(check["status"], "warn")
        self.assertIn("scan", check["detail"])
        self.assertEqual(report["overall"], "warn")  # warn, not fail

    def test_sentinel_like_value_warns_without_failing(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(prerequisites="not mentioned")
        report, _, _ = validate_dataset(records, log, self.contract)
        check = next(c for c in report["checks"] if c["name"] == "sentinel_values")
        self.assertEqual(check["status"], "warn")
        self.assertIn("prerequisites", check["detail"])
        self.assertEqual(report["overall"], "warn")

    def test_entirely_empty_field_warns_and_report_carries_percentages(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(textbooks=None)
        report, _, _ = validate_dataset(records, log, self.contract)
        check = next(c for c in report["checks"] if c["name"] == "completeness")
        self.assertEqual(check["status"], "warn")
        self.assertIn("textbooks", check["detail"])
        self.assertIn("textbooks", report["completeness_pct"])
        self.assertEqual(report["completeness_pct"]["country"], 100.0)
        self.assertEqual(report["overall"], "warn")


class NormalizationAuditTests(unittest.TestCase):
    """Every change the validator makes is logged; normalization is real."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)

    def test_every_log_entry_gains_a_normalizations_list(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset()
        _, _, out_log = validate_dataset(records, log, self.contract)
        for entry in out_log["records"]:
            self.assertEqual(entry["normalizations"], [])

    def test_bare_year_normalizes_to_iso_and_is_logged(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(year="2023")
        report, out_records, out_log = validate_dataset(records, log, self.contract)
        self.assertEqual(out_records[0]["year"], "2023-01-01")
        entry = next(e for e in out_log["records"] if e["syllabus_id"] == "S001")
        self.assertEqual(
            entry["normalizations"],
            [{"field": "year", "from": "2023", "to": "2023-01-01", "rule": "iso_date"}],
        )

    def test_parseable_dates_and_verbatim_passthroughs(self):
        from ai_syllabi_etl.validation import normalize_year

        cases = {
            "2023": "2023-01-01",                      # bare year (manual-export convention)
            "2023-09": "2023-09-01",                   # year-month
            "2023-09-01": "2023-09-01",                # already ISO -> no action
            "9/1/2023": "2023-09-01",                  # US M/D/YYYY
            "September 2023": "2023-09-01",            # month name
            "Sept. 2023": "2023-09-01",                # abbreviated month name
            "September 15, 2023": "2023-09-15",        # month day, year
        }
        for raw, expected in cases.items():
            value, action = normalize_year(raw)
            self.assertEqual(value, expected, msg=raw)
            if raw == expected:
                self.assertIsNone(action, msg=raw)
            else:
                self.assertEqual(action, (raw, expected), msg=raw)

    def test_unparseable_year_stays_verbatim(self):
        from ai_syllabi_etl.validation import normalize_year

        for raw in ("Fall 2024", "2024/2025", "unknown"):
            value, action = normalize_year(raw)
            self.assertEqual((value, action), (raw, None), msg=raw)

    def test_null_year_untouched(self):
        from ai_syllabi_etl.validation import normalize_year

        self.assertEqual(normalize_year(None), (None, None))

    def test_misaligned_or_minimal_log_does_not_crash_and_still_audits(self):
        from ai_syllabi_etl.validation import validate_dataset

        records, log = _dataset(n=2)
        # An entry without syllabus_id, and one record with no entry at all.
        log["records"].append({"status": "ok"})
        records.append(
            {
                "syllabus_id": "S099",
                "source_file": "orphan.pdf",
                "content_hash": "hash99",
                **_fields(),
            }
        )
        log["distinct_files"] = len(records)  # keep the file-count gate out of this
        report, out_records, out_log = validate_dataset(records, log, self.contract)
        self.assertEqual(report["overall"], "pass")
        for entry in out_log["records"]:
            self.assertIn("normalizations", entry)  # audit holds for every entry


if __name__ == "__main__":
    unittest.main()
