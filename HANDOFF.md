# HANDOFF — where we left off (2026-11-11)

Read this first if you're a session opening in this repo after a break.

## Status: stable baseline, revision pending

- The **CSV-ingestion pipeline** is complete and green: 113/113 rows preserved,
  3,248 items classified (rule backend), quality PASS, 5/5 figures pass the
  19-point checklist. 54 tests OK. CI badge is green
  ([latest run](https://github.com/kimoz1994/AI_Course_Syllabi_ETL_Pipeline/actions)).
- The **next major revision is agreed but NOT started** — do not pre-build it.
  It is recorded as accepted architecture in
  [`docs/adr/0001-pdf-first-input-and-llm-first-classification.md`](docs/adr/0001-pdf-first-input-and-llm-first-classification.md):
  1. **Stage 0: PDF → structured table.** Input becomes `data/pdfs/*.pdf`;
     per-PDF text extraction + LLM field extraction under a strict schema
     contract mirroring the original Google Form fields; the extractor emits
     **real nulls** (sentinels become a backstop, not a mechanism).
  2. **File-count gate:** N PDFs in → N syllabus records out.
  3. **Taxonomy slimmed to schema:** 7 AIMA classes + short descriptions as the
     primary classification schema; the LLM classifies (like the owner's
     original prompts); keyword lists demoted to an offline-fallback file for
     the `rule` backend (CI baseline only).
  4. **Book-grounded classification (mini-RAG):** the classification prompt is
     grounded with retrieved passages from the actual AIMA 4th-edition book —
     the owner reports this improved classification a lot vs. model memory alone.

## How the revision will be run

The owner drives the workflow with the agent skills installed in
`.opencode/skills/` (mattpocock/skills, repo-local, gitignored):

```
grilling / grill-with-docs  →  to-spec  →  to-tickets  →  implement
```

Issue tracker: GitHub Issues via `gh` (see `docs/agents/issue-tracker.md`);
triage labels `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`
are already created on the remote.

## ⛔ Waiting on the owner (the three blockers)

1. **The PDF corpus** — the raw syllabi PDFs (folder or link). The Kaggle
   dataset ships only the transcribed CSV; the PDFs are Stage-0's real input.
2. **The Google-Form field definitions** — what each captured field meant
   (names, semantics, edge cases). This becomes the Stage-0 extraction schema
   contract, verbatim.
3. **The AIMA 4th-edition book** (file) — for book-grounded classification.

## Open decisions (not blocking, decide during grill/spec)

- **Production LLM backend**: LM Studio (local) vs Ollama vs cloud
  OpenAI-compatible. The pipeline supports any via `backend: openai` +
  `config.yaml`; `rule` stays the deterministic baseline for accuracy
  comparison.
- **Accuracy evaluation** vs the rule baseline once the LLM backend is chosen.

## Housekeeping (owner, manual)

- Delete the accidental empty repo `kimoz1994/ai_course_syllabi_etl`
  (Settings → Danger Zone → Delete; the agent's token lacks `delete_repo`).

## Environment gotchas (Windows, local)

- `python -m pip` is broken — do NOT try to install packages.
- Tests: `$env:PYTHONPATH="src"; $env:PYTHONIOENCODING='utf-8'` then
  `python -m unittest discover -s tests -t .` (54 tests; unittest, not pytest).
- Full pipeline: `python -m ai_syllabi_etl run --backend rule` from repo root.
- PowerShell 5.1 note: `python ... 2>&1 | Select-String` can report a bogus
  exit code 1 even when tests pass; check `$LASTEXITCODE` directly.
- `clean.py` text-column detection is dtype-agnostic (pandas 2 `object` vs
  pandas 3 `str`) — keep it that way; CI runs pandas 3.x, locally 2.2.2.
