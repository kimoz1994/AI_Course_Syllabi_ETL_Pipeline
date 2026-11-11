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


if __name__ == "__main__":
    unittest.main()
