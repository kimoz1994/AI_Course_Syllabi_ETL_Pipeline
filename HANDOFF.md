# HANDOFF — where we left off (2026-11-11)

Read this first if you're a session opening in this repo after a break.

## Status: stable baseline, revision pending

> **UPDATE 2026-11-11 (later the same day): the three blockers are now
> SATISFIED — see "Reference material received" below.**

- The **CSV-ingestion pipeline** is complete and green: 113/113 rows preserved,
  3,248 items classified (rule backend), quality PASS, 5/5 figures pass the
  19-point checklist. 54 tests OK. CI badge is green
  ([latest run](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions)).
- The **next major revision is agreed but NOT started** — do not pre-build it.
  It is recorded as accepted architecture in
  [`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`](docs/adr/0001-pdf-first-input-and-llm-first-classification.md):
  1. **Stage 0: PDF → structured table.** Input becomes `data/pdfs/*.pdf`;
     per-PDF text extraction + LLM field extraction under a strict schema
     contract mirroring the original Google Form fields; the extractor emits
     **real nulls** (sentinels become a backstop, not a mechanism).
  2. **File-count gate:** N PDFs in → N syllabus records out.
  3. **Taxonomy slimmed to schema:** 7 AIMA classes + short descriptions as the
     primary classification schema; the LLM classifies (like the owner's
     original prompts); keyword lists demoted to an offline-fallback file for
     the `rule` backend (CI baseline only).
  4. **Book-grounded classification (mini-RAG):** the classification prompt is
     grounded with retrieved passages from the actual AIMA 4th-edition book —
     the owner reports this improved classification a lot vs. model memory alone.

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

## Open decisions (not blocking, decide during grill/spec)

- **Production LLM backend**: LM Studio (local) vs Ollama vs cloud
  OpenAI-compatible. The pipeline supports any via `backend: openai` +
  `config.yaml`; `rule` stays the deterministic baseline for accuracy
  comparison.
- **Accuracy evaluation** vs the rule baseline once the LLM backend is chosen.

## Housekeeping (owner, manual)

- Delete the accidental empty repo `kimoz1994/ai_course_syllabi_etl`
  (Settings → Danger Zone → Delete; the agent's token lacks `delete_repo`).

## Environment gotchas (Windows, local)

- `python -m pip` is broken — do NOT try to install packages.
- Tests: `$env:PYTHONPATH="src"; $env:PYTHONIOENCODING='utf-8'` then
  `python -m unittest discover -s tests -t .` (54 tests; unittest, not pytest).
- Full pipeline: `python -m ai_syllabi_etl run --backend rule` from repo root.
- PowerShell 5.1 note: `python ... 2>&1 | Select-String` can report a bogus
  exit code 1 even when tests pass; check `$LASTEXITCODE` directly.
- `clean.py` text-column detection is dtype-agnostic (pandas 2 `object` vs
  pandas 3 `str`) — keep it that way; CI runs pandas 3.x, locally 2.2.2.
