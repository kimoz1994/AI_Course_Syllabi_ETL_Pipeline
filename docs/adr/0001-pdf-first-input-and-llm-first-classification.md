# ADR-0001: PDF-first input and LLM-first classification with book-grounded RAG

**Status:** Accepted (2026-11-11). **Implementation status (2026-11-12):**
Decisions 1–4 are implemented as the v1 pipeline (tickets #2–#7); Decision 5
(taxonomy slimming) holds in the codebase; Decision 6 and classification
itself are **deferred** (dormant code) — see the scope revision below.
**Deciders:** Ahmed Abdulhakim (project owner), with agent assistance

## Context

The current pipeline ingests `data/raw/AI_course_syllabi_CSV.csv` — the output
of a **manual** Google-Form transcription of PDF syllabi. Several design
elements are artifacts of that manual stage rather than of the real problem:

1. `SENTINELS` (`not mentioned`, `none`, …) exist because a human had to type
   something into every form field. In real use, the pipeline's actual input is
   a **fresh set of PDF files**, and an automated extractor should emit real
   nulls for absent fields — sentinels are not the mechanism.
2. The taxonomy shipped with large keyword lists to feed the offline `rule`
   backend. The owner's proven workflow (and original prompts) instead uses the
   **high-level AIMA class structure** with the LLM doing the classification.
3. Classification quality improved substantially when the LLM was grounded
   with the **actual AIMA book** as guidance (a mini-RAG pattern) rather than
   relying on the model's knowledge alone.
4. The row-count quality gate was framed against the CSV; with PDF input the
   equivalent risk is silent file loss during extraction.

## Decision

1. **Stage 0 (planned): PDF → structured table.** Input becomes
   `data/pdfs/*.pdf` (one file = one syllabus). Extraction uses per-PDF text
   extraction plus an LLM field-extraction step under a strict schema contract
   mirroring the original Google Form field definitions (to be provided by the
   owner). The extractor emits **real nulls** for fields not present in the
   document.
2. **Sentinels demoted to a backstop** — kept in `clean.py` to catch legacy
   CSV data and sloppy extraction output, no longer a headline mechanism.
3. **Header normalization demoted to a backstop** — Stage 0 defines clean
   column names from the start; the CSV path keeps its handling unchanged.
4. **File-count gate** — validation's row-preservation check is recast as
   "N PDF files in → N syllabus records out" when Stage 0 runs.
5. **Taxonomy slimmed to schema** — 7 classes with short descriptions become
   the primary `taxonomy/aima_taxonomy.json`; keyword lists move to a separate
   offline-fallback file consumed only by the `rule` backend, which is
   explicitly labelled the deterministic CI baseline.
6. **Book-grounded classification (planned)** — the classification prompt
   incorporates retrieved passages from the AIMA book (owner will supply it)
   to ground LLM judgments; retrieval design to be specified in Stage-0
   tickets.

> **Correction (2026-11-11, on receiving the reference material):** the
> supplied book is *AIMA **3rd edition***, not 4th. The taxonomy class names
> above ("Knowledge, Reasoning & Planning", "Machine Learning") are
> **4th-edition part names**. Open decision for the grill session: use the
> 3rd-edition book's own part structure as the classification schema (keeping
> history with the owner's original prompts), or keep 4th-edition names with
> the 3rd-edition book as grounding text. Also received: **Bloom's Taxonomy
> verb table** + owner rule that outcome items are collected only when they
> contain a listed Bloom verb, and the outcomes section is identified **by
> content, not title**. Full inventory: `HANDOFF.md`.

> **Resolution (2026-11-12):** the owner replaced the 3rd-edition file with the
> **4th edition** (now in `reference/aima/`). The open decision above is
> resolved: the classification schema and the grounding text are both
> **4th edition** — no relabeling, no edition mismatch.

> **Scope revision (2026-11-12):** v1 of the pipeline is **extraction-only** —
> the output is a single dataset file (one row per distinct PDF, all form
> fields, real nulls, list-valued fields as JSON arrays). Topic
> classification (Decisions 5–6, including the book-grounded mini-RAG) is
> **deferred** to a later ticket; reporting/analysis is deferred too. Two new
> planned steps are recorded as roadmap items: **syllabus scraping**
> (auto-collect syllabus PDFs from university websites) and **reporting**.

## Consequences

- Stage 0 requires the owner's three inputs: the **PDF corpus**, the
  **Google-Form field definitions**, and the **AIMA book**.
- A `pypdf`-based text extractor (skeleton already in `extract.py`) plus an
  LLM extraction prompt must be built and evaluated.
- Accuracy of LLM classification must be reported **against the rule
  baseline** (deterministic comparison point; see GLOSSARY).
- The CSV path remains functional for backward compatibility and CI.
