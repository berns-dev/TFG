# Content Agent

Converts PDF and PPTX teaching materials into **one faithful Markdown document per thematic block** for professor review.

**Part of:** [AI Teaching Suite](../README.md) — Agent 2 of 3  
**UI:** [`app-unificada/app.py`](../app-unificada/app.py)

---

## What it does

For each thematic **block**:

1. **Extract** text from PDF/PPTX linked to the block in the database.
2. **Curate** the full block in one API pass (`procesar_bloque`) — faithful extraction, **no hour-density calibration**.
3. **Check coverage** — `verificar_cobertura()` warns if Organiser subtopics seem missing in the curated MD.
4. **Review** — professor edits and approves the **whole block** (stored in `contenido_tema`).

Lexical fidelity validator (threshold 0.85) checks key terms from the source.

## Input

- Theory materials: PDF or PPTX (paths from DB)
- Organiser subtopics: **checklist only** (not used to split the markdown)

## Output

- One Markdown per block in `contenido_tema` — states: `pendiente` → `generado` → `editado` → `aprobado`
- Consumable by the Presentation Agent

## Key modules

- `pipeline.py` — `procesar_bloque()`
- `coverage_checklist.py` — `verificar_cobertura()`
- `extractor.py` — PyMuPDF → pdfplumber → plain; PPTX
- `split_monotono.py` — **legacy** (deterministic split for tests; not used in unified UI)

## Validation scripts (no API)

```bash
cd agente-contenido
python tools/validate_cleaner.py
python tools/validate_pdf_enriched.py
python tools/validate_split_monotono.py   # legacy module
```

See [`CLAUDE.md`](CLAUDE.md) for full architecture.
