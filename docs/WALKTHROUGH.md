# Code Walkthrough — every file explained

This document explains **every file in this repository**, what every important
block of code does, and — most importantly — **how the real dataset itself
shaped every decision**. Read it top to bottom and you will understand the
whole system.

---

## 0. The big picture: what is an ETL pipeline?

**ETL = Extract, Transform, Load** — the standard industry pattern for moving
raw data into an analysis-ready state:

| Stage | Meaning | In this project |
|---|---|---|
| **Extract** | Pull raw data from its source *without changing it* | Read the Kaggle CSV exactly as exported |
| **Transform** | Clean, standardize, enrich into the shape analysis needs | Rename headers, fix sentinels, parse years, classify topics |
| **Load** | Write the result into durable, queryable storage | CSVs + SQLite database |

You already did all three stages **manually**: you *extracted* text from PDFs
via a Google Form, *transformed* it by copy-pasting the "outcomes" section
into an LLM and copying answers into Excel, and *loaded* it by uploading the
resulting table to Kaggle. The pipeline automates exactly that loop — so that
re-running it on new syllabi takes one command instead of one week.

Two extra stages sit on top of ETL because this project is also a **research
instrument**:

- **Validate** — data-quality gates that prove the transformation didn't
  corrupt anything (industry name: *data quality framework*).
- **Report** — turn the loaded tables into the four research questions
  (RQ1–RQ4) your Kaggle description promises.

```
        ┌────────────────────── one command: python -m ai_syllabi_etl run ─────────────────────┐
        │                                                                                      │
 data/raw/*.csv ──► EXTRACT ──► CLEAN ──► CLASSIFY ──► VALIDATE ──► LOAD ──► REPORT ──► output/*.html, report.md
 (untouched)         (read)    (13 cols,  (rule/openai/   (8 gates,     (CSV +     (5 figures,
                                sentinels, mock backend)  anomalies)   SQLite)    tables, checklist)
                                years)         │
                                               ▼
                                    data/processed/ (syllabi.db, clean CSVs, quality_report.json)
```

### The golden rule of every pipeline

> **Extract never drops or changes data. Transform never loses a row.
> Validate proves both.**

You'll see this rule enforced literally in `clean.py` (rows are never
filtered, only values normalized) and `validate.py` (check #1 fails the run
if row counts change).

---

## 1. How the real dataset shaped every decision

This is the part most tutorials skip: **you don't design a pipeline from a
book, you design it from the actual data.** Before writing any code, I
profiled `data/raw/AI_course_syllabi_CSV.csv` (113 rows × 12 columns) and let
each finding dictate a cleaning rule:

| # | Finding in YOUR data | Code it produced | File / line concept |
|---|---|---|---|
| 1 | Headers are Google-Form questions with stray spaces: `Which country ? `, `What is the course  content/topics?` (double space!) | `normalize_header()` — collapses whitespace, lowercases, strips trailing `?`, then maps to snake_case | `clean.py` |
| 2 | `not mentioned` appears 76 times across 6 columns; `none` 4× in prerequisites | `SENTINELS` set + `clean_text()` converts them to real missing values (`NaN`) | `clean.py` |
| 3 | Years stored as `2018-01-01` strings (Excel date exports) | `parse_year()` — regex extracts the first 4-digit group, sanity-banded 1900–2100 | `clean.py` |
| 4 | Assessment methods joined by `;` (`Short Quizes;Final Exam`) | `split_items(seps=(";", "|", "\n"))` for counting | `clean.py` → `report.py` |
| 5 | Outcomes are numbered lines (`1. Understand search\n2. Understand planning`) | `split_outcomes()` strips the numbering regex `^\s*\d+[.)]\s*` | `clean.py` |
| 6 | Topics mix newlines, `○` bullets, and **commas inside phrases** (`Search, A* and planning`) | `split_topic_items()` splits on lines/bullets only — **deliberately not commas**, or phrases would be chopped mid-sentence | `clean.py` |
| 7 | 6 rows missing country, 29 missing year, 49 missing outcomes | `validate.py` reports per-column **completeness %** instead of failing — real data is imperfect, silently hiding that would be worse | `validate.py` |
| 8 | Some topics cells are full sentences, not lists ("…we will begin by discussing how") | Classification is **item-level with a catch-all class 7 (Other)** + confidence, and the LLM backend exists for context-aware reading | `classify.py` |
| 9 | The AIMA taxonomy in your two prompts (7 classes + keyword lists) | Lifted verbatim into a **machine-readable** `taxonomy/aima_taxonomy.json` — data, not prose | `taxonomy/` |
| 10 | Your prompts asked the LLM to "return only a python dictionary" (brittle to parse) | Replaced with a strict **JSON contract** `{"topics": [{"topic": ..., "class": 1-7}]}` + tolerant parser | `prompts/`, `classify.py` |
| 11 | Your bar-plot template had a 19-point manual QA checklist | Encoded as **automatic verification** of every figure | `report.py` |

**Lesson:** every weird value in a dataset is a *requirement* in disguise.
Profiling first (I ran `pandas` value-counts, null counts, and separator
sampling on your CSV before writing code) is what separates a pipeline that
works from one that explodes on row 57.

---

## 2. Configuration files

### `config.yaml` — the control panel

```yaml
input: data/raw/AI_course_syllabi_CSV.csv   # which file to process
taxonomy: taxonomy/aima_taxonomy.json       # where the 7 classes live
prompt: prompts/classify_topics.md          # the LLM prompt template
paths:
  processed: data/processed                 # pipeline outputs (gitignored)
  output: output                            # report artifacts (committed)
backend: rule                               # rule | openai | mock
llm:
  base_url: http://localhost:1234/v1        # LM Studio default; Ollama: :11434/v1
  model: lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
  api_key_env: LMSTUDIO_API_KEY             # secret read from env, never from the file
  temperature: 0.0                          # deterministic LLM output
  timeout_seconds: 60
  max_retries: 3
  fallback_to_rule: true                    # if LLM fails → rule backend takes over
validation:
  min_year: 1990
  max_year: 2030
  min_topic_coverage: 0.8                   # ≥80% of syllabi must have topics
  required_columns: [country, institution, year, ...]
report:
  top_n_methods: 10
```

Why this matters:

- **No secrets in code.** The original repo committed an AnythingLLM API key
  (`7FMSR1T-...`). Here the key is read from an *environment variable*
  (`api_key_env`), so the file is safe to publish.
- **Swapping LLMs = editing one line.** LM Studio, Ollama, vLLM and cloud
  APIs all speak the same `/v1/chat/completions` protocol.
- **Thresholds live in config, not code** — tune `min_topic_coverage`
  without touching Python.

### `taxonomy/aima_taxonomy.json` — your prompts, as data

Your original prompts contained the 7 AIMA classes as prose. I turned them
into a JSON file the code can load:

```json
{"id": 5, "name": "Machine Learning",
 "keywords": ["machine learning", "supervised", "decision tree", ...]}
```

Each class has `id` (1–7), `name`, and `keywords`. The `keywords` do double
duty: the `rule` backend scores with them, and the LLM prompt renders them
as hints. **Editing the JSON changes both backends instantly** — no code.

### `prompts/classify_topics.md` — the prompt as a template

```
You are an expert in AI education ... Classify every topic below into exactly
one class from this taxonomy:

<<<TAXONOMY>>>

Rules:
1. Return ONLY a JSON object ... {"topics": [{"topic": "...", "class": <1-7>}]}
...
Topics to classify:

<<<TEXT>>>
```

The two `<<<...>>>` placeholders are substituted at runtime (`<<<TEXT>>>` =
the bullet list of one syllabus's topics). Your original prompt demanded "a
python dictionary with no text before or after" — LLMs break that constantly
(they add "Sure! Here is..."). The JSON-contract version survives
prose-wrapping because the parser (see `_extract_json`) pulls the JSON out of
whatever surrounds it.

---

## 3. The package skeleton

```
src/ai_syllabi_etl/
├── __init__.py     # marks the folder as an importable Python package; __version__
├── __main__.py     # makes `python -m ai_syllabi_etl` work (delegates to cli.main)
├── config.py       # loads + validates + path-resolves config.yaml
├── extract.py      # stage 1: read raw table
├── clean.py        # stage 2: standardize
├── classify.py     # stage 3: AIMA labeling (3 backends)
├── validate.py     # stage 4: quality gates
├── load.py         # stage 5: persist CSV + SQLite
├── report.py       # stage 6: figures + checklist + report.md
└── cli.py          # the conductor: wires stages together, one command each
```

Why a package (`src/`) and not loose scripts? **Imports and tests.** Loose
scripts copy-paste code and drift; a package gives one importable source of
truth (`from ai_syllabi_etl.clean import clean_dataframe`) that both the CLI
and the test suite use. The `src/` layout is the packaging-community standard
that prevents accidentally importing the folder you're sitting in instead of
the installed package.

---

## 4. `config.py` — configuration loading

Key blocks:

```python
DEFAULTS: dict[str, Any] = {...}          # full default config, mirroring config.yaml
```
Every value has a default, so a *partial* `config.yaml` still works.

```python
def _deep_merge(base, override): ...
```
Recursive dict merge: your file's values override defaults **key by key** —
override `llm.model` and you keep `llm.timeout_seconds` from defaults. (A
shallow merge would wipe whole sections.)

```python
def _resolve(base: Path, value: str) -> str:
    p = Path(value)
    if p.is_absolute(): return str(p)
    return str((base / p).resolve())
```
**Path resolution**: all relative paths inside the config are resolved
against the *config file's directory*, so `python -m ai_syllabi_etl run`
works from any working directory. This one detail kills the classic
"works on my machine, fails in CI" bug.

```python
def _find_config(path):
    ...  # explicit --config arg → ./config.yaml → repo root/config.yaml
```
Three-tier lookup: explicit argument beats cwd beats repo root.

---

## 5. `extract.py` — stage 1: read, don't touch

```python
df = pd.read_csv(p, dtype=str)
```

**`dtype=str` is the single most important line in this file.** Without it,
pandas would type-infer `Year ?` into floats (`2018.0`) and your sentinel
strings into a mixed mess. Reading *everything as strings* defers all
interpretation to the cleaning stage, where it's explicit, logged, and
testable. This is the "extract ≠ transform" separation made real.

The error paths are deliberate:

```python
if suffix == ".pdf":
    raise ExtractError("PDF input is on the roadmap ... Convert the syllabi to CSV/XLSX first")
```
Fail **loudly with guidance** instead of silently producing garbage.

```python
class PdfExtractor:
    def extract_text(self) -> str: ...      # all pages joined
    def extract_section(self, *headings):   # e.g. extract_section("outcomes", "objectives")
```
Groundwork for the future PDF→columns stage: finds a heading line, captures
until the next heading-like line. Same job you did by eye when filling the
Google Form.

---

## 6. `clean.py` — stage 2: the dataset's fingerprints become rules

### Header mapping (finding #1)

```python
def normalize_header(column):
    text = unicodedata.normalize("NFKC", str(column))   # 'A' vs fullwidth 'Ａ' → same char
    text = re.sub(r"\s+", " ", text).strip().lower()    # "course  content" → "course content"
    text = text.rstrip("?").strip()                     # "Year ? " → "year"
    return text

EXPECTED_COLUMNS = {"which country": "country", ..., "what is the course content/topics": "course_topics"}
```

Your headers have *trailing spaces, double spaces, stray question marks* —
normalize first, then look up in the map. If a column isn't in the map, it
falls through to `snake_case()` (so a future re-export with a new question
still lands with a sane name + a log entry, not a crash).

### Sentinels (finding #2)

```python
SENTINELS = {"", "not mentioned", "n/a", "na", "none", "-", "--",
             "not specified", "not available", "none mentioned",
             "not applicable", "no prerequisites"}

def clean_text(value, preserve_newlines=True):
    if is_sentinel(value): return None      # NaN in pandas
    ...                                     # NFKC, \r\n → \n, collapse runs of spaces
```

Why this matters: `"not mentioned"` is not data — it's a *transcriber's
note*. Treating it as a real topic would poison classification; treating it
as a value in `"Year ?"` would break parsing. Converting to `None` lets
pandas' `.notna()` give honest completeness numbers (the difference between
raw 113 and clean 103 for topics is exactly these sentinels).

**Caveat baked into DATA_DICTIONARY.md:** a missing value means "the Google
Form didn't capture it", which is *not* proof the PDF lacked it. Don't
over-interpret completeness.

### Year parsing (finding #3)

```python
_YEAR_RE = re.compile(r"(\d{4})")
def parse_year(value):
    ...
    match = _YEAR_RE.search(str(value))
    year = int(match.group(1))
    return year if 1900 <= year <= 2100 else None
```

Regex-first-4-digits handles `2018-01-01`, `2022`, `c. 2015 edition`. The
band check rejects garbage like `1850` (there's a validation test proving
exactly that case warns downstream).

### The three splitters (findings #4, #5, #6)

```python
_BULLET_RE   = re.compile(r"^\s*(?:[○•▪◦‣●·*+-]|\d+[.)])\s*")   # strips ○, •, -, 1. 2)
_NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s*")
```

- `split_items(v, seps=(";", "|"))` — assessment/teaching cells.
- `split_outcomes(v)` — per line, strip numbering: your outcomes are numbered
  lists, so `"1. Understand search"` → `"Understand search"`.
- `split_topic_items(v)` — per line, strip bullets, **commas preserved**.

That last one is a design decision, not an accident: comma-splitting
`"Search, A* and planning"` would destroy a real topic phrase. Line-based
splitting keeps phrases intact; fragments only appear when the *source cell
itself* has a line break mid-sentence (and the LLM backend handles those).

### The orchestrator + audit trail

```python
def clean_dataframe(raw):
    df, log = standardize_columns(raw)
    df.insert(0, "syllabus_id", [f"S{i:03d}" for i in range(1, len(df)+1)])
    for col in text_columns:
        before_missing = df[col].isna().sum()
        df[col] = df[col].map(clean_text)
        filled = after_missing - before_missing
        if filled: log.append({"rule": "sentinel_to_missing", "column": col, "result": str(filled)})
```

- **`syllabus_id` is assigned in raw order, before any value changes** — so
  `S042` in the clean table is always raw row 42. Traceability 1:1.
- **No row is ever dropped.** Cleaning changes *values*, never *records*.
- **The `log` is the audit trail**: every applied rule + how many cells it
  touched. When someone asks "why is this cell empty?", the answer is in the
  log, not in your memory. Industry term: *data lineage*.

---

## 7. `classify.py` — stage 3: your prompts, industrialized

This is the biggest file; it converts your manual LLM workflow into
software. The core concept: **Strategy pattern** — one interface,
three interchangeable implementations.

```python
class Backend(Protocol):
    def classify_batch(self, syllabus_id, field, texts) -> list[tuple[int, float]]: ...
```
Any object with `classify_batch` works. The pipeline doesn't know or care
whether the "brain" is regexes or Llama-3.

### 7.1 The taxonomy loader

```python
@dataclass(frozen=True)  class TaxonomyClass: id, name, keywords
@dataclass(frozen=True)  class Taxonomy:
    classes: tuple[TaxonomyClass, ...]
    @classmethod def load(cls, path)         # json → objects, validates ids
    def prompt_block(self)                   # renders classes as prompt text
```
`frozen=True` = immutable after load; a typo can't mutate shared state.

### 7.2 The rule backend (deterministic, offline, free)

```python
def _has_keyword(low_text, keyword):
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}s?(?![a-z0-9])"
    if re.search(pattern, low_text): return True
    if not re.fullmatch(r"[a-z0-9 ]*", keyword):   # symbolic like "a*"
        return keyword in low_text
    return False
```

Three regex ideas worth learning:

1. **Lookarounds `(?<![a-z0-9]) ... (?![a-z0-9])`** = word boundaries that
   actually work: `search` inside `research` is rejected (preceded by `e`),
   but `"A* search"` matches.
2. **`s?`** = plural tolerance: keyword `decision tree` matches
   `"decision trees"`.
3. **The fallback branch** exists because `a*` ends in a non-word char —
   the trailing lookahead would fail against `"A* search"`, so symbolic
   keywords get a plain substring test instead.

Scoring + tie-break:

```python
def score_text(self, text):
    for cls in classes:                      # count keyword hits per class
        hits = [k for k in cls.keywords if _has_keyword(low, k)]
        if len(hits) > best_hits or (len(hits) == best_hits and total_len > best_len):
            best_id = cls.id
    confidence = min(1.0, best_hits / 3.0)   # 3+ hits ⇒ full confidence
```
Winner = most hits; ties broken by **total matched keyword length**
(longer keywords are more specific: `constraint satisfaction` beats
`search`). Zero hits → class 7 (Other), confidence 0 — honest, not fake.

### 7.3 The OpenAI-compatible backend (your LM Studio workflow, hardened)

```python
def _chat(self, user_content):
    response = requests.post(f"{self.base_url}/chat/completions",
        json={"model": self.model, "temperature": 0.0,
              "messages": [{"role": "system", ...}, {"role": "user", user_content}]},
        headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
```
One HTTP POST to any OpenAI-compatible server — LM Studio, Ollama, vLLM, or
OpenAI itself. `temperature: 0.0` = max determinism (same input → same
classification), which you *want* for research reproducibility.

The response parsing gauntlet — LLMs break format promises, so:

```python
def _extract_json(content):          # try ```json fence first, then first '{' .. last '}'
def _parse_response(content):        # validate shape; skip malformed entries
def _coerce_class(value):            # 5 | "5" | "5. Machine Learning" | "Machine Learning"
```

Resilience ladder (the part your manual workflow had no answer for):

```python
for attempt in range(1, self.max_retries + 1):
    try: ...parse & align...; return results
    except Exception: time.sleep(2 ** (attempt - 1))       # 1s, 2s, 4s backoff
if self.fallback_to_rule:
    return self.rule.classify_batch(...)                   # graceful degradation
raise ClassificationError(...)                             # or fail loudly
```
- **Retry with exponential backoff** — transient server hiccups don't kill a 113-syllabus run.
- **Per-item alignment**: the model returns a dict keyed by topic text; items it *skipped or reworded* fall to the rule scorer individually. One bad response costs one item, not the run.
- **Fallback backend** = the run always produces output; the `backend` column in `topic_classifications.csv` records *which* engine labeled each item, so you can audit exactly that.

### 7.4 The pipeline helpers

```python
def classify_dataframe(clean_df, taxonomy, backend, fields=("course_topics", "course_outcomes")):
    for record in clean_df.to_dict(orient="records"):
        items = FIELD_SPLITTERS[field_name](record.get(field_name))
        results = backend.classify_batch(sid, field_name, items)
        rows.append({... "class_id": cid, "label": taxonomy.name_of[cid],
                     "backend": backend.name, "confidence": conf})
```
Output = **long-format table**: one row per (syllabus, field, topic item).
Long format is the analysis-friendly shape (every aggregation is a
`groupby`), versus the wide raw table (one row = one syllabus). You'll use
both: wide for completeness stats, long for everything topic-related.

```python
def coverage_table(class_df, taxonomy, total_syllabi, field):
    # per class: n_topics (items), n_syllabi (distinct), pct_syllabi
```
The RQ1 metric: *share of syllabus that touch each theme* — robust to
syllabi that list 50 topics vs 5 (counting raw items would bias toward
verbose syllabi).

---

## 8. `validate.py` — stage 4: prove the pipeline didn't lie

Design philosophy in one line: **structural problems fail; data imperfections warn.**

```python
def add(name, status, detail): checks.append({"name": name, "status": status, "detail": detail})
```
Nine gates, each born from a way pipelines *actually* corrupt data:

| Gate | Catches |
|---|---|
| `row_count_preserved` | a "helpful" `dropna()` in cleaning silently deleting 30 rows |
| `unique_ids` | id collisions breaking the 1:1 traceability |
| `required_columns` | a renamed question in next year's form export |
| `no_sentinel_residues` | new sentinel wording ("N.A.", "Not Given") the cleaner doesn't know |
| `year_range` | typo'd years (`1850`), with row ids in `anomalies` |
| `topic_coverage` | extraction regression (suddenly 40% of syllabi have no topics) |
| `taxonomy_labels` | an LLM inventing class `9` |
| `duplicate_records` | the same course uploaded twice |
| `completeness_pct` | (report only) per-column missingness for the dictionary |

```python
overall = "pass"
for check in checks:
    if STATUS_ORDER[check["status"]] > STATUS_ORDER[overall]: overall = check["status"]
```
Worst check wins: any `fail` ⇒ run exits non-zero ⇒ **CI goes red**. That's
the whole point: quality gates are only real if they can block automation.

---

## 9. `load.py` — stage 5: make it durable and queryable

```python
for key, filename in CSV_TABLES.items():
    df.to_csv(out / filename, index=False, encoding="utf-8")     # utf-8: your data has ○, é, ’...

with sqlite3.connect(db_path) as conn:
    df.to_sql(table, conn, if_exists="replace", index=False)
    conn.execute("VACUUM")
```

Why *both* formats:

- **CSV** = human-readable, diffable, opens anywhere, uploads to Kaggle.
- **SQLite** = a real database in one file — `SELECT label, COUNT(*) FROM
  topic_classifications GROUP BY label` runs without loading anything into
  pandas. `if_exists="replace"` makes every run idempotent: re-running never
  duplicates rows.
- `VACUUM` compacts the file after replaces.

`quality_report.json` is written here too — validation results are *data*,
so they're persisted next to the data they describe.

---

## 10. `report.py` — stage 6: your 19-point checklist, automated

### The RQ tables (all computed, none hardcoded)

```python
cov_topics   = coverage_table(class_df, taxonomy, total, field="course_topics")     # RQ1
teaching     = method_counts(clean_df["teaching_methods"])                          # RQ2
assessment   = method_counts(clean_df["assessment_methods"])                        # RQ3
cov_outcomes = coverage_table(class_df, taxonomy, total, field="course_outcomes")   # RQ4
```

### The 19-point checklist as code

Your original org file listed 19 manual checks for every figure
("title", "font y-label 14", "values on bars", "percentages correct",
"check capitalization for all", ...). Two functions turn that into software:

1. **Builders encode the checklist** (constants mirror your spec):

```python
FIG_WIDTH, FIG_HEIGHT = 1000, 500        # your "10 x 5 inches" at 100 dpi
TITLE_FS, AXIS_FS, TICK_FS, BAR_FS = 16, 14, 10, 10
BAR_WIDTH_V, BAR_WIDTH_H = 0.6, 0.5      # your vertical/horizontal bar spec
PALETTE = {1: "#0072B2", 2: "#D55E00", ...}   # Okabe-Ito, CVD-safe

fig = go.Bar(..., text=texts, textposition="outside", textfont=dict(size=BAR_FS))
fig.update_yaxes(range=[0, vmax * 1.15]) # your "y-axis range" + label headroom
```
The count-axis title carries your item #17: `f"Number of syllabi covering (out of {total})"`.

2. **`verify_figure()` re-checks the *finished* figure** by inspecting the
   live Plotly object — title present, axis titles present, font sizes match,
   bar text present, every text contains `%`, **and the percentages are
   recomputed and compared** against expected strings:

```python
"check if percentages correct": texts == meta["expected_texts"]
"check capitalization for all": _capitalization_ok([title, x_title, y_title])
```
Results land in `output/report_checklist.json` — currently **5/5 figures,
19/19 items each**. The same checklist you ticked by hand, now provable in CI.

### `report.md` — generated findings

The markdown report is written from the computed tables (top themes, top
methods, quality summary, reproduction commands) — nothing hand-typed, so
re-running with a new backend regenerates everything.

---

## 11. `cli.py` — the conductor

```python
STAGES = ("extract", "clean", "classify", "validate", "load", "report")

def run_pipeline(cfg, up_to):
    raw = extract(cfg["input"]);          if stop == 0: return 0
    clean_df, log = clean_dataframe(raw); if stop == 1: return 0
    class_df = classify_dataframe(...);   if stop == 2: return 0
    ...
```

- **Cumulative stages**: `classify` runs extract+clean first, so every
  command produces a correct result without intermediate files. `run` = all six.
- **Exit codes are the CI contract**: `0` = success, `1` = quality gate
  failed, `2` = bad config/input. GitHub Actions fails automatically on
  non-zero — no special wiring needed.
- Console output mirrors the audit trail (`[clean] 113 rows preserved, 6
  column(s) had sentinel values converted`).

---

## v1 PDF intake — `schema.py`, `extraction.py`, `pdf_intake.py`, `validation.py`

The PDF-first revision (spec: issue #1) adds these modules, exercised by
`tests/test_extraction.py` (plain-dict seam tests), `tests/test_validation.py`
(validation-boundary tests), `tests/test_extraction_cache.py` (extraction-
cache tests), `tests/test_llm_extraction.py` (the `llm` backend against a
stub OpenAI-compatible server, offline) and `tests/test_pdf_pipeline.py`
(fixture PDFs):

- **`schema_contract.yaml`** (repo root, next to `config.yaml`) — the
  schema contract's *configurable* half: the three closed vocabularies
  (`course_level`, `teaching_method`, `assessment_methods`) with the form
  spec's exact canonical value strings, plus the synonym→canonical alias
  map the extractor's near-variants normalize through (`lecture` →
  `Lecture based learning`, `undergrad` → `Undergraduate`, …). Maintain
  this file, never code; matching is case- and whitespace-insensitive;
  `not mentioned` needs no alias (it normalizes to null) and
  `Other/not clear` is a legal distinct label everywhere.
- **`schema.py`** — the contract's *code* half: the 14 `FIELD_COLUMNS`
  (the form spec is canonical; the legacy CSV exported only 12),
  `LIST_FIELDS` (topics, outcomes, tools, textbooks, teaching method,
  assessment methods — dataset cells are JSON arrays; `tools` is a single
  inferred field, no hardware/software split), and two entry points:
  `normalize_record()` (empty→null, `not mentioned`→null, alias map, list
  cleanup) and `validate_record()` (14 fields present, real nulls allowed,
  types, vocabulary membership). `normalize_record` returns unmappable
  values alongside the record so validation can fail on them.
- **`tests/fixtures/pdfs/`** — four tiny authored PDFs: two distinct one-page
  syllabi, one byte-identical duplicate of the first, and one blank-page PDF
  with no text layer (a simulated scan). Hand-written minimal PDF syntax, so
  CI needs no PDF-authoring dependency.
- **`extraction.py`** — the *extraction-backend seam*: the Strategy boundary
  that turns one PDF's text into a dict of form-field values. `mock` returns
  canned records (offline tests/CI); **`llm` (T6)** talks to any
  OpenAI-compatible chat server (LM Studio, Ollama, vLLM, cloud) — endpoint,
  model, sampling parameters, timeout, retries and API-key env var are all
  config (the `llm` block), never code. Its prompt is built once from the
  schema contract + `prompts/bloom_verbs.txt` (the owner's Bloom verb table,
  one verb per line) and encodes: verbatim extraction with no translation,
  real nulls, the closed vocabularies' canonical values, JSON-array list
  fields, tools inferred from other sections, and the Bloom verb rule
  (outcomes identified by content not title; collect a line iff it starts
  with or contains a listed verb, stem-matched case-insensitively; for
  non-English text the rule applies semantically, with the English list as
  backstop). Conformance check: all 14 keys present, scalars string-or-null,
  list fields string arrays — violations (and non-JSON, HTTP errors) are
  retried up to `llm.max_retries` with backoff; exhaustion raises
  `ExtractionError`, which the intake stage turns into an all-null record
  with `status: "failed"` + warning so the run completes and the failure
  stays visible. Vocabulary canonicalization is deliberately *not* a retry
  condition: the seam's alias map owns it, and unmappable values surface as
  `issues` for validation to fail on.
- **`pdf_intake.py`** — the v1 stages: SHA-256 content hashing → dedup
  (byte-identical files collapse to the lexicographically-first filename;
  drops are logged, never silent) → `syllabus_id` assignment in lexicographic
  filename order *after* dedup → **extraction cache (T4)**: the previous
  run's `extraction_log.json` doubles as the cache index keyed by content
  hash; a file with a clean, same-backend cached entry skips text extraction
  and the backend call entirely, while new files, scans, issue-carrying
  records, other backends and `--force` runs extract fresh → pypdf text
  extraction (no text layer = an all-null record plus a warning) →
  extraction backend (an `ExtractionError` — e.g. the `llm` backend
  exhausting its retries — becomes an all-null record with
  `status: "failed"` + a warning, so the run completes with the failure
  visible) → **normalize + validate at the seam** (structural
  violations raise; unmappable vocabulary values stay in the record and are
  logged under `issues` in the extraction log) → the validation stage below
  → outputs: `output/syllabi_dataset.csv` (real nulls as empty cells, list
  fields as JSON arrays) and `output/extraction_log.json` (per-file status,
  hash, dropped duplicates, warnings, issues, normalizations, plus the
  cached `fields` and `cache: "hit"|"miss"` provenance that make the log
  the next run's cache index). The CLI runs this flow whenever the config
  `input` is a directory; `--force` bypasses the cache; the CSV flow below
  stays for the legacy dataset until its retirement ticket.
- **`validation.py`** — the v1 *normalize-then-assert* stage. Normalization:
  `year` values become ISO dates where parseable (`2023` → `2023-01-01`,
  matching the manual export's `YYYY-01-01` convention; `September 2023` →
  `2023-09-01`; US `M/D/YYYY` and `Month D, YYYY` supported; seasons and
  academic-year ranges stay verbatim) — every action is logged per record
  under `normalizations`. Assertion runs `validate_record()` over the exact
  records about to be written, so a PASS certifies the file on disk.
  Severity model: the file-count gate, structural contract violations and
  unmappable vocabulary values **fail the run** (exit 1; the message names
  file, field and value, and the dataset is still written for audit);
  completeness (an entirely empty form field), scan/failed records and
  sentinel-like backstop values only **warn** (exit 0).

## 12. The tests — how you *know* it works

`tests/fixtures/sample.csv` = 5 handcrafted rows with the **exact raw
headers** (trailing spaces included) covering every edge: sentinel year,
missing country, `○`-bulleted topics, numbered outcomes, a quantum-computing
syllabus that must classify as *Other*.

| File | Proves |
|---|---|
| `test_clean.py` | every header renames; `2018-01-01`→2018; sentinels→NaN; bullets/numbering stripped; **commas not split**; ids `S001..` unique; rows never dropped; audit log entries recorded |
| `test_classify.py` | `"research methods"` does **not** trigger `search` (lookarounds); plurals match; `a*` matches; each AIMA class maps correctly; JSON extracted from fences *and* prose; `"5. Machine Learning"` coerces to 5; **LLM failures fall back to rule per-item, and raise only when fallback is off** |
| `test_validate.py` | healthy fixture → PASS; row loss → FAIL; missing column → FAIL; invented class → FAIL; year 1850 → WARN + anomaly; duplicate record → WARN |
| `test_pipeline.py` | the real CLI, end to end: fixture → all outputs exist → quality not FAIL → **every figure passes 19/19** → report links figures |

And the v1 PDF-flow tests:

| File | Proves |
|---|---|
| `test_extraction.py` | the backend seam + schema contract: alias mapping, real nulls, list cleanup, wrong types rejected, unmappable values surfaced |
| `test_validation.py` | normalize-then-assert: fail model (file-count gate, unmappable values, structural violations), warn model (completeness, scans, sentinels), ISO-date normalization + audit log |
| `test_pdf_pipeline.py` | fixture PDFs end to end: dedup, lexicographic ids, all-null scan record, exit codes, the on-disk dataset + extraction log |
| `test_extraction_cache.py` | the extraction cache at the intake + pipeline seams: clean same-backend hits perform zero extractions and write a byte-identical dataset; scans/issues/other backends/old-format logs are retried; renamed files still hit by hash; contract-stale cache entries fall back to fresh extraction; `--force` re-extracts everything and only new files are extracted when one is added |
| `test_llm_extraction.py` | the `llm` extraction backend against a stub OpenAI-compatible server on localhost (offline): prompt contract (verbatim, real nulls, canonical vocabularies, JSON arrays, Bloom verb rule with the semantic rule), JSON parsing + shape conformance, bounded retries on invalid/HTTP-failing output, exhaustion → `ExtractionError`; and the intake failure path: an exhausted backend yields all-null records with `status: "failed"` + warning, the run completes, and failed entries are never cached as successes |

Testing concept: the `mock` backend makes LLM behavior **deterministic in
tests** — no server, no network, no flakiness. This is why `mock` exists at all.

---

## 13. `.github/workflows/ci.yml` — CI in plain words

```yaml
on: [push, pull_request]           # run on every push + every PR
strategy:
  matrix: python-version: ["3.10", "3.11", "3.12"]   # same tests, 3 Pythons
- python -m pip install -e .                        # install the package itself
- ruff check --select E9,F63,F7,F82 src tests       # syntax + undefined-name errors only
- python -m unittest discover -s tests -t . -v      # the 54 tests
- python -m ai_syllabi_etl run --backend rule       # full pipeline smoke run on real data
- actions/upload-artifact                           # attach output/ to the run
```

The smoke run is the interesting part: **CI executes the actual pipeline on
the actual dataset** on every push. If a future edit breaks cleaning, you
know from the red badge before you ever pull.

---

## 14. Concept glossary (the vocabulary you just learned)

| Term | Meaning | Where you saw it |
|---|---|---|
| **ETL** | Extract-Transform-Load: the standard data-engineering loop | The whole repo |
| **Schema** | The agreed column set + types of a table | `EXPECTED_COLUMNS`, required_columns gate |
| **Sentinel value** | A string that pretends to be data but means "nothing" (`not mentioned`) | `SENTINELS` |
| **Idempotency** | Running twice gives the same result as running once | `if_exists="replace"`, deterministic rule backend, `temperature=0` |
| **Data lineage / audit trail** | Machine-readable record of *what* was done to *which* values | `cleaning log`, `backend` column |
| **Data quality gate** | An automated check that can fail a pipeline run | `validate.py` |
| **Completeness** | % of non-missing values per column | `quality_report.json` |
| **Long vs wide format** | One-row-per-observation vs one-row-per-entity | `topic_classifications` (long) vs `syllabi_clean` (wide) |
| **Strategy pattern** | One interface, swappable implementations | `RuleBackend` / `OpenAICompatibleBackend` / `MockBackend` |
| **Graceful degradation** | Falling back to a lesser mode instead of crashing | `fallback_to_rule`, per-item rule rescue |
| **Strict output contract** | Demanding machine-parseable output (JSON) with a tolerant parser | `prompts/`, `_extract_json` |
| **Deterministic baseline** | A free, reproducible method to compare fancy methods against | `rule` backend in CI |
| **Inter-rater style audit** | Record *who* (which engine) rated each item, to spot-check later | `backend` + `confidence` columns |
| **CI (Continuous Integration)** | Every push runs tests + the pipeline automatically | `ci.yml` |
| **Fixture** | Small handcrafted input with known edge cases | `tests/fixtures/sample.csv` |

---

## 15. Reproduce everything yourself

```bash
git clone https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline.git
cd AI_Course_Syllabi_ETL_Pipeline
python -m pip install -e .

python -m unittest discover -s tests -t .      # 54 tests
python -m ai_syllabi_etl run --backend rule    # full pipeline on the 113-syllabus dataset
# then read output/report.md and open output/*.html
```

With LM Studio running a model: set `backend: openai` in `config.yaml` and
re-run — same data, same validation, smarter labels.
