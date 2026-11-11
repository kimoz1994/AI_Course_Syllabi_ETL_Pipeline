# AGENTS.md — AI Course Syllabi ETL Pipeline

## Project

ETL pipeline for AI course syllabi: currently ingests the manually-extracted
Kaggle CSV (`data/raw/AI_course_syllabi_CSV.csv`, CC BY 4.0), classifies every
topic/outcome item into the 7-part AIMA 4th-edition taxonomy, runs data-quality
gates, and renders RQ1–RQ4 figures with an auto-verified 19-point figure
checklist. A Stage-0 "PDF → structured table" extraction layer is the next
major revision — see `docs/adr/0001-pdf-first-input-and-llm-first-classification.md`.

## Key facts

- Python 3.10+. Install: `python -m pip install -e .`
- Run: `python -m ai_syllabi_etl run --backend rule` (offline, deterministic)
- Tests: `python -m unittest discover -s tests -t .` (unittest, no network/LLM)
- `docs/WALKTHROUGH.md` explains every file and the dataset-driven design
- `DATA_DICTIONARY.md` documents every column, cleaning rule and interpretation caveat
- `AI_course_syllabi_scripts.md` at the root is the **legacy** snippet file — read for
  context, never modify it
- Quality gates in `validate.py` decide the CLI exit code; CI (`ci.yml`) runs the
  full pipeline offline on every push

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
