# GLOSSARY

Domain vocabulary for the AI Course Syllabi ETL Pipeline. Skills and agents
should use these terms as defined here; propose additions via `/domain-modeling`.

## Data & pipeline

- **Syllabus record** — one row = one course syllabus (113 in the source CSV; the PDF corpus has ~119 files before dedup). Identified by a stable `syllabus_id` (`S001…`) assigned *before* any transformation — in raw input order (legacy CSV) or **lexicographic filename order after dedup** (PDF input) — so raw ↔ clean stay traceable 1:1.
- **Raw input** — the folder `data/pdfs/*.pdf` (one file = one syllabus), per ADR-0001. The Kaggle CSV (`data/raw/AI_course_syllabi_CSV.csv`) is **not an input**: it is the owner's manually-produced example output, kept only for comparison and as a test fixture.
- **Dedup** — collapsing byte-identical input files (SHA-256 content hash) to one representative before extraction. Dropped copies are recorded in the extraction log, never silently discarded.
- **Sentinel value** — a string that looks like data but means "nothing" (`not mentioned`, `none`, `n/a`). An artifact of manual Google-Form transcription — they exist only in the legacy CSV. The PDF extractor emits **real nulls** (empty cells), so on PDF input the sentinel scrubber never fires; kept as a validation backstop for legacy CSV data (per ADR-0001).
- **Bloom verb signal** — the owner's outcome-collection rule, **active in v1 as an extraction rule**: a line is collected as an outcome iff it starts with (or contains) a Bloom's Taxonomy verb from `reference/bloom verbs .txt`; the outcomes section is identified **by content, not title** (titles vary: "Outcomes", "Objectives", "Learning Goals", …). Verbs match case-insensitively on the stem (`analyz*`, `construct*`). For non-English text the rule is applied **semantically** by the LLM (verb equivalents in any language); the string-stem matcher remains the English backstop. The outcome section must not be confused with "course objectives".
- **Canonical vocabulary** — the form spec's exact value strings for the three closed vocabularies (`course_level`; `teaching_method`; `assessment_method`), e.g. `Short Quizzes` (the CSV's `Short Quizes` was a typo, not canonical). The LLM may emit near-variant wording (`lecture`, `lecture-based`); validation's alias map normalizes every value to canonical before the dataset is written; a value that cannot be mapped to a canonical choice (and isn't `Other/not clear`) fails the run. These fields exist to be **counted**, so synonyms must land in one category.
- **Cleaning log (audit trail)** — machine-readable record of every cleaning rule applied and how many cells it touched.
- **Quality gate** — an automated check in `validate.py` that can fail the run. Structural problems **fail** (exit code 1); data imperfections **warn**. Validation is **normalize-then-assert**: at the validation boundary the pipeline normalizes values (ISO dates, empty→null, synonym→canonical vocabulary mapping) and then asserts the result is clean, so a PASS certifies the file on disk.
- **Completeness** — percentage of non-missing values per column; means "the form/extractor captured it", **not** "the PDF contained it".
- **Long format** — one row per observation (`topic_classifications.csv`: one row per topic item). **Wide format** — one row per entity (`syllabi_clean.csv`). Aggregations happen in long format.

## Classification

> ⚠️ **Deferred out of v1 scope** (2026-11-12 scope revision): no classification
> runs in the v1 pipeline — topics are extracted as clean list-valued fields.
> The terms below apply when the classification ticket resumes (the
> **Bloom verb signal** above is the exception — it is an extraction rule and
> stays active).

- **AIMA taxonomy** — the 7-part classification schema from *Artificial Intelligence: A Modern Approach* (Foundations; Problem Solving; Knowledge, Reasoning & Planning; Uncertain Knowledge & Reasoning; Machine Learning; Communicating, Perceiving & Acting; Other). The **high-level class names + descriptions are the schema** (per ADR-0001); keyword lists are NOT the taxonomy. The reference book is the **4th edition** (owner-supplied 2026-11-12, replacing the 3rd-edition file), so the schema and the grounding text are the same edition — the ADR-0001 correction is resolved.
- **Topic item** — one topic/outcome line extracted from a syllabus record, the unit that gets classified.
- **Classification backend** — swappable engine implementing `classify_batch`: `rule` (keyword scorer), `openai` (any OpenAI-compatible LLM server), `mock` (canned, tests only). See Strategy pattern in `docs/WALKTHROUGH.md` §7.
- **Rule baseline** — the deterministic keyword backend; free, offline, reproducible. Used by CI as the fixed comparison point for LLM accuracy evaluation.
- **Book-grounded classification (planned, ADR-0001)** — classification prompt grounded with retrieved passages from the AIMA book itself (mini-RAG) instead of relying on the model's knowledge alone.
- **Coverage (syllabus-level)** — share of syllabi whose items touch a given class; the RQ1/RQ4 metric. Robust to verbose vs terse syllabi (unlike raw item counts).
- **`backend` / `confidence` columns** — per-item provenance: which engine labeled it and how sure. Enables inter-rater-style spot audits on low-confidence items.

## Reporting

- **Figure checklist** — the 19-point figure QA spec inherited from the legacy research workflow, encoded as constants and auto-verified by `verify_figure()`; results in `output/report_checklist.json`.
- **RQ1–RQ4** — the dataset's research questions: predominant topic categories (RQ1), teaching methods (RQ2), assessment methods (RQ3), emphasized outcomes (RQ4).

## Roadmap terms (not yet implemented)

- **OCR (planned)** — text recognition for image-only scanned PDFs. Out of v1 scope: a scan yields an all-null record plus a warning; OCR is a later upgrade ticket.
- **Reporting (deferred)** — the RQ1–RQ4 figures + figure checklist step; v1 of the pipeline ends at the extracted dataset file. Its requirements get their own ticket.
- **Syllabus scraping (planned)** — an initial pipeline step that scrapes university websites for syllabus files on a chosen subject/course, feeding Stage 0's PDF corpus (replacing the manual search-and-download that produced `reference/syllabi files/`). Its own later ticket.
- **Stage 0 / PDF extraction (planned)** — per-PDF text extraction + LLM field extraction under a strict schema contract mirroring the original Google Form fields; emits one row per distinct PDF with real nulls. Inputs all received (PDF corpus, form field definitions, AIMA 4th-edition book); design is being grilled → spec → tickets.
- **Topic classification (deferred)** — the AIMA classification of topic items (LLM or rule backend, book-grounded) is out of v1 scope per the 2026-11-12 scope revision; topics are extracted as clean list-valued fields instead. The taxonomy and backends remain in the codebase unused until this ticket.
- **File-count gate (planned)** — the row-preservation gate recast for PDF input: N **distinct-hash** PDF files in → N syllabus records out. A failed extraction emits an all-null record plus a warning (data-quality warning, not a structural failure).
