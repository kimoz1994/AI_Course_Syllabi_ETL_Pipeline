# AGENTS.md — AI Course Syllabi ETL Pipeline

## Project

ETL pipeline for AI course syllabi: the **v1 PDF-only flow** ingests a
folder of syllabus PDFs (`data/pdfs/*.pdf`), dedups by SHA-256, extracts
text, fills the 14-field schema through the extraction backend, runs
normalize-then-assert data-quality gates, and writes
`output/syllabi_dataset.csv` + `output/extraction_log.json`. Topic
classification stays in the codebase but **dormant** — not on the v1 run
path (deferred ticket). The legacy CSV-input flow is retired: the Kaggle
CSV lives archived in `data/archive/` (cross-checking reference, not an
input) and its stage modules stay dormant in the codebase. ADR-0001
records the design:
`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`.

## Key facts

- Python 3.10+. Install: `python -m pip install -e ".[pdf]"`
- Run: `python -m ai_syllabi_etl run` (PDF-only flow; default input `data/pdfs`,
  `extraction_backend: mock` = offline/deterministic; CI smoke-runs over
  `tests/fixtures/pdfs`)
- Tests: `python -m unittest discover -s tests -t .` (unittest, no network/LLM)
- `docs/WALKTHROUGH.md` explains every file and the dataset-driven design
- `DATA_DICTIONARY.md` documents every column, cleaning rule and interpretation caveat
- `AI_course_syllabi_scripts.md` at the root is the **legacy** snippet file — read for
  context, never modify it
- Quality gates in `validation.py` (normalize-then-assert) decide the CLI exit
  code; CI (`ci.yml`) runs the tests + a PDF-flow smoke run on every push.
  `extract/clean/classify/validate/load/report.py` are dormant legacy modules —
  don't wire them into the run path

## Agent skills

Engineering + productivity skills (mattpocock/skills) are installed **locally**
in `.opencode/skills/` (gitignored — per-machine tooling). Run sessions from the
repo root so they are discovered.

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the root + `docs/adr/`. See `docs/agents/domain.md`.
