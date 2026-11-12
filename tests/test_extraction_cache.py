"""T4: extraction cache keyed by content hash + ``--force``.

Seams under test (the pre-agreed set):

- ``pdf_intake.intake`` — the cache decision at the intake stage: a
  previous extraction log in, cache hit/miss per file out. Catches: the
  reuse rule (only clean ``ok`` entries of the same backend are reused),
  provenance recomputation (renames still hit), and ``force``.
- ``pdf_intake.run_pdf_pipeline`` — the cache is loaded from the previous
  ``extraction_log.json`` in the output directory and the ``--force`` CLI
  flag bypasses it. Catches: reruns actually get cheaper (zero backend
  calls), new files are the only ones extracted, and the dataset written
  by a fully-cached run is identical to the original.
"""

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_syllabi_etl import pdf_intake
from ai_syllabi_etl.extraction import ExtractionBackend
from ai_syllabi_etl.schema import DEFAULT_CONTRACT_PATH, load_schema_contract

REPO = Path(__file__).resolve().parents[1]
PDF_DIR = REPO / "tests" / "fixtures" / "pdfs"


class CountingBackend(ExtractionBackend):
    """Stub backend that counts extract() calls (cache observability)."""

    name = "counting"

    def __init__(self, fields):
        self._fields = fields
        self.calls = 0

    def extract(self, text, source=None):
        self.calls += 1
        return dict(self._fields)


def _clean_fields(**overrides):
    """A contract-clean 14-field record (canonical vocabulary values)."""
    fields = {
        "country": "Narnia",
        "institution": "Alpha University",
        "year": None,
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


def _read_csv(path: Path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _by_file(log):
    """Extraction-log entries keyed by source file."""
    return {e["source_file"]: e for e in log["records"]}


def _read_log(tmp: Path):
    return json.loads(
        (tmp / "output" / "extraction_log.json").read_text(encoding="utf-8")
    )


class IntakeCacheTests(unittest.TestCase):
    """The intake seam: previous log in, per-file cache hit/miss out."""

    def setUp(self):
        self.contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
        self.backend = CountingBackend(_clean_fields())
        self.records, self.log = pdf_intake.intake(PDF_DIR, self.backend, self.contract)

    def _rerun(self, log, force=False):
        backend = CountingBackend(_clean_fields())
        records2, log2 = pdf_intake.intake(
            PDF_DIR, backend, self.contract, previous_log=log, force=force
        )
        return backend, records2, log2

    def test_first_run_is_all_misses_and_stores_fields(self):
        # alpha + bravo reach the backend; the scan never does (no text layer)
        self.assertEqual(self.backend.calls, 2)
        by_file = _by_file(self.log)
        self.assertEqual(by_file["alpha_syllabus.pdf"]["cache"], "miss")
        self.assertEqual(by_file["bravo_syllabus.pdf"]["cache"], "miss")
        self.assertEqual(by_file["charlie_scan.pdf"]["cache"], "miss")
        self.assertEqual(by_file["alpha_syllabus.pdf"]["fields"], _clean_fields())
        self.assertEqual(by_file["alpha_syllabus.pdf"]["backend"], "counting")

    def test_rerun_with_unchanged_log_performs_zero_extractions(self):
        backend2, records2, log2 = self._rerun(self.log)
        self.assertEqual(backend2.calls, 0)
        self.assertEqual(records2, self.records)
        by_file = _by_file(log2)
        self.assertEqual(by_file["alpha_syllabus.pdf"]["cache"], "hit")
        self.assertEqual(by_file["bravo_syllabus.pdf"]["cache"], "hit")

    def test_scan_entries_are_never_reused(self):
        """A scan is not a cached success: it is recomputed every run."""
        _, _, log2 = self._rerun(self.log)
        scan = _by_file(log2)["charlie_scan.pdf"]
        self.assertEqual(scan["cache"], "miss")
        self.assertEqual(scan["status"], "scan")

    def test_entries_with_issues_are_retried(self):
        """Failures are not cached as successes: unmapped issues -> retry."""
        log = copy.deepcopy(self.log)
        alpha = _by_file(log)["alpha_syllabus.pdf"]
        alpha["issues"] = [
            {"field": "course_level", "issue": "unmapped_value", "value": "Narnian"}
        ]
        backend2, _, log2 = self._rerun(log)
        self.assertEqual(backend2.calls, 1)  # alpha retried; bravo still cached
        by_file = _by_file(log2)
        self.assertEqual(by_file["alpha_syllabus.pdf"]["cache"], "miss")
        self.assertEqual(by_file["bravo_syllabus.pdf"]["cache"], "hit")

    def test_different_backend_name_reextracts(self):
        """Cache entries carry the backend that produced them."""

        class OtherBackend(CountingBackend):
            name = "other"

        backend2 = OtherBackend(_clean_fields())
        _, log2 = pdf_intake.intake(
            PDF_DIR, backend2, self.contract, previous_log=self.log
        )
        self.assertEqual(backend2.calls, 2)
        self.assertEqual(_by_file(log2)["alpha_syllabus.pdf"]["cache"], "miss")

    def test_old_format_log_without_fields_is_a_cold_cache(self):
        """Logs written before T4 carry no fields -> nothing is reusable."""
        log = copy.deepcopy(self.log)
        for entry in log["records"]:
            entry.pop("fields", None)
            entry.pop("backend", None)
        backend2, _, log2 = self._rerun(log)
        self.assertEqual(backend2.calls, 2)
        self.assertEqual(_by_file(log2)["alpha_syllabus.pdf"]["cache"], "miss")

    def test_renamed_file_still_hits_by_content_hash(self):
        log = copy.deepcopy(self.log)
        alpha = _by_file(log)["alpha_syllabus.pdf"]
        alpha["source_file"] = "renamed_syllabus.pdf"
        backend2, _, log2 = self._rerun(log)
        self.assertEqual(backend2.calls, 0)  # alpha hit by hash; bravo cached too
        alpha2 = _by_file(log2)["alpha_syllabus.pdf"]
        self.assertEqual(alpha2["cache"], "hit")
        self.assertEqual(alpha2["fields"], _clean_fields())

    def test_force_reextracts_everything(self):
        backend2, _, log2 = self._rerun(self.log, force=True)
        self.assertEqual(backend2.calls, 2)
        by_file = _by_file(log2)
        self.assertEqual(by_file["alpha_syllabus.pdf"]["cache"], "miss")
        self.assertEqual(by_file["bravo_syllabus.pdf"]["cache"], "miss")
        # ...and the forced run still stores fields for the next run
        self.assertEqual(by_file["alpha_syllabus.pdf"]["fields"], _clean_fields())

    def test_structurally_stale_cache_entry_falls_back_to_fresh_extraction(self):
        """A cached record that no longer matches the contract is re-extracted,
        not raised on — the fresh output then faces the usual seam checks."""
        log = copy.deepcopy(self.log)
        _by_file(log)["alpha_syllabus.pdf"]["fields"] = {"course_title": "only one"}
        backend2, _, log2 = self._rerun(log)
        self.assertEqual(backend2.calls, 1)  # alpha re-extracted, bravo cached
        alpha2 = _by_file(log2)["alpha_syllabus.pdf"]
        self.assertEqual(alpha2["cache"], "miss")
        self.assertEqual(alpha2["fields"], _clean_fields())


class PipelineCacheTests(unittest.TestCase):
    """The pipeline seam: the output dir's previous log is the cache index."""

    def _copy_pdfs(self, tmp: Path):
        in_dir = tmp / "pdfs"
        in_dir.mkdir(parents=True, exist_ok=True)
        for name in ("alpha_syllabus.pdf", "bravo_syllabus.pdf"):
            data = (PDF_DIR / name).read_bytes()
            (in_dir / name).write_bytes(data)
        return in_dir

    def _write_extra_pdf(self, in_dir: Path):
        """A genuinely distinct PDF (alpha's page + one blank page)."""
        import pypdf

        reader = pypdf.PdfReader(str(PDF_DIR / "alpha_syllabus.pdf"))
        writer = pypdf.PdfWriter()
        writer.add_page(reader.pages[0])
        writer.add_page(pypdf.PageObject.create_blank_page(width=612, height=792))
        with (in_dir / "delta_syllabus.pdf").open("wb") as fh:
            writer.write(fh)

    def _make_cfg(self, in_dir: Path, tmp: Path, **extra):
        return {
            "input": str(in_dir),
            "paths": {"output": str(tmp / "output")},
            "extraction_backend": "counting",
            **extra,
        }

    def _run(self, cfg):
        backend = CountingBackend(_clean_fields())
        with patch.object(
            pdf_intake, "make_extraction_backend", return_value=backend
        ):
            return backend, pdf_intake.run_pdf_pipeline(cfg)

    def test_rerun_zero_extractions_and_identical_dataset(self):
        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t4_") as td:
            tmp = Path(td)
            in_dir = self._copy_pdfs(tmp)
            cfg = self._make_cfg(in_dir, tmp)
            backend, code1 = self._run(cfg)
            self.assertEqual(code1, 0)
            self.assertEqual(backend.calls, 2)
            first_csv = (tmp / "output" / "syllabi_dataset.csv").read_bytes()

            backend2, code2 = self._run(cfg)
            self.assertEqual(code2, 0)
            self.assertEqual(
                backend2.calls, 0, "re-run with unchanged inputs must not re-extract"
            )
            self.assertEqual(
                (tmp / "output" / "syllabi_dataset.csv").read_bytes(),
                first_csv,
                "fully-cached re-run writes an identical dataset",
            )
            log = _read_log(tmp)
            self.assertEqual([e["cache"] for e in log["records"]], ["hit", "hit"])
            self.assertEqual(log["cache"], {"hits": 2, "misses": 0})

    def test_added_pdf_extracts_only_the_new_file(self):
        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t4_") as td:
            tmp = Path(td)
            in_dir = self._copy_pdfs(tmp)
            cfg = self._make_cfg(in_dir, tmp)
            backend, _ = self._run(cfg)
            self.assertEqual(backend.calls, 2)

            self._write_extra_pdf(in_dir)
            backend2, code2 = self._run(cfg)
            self.assertEqual(code2, 0)
            self.assertEqual(backend2.calls, 1, "only the new file is extracted")
            rows = _read_csv(tmp / "output" / "syllabi_dataset.csv")
            self.assertEqual(
                [r["source_file"] for r in rows],
                ["alpha_syllabus.pdf", "bravo_syllabus.pdf", "delta_syllabus.pdf"],
            )
            by_file = _by_file(_read_log(tmp))
            self.assertEqual(by_file["delta_syllabus.pdf"]["cache"], "miss")
            self.assertEqual(by_file["alpha_syllabus.pdf"]["cache"], "hit")

    def test_force_rerun_reextracts_everything(self):
        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t4_") as td:
            tmp = Path(td)
            in_dir = self._copy_pdfs(tmp)
            cfg = self._make_cfg(in_dir, tmp)
            backend, _ = self._run(cfg)
            self.assertEqual(backend.calls, 2)

            backend2, code2 = self._run({**cfg, "force": True})
            self.assertEqual(code2, 0)
            self.assertEqual(backend2.calls, 2, "--force must re-extract every file")
            self.assertEqual(_read_log(tmp)["cache"], {"hits": 0, "misses": 2})

    def test_cli_force_flag_reaches_the_pipeline(self):
        """`run --force` on the real CLI must set cfg['force']."""
        from ai_syllabi_etl.cli import main

        with tempfile.TemporaryDirectory(prefix="ai_syllabi_etl_t4_") as td:
            tmp = Path(td)
            in_dir = self._copy_pdfs(tmp)
            cfg_path = tmp / "config.yaml"
            cfg_path.write_text(
                "input: '"
                + str(in_dir).replace("\\", "/")
                + "'\npaths:\n  output: '"
                + str(tmp / "output").replace("\\", "/")
                + "'\nextraction_backend: mock\n",
                encoding="utf-8",
            )
            seen = {}

            def fake_make_backend(cfg):
                seen["force"] = bool(cfg.get("force"))
                return CountingBackend(_clean_fields())

            with patch.object(pdf_intake, "make_extraction_backend", fake_make_backend):
                code = main(["run", "--config", str(cfg_path), "--force"])
            self.assertEqual(code, 0)
            self.assertTrue(seen["force"], "--force must set cfg['force']")


if __name__ == "__main__":
    unittest.main()
