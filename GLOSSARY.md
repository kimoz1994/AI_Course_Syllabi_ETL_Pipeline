# GLOSSARY

Domain vocabulary for the AI Course Syllabi ETL Pipeline. Skills and agents
should use these terms as defined here; propose additions via `/domain-modeling`.

## Data & pipeline

- **Syllabus record** — one row = one course syllabus (113 in the source dataset). Identified by a stable `syllabus_id` (`S001…`), assigned in raw input order *before* any transformation, so raw ↔ clean stay traceable 1:1.
- **Raw input** — currently the Kaggle CSV (`data/raw/AI_course_syllabi_CSV.csv`); per ADR-0001, future raw input is a folder of syllabus **PDF files**.
- **Sentinel value** — a string that looks like data but means "nothing" (`not mentioned`, `none`, `n/a`). An artifact of manual Google-Form transcription. Cleaning converts them to real missing values; per ADR-0001 sentinels are a **backstop**, not a mechanism — the PDF extractor emits real nulls.
- **Cleaning log (audit trail)** — machine-readable record of every cleaning rule applied and how many cells it touched.
- **Quality gate** — an automated check in `validate.py` that can fail the run. Structural problems **fail** (exit code 1); data imperfections **warn**.
- **Completeness** — percentage of non-missing values per column; means "the form/extractor captured it", **not** "the PDF contained it".
- **Long format** — one row per observation (`topic_classifications.csv`: one row per topic item). **Wide format** — one row per entity (`syllabi_clean.csv`). Aggregations happen in long format.

## Classification

- **AIMA taxonomy** — the 7-part classification schema from *Artificial Intelligence: A Modern Approach*, 4th ed. (Foundations; Problem Solving; Knowledge, Reasoning & Planning; Uncertain Knowledge & Reasoning; Machine Learning; Communicating, Perceiving & Acting; Other). The **high-level class names + descriptions are the schema** (per ADR-0001); keyword lists are NOT the taxonomy.
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

- **Stage 0 / PDF extraction (planned)** — per-PDF text extraction + LLM field extraction under a strict schema contract mirroring the original Google Form fields; emits one row per PDF with real nulls. Blocked on: user-provided PDF corpus + form field definitions.
- **File-count gate (planned)** — the row-preservation gate recast for PDF input: N PDF files in → N syllabus records out.
