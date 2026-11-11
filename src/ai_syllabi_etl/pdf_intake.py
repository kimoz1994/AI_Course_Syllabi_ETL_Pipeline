"""v1 PDF intake: a folder of syllabus PDFs -> one clean dataset file.

Tracer implementation (T1): SHA-256 dedup, lexicographic ``syllabus_id``
assignment, pypdf text extraction, the extraction-backend seam for field
extraction, a stub file-count validation, and the output contract
(``syllabi_dataset.csv`` + ``extraction_log.json``). Later tickets deepen
each stage: the schema contract + vocabularies (T2), normalize-then-assert
validation (T3), the extraction cache (T4).
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .extraction import ExtractionBackend, make_extraction_backend
from .schema import (
    DEFAULT_CONTRACT_PATH,
    FIELD_COLUMNS,
    SchemaContract,
    load_schema_contract,
    normalize_record,
    validate_record,
)

# Re-exported for backward compatibility (the dataset column layout).
__all__ = ["DATASET_COLUMNS", "FIELD_COLUMNS", "intake", "run_pdf_pipeline", "write_outputs"]

# Provenance columns precede the form fields in the dataset.
DATASET_COLUMNS = ("syllabus_id", "source_file", "content_hash") + FIELD_COLUMNS

DATASET_FILENAME = "syllabi_dataset.csv"
LOG_FILENAME = "extraction_log.json"


class IntakeError(RuntimeError):
    """Raised when the PDF input folder cannot be processed."""


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes (the dedup + cache key)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_text(path: Path) -> str:
    """Text layer of a PDF via pypdf; empty string when there is none."""
    import pypdf

    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # unreadable/corrupt PDF -> treated like a scan
        print(f"[intake] warning: could not read {path.name}: {exc}")
        return ""


def intake(
    folder: str | Path,
    backend: ExtractionBackend,
    contract: SchemaContract | None = None,
) -> tuple[list[dict], dict]:
    """Run the intake stages over ``folder``; return ``(records, log)``.

    Stages: hash every PDF, collapse byte-identical duplicates (the
    lexicographically-first filename is the representative), assign
    ``syllabus_id``s in lexicographic filename order after dedup, extract
    text, and fill field dicts through the extraction backend. Backend
    output is normalized against the schema contract (alias map, real
    nulls) and validated right at the seam: structural violations raise
    :class:`IntakeError`, and unmappable vocabulary values stay in the
    record and are logged in the entry's ``issues`` for the validation
    stage to fail on. A file with no text layer (a scan) yields an
    all-null record plus a warning — never a dropped file.
    """
    if contract is None:
        contract = load_schema_contract(DEFAULT_CONTRACT_PATH)
    root = Path(folder)
    paths = sorted(root.glob("*.pdf"), key=lambda p: p.name)
    if not paths:
        raise IntakeError(f"no PDF files found in {root}")

    # ---- dedup: group by content hash, keep lexicographically-first name --
    representatives: dict[str, Path] = {}
    dropped: list[dict[str, str]] = []
    for path in paths:
        digest = sha256_file(path)
        kept = representatives.get(digest)
        if kept is None:
            representatives[digest] = path
        else:
            dropped.append({"file": path.name, "hash": digest, "kept_as": kept.name})

    distinct = sorted(representatives.items(), key=lambda kv: kv[1].name)

    # ---- extract + identify (IDs assigned before any transformation) ------
    records: list[dict[str, Any]] = []
    log_records: list[dict[str, Any]] = []
    for index, (digest, path) in enumerate(distinct, start=1):
        syllabus_id = f"S{index:03d}"
        text = _extract_text(path)
        entry: dict[str, Any] = {
            "syllabus_id": syllabus_id,
            "source_file": path.name,
            "content_hash": digest,
        }
        if not text.strip():
            entry["status"] = "scan"
            entry["warnings"] = ["no text layer (image-only scan?) - all-null record"]
            entry["issues"] = []
            fields = {name: None for name in FIELD_COLUMNS}
        else:
            fields = backend.extract(text, source={"file": path.name})
            fields, _unmapped = normalize_record(fields, contract)
            issues = validate_record(fields, contract)
            structural = [i for i in issues if i["issue"] != "unmapped_value"]
            if structural:
                raise IntakeError(
                    f"{path.name}: extraction output violates the schema contract: "
                    + "; ".join(f"{i['field']}: {i['issue']}" for i in structural)
                )
            entry["status"] = "ok"
            entry["warnings"] = []
            entry["issues"] = [i for i in issues if i["issue"] == "unmapped_value"]
        records.append(
            {
                "syllabus_id": syllabus_id,
                "source_file": path.name,
                "content_hash": digest,
                **fields,
            }
        )
        log_records.append(entry)

    log = {
        "input_folder": str(root),
        "files_seen": len(paths),
        "distinct_files": len(distinct),
        "dropped_duplicates": dropped,
        "records": log_records,
    }
    return records, log


def file_count_gate(records: list[dict], distinct_files: int) -> dict[str, Any]:
    """Stub validation (T1): the structural gate N files in -> N records out."""
    ok = len(records) == distinct_files
    return {
        "overall": "pass" if ok else "fail",
        "checks": [
            {
                "name": "file_count_gate",
                "status": "pass" if ok else "fail",
                "detail": f"{distinct_files} distinct files -> {len(records)} records",
            }
        ],
    }


def _cell(value: Any) -> str:
    """Dataset cell encoding: real nulls -> empty, lists -> JSON arrays."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    return str(value)


def write_outputs(
    records: list[dict], log: dict, output_dir: str | Path
) -> tuple[Path, Path]:
    """Write ``syllabi_dataset.csv`` + ``extraction_log.json``; return paths."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    dataset_path = out / DATASET_FILENAME
    with dataset_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(DATASET_COLUMNS)
        for record in records:
            writer.writerow([_cell(record.get(col)) for col in DATASET_COLUMNS])

    log_path = out / LOG_FILENAME
    log_path.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
    return dataset_path, log_path


def run_pdf_pipeline(cfg: dict[str, Any]) -> int:
    """CLI entry: PDF folder in -> dataset + extraction log out (exit 0/1)."""
    backend = make_extraction_backend(cfg)
    print(f"[intake]   backend={backend.name}: scanning {cfg['input']}")
    records, log = intake(cfg["input"], backend)
    print(
        f"[intake]   {log['files_seen']} files seen, {log['distinct_files']} distinct, "
        f"{len(log['dropped_duplicates'])} duplicate(s) dropped"
    )

    quality = file_count_gate(records, log["distinct_files"])
    print(f"\n  quality: {quality['overall'].upper()}")
    for check in quality["checks"]:
        mark = {"pass": "ok  ", "fail": "FAIL"}[check["status"]]
        print(f"    [{mark}] {check['name']}: {check['detail']}")

    dataset_path, log_path = write_outputs(records, log, cfg["paths"]["output"])
    print(f"[write]    - {dataset_path.name}")
    print(f"           - {log_path.name}")

    if quality["overall"] == "fail":
        print("\nPipeline finished with FAILING quality gates.", file=sys.stderr)
        return 1
    print("\nPipeline finished successfully.")
    return 0
