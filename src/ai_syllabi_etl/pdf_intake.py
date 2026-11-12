"""v1 PDF intake: a folder of syllabus PDFs -> one clean dataset file.

SHA-256 dedup, lexicographic ``syllabus_id`` assignment, pypdf text
extraction, the extraction-backend seam for field extraction, and the
output contract (``syllabi_dataset.csv`` + ``extraction_log.json``).
Backend output is normalized + contract-checked at the seam (T2); the
normalize-then-assert validation stage lives in
:mod:`ai_syllabi_etl.validation` (T3). Later tickets deepen each stage:
the extraction cache (T4), the LLM backend (T6).
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
from .validation import validate_dataset

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


def _cache_index(
    previous_log: dict[str, Any] | None, backend_name: str
) -> dict[str, dict[str, Any]]:
    """Reuse index over the previous run's extraction log.

    The extraction log doubles as the cache index: an entry is reusable
    when it stored its ``fields``, was a clean success (``status == "ok"``
    with no ``issues``), and was produced by the same backend. Only clean
    successes are cached — scans and issue-carrying records are retried.
    """
    index: dict[str, dict[str, Any]] = {}
    for entry in (previous_log or {}).get("records", []):
        if "fields" not in entry:
            continue  # pre-T4 log format: nothing cached yet
        if entry.get("status") != "ok" or entry.get("issues"):
            continue
        if entry.get("backend") != backend_name:
            continue
        digest = entry.get("content_hash")
        if digest:
            index[digest] = entry["fields"]
    return index


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
    previous_log: dict[str, Any] | None = None,
    force: bool = False,
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

    Extraction cache (T4): ``previous_log`` — the previous run's
    extraction log — is the cache index. A file whose ``content_hash`` has
    a clean, same-backend entry is *not* re-extracted: its cached fields
    are reused (text extraction and the backend call are both skipped).
    Provenance columns (``syllabus_id``, ``source_file``) are recomputed
    from the current scan, so a renamed file still hits. Anything else —
    new files, scans, entries with issues, other backends, logs predating
    the cache format, and everything when ``force`` is true — is a miss
    and is extracted fresh. Log entries record ``cache: "hit"|"miss"`` so
    re-run cost is auditable.
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
    cache = {} if force else _cache_index(previous_log, backend.name)

    # ---- extract + identify (IDs assigned before any transformation) ------
    records: list[dict[str, Any]] = []
    log_records: list[dict[str, Any]] = []
    for index, (digest, path) in enumerate(distinct, start=1):
        syllabus_id = f"S{index:03d}"
        entry: dict[str, Any] = {
            "syllabus_id": syllabus_id,
            "source_file": path.name,
            "content_hash": digest,
            "backend": backend.name,
        }
        # Cache hit: reuse the stored fields; still run the seam checks so a
        # contract drifted since the cached run falls back to a fresh
        # extraction instead of raising on stale data.
        cached = cache.get(digest)
        hit = False
        if cached is not None:
            fields, _unmapped = normalize_record(dict(cached), contract)
            if not validate_record(fields, contract):
                hit = True
        if not hit:
            text = _extract_text(path)
            if not text.strip():
                entry["status"] = "scan"
                entry["warnings"] = [
                    "no text layer (image-only scan?) - all-null record"
                ]
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
        if hit:
            entry["status"] = "ok"
            entry["warnings"] = []
            entry["issues"] = []
            entry["cache"] = "hit"
        else:
            entry["cache"] = "miss"
        entry["fields"] = fields
        records.append(
            {
                "syllabus_id": syllabus_id,
                "source_file": path.name,
                "content_hash": digest,
                **fields,
            }
        )
        log_records.append(entry)

    hits = sum(1 for e in log_records if e.get("cache") == "hit")
    log = {
        "input_folder": str(root),
        "backend": backend.name,
        "cache": {"hits": hits, "misses": len(log_records) - hits},
        "files_seen": len(paths),
        "distinct_files": len(distinct),
        "dropped_duplicates": dropped,
        "records": log_records,
    }
    return records, log


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
    contract = load_schema_contract(cfg.get("schema_contract") or DEFAULT_CONTRACT_PATH)
    backend = make_extraction_backend(cfg)
    force = bool(cfg.get("force"))
    print(f"[intake]   backend={backend.name}: scanning {cfg['input']}")

    # The previous extraction log doubles as the extraction cache index; a
    # corrupt or unreadable log is simply a cold cache.
    previous_log = None
    if not force:
        previous_path = Path(cfg["paths"]["output"]) / LOG_FILENAME
        if previous_path.is_file():
            try:
                previous_log = json.loads(
                    previous_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[intake]   warning: ignoring unreadable cache: {exc}")

    records, log = intake(
        cfg["input"], backend, contract, previous_log=previous_log, force=force
    )
    hits = log["cache"]["hits"]
    misses = log["cache"]["misses"]
    cache_note = " (--force: cache bypassed)" if force else ""
    print(
        f"[intake]   {log['files_seen']} files seen, {log['distinct_files']} distinct, "
        f"{len(log['dropped_duplicates'])} duplicate(s) dropped"
    )
    print(f"[intake]   cache{cache_note}: {hits} hit(s), {misses} extracted fresh")

    quality, records, log = validate_dataset(records, log, contract)
    print(f"\n  quality: {quality['overall'].upper()}")
    for check in quality["checks"]:
        mark = {"pass": "ok  ", "warn": "warn", "fail": "FAIL"}[check["status"]]
        print(f"    [{mark}] {check['name']}: {check['detail']}")

    dataset_path, log_path = write_outputs(records, log, cfg["paths"]["output"])
    print(f"[write]    - {dataset_path.name}")
    print(f"           - {log_path.name}")

    if quality["overall"] == "fail":
        print("\nPipeline finished with FAILING quality gates.", file=sys.stderr)
        return 1
    print("\nPipeline finished successfully.")
    return 0
