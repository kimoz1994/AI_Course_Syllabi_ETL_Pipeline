"""End-to-end v1 smoke test: fixture PDF folder -> dataset + extraction log.

Exercises the pipeline seam (CLI ``run``) over four authored fixture PDFs:
two distinct syllabi, one byte-identical duplicate, and one blank-page PDF
with no text layer (a simulated scan).
"""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from ai_syllabi_etl.cli import main
from ai_syllabi_etl.extraction import ExtractionBackend

REPO = Path(__file__).resolve().parents[1]
PDF_DIR = REPO / "tests" / "fixtures" / "pdfs"


def _read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class PdfPipelineSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_pdf_")
        cls.tmp = Path(cls._tmpdir.name)
        cfg_path = cls.tmp / "config.yaml"
        cfg_path.write_text(
            "input: '"
            + str(PDF_DIR).replace("\\", "/")
            + "'\npaths:\n  output: '"
            + str(cls.tmp / "output").replace("\\", "/")
            + "'\nextraction_backend: mock\n",
            encoding="utf-8",
        )
        cls.cfg_path = cfg_path
        cls.exit_code = main(["run", "--config", str(cfg_path)])

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_pipeline_exits_zero(self):
        self.assertEqual(self.exit_code, 0)

    def test_dataset_written_with_contract_columns(self):
        dataset = self.tmp / "output" / "syllabi_dataset.csv"
        self.assertTrue(dataset.is_file())
        rows = _read_csv(dataset)
        header = list(rows[0].keys())
        self.assertEqual(
            header[:4], ["syllabus_id", "source_file", "content_hash", "country"]
        )
        self.assertIn("assessment_methods", header)

    def test_dedup_and_lexicographic_ids(self):
        rows = _read_csv(self.tmp / "output" / "syllabi_dataset.csv")
        self.assertEqual(
            [(r["syllabus_id"], r["source_file"]) for r in rows],
            [
                ("S001", "alpha_syllabus.pdf"),
                ("S002", "bravo_syllabus.pdf"),
                ("S003", "charlie_scan.pdf"),
            ],
        )

    def test_duplicate_dropped_by_content_hash(self):
        rows = _read_csv(self.tmp / "output" / "syllabi_dataset.csv")
        by_id = {r["syllabus_id"]: r for r in rows}
        self.assertEqual(len(rows), 3)  # 4 files in, duplicate collapsed
        self.assertNotEqual(by_id["S001"]["content_hash"], by_id["S002"]["content_hash"])
        self.assertTrue(all(r["content_hash"] for r in rows))

    def test_extracted_record_has_mock_fields(self):
        rows = _read_csv(self.tmp / "output" / "syllabi_dataset.csv")
        alpha = next(r for r in rows if r["syllabus_id"] == "S001")
        self.assertEqual(alpha["course_title"], "Introduction to Artificial Intelligence")
        self.assertEqual(json.loads(alpha["course_topics"]), ["Search", "Machine learning", "Ethics"])

    def test_scan_yields_all_null_record(self):
        rows = _read_csv(self.tmp / "output" / "syllabi_dataset.csv")
        scan = next(r for r in rows if r["syllabus_id"] == "S003")
        form_fields = {k: v for k, v in scan.items() if k not in ("syllabus_id", "source_file", "content_hash")}
        self.assertNotEqual(
            scan["content_hash"], "", "scan must still carry a content hash"
        )
        self.assertEqual(form_fields.get("course_title"), "", "form fields empty, not sentinel words")

    def test_extraction_log_records_dedup_and_scan(self):
        log = json.loads((self.tmp / "output" / "extraction_log.json").read_text(encoding="utf-8"))
        self.assertEqual(log["files_seen"], 4)
        self.assertEqual(log["distinct_files"], 3)
        dropped = [d["file"] for d in log["dropped_duplicates"]]
        self.assertEqual(dropped, ["alpha_syllabus_copy.pdf"])
        scan_entry = next(r for r in log["records"] if r["syllabus_id"] == "S003")
        self.assertEqual(scan_entry["status"], "scan")
        self.assertTrue(scan_entry["warnings"])
        ok_entry = next(r for r in log["records"] if r["syllabus_id"] == "S001")
        self.assertEqual(ok_entry["status"], "ok")


class IntakeSchemaValidationTests(unittest.TestCase):
    """The pipeline seam: backend records are normalized + validated at intake."""

    class _StubBackend(ExtractionBackend):
        name = "stub"

        def __init__(self, fields):
            self._fields = fields

        def extract(self, text, source=None):
            return dict(self._fields)

    def _stub_fields(self, **overrides):
        fields = {
            "country": "Narnia",
            "institution": "Alpha University",
            "year": None,
            "course_level": "undergrad",
            "target_audience": None,
            "course_title": "Introduction to Artificial Intelligence",
            "prerequisites": None,
            "course_description": None,
            "course_topics": ["search", "machine learning"],
            "course_outcomes": None,
            "tools": ["Python"],
            "textbooks": None,
            "teaching_method": ["lecture-based", "Cooperative learning"],
            "assessment_methods": ["quizzes"],
        }
        fields.update(overrides)
        return fields

    def test_records_normalized_and_unmapped_surfaced_in_log(self):
        from ai_syllabi_etl.pdf_intake import intake
        from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        backend = self._StubBackend(self._stub_fields())
        records, log = intake(PDF_DIR, backend, contract)
        alpha = next(r for r in records if r["source_file"] == "alpha_syllabus.pdf")
        self.assertEqual(alpha["course_level"], "Undergraduate")
        self.assertEqual(
            alpha["teaching_method"], ["Lecture based learning", "Cooperative learning"]
        )
        self.assertEqual(
            alpha["assessment_methods"], ["Short Quizzes"]
        )
        entry = next(e for e in log["records"] if e["syllabus_id"] == alpha["syllabus_id"])
        self.assertEqual(
            entry["issues"],
            [{"field": "teaching_method", "issue": "unmapped_value",
              "value": "Cooperative learning"}],
        )

    def test_structurally_invalid_backend_output_raises(self):
        from ai_syllabi_etl.pdf_intake import IntakeError, intake
        from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        backend = self._StubBackend({"course_title": "only one field"})
        with self.assertRaises(IntakeError):
            intake(PDF_DIR, backend, contract)

    def test_clean_stub_record_logs_no_issues(self):
        from ai_syllabi_etl.pdf_intake import intake
        from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        backend = self._StubBackend(self._stub_fields(teaching_method=["Seminar"],
                                                      course_level="Master",
                                                      assessment_methods=["Final Exam"]))
        records, log = intake(PDF_DIR, backend, contract)
        alpha = next(r for r in records if r["source_file"] == "alpha_syllabus.pdf")
        self.assertEqual(alpha["course_level"], "Master")
        entry = next(e for e in log["records"] if e["syllabus_id"] == alpha["syllabus_id"])
        self.assertEqual(entry["issues"], [])

    def test_run_pdf_pipeline_honors_config_schema_contract_path(self):
        """The config's `schema_contract` key must be loaded, not ignored."""
        import tempfile

        from ai_syllabi_etl.pdf_intake import run_pdf_pipeline
        from ai_syllabi_etl.schema import SchemaContractError

        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t2_") as td:
            tmp = Path(td)
            cfg = {
                "input": str(PDF_DIR),
                "paths": {"output": str(tmp / "output")},
                "extraction_backend": "mock",
                "schema_contract": str(tmp / "missing_contract.yaml"),
            }
            with self.assertRaises(SchemaContractError):
                run_pdf_pipeline(cfg)


class ValidationStagePipelineTests(unittest.TestCase):
    """The pipeline seam: the validation stage decides the exit code and
    the file on disk is the normalized, asserted version."""

    class _StubBackend(ExtractionBackend):
        name = "stub"

        def __init__(self, fields):
            self._fields = fields

        def extract(self, text, source=None):
            return dict(self._fields)

    def _stub_fields(self, **overrides):
        fields = {
            "country": "Narnia",
            "institution": "Alpha University",
            "year": "September 2023",
            "course_level": "Undergraduate",
            "target_audience": None,
            "course_title": "Introduction to Artificial Intelligence",
            "prerequisites": None,
            "course_description": None,
            "course_topics": ["Search"],
            "course_outcomes": None,
            "tools": ["Python"],
            "textbooks": None,
            "teaching_method": ["Lecture based learning"],
            "assessment_methods": ["Final Exam"],
        }
        fields.update(overrides)
        return fields

    def _run(self, tmp, fields):
        """Run run_pdf_pipeline with the stub backend at the backend seam."""
        from unittest.mock import patch

        from ai_syllabi_etl import pdf_intake

        backend = self._StubBackend(fields)
        cfg = {
            "input": str(PDF_DIR),
            "paths": {"output": str(tmp / "output")},
            "extraction_backend": "stub",
        }
        with patch.object(pdf_intake, "make_extraction_backend", return_value=backend):
            return pdf_intake.run_pdf_pipeline(cfg)

    def test_unmappable_value_fails_run_but_writes_dataset_and_log(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t3_") as td:
            tmp = Path(td)
            exit_code = self._run(tmp, self._stub_fields(course_level="Narnian"))
            self.assertEqual(exit_code, 1)
            dataset = tmp / "output" / "syllabi_dataset.csv"
            self.assertTrue(dataset.is_file(), "dataset written for audit on fail")
            log = json.loads(
                (tmp / "output" / "extraction_log.json").read_text(encoding="utf-8")
            )
            entry = next(
                e for e in log["records"] if e["source_file"] == "alpha_syllabus.pdf"
            )
            self.assertEqual(
                entry["issues"],
                [{"field": "course_level", "issue": "unmapped_value", "value": "Narnian"}],
            )

    def test_passing_run_writes_iso_normalized_year_and_logged_actions(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t3_") as td:
            tmp = Path(td)
            exit_code = self._run(tmp, self._stub_fields())
            self.assertEqual(exit_code, 0)
            rows = _read_csv(tmp / "output" / "syllabi_dataset.csv")
            alpha = next(r for r in rows if r["source_file"] == "alpha_syllabus.pdf")
            self.assertEqual(alpha["year"], "2023-09-01")
            log = json.loads(
                (tmp / "output" / "extraction_log.json").read_text(encoding="utf-8")
            )
            entry = next(
                e for e in log["records"] if e["source_file"] == "alpha_syllabus.pdf"
            )
            self.assertEqual(
                entry["normalizations"],
                [{"field": "year", "from": "September 2023", "to": "2023-09-01",
                  "rule": "iso_date"}],
            )


if __name__ == "__main__":
    unittest.main()
