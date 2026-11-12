# AI Course Syllabi ETL

[![CI](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Dataset: CC BY 4.0](https://img.shields.io/badge/dataset-CC%20BY%204.0-orange.svg)](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi)

An **ETL pipeline for AI course syllabi**. A folder of syllabus PDFs goes
in, a single clean dataset file comes out (v1, extraction-only) — later
extended with topic classification into the 7-part taxonomy of *Artificial
Intelligence: A Modern Approach* (4th edition) and the four research
questions (RQ1–RQ4) as verified, publication-style figures.

**Where things stand:** the **v1 PDF pipeline is implemented and is the
only run path** — a folder of syllabus PDFs in, one clean dataset file +
an extraction log out (extraction-only; classification and reporting are
deferred tickets). The **legacy CSV pipeline is retired**: the Kaggle CSV
lives archived in `data/archive/`, its stages stay in the codebase but
dormant, and the CLI speaks PDF only. Domain decisions live in
[`GLOSSARY.md`](GLOSSARY.md) and
[`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`](docs/adr/0001-pdf-first-input-and-llm-first-classification.md).

The v1 pipeline (spec #1):

```
PDFs in (data/pdfs) ──► DEDUP ──► TEXT ──► EXTRACT ──► VALIDATE ──► syllabi_dataset.csv
                       (SHA-256) (pypdf)  (14-field     (normalize-   + extraction_log.json
                                           schema,       then-assert,
                                           mock/llm)     gate + warnings)
```

The retired legacy CSV pipeline (dormant code, no longer on any run path):

```
raw CSV/XLSX ──► EXTRACT ──► CLEAN ──► CLASSIFY ──► VALIDATE ──► LOAD ──► REPORT
```

### How it works — the v1 flow, stage by stage

| Stage | Module | What it does |
|---|---|---|
| **Dedup** | `pdf_intake.py` | Scans the input folder, hashes each PDF (SHA-256), collapses byte-identical copies to one representative (logged, never silently dropped) and assigns `syllabus_id`s in lexicographic filename order |
| **Text** | `pdf_intake.py` | Extracts each PDF's text layer with pypdf; a file with no text layer (a scan) yields an all-null record + warning (no OCR in v1) |
| **Extract** | `extraction.py` | The extraction-backend seam: `mock` (canned records, offline) or `llm` (any OpenAI-compatible server) fills the 14 form fields from the text. Invalid backend output is retried (`llm` backend), then surfaces as an all-null `failed` record — a file is never dropped |
| **Schema seam** | `schema.py` | Normalizes + validates every record against `schema_contract.yaml`: list fields as JSON arrays, `not mentioned` → null, synonym → canonical vocabulary mapping via the alias map; unmappable values are logged, not guessed |
| **Validate** | `validation.py` | Normalize-then-assert: year → ISO date where parseable, then asserts the exact records about to be written. Structural problems + unmappable values **fail** the run (exit 1); imperfections (empty fields, scans, failures) **warn** (exit 0) |
| **Write** | `pdf_intake.py` | `output/syllabi_dataset.csv` (3 provenance + 14 form-field columns) + `output/extraction_log.json` (per-file status, warnings, issues, cache provenance) |

Column-by-column semantics (null rules, arrays, vocabularies, caveats) live
in [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md); every file explained, in
[`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

This repository is a from-scratch rebuild of the original snippet collection
`AI_course_syllabi_scripts.md` (kept untouched at the repo root: LM Studio /
AnythingLLM calls, prompts and a bar-plot template).

## Dataset

| | |
|---|---|
| Source | [kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi) (v2, CC BY 4.0) |
| Origin | Public syllabi found via Google (`… filetype:pdf OR filetype:html`), manually extracted into a Google Form → one row per course |
| Size | 113 syllabi × 12 columns, 18 countries, years 2000–2024 |
| In this repo | `data/archive/AI_course_syllabi_CSV.csv` — **archived**: the owner's manual example output, kept in-repo for cross-checking extracted rows. **No longer an input** — the pipeline reads only the PDF folder |

See [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) for every column, its
cleaning rule, and interpretation caveats.

## Quickstart (PDF pipeline)

```bash
git clone https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline.git
cd ai_course_syllabi_etl
python -m pip install -e ".[pdf]"    # pypdf for text extraction

# put syllabus PDFs in data/pdfs/ (create the folder if it doesn't exist),
# or point --input at any folder, then:
python -m ai_syllabi_etl run         # extraction_backend: mock (offline) by default
python -m ai_syllabi_etl run --input path/to/pdfs --force   # override + bypass the cache
```

The default `extraction_backend: mock` is a deterministic placeholder — it
produces the real pipeline shape (dedup, validation, outputs) with canned
field values, so you can verify your setup before wiring an LLM. For real
extraction, switch to `extraction_backend: llm` below. A first run looks
like:

```
[intake]   backend=mock: scanning …/data/pdfs
[intake]   119 files seen, 117 distinct, 2 duplicate(s) dropped
[intake]   cache: 0 hit(s), 117 extracted fresh

  quality: WARN
    [ok  ] file_count_gate: 117 distinct-hash files -> 117 records
    ...
[write]    - syllabi_dataset.csv
           - extraction_log.json

Pipeline finished successfully.
```

Outputs land in `output/`: `syllabi_dataset.csv` (one row per distinct
syllabus, 3 provenance + 14 form-field columns) and `extraction_log.json`
(per-file status, warnings, issues, cache provenance). Table ingestion
(CSV/XLSX) was **retired** — the Kaggle CSV lives in `data/archive/` and
is no longer an input; pointing `input` at a table file is refused with
an explanatory error.

### Using the llm extraction backend (LM Studio / Ollama / any OpenAI-compatible server)

Set `extraction_backend: llm` to extract with any **OpenAI-compatible**
chat server — LM Studio, Ollama, vLLM, or a cloud API; the choice is
**config, not code**, driven by the `llm` block (`base_url`, `model`,
`temperature`, `timeout_seconds`, `max_retries`, `api_key_env`). The
extraction prompt encodes the schema contract: the 14 fields, verbatim
extraction with **no translation**, real nulls (never sentinel words), the
closed vocabularies' canonical values, JSON-array list fields, tools
inferred from other sections, and the **Bloom verb rule** for outcomes
(collect a line iff it starts with or contains a Bloom's Taxonomy verb
from `prompts/bloom_verbs.txt`, matched case-insensitively on the stem;
the section is identified by content, not title; for non-English text the
rule applies **semantically**, with the English verb list as backstop).
Failure handling: invalid or non-conforming LLM output is retried up to
`llm.max_retries` times (with backoff); after exhaustion the file yields
an **all-null record plus a warning** — the run completes (exit 0,
quality WARN) and failures stay visible in `extraction_log.json`
(`status: "failed"`). Vocabulary values that the alias map cannot
canonicalize are not retried: they surface as `issues` and fail
validation, naming file/field/value.

```yaml
extraction_backend: llm
llm:
  base_url: http://localhost:1234/v1   # LM Studio default; Ollama: http://localhost:11434/v1
  model: <your-model>                  # any chat model the server exposes
  max_retries: 3
  structured_output: true              # forces the JSON shape via OpenAI json_schema (LM Studio: yes)
  api_key_env: LMSTUDIO_API_KEY        # optional; local servers need no key
```

Files with no text layer (scans) produce an all-null record plus a warning
(no OCR in v1).

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

## Retired legacy pipeline (dormant code)

The CSV-input pipeline below was retired when the PDF flow went
end-to-end: its stage modules remain in the codebase (with their offline
tests) but **nothing on the run path calls them**, and the CLI exposes no
stage subcommands. Topic classification stays dormant until its deferred
ticket; the Kaggle CSV it consumed lives in `data/archive/`.

| Stage | Module | What it did |
|---|---|---|
| **Extract** | `extract.py` | Reads CSV/XLSX with all values as strings. |
| **Clean** | `clean.py` | Renames questionnaire headers, converts sentinels, parses years, assigns stable `syllabus_id`s — every rule logged, no row dropped. |
| **Classify** | `classify.py` | Splits topics/outcomes into items and labels each with the AIMA taxonomy (`rule` / `openai` / `mock` backends). **Dormant — revived by the deferred classification ticket.** |
| **Validate** | `validate.py` | 8 quality gates for the table flow. Superseded on the run path by `validation.py` (normalize-then-assert). |
| **Load** | `load.py` | Wrote 4 CSVs + `quality_report.json` + SQLite (`syllabi.db`). |
| **Report** | `report.py` | RQ1–RQ4 figures + 19-point checklist + `report.md`. **Dormant — revived by the deferred reporting ticket.** |

## Archived results (legacy rule-backend baseline, full CSV dataset)

These numbers come from the retired CSV pipeline and are kept only as the
manual-transcription baseline the PDF flow will be cross-checked against
(the PDF corpus has ~119 files before dedup):

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

> **Honest caveat (classification, dormant):** with the offline `rule`
> backend, ~81 % of syllabi have at least one item in class *Other* —
> mostly administrative lines keyword matching cannot place. The deferred
> classification ticket will use the `openai` backend for context-aware
> labelling; the taxonomy and prompt are already tuned for it.

## The 19-point figure checklist (dormant reporting)

The original research workflow kept a manual checklist for every chart;
the retired `report.py` encoded and auto-verified it (title · labels ·
font sizes · values and percentages on bars · base counts · 10×5 canvas ·
Okabe–Ito palette …). It revives with the deferred reporting ticket,
re-run against the v1 dataset.

## Tests & CI

```bash
python -m unittest discover -s tests -t .     # 132 tests, no network, no LLM needed
```

`tests/` covers the extraction seam (mock + the `llm` backend against a
stub OpenAI-compatible server, offline), the schema contract, validation,
the extraction cache, the PDF pipeline over fixture PDFs, the CLI
retirement contract, and the dormant legacy modules (cleaning rules,
classification backends, table quality gates). GitHub Actions runs the
suite on Python 3.10–3.12, plus a full offline smoke run over the fixture
PDF folder, and uploads the generated dataset + log as an artifact.

## Project layout

```
ai_course_syllabi_etl/
├── config.yaml                    # input folder, extraction backend, LLM endpoint
├── schema_contract.yaml           # canonical vocabularies + alias map (PDF flow)
├── prompts/bloom_verbs.txt        # Bloom verb table (llm extraction backend)
├── src/ai_syllabi_etl/            # pdf_intake · extraction · schema · validation · cli (+ dormant legacy stages)
├── tests/                         # unittest suite + fixture PDFs
├── data/archive/                  # archived Kaggle CSV (cross-checking reference, not an input)
├── data/pdfs/                     # your syllabus PDF folder (the pipeline's input)
├── output/                        # generated: syllabi_dataset.csv + extraction_log.json
├── docs/                          # walkthrough: every file explained
├── AI_course_syllabi_scripts.md   # legacy snippets this repo was rebuilt from (kept as-is)
└── .github/workflows/ci.yml
```

## Roadmap

- [x] **v1: PDF extraction (spec: issue #1)** — `data/pdfs/*.pdf` in → SHA-256 dedup → pypdf text extraction → LLM field extraction (14-field schema contract, any OpenAI-compatible backend) → normalize-and-validate → `output/syllabi_dataset.csv` + `extraction_log.json`. Classification, reporting, and the legacy table stages are out of the v1 run path (dormant; the CSV is archived in `data/archive/`).
- [ ] **First real run + owner spot-check** — run the ~119-file corpus through the `llm` backend, then sample ~10 extracted rows for manual review against the archived CSV.
- [ ] **Topic classification (deferred ticket)** — AIMA 4th-edition classification of topic items, book-grounded; dormant until then.
- [ ] **Reporting (deferred ticket)** — RQ1–RQ4 figures + 19-point checklist, regenerated from the v1 dataset.
- [ ] **Syllabus scraping (planned ticket)** — auto-collect syllabus PDFs from university websites to feed the PDF corpus.
- [ ] **OCR (planned ticket)** — text recognition for image-only scans (v1 warns + emits an all-null record instead).
- [ ] **Production LLM bake-off** — pick the production model (LM Studio local vs. Ollama vs. cloud) when running the real pipeline.
- [ ] Publish figures to GitHub Pages (after the deferred reporting ticket)

## License & attribution

- **Code:** MIT — see [LICENSE](LICENSE)
- **Dataset:** [AI Course Syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi) by Ahmed abdulhakim, **CC BY 4.0** — cite the Kaggle dataset when using the data
- Taxonomy structure based on *Artificial Intelligence: A Modern Approach*, 4th edition (Russell & Norvig)
