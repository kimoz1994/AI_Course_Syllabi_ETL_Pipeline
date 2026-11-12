# AI Course Syllabi ETL

[![CI](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Dataset: CC BY 4.0](https://img.shields.io/badge/dataset-CC%20BY%204.0-orange.svg)](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi)

An **ETL pipeline for AI course syllabi**. Target shape: a folder of
syllabus PDFs goes in, a single clean dataset file comes out (v1,
extraction-only) — later extended with topic classification into the
7-part taxonomy of *Artificial Intelligence: A Modern Approach* (4th
edition) and the four research questions (RQ1–RQ4) as verified,
publication-style figures.

**Where things stand:** the **legacy CSV pipeline** (diagram below) is
the only implemented code today — it ingests the manually-transcribed
Kaggle CSV. The **v1 PDF pipeline** is fully specced in
[issue #1](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/issues/1)
and is being implemented ticket-by-ticket (#2–#8). Domain decisions live in
[`GLOSSARY.md`](GLOSSARY.md) and
[`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`](docs/adr/0001-pdf-first-input-and-llm-first-classification.md).

v1 pipeline — **in progress** (spec #1, tickets #2–#8):

```
PDFs in (data/pdfs) ──► DEDUP ──► TEXT ──► EXTRACT ──► VALIDATE ──► syllabi_dataset.csv
                       (SHA-256) (pypdf)  (14-field     (normalize-   + extraction_log.json
                                           schema,       then-assert,
                                           mock/llm)     gate + warnings)
```

Legacy CSV pipeline — **current working implementation**:

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
| In this repo | `data/raw/AI_course_syllabi_CSV.csv` — the legacy CSV pipeline's input; in the v1 PDF pipeline the CSV is the owner's manual example output (archived, not an input) |

See [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) for every column, its
cleaning rule, and interpretation caveats.

## Quickstart (legacy CSV pipeline)

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

### Running the v1 PDF pipeline (in progress)

The next revision — a folder of syllabus PDFs in, a single clean dataset
file out — is being built ticket-by-ticket
([spec #1](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/issues/1)).
Its first vertical slice (T1) is implemented: point the config `input` at a
**directory** of PDFs and the pipeline dedups byte-identical files by
SHA-256, assigns `syllabus_id`s in lexicographic filename order, extracts
text with pypdf, fills the 14 form fields through the extraction backend,
and writes `output/syllabi_dataset.csv` + `output/extraction_log.json`:

```yaml
input: data/pdfs                    # a folder of PDFs (not the legacy CSV)
extraction_backend: mock            # canned records; the llm backend lands in T6
```

```bash
python -m ai_syllabi_etl run        # PDF flow runs whenever `input` is a directory
```

Files with no text layer (scans) produce an all-null record plus a warning
(no OCR in v1). The real LLM backend lands in its own ticket.

**Schema contract (T2).** Every record the extraction backend emits is
normalized and validated against the 14-field form schema before it reaches
the dataset (`schema.py`):

- the 14 form fields must be present — values may be real nulls; list-valued
  fields (topics, outcomes, tools, textbooks, teaching method, assessment
  methods) must be JSON arrays; `tools` is a single inferred field (no
  hardware/software split);
- the three closed vocabularies (`course_level`, `teaching_method`,
  `assessment_methods`) use the form spec's exact canonical strings — e.g.
  `Short Quizzes`, not the legacy CSV's `Short Quizes` typo — defined in
  **`schema_contract.yaml`** (config, not code), together with a maintained
  synonym→canonical alias map (`lecture` → `Lecture based learning`,
  `undergrad` → `Undergraduate`, …). `not mentioned` normalizes to null;
  `Other/not clear` passes through as a distinct label;
- a vocabulary value with no alias that is not canonical (and isn't
  `Other/not clear`) is **unmappable**: it stays in the record verbatim and
  is listed under `issues` in `output/extraction_log.json`.

**Validation — normalize-then-assert (T3).** At the validation boundary
(`validation.py`) the pipeline normalizes the dataset and then asserts the
*exact records about to be written*, so a PASS certifies the file on disk:

- **Normalization rules** — `year` values become ISO dates where parseable
  (`2023` → `2023-01-01`, matching the manual export's convention;
  `September 2023` → `2023-09-01`; `9/1/2023` (US) and `Month D, YYYY`
  supported; seasons like `Fall 2024` and academic-year ranges like
  `2024/2025` stay verbatim — normalization never invents data). Empty→null
  and synonym→canonical vocabulary mapping already happened at the
  extraction seam. Every normalization is recorded per record under
  `normalizations` in `output/extraction_log.json`.
- **Fails the run (exit 1)** — the file-count gate (N distinct-hash files
  in → N records out; no file may be silently lost), structural contract
  violations, and unmappable vocabulary values (the failure message names
  the file, field and value). The dataset and log are still written on a
  failing run so the offending rows can be audited.
- **Warns only (exit 0)** — completeness per form field (an entirely empty
  field is a warning), scan and per-file failure records (all-null rows),
  and sentinel-like values (`not mentioned`, `none`, `n/a`…) appearing in
  PDF output — the extractor emits real nulls, so sentinels are a backstop.

**Extraction cache (T4).** Re-runs are cheap: the previous
`output/extraction_log.json` doubles as the cache index, keyed by the
SHA-256 content hash (the same key dedup uses). A file whose hash matches a
clean, same-backend entry from the previous run is **not re-extracted** —
neither the PDF text extraction nor the backend call happens, and the
cached fields are reused. Provenance columns (`syllabus_id`,
`source_file`) are always recomputed from the current scan, so a renamed
file still hits. Everything else is extracted fresh and then cached:

- new or changed files (hash mismatch), files whose previous record was a
  scan or carried `issues` (failures are never cached as successes), runs
  with a different extraction backend, and logs written before the cache
  format existed (cold cache);
- a cached record that no longer satisfies the schema contract (e.g. the
  contract was edited since) falls back to a fresh extraction instead of
  raising on stale data;
- `--force` (`python -m ai_syllabi_etl run --force`) bypasses the cache and
  re-extracts every file — use it after improving the extraction prompt or
  backend.

The console reports `cache: N hit(s), M extracted fresh`; each log entry
carries `cache: "hit"|"miss"` plus its stored `fields` and `backend`, so
re-run cost is auditable. The dataset written by a fully-cached re-run is
byte-identical to the original; the log differs only in cache provenance.

## Legacy pipeline stages (CSV input)

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
python -m unittest discover -s tests -t .     # 124 tests, no network, no LLM needed
```

`tests/` covers cleaning rules, the rule/mock/OpenAI-parsing backends,
validation gates, the extraction cache, and an end-to-end CLI run on a
fixture (including the figure checklists). GitHub Actions runs the suite
on Python 3.10–3.12, plus a full offline smoke run, and uploads the
generated report as an artifact.

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

- [ ] **v1: PDF extraction (spec: issue #1)** — `data/pdfs/*.pdf` in → SHA-256 dedup → pypdf text extraction → LLM field extraction (14-field schema contract, any OpenAI-compatible backend) → normalize-and-validate → `output/syllabi_dataset.csv` + `extraction_log.json`. Classification, reporting, and the separate clean stage move out of the v1 run path.
- [ ] **Topic classification (deferred ticket)** — AIMA 4th-edition classification of topic items, book-grounded; dormant until then.
- [ ] **Reporting (deferred ticket)** — RQ1–RQ4 figures + 19-point checklist, regenerated from the v1 dataset.
- [ ] **Syllabus scraping (planned ticket)** — auto-collect syllabus PDFs from university websites to feed the PDF corpus.
- [ ] **OCR (planned ticket)** — text recognition for image-only scans (v1 warns + emits an all-null record instead).
- [ ] **Production LLM bake-off** — pick the production model (LM Studio local vs. Ollama vs. cloud) when running the real pipeline.
- [ ] Publish `output/report.md` + figures to GitHub Pages
- [ ] Inter-annotator-style spot checks: sample extracted rows for manual review (first real run, per spec #1)

## License & attribution

- **Code:** MIT — see [LICENSE](LICENSE)
- **Dataset:** [AI Course Syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi) by Ahmed abdulhakim, **CC BY 4.0** — cite the Kaggle dataset when using the data
- Taxonomy structure based on *Artificial Intelligence: A Modern Approach*, 4th edition (Russell & Norvig)
