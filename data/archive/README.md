# data/archive — retired inputs, kept for cross-checking

`AI_course_syllabi_CSV.csv` is the Kaggle CSV: the owner's **manually
produced example output** (113 syllabi, Google-Form export, CC BY 4.0).
It was the input of the legacy CSV pipeline, which was retired when the
PDF-first flow (ADR-0001) went end-to-end — it is **no longer read by the
pipeline**.

It stays in-repo because it is the cross-checking reference for the PDF
flow: rows extracted from the syllabus PDFs can be compared against the
owner's manual transcription. The canonical 14-field schema it mirrors is
`schema_contract.yaml` at the repo root (the CSV's `Short Quizes` spelling
was a transcription artifact; see the schema contract header).

Do not point the pipeline's `input` at a table file: `input` must be a
folder of syllabus PDFs (`data/pdfs` by default).
