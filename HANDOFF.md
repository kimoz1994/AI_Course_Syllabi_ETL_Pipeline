# HANDOFF — where we left off (2026-11-12)

Read this first if you're a session opening in this repo after a break.

## Status: v1 extraction pipeline implemented — first real run pending

- The **v1 PDF pipeline (ADR-0001 Stage 0) is implemented and green** — it
  is the only run path: a folder of PDFs in → dedup (SHA-256) → pypdf text
  → extraction backend (`mock` offline / `llm` any OpenAI-compatible
  server) → normalize-then-assert validation → `output/syllabi_dataset.csv`
  + `output/extraction_log.json`. 132 tests OK; CI green
  ([latest run](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions)).
- Tickets T1–T6 (#2–#7) are closed COMPLETED; **#8 (T7 docs rewrite)** is
  the last ticket of spec #1. The **legacy CSV pipeline is retired**: the
  Kaggle CSV is archived in `data/archive/` (cross-checking reference, not
  an input) and its stage modules stay dormant in the codebase.
- **Next step (outside ticket scope):** the **first real run** — the
  ~119-file corpus into `data/pdfs/`, `extraction_backend: llm` against the
  owner's LM Studio/Ollama server, then the owner spot-checks ~10 rows
  against source PDFs / the archived CSV (the spec's acceptance bar). Note
  the local cache makes follow-up runs cheap: only new/changed files
  re-extract; use `--force` after prompt changes.

The architecture (recorded in
[`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`](docs/adr/0001-pdf-first-input-and-llm-first-classification.md),
implemented except where noted):
1. **Stage 0: PDF → structured table.** Input `data/pdfs/*.pdf`;
   per-PDF text extraction + LLM field extraction under a strict schema
   contract mirroring the original Google Form fields; the extractor emits
   **real nulls** (sentinels become a backstop, not a mechanism).
2. **File-count gate:** N distinct-hash PDFs in → N syllabus records out.
3. **Taxonomy slimmed to schema:** 7 AIMA classes + short descriptions as
   the primary classification schema; keyword lists demoted to an
   offline-fallback file for the `rule` backend (CI baseline only).
   *Classification itself is dormant — deferred ticket.*
4. **Book-grounded classification (mini-RAG, deferred):** the classification
   prompt grounded with retrieved passages from the actual AIMA 4th-edition
   book — the owner reports this improved classification a lot vs. model
   memory alone.

## How the revision will be run

The owner drives the workflow with the agent skills installed in
`.opencode/skills/` (mattpocock/skills, repo-local, gitignored):

```
grilling / grill-with-docs  →  to-spec  →  to-tickets  →  implement
```

Issue tracker: GitHub Issues via `gh` (see `docs/agents/issue-tracker.md`);
triage labels `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`
are already created on the remote.

## ⛔ Waiting on the owner (the three blockers)

1. **The PDF corpus** — ✅ *received 2026-11-11, see below.*
2. **The Google-Form field definitions** — ✅ *received 2026-11-11, see below.*
3. **The AIMA book** — ✅ received; owner swapped in the **4th edition**
   (2026-11-12), so schema and grounding text are the same edition.

## Reference material received (2026-11-11)

Everything is in `reference/` (gitignored — third-party copyrighted PDFs,
~80 MB total; keep local, never push to GitHub):

| Item | Location | Notes |
|---|---|---|
| **119 syllabus PDFs** (59.4 MB) | `reference/syllabi files/` | The Stage-0 corpus. Note: 119 files vs 113 CSV rows — the CSV likely deduplicated some (several byte-identical duplicates visible, e.g. two copies of `9YUE2cwBNq5lVtrlORc1VWb93hVIcCnadSkWiSoy.pdf`, two of `Artificial_intelligence_course.pdf`). Stage 0 needs a **hash-based dedup rule** and the file-count gate must count *distinct* files. |
| **AIMA book** | `reference/aima/` | ✅ **4th edition** (owner swapped out the 3rd-edition file on 2026-11-12); classification schema and grounding text are now the same edition. |
| **Form spec** | `reference/form questions .txt` | The 13 form fields with descriptions + allowed value lists (course_level and teaching_method and assessment_method have **closed vocabularies**; country/institution/year/audience/title/prerequisites/description/topics/outcomes/tools/textbooks are free text). Key extraction rules embedded: **hardware/software tools have no dedicated section — must be inferred from other sections**; teaching method is sometimes called "course format". |
| **Bloom's verb table** | `reference/bloom verbs .txt` | LaTeX table, 6 levels (remember/understand/apply/analyze/evaluate/create). **Owner's collection rule: outcome lines are collected only if they contain a verb on this list; verbs not on the list are not collected.** |

### Outcomes-section identification rule (from the owner, 2026-11-11)

The outcomes section must be identified **by content, not by title** — titles
vary wildly ("Outcomes", "Objectives", "Learning Goals", …). Two-part rule:

1. Candidate section = text after a heading like outcomes/objectives/learning
   goals (the heading is a *hint*, never the deciding signal).
2. A line is an outcome item iff it starts with (or contains) a **Bloom's
   Taxonomy verb** from `reference/bloom verbs .txt`. No Bloom verb → not
   collected.

This matters because the form spec warns outcomes must not be confused with
"course objectives" — the Bloom-verb signal is the discriminator.

### Stage-0 environment gotcha — RESOLVED (2026-11-12)

`pypdf` now imports locally. The fix: the broken `python -m pip` was a
**corrupted user-site pip** (`pip._vendor.rich._emoji_codes` missing).
Deleting `pip` + `pip-*.dist-info` from the Store-Python user site-packages
(`…\Packages\PythonSoftwareFoundation.Python.3.10_…\LocalCache\local-packages\Python310\site-packages`)
and re-running `python -m ensurepip --upgrade` restored a clean pip (23.0.1
from the Store package itself). Then `python -m pip install -e ".[pdf]"`
installed **pypdf 7.0.1**. There is no `py` launcher on this machine.

### T1 implemented (2026-11-12)

The first tracer slice of Stage 0 is done: `extraction.py` (backend seam +
mock), `pdf_intake.py` (dedup → IDs → text → mock extraction → file-count
gate → `syllabi_dataset.csv` + `extraction_log.json`), fixture PDFs under
`tests/fixtures/pdfs/`, smoke test at the pipeline seam. The CLI runs the
PDF flow whenever `input` is a directory. Remaining tickets: #3 schema+vocab,
#4 validation, #5 cache, #6 CSV archival, #7 llm backend, #8 docs rewrite.

### T2 implemented (2026-11-12)

Schema contract at the seam: new `schema.py` (`FIELD_COLUMNS` moved here
from `pdf_intake.py`, `normalize_record`, `validate_record`) and
`schema_contract.yaml` (canonical vocabularies + alias map as config;
canonical strings are the form spec's exact values, e.g. `Short Quizzes`).
`pdf_intake.intake()` normalizes + validates backend output (structural →
`IntakeError`; unmappable vocabulary values stay in the record and land in
`extraction_log.json` `issues` for T3 to fail on). Optional
`schema_contract` path key in `config.yaml`. 94 tests green offline.

### T3 implemented (2026-11-12)
Normalize-then-assert validation: new `validation.py` — `validate_dataset()`
normalizes (`year` → ISO date where parseable; actions logged per record
under `normalizations`) then asserts the exact records-to-be-written, so a
PASS certifies the file on disk. Fail the run (exit 1): file-count gate,
structural contract violations, unmappable vocabulary values (message names
file/field/value; dataset still written for audit). Warn only: completeness,
scan/failed records, sentinel-like backstop values. `pdf_intake` stub
`file_count_gate` removed. 110 tests green offline. Remaining tickets:
#5 cache, #7 llm backend, #6 CSV archival, #8 docs rewrite.

### T4 implemented (2026-11-12)

Extraction cache keyed by content hash, `--force` flag: the previous
`output/extraction_log.json` doubles as the cache index — each entry now
also stores its `fields` and `backend`, so a hit (same SHA-256 hash, clean
`ok` entry, no `issues`, same backend) reuses the fields and skips both
text extraction and the backend call. Provenance columns are recomputed
from the current scan (renames still hit). Scans, issue-carrying records,
other backends and pre-T4 logs extract fresh (failures are never cached as
successes); a cache hit that fails the seam's structural check (contract
drift) falls back to a fresh extraction instead of raising. CLI gained
`--force` (any subcommand) → `cfg["force"]`. Log entries carry
`cache: "hit"|"miss"`; top-level log gained `backend` and
`cache: {hits, misses}`; the console prints
`cache: N hit(s), M extracted fresh`. New `tests/test_extraction_cache.py`
(13 tests) at the intake + pipeline seams. 124 tests green offline.
Remaining tickets: #7 llm backend, #6 CSV archival, #8 docs rewrite.

### T6 implemented (2026-11-12)

The `llm` extraction backend (provider-agnostic, OpenAI-compatible) in
`extraction.py`: endpoint/model/params/retries/API-key env var all config
(shared `llm` block), never code. The prompt is built once from the schema
contract + `prompts/bloom_verbs.txt` (the owner's Bloom verb table derived
from `reference/bloom verbs .txt`, 234 verbs after the owner-approved
typo fixes (`example` noun removed, `trnscribe` → `transcribe`),
multi-word entries kept) and
encodes verbatim/no-translation extraction, real nulls, canonical
vocabularies, JSON-array list fields, tools inferred from other sections,
and the Bloom verb rule (content-not-title, stem matching, semantic rule
for non-English). Shape conformance (14 keys, string-or-null scalars,
string arrays) + non-JSON + HTTP errors are retried up to `llm.max_retries`
with backoff; exhaustion raises `ExtractionError`, which `pdf_intake` turns
into an all-null record with `status: "failed"` + warning — run completes
(quality WARN), failure visible, never cached as a success. Vocabulary
canonicalization is NOT a retry condition (seam alias map owns it; unmapped
values fail validation naming file/field/value). Config gained
`extraction_backend` (mock | llm) and `bloom_verbs` path keys. New
`tests/test_llm_extraction.py` (10 tests) against a stub OpenAI-compatible
HTTP server on 127.0.0.1:0 — offline, no external network. 134 tests green
offline.

### T5 implemented (2026-11-12)

The legacy CSV path is retired: the Kaggle CSV moved to
`data/archive/AI_course_syllabi_CSV.csv` (git mv, still tracked — kept
in-repo as the cross-checking reference for extracted rows; see
`data/archive/README.md`). The CLI is **PDF-only**: `run` over a folder
(+ `--config`, `--input`, `--force`); the six stage subcommands and the
`--backend` classification override left the parser; a table-file input
is refused with an explanatory error pointing at the archive. The legacy
stage modules (`extract/clean/classify/validate/load/report.py`) stay in
the codebase **dormant** with their offline tests — nothing on the run
path calls them; classification revives in its deferred ticket. Config:
`input` default is now `data/pdfs`; config.yaml keeps only PDF-flow keys
(legacy keys documented as dormant comments). CI: smoke run is
`python -m ai_syllabi_etl run --input tests/fixtures/pdfs`; artifacts are
`output/` only. `tests/test_pipeline.py` (legacy CLI E2E) deleted;
`tests/test_cli.py` added (5 retirement-seam tests). 132 tests green
offline. Committed `output/` now holds the PDF-flow products
(`syllabi_dataset.csv` + `extraction_log.json` from the fixture run); the
stale legacy figures/report were removed. Remaining tickets: #8 docs
rewrite (done — see T7 below), then the first real run on the ~119-file
corpus.

### T7 implemented (2026-11-12)

Documentation coherence pass (docs-only, no code change): README gained a
"how it works" stage table (dedup → text → extract → schema seam →
validate → write) and a first-run console sample so a new user goes
clone → first PDF run without reading source; DATA_DICTIONARY.md was
rewritten around the **v1 dataset** (provenance columns, all 14 form
fields with form-spec semantics, null semantics, JSON-array list fields,
canonical vocabularies + alias map + unmappable-value failure, Bloom verb
rule, `extraction_log.json` schema) with the archived Kaggle CSV demoted
to a documented appendix; HANDOFF's status header updated to
"v1 implemented — first real run pending" and the stale "pip is broken"
note corrected. GLOSSARY "Stage 0 (planned)" term marked implemented;
ADR-0001 gained an implementation-status note (history unchanged).
**No further ticket work is pending; the next step is outside ticket
scope — the first real run on the ~119-file corpus + owner spot-check.**

### Layout A/B experiment (2026-11-12, inconclusive — blocked on model)

5 real PDFs (spread across the corpus) × two pypdf text modes (default =
the pipeline's exact extraction; `extraction_mode="layout"`) through the
real `llm` backend against the owner's LM Studio (`llama-3.2-3b-instruct`).
**All 10 extractions failed** on shape conformance after 3 retries:
scalar-got-list (`prerequisites`), non-array (`teaching_method`), and
missing fields (`textbooks`) — the 3B model cannot reliably produce the
strict JSON shape, so the layout comparison never reached the field level.
What the run *did* show: layout mode yields more complete text (e.g. 7,612
vs 5,917 chars on one file) and flags rotated text ("Output will be
incomplete"). Artifacts: `experiments/layout_ab/` (gitignored — contains
copies of copyrighted PDFs): `ab_report.html` (per-file FAILED entries),
`default|layout/results.csv`, `default|layout/texts/*.txt` (the raw text
pairs — the meaningful eyeball now). Candidate next steps: load a larger
instruct model in LM Studio, and/or have the backend enforce structured
output (LM Studio supports OpenAI `json_schema` response_format), and/or
treat *missing* fields as null at the seam instead of retrying.

## Open decisions (not blocking, decide during grill/spec)

- **Production LLM backend**: LM Studio (local) vs an OpenAI-compatible
  cloud endpoint (owner is deciding; LM Studio works today via
  `extraction_backend: llm` + the shared `llm` block in `config.yaml` —
  any OpenAI-compatible `/v1/chat/completions` endpoint drops in by
  editing `base_url`/`model`/`api_key_env`, no code change). `mock`
  stays the offline baseline for tests/CI, and the archived CSV is the
  cross-checking reference for extraction accuracy.
- **Accuracy evaluation** of extracted rows vs the archived Kaggle CSV
  (owner's manual transcription) once the production backend is chosen.

## Housekeeping (owner, manual)

- Delete the accidental empty repo `kimoz1994/ai_course_syllabi_etl`
  (Settings → Danger Zone → Delete; the agent's token lacks `delete_repo`).

## Environment gotchas (Windows, local)

- `python -m pip` **works** since 2026-11-12 (corrupted user-site pip was
  repaired via `ensurepip`; see "Stage-0 environment gotcha" above).
  Install: `python -m pip install -e ".[pdf]"` (pypdf 7.0.1 installed).
- Tests: `$env:PYTHONPATH="src"; $env:PYTHONIOENCODING='utf-8'` then
  `python -m unittest discover -s tests -t .` (132 tests as of T5; unittest,
  not pytest).
- Full pipeline (PDF flow): `python -m ai_syllabi_etl run` from repo root
  (input folder `data/pdfs`; CI smoke-runs `--input tests/fixtures/pdfs`).
- PowerShell 5.1 note: `python ... 2>&1 | Select-String` can report a bogus
  exit code 1 even when tests pass; check `$LASTEXITCODE` directly.
- `clean.py` text-column detection is dtype-agnostic (pandas 2 `object` vs
  pandas 3 `str`) — keep it that way; CI runs pandas 3.x, locally 2.2.2.
