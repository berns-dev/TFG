# Presentation Agent

Generates institutional PDF and interactive presentation HTML from curated block Markdown, via an **iterative prompt workshop** for professors.

**Part of:** [AI Teaching Suite](../README.md) — Agent 3 of 3  
**UI:** [`app-unificada/app.py`](../app-unificada/app.py)

---

## What it does

Per thematic **block**:

1. **Workshop** — professor describes visualisations in natural language (`workshop.py`).
2. **Preview** — embedded HTML in Streamlit; refine with follow-up prompts.
3. **Approve** — save fragment with section anchor (`visualizacion_interactiva` in DB).
4. **Export** — PDF of block; full presentation HTML with theory + approved interactives (`generar_presentacion_con_fragmentos()`).

## Input

- Curated block Markdown from Content Agent (`contenido_tema`)
- Optional: original PDF/PPTX text for realistic parameter ranges in the workshop

## Outputs

- **PDF** — ReportLab institutional template (no API required)
- **Full presentation HTML** — scrollable document with sidebar, theory sections, embedded interactives at anchored positions

## Key modules

- `workshop.py` — `generar_desde_instruccion()`, `refinar_html()`
- `generador_presentacion.py` — `generar_presentacion_con_fragmentos()`
- `generador_pdf.py` — `generar_pdf()`
- `generador_html.py`, `detector.py` — legacy detector/razonador pipeline (still used internally)

## Running

```bash
streamlit run app-unificada/app.py
```

Requires `ANTHROPIC_API_KEY` in `agente-presentacion/.env` for the workshop.

See [`CLAUDE.md`](CLAUDE.md) for prompts and architecture.
