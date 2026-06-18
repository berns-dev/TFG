# Content Agent

Converts PDF and PPTX teaching materials into structured Markdown faithful to the original, calibrated by block hours from the Organiser, then split into subtopics for professor review.

**Part of:** [AI Teaching Suite](../README.md) — Agent 2 of 3  
**UI:** [`app-unificada/app.py`](../app-unificada/app.py) (no standalone Streamlit app)

---

## What it does

For each thematic **block** (not per subtopic API call):

1. **Extract** text from all PDF/PPTX files linked to the block in the database.
2. **Curate** the full block in one API pass (`procesar_bloque`) using block hours as density context.
3. **Split** the curated Markdown across subtopics with `split_monotono()` (deterministic, no API).
4. **Preview** anchors and confidence; professor confirms the split.
5. **Review** each subtopic — edit, score 1–10, approve.

A lexical fidelity validator (threshold 0.85) checks that key terms from the source appear in the output.

## Input

- Theory materials: PDF or PPTX (paths from DB after Organiser upload)
- Block hours and subtopic names/order from Organiser (via SQLite / distribution `.md`)

## Output

- Per-subtopic Markdown in `contenido_subbloque` (DB), with lifecycle states: `pendiente` → `generado` → `editado` → `aprobado`
- Consumable by the Presentation Agent

## Key design decisions

- **Block-first curation:** one API pass per block avoids fragile per-subtopic PDF segmentation; `split_monotono` assigns content by heading match in document order.
- **PyMuPDF first for PDF:** `shared/pdf_enriched.build_pdf_markdown_pymupdf()` decodes math fonts and reading order better than pdfplumber on PPT-exported PDFs; pdfplumber remains fallback.
- **Light cleaner on enriched PDF:** preserves `#`/`##`/`###` headings; drops repeated 1–2 character header glyphs (≥80% of pages); marks broken equations as `[ECUACION_PARCIAL]` without LLM completion.
- **Model routing:** `select_model()` sends math-dense chunks to Sonnet, plain text to Haiku.
- **XML delimiters:** `<TIPO>`, `<MARKDOWN>`, etc., with tolerant parsing and retries.

## Running (unified app)

```bash
cd ..   # monorepo root TFG/
pip install -r agente-contenido/requirements.txt
cp agente-contenido/.env.example agente-contenido/.env
streamlit run app-unificada/app.py
```

## Validation scripts (no API)

```bash
cd agente-contenido
python tools/validate_split_monotono.py
python tools/validate_cleaner.py
python tools/validate_pdf_enriched.py
```

## Dependencies

- `anthropic` — Claude API
- `pymupdf` — primary PDF extraction (Content agent)
- `pdfplumber` — PDF fallback
- `python-pptx` — PPTX extraction
- `streamlit` — UI (via app-unificada)
- `python-dotenv` — credentials

See [`CLAUDE.md`](CLAUDE.md) for full architecture and development rules.
