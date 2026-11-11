# AI Course Syllabi ETL

[![CI](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Dataset: CC BY 4.0](https://img.shields.io/badge/dataset-CC%20BY%204.0-orange.svg)](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi)

An **ETL pipeline for AI course syllabi**: extract a structured syllabus
table, clean it into an analysis-ready dataset, classify every topic and
course outcome into the 7-part taxonomy of *Artificial Intelligence: A
Modern Approach* (4th edition), run data-quality gates, and render the four
research questions (RQ1–RQ4) as verified, publication-style figures.

```
raw CSV/XLSX ──► EXTRACT ──► CLEAN ──► CLASSIFY ──► VALIDATE ──► LOAD ──► REPORT
                (read)     (columns,   (rule /       (8 quality   (CSV +   (5 figures
                            sentinels,  openai /      gates,       SQLite)  + tables +
                            years)      mock backend) anomalies)           19-pt checklist)
```

This repository is a from-scratch rebuild of the original snippet collection
`AI_course_syllabi_scripts.md` (kept untouched at the repo root: LM Studio /
AnythingLLM calls, prompts and a bar-plot template).

## Dataset

| | |
|---|---|
| Source | [kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi) (v2, CC BY 4.0) |
| Origin | Public syllabi found via Google (`… filetype:pdf OR filetype:html`), manually extracted into a Google Form → one row per course |
| Size | 113 syllabi × 12 columns, 18 countries, years 2000–2024 |
| In this repo | `data/raw/AI_course_syllabi_CSV.csv` — the canonical raw input |

See [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) for every column, its
cleaning rule, and interpretation caveats.

## Quickstart

```bash
git clone https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline.git
cd ai_course_syllabi_etl
python -m pip install -e .          # or: pip install -r requirements.txt

python -m ai_syllabi_etl run --backend rule      # offline, deterministic, free
```

Outputs land in `data/processed/` (clean tables + SQLite + quality report)
and `output/` (figures, RQ tables, `report.md`). Committed outputs in this
repo were produced by the `rule` backend run shown above.

### Using an LLM backend (LM Studio / Ollama / any OpenAI-compatible server)

Edit `config.yaml`:

```yaml
backend: openai
llm:
  base_url: http://localhost:1234/v1     # LM Studio (Ollama: http://localhost:11434/v1)
  model: llama3.1                        # whatever model you loaded
  api_key_env: LMSTUDIO_API_KEY          # local servers accept any value
  fallback_to_rule: true                 # degrade gracefully if the server is down
```

then run `python -m ai_syllabi_etl run --backend openai`. The client speaks
plain `chat/completions`, so cloud APIs work too — just change `base_url`,
`model` and set the matching key env var. **The LLM backend is the
recommended path for publication-grade accuracy**; the rule backend is the
reproducible offline baseline used by CI.

## Pipeline stages

| Stage | Module | What it does |
|---|---|---|
| **Extract** | `extract.py` | Reads CSV/XLSX with all values as strings (so `2018-01-01` survives for explicit parsing). `PdfExtractor` groundwork for future direct-PDF intake (optional `pypdf`). |
| **Clean** | `clean.py` | Renames the questionnaire headers (`"Which country ? "` → `country`), converts sentinels (`not mentioned`, `none`, `n/a`…) to missing values, parses years, normalizes whitespace, and assigns stable `syllabus_id`s — **every rule is logged, no row is ever dropped**. |
| **Classify** | `classify.py` | Splits topics/outcomes into items and labels each with the AIMA taxonomy. Three backends: `rule` (keyword scoring, offline), `openai` (LM Studio/Ollama/cloud, strict-JSON parsing with retries and per-item rule fallback), `mock` (tests). |
| **Validate** | `validate.py` | 8 quality gates: row-count preservation, unique ids, required columns, sentinel residue, year plausibility, topic coverage, taxonomy label validity, duplicate detection + per-column completeness. Structural problems **fail** the run; imperfect-but-real data warns. |
| **Load** | `load.py` | Writes 4 CSVs + `quality_report.json` + a SQLite database (`syllabi.db`). |
| **Report** | `report.py` | RQ1–RQ4 tables and 5 interactive Plotly figures, each verified against the 19-point figure checklist → `report_checklist.json`, plus a findings summary in `report.md`. |

## Results (rule-backend baseline, full dataset)

Quality report: **PASS** — 113/113 rows preserved, 3,248 items classified,
0 anomalies, topic coverage 91.2%.

**RQ1 — predominant topic categories** (share of syllabi covering each theme):

| Theme | Syllabi | % |
|---|---|---|
| Machine Learning | 87 | 77.0 % |
| Artificial Intelligence Foundations | 72 | 63.7 % |
| Problem Solving | 71 | 62.8 % |
| Knowledge, Reasoning, and Planning | 65 | 57.5 % |
| Uncertain Knowledge and Reasoning | 57 | 50.4 % |
| Communicating, Perceiving, and Acting | 53 | 46.9 % |

**RQ2 — teaching methods:** lecture-based (74), online course (16), lab demos (14)
**RQ3 — assessment methods:** assignments (70), final exam (63), project (53)
**RQ4 — outcomes emphasised:** Foundations (31.0 %), Machine Learning (25.7 %), Knowledge & Reasoning (16.8 %)

Figures: `output/*.html` (interactive, Plotly/CDN) · tables: `output/*.csv` ·
findings: [`output/report.md`](output/report.md)

> **Honest caveat:** with the offline `rule` backend, ~81 % of syllabi have at
> least one item in class *Other* — those are mostly administrative lines
> (`"Topics in session 11:"`, `"Course structure and policies"`) and
> sentence fragments that keyword matching cannot place. Run
> `--backend openai` for context-aware classification; the taxonomy and
> prompt are already tuned for it.

## The 19-point figure checklist

The original research workflow kept a manual checklist for every chart.
Here it is **encoded and automatically verified** for each figure
(`output/report_checklist.json` — currently **5/5 figures pass 19/19**):

title · x/y-labels · font sizes (title 16, axes 14, ticks/values 10) ·
tick labels · values **and** percentages on bars · percentages recomputed
and compared · 10×5 in canvas · bar width 0.6 (vertical) / 0.5
(horizontal) · base count stated on the count axis ("out of N syllabi") ·
capitalization check · value-axis range.

Colours use the **Okabe–Ito** colour-vision-deficiency-safe palette.

## Tests & CI

```bash
python -m unittest discover -s tests -t .     # 54 tests, no network, no LLM needed
```

`tests/` covers cleaning rules, the rule/mock/OpenAI-parsing backends,
validation gates, and an end-to-end CLI run on a fixture (including the
figure checklists). GitHub Actions runs the suite on Python 3.10–3.12,
plus a full offline smoke run, and uploads the generated report as an
artifact.

## Project layout

```
ai_course_syllabi_etl/
├── config.yaml                  # backend, LLM endpoint, validation thresholds
├── taxonomy/aima_taxonomy.json  # 7 classes + keyword hints (editable)
├── prompts/classify_topics.md   # LLM prompt template (<<<TAXONOMY>>>/<<<TEXT>>>)
├── src/ai_syllabi_etl/          # extract · clean · classify · validate · load · report · cli
├── tests/                       # unittest suite + 5-row fixture
├── data/raw/                    # Kaggle CSV (CC BY 4.0)
├── data/processed/              # generated: clean tables + SQLite + quality report
├── output/                      # generated: figures, RQ tables, report.md, checklist
├── docs/                        # walkthrough: every file explained
├── AI_course_syllabi_scripts.md # legacy snippets this repo was rebuilt from (kept as-is)
└── .github/workflows/ci.yml
```

## Roadmap

- [ ] **PDF intake** — extract sections (`outcomes`, `topics`) directly from syllabus PDFs (`pypdf` extra is already wired in)
- [ ] **LLM backend bake-off** — pick the production model (LM Studio local vs. cloud) and record accuracy vs. the rule baseline
- [ ] Publish `output/report.md` + figures to GitHub Pages
- [ ] Inter-annotator-style spot checks: sample classified items for manual review

## License & attribution

- **Code:** MIT — see [LICENSE](LICENSE)
- **Dataset:** [AI Course Syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi) by Ahmed abdulhakim, **CC BY 4.0** — cite the Kaggle dataset when using the data
- Taxonomy structure based on *Artificial Intelligence: A Modern Approach*, 4th edition (Russell & Norvig)
