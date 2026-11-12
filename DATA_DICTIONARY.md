# Data Dictionary — AI Course Syllabi ETL

This documents the **v1 dataset**: `output/syllabi_dataset.csv` (one row per
distinct syllabus PDF) and its companion audit file
`output/extraction_log.json`. Both are produced by
`python -m ai_syllabi_etl run`.

> **History note:** this repo's first dataset was the archived Kaggle CSV
> (`data/archive/AI_course_syllabi_CSV.csv`) — the owner's *manually
> transcribed* example output. It is no longer an input (the pipeline reads
> only the PDF folder); it is kept for cross-checking extracted rows and is
> documented in the appendix at the bottom.

## Dataset at a glance

| | |
|---|---|
| File | `output/syllabi_dataset.csv` (UTF-8, RFC-4180 CSV) |
| Grain | 1 row = 1 **distinct** syllabus PDF (byte-identical duplicates collapsed by SHA-256 before extraction) |
| Row order | `syllabus_id` in **lexicographic filename order after dedup** — stable across re-runs for an unchanged folder |
| Columns | 3 provenance + 14 form fields (the original Google-Form schema; the archived CSV exported only 12 — its export never captured `course_level` or `target_audience`) |
| Missing values | **Real nulls** — empty cells in the CSV, `null` in the log. No sentinel words, no placeholder strings |
| List fields | 6 fields are written as **JSON arrays** (`["item", …]`) |
| Closed vocabularies | 3 fields restricted to the form spec's canonical values (`schema_contract.yaml`) |

## Provenance columns

| Column | Type | Contents |
|---|---|---|
| `syllabus_id` | text, `S001…` | Stable sequential id assigned **after dedup**, in lexicographic `source_file` order. Recomputed on every run, so renaming files can renumber rows (rows still 1:1 with distinct files) |
| `source_file` | text | Filename of the kept (dedup representative) PDF, as scanned from the input folder |
| `content_hash` | text | SHA-256 hex digest of the PDF's bytes. The dedup key and the extraction-cache key — identical content always yields one row |

## The 14 form fields

Field descriptions come from the original Google-Form spec
(`reference/form questions .txt`); the schema contract
(`schema_contract.yaml`) is the in-repo source of truth. Extraction is
**verbatim, no translation** — value wording is the syllabus's own wording
(vocabulary fields excepted, see below).

| Column | Format | Semantics / interpretation |
|---|---|---|
| `country` | scalar | Country where the course is taught; may be inferred from the institution's location |
| `institution` | scalar | University or school name |
| `year` | scalar, normalized | When the course runs. Normalized at validation to an ISO date **where parseable** (`2023` → `2023-01-01`, matching the manual export's convention; `September 2023` → `2023-09-01`; `9/1/2023` US-style and `Month D, YYYY` supported). Seasons (`Fall 2024`) and academic-year ranges (`2024/2025`) stay **verbatim** — normalization never invents data. Every normalization is logged per record under `normalizations` |
| `course_level` | scalar, **closed vocabulary** (single choice) | One of the canonical values below |
| `target_audience` | scalar | The group the course is offered to (e.g. engineers, business students) |
| `course_title` | scalar | Official course title as it appears on the syllabus |
| `prerequisites` | scalar | Courses or knowledge areas expected before the course |
| `course_description` | scalar | Catalog-style description / syllabus intro paragraphs |
| `course_topics` | **JSON array** | The AI topics the course covers, one item per topic line/bullet |
| `course_outcomes` | **JSON array** | Learning outcomes, collected under the **Bloom verb rule** (below) — not to be confused with "course objectives" |
| `tools` | **JSON array** | Languages, frameworks, platforms students use. **No dedicated section in a syllabus** — inferred from other sections; treat as best-effort |
| `textbooks` | **JSON array** | Textbook/references; no distinction between main and secondary texts |
| `teaching_method` | **JSON array**, **closed vocabulary** (multi-choice) | One or more canonical values. The form spec calls this "sometimes the course format" |
| `assessment_methods` | **JSON array**, **closed vocabulary** (multi-choice) | The grading scheme: one or more canonical values |

## Null semantics

- **Missing = real null** (empty CSV cell / `null` in the log). The extractor
  is instructed to emit nulls, never placeholder words.
- `not mentioned` is a legal *canonical* vocabulary value only inside the
  three closed vocabularies (the form spec offers it as a choice); it is
  normalized to **null** before the dataset is written — in vocabulary list
  fields the item is dropped from the array. In other fields a backend that
  still emits such words stays verbatim and triggers a validation warning
  (next bullet).
- Outside vocabularies, a backend that emits the words `not mentioned`,
  `none`, `n/a`… (sentinel-like values) triggers a **validation warning** —
  sentinels are a backstop, not a mechanism (per ADR-0001).
- A file with **no text layer** (a scan — no OCR in v1) or an LLM backend
  that failed after retries yields an **all-null record** with
  `status: "scan"` or `"failed"` in the log and a validation warning. The
  row is kept (never dropped): the file-count gate requires
  N distinct-hash files in → N records out.
- **Completeness means extraction coverage, not syllabus content**: an empty
  cell can mean the syllabus omitted it *or* the extractor missed it (the
  archived CSV has the mirror-image caveat for manual transcription). An
  entirely empty field across all records is a validation warning.

## JSON-array list fields

Six fields are lists (`course_topics`, `course_outcomes`, `tools`,
`textbooks`, `teaching_method`, `assessment_methods`) and are serialized as
JSON arrays in the CSV cell, e.g.
`["Search", "Machine learning", "Ethics"]`. Consumers should parse the cell
(JSON) before splitting/counting. Empty lists never reach the CSV: a list
that empties out during normalization (e.g. all items were `not mentioned`)
becomes **null**, as does a list field in an all-null record.

## Closed vocabularies + alias map

Three fields are restricted to the form spec's exact canonical value strings
(defined in `schema_contract.yaml` — config, not code; matching is case- and
whitespace-insensitive):

- `course_level` (single choice): `School`, `Undergraduate`, `Master`, `PhD`
- `teaching_method` (multi-choice): `Collaborative or Group-based learning`,
  `Lecture based learning`, `Project based learning (i.e., team project)`,
  `Learning using case study`, `Flipped classroom`, `LAB demos`, `Seminar`,
  `Workshop`, `Online course`, `Hybrid learning (face-to-face and online)`
- `assessment_methods` (multi-choice): `Short Quizzes`, `Assignments`,
  `Final Exam`, `Midterm Exam`, `Project`, `Attendance or participation`,
  `Presentation`, `Report`
- Each vocabulary also allows `not mentioned` (normalizes to null — see
  above) and `Other/not clear` — a **legal distinct label** meaning the
  syllabus states something outside the enumerated choices (kept verbatim,
  countable).

The backend may emit near-variant wording; the alias map (same file)
normalizes it — e.g. `lecture`, `lecture-based`, `lectures` all →
`Lecture based learning`; `undergrad`, `bachelor` → `Undergraduate`;
`homework` → `Assignments`. The archived CSV's `Short Quizes` spelling was a
transcription artifact and is **not** canonical.

**Unmappable values:** a value that has no alias, is not canonical, and is
not `Other/not clear` is kept verbatim in the record, logged under `issues`
in `extraction_log.json` (naming file, field, value), and the validation
stage **fails the run** on it (exit 1) — canonicalization is never guessed.
Vocabulary fields exist to be counted, so synonyms must land in one
category.

## The Bloom verb rule (`course_outcomes`)

Outcome lines are collected only when they start with or contain a verb from
the Bloom's Taxonomy table (`prompts/bloom_verbs.txt` — the owner's table,
derived from `reference/bloom verbs .txt`), matched case-insensitively on
the stem (`analyz*`, `construct*`). The outcomes *section* is identified by
content, not title (titles vary: "Outcomes", "Objectives", "Learning
Goals", …). For non-English text the rule applies **semantically** (verb
equivalents in any language), with the English list as backstop. Lines
without a Bloom verb are not collected — this is the discriminator against
"course objectives".

## `extraction_log.json` — the audit trail

Top level:

| Key | Contents |
|---|---|
| `input_folder`, `backend` | Where the run read, which extraction backend ran |
| `cache` | `{hits, misses}` for the run |
| `files_seen`, `distinct_files` | Folder scan totals (before/after dedup) |
| `dropped_duplicates` | Each collapsed copy: `file`, `hash`, `kept_as` |
| `records` | One entry per distinct file (below) |

Each record entry:

| Key | Contents |
|---|---|
| `syllabus_id`, `source_file`, `content_hash` | Same values as the dataset row |
| `backend` | Which engine filled `fields` (informational; e.g. cache hits keep the original backend) |
| `status` | `ok` · `scan` (no text layer) · `failed` (extraction error after retries) |
| `warnings`, `issues` | Human-readable strings: warnings = kept-but-imperfect (scan/failed/sentinel-like); issues = unmappable vocabulary values / contract problems (issues fail validation) |
| `cache` | `hit` \| `miss` — whether this file's fields were reused from the previous log |
| `fields` | The 14-field dict exactly as written to the dataset (arrays for list fields) |
| `normalizations` | Per-record log of every change validation made (e.g. year → ISO date) |

Re-run economics: the log doubles as the **cache index**; a fully-cached
re-run writes a byte-identical dataset (only `cache` provenance differs).
`--force` re-extracts everything.

## Appendix — the archived Kaggle CSV (cross-checking reference)

`data/archive/AI_course_syllabi_CSV.csv` — [Kaggle: AI Course Syllabi](https://www.kaggle.com/datasets/ahmedabdulhakim/ai-course-syllabi)
(v2, 2024-08-10, **CC BY 4.0**). One row per syllabus (**113 rows**, no
duplicates), collected via Google search (`Artificial + Intelligence + AI +
Course + Syllabus filetype:pdf OR filetype:html`), **manually transcribed
through a Google Form** — each form question became a column. Coverage:
18 countries (US 66, India 19, …), years 2000–2024 (84 rows carry a year,
stored as `YYYY-01-01`).

Its columns are the pre-v1 rendering of the same form questions
(`Which country ? ` → `country`, etc.), cleaned by the dormant
`clean.py` stage: sentinels (`not mentioned`, `none`, `n/a`, `-`,
`not specified`, …) converted to missing, years parsed to integers,
whitespace normalized, and stable `syllabus_id`s (`S001…S113`) assigned in
raw row order before cleaning. The `Short Quizes` spelling was a
transcription artifact — the canonical value is `Short Quizzes`.

> **Interpretation caveat (mirrors the v1 caveat):** because transcription
> was manual, a missing value means *"the transcriber did not record it"* —
> it does **not** prove the original PDF omitted it. Treat completeness
> figures as form-coverage, not as syllabus content.

Use it to **cross-check** extracted rows against the owner's manual
transcription of (presumably) the same corpus — spot-check ~10 rows per the
spec's acceptance bar. It is not an input: the pipeline refuses table files.
