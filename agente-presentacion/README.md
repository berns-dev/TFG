# Presentation Agent

Detects mathematical content in curated Markdown and generates three outputs: institutional PDF, tabbed interactive HTML, and a full scrollable topic presentation.

**Part of:** [AI Teaching Suite](../README.md) — Agent 3 of 3  
**UI:** [`app-unificada/app.py`](../app-unificada/app.py) (no standalone Streamlit app)

---

## What it does

Receives Markdown from the Content Agent (from DB or file). Regex detects LaTeX, parametric relations, and tables; optional Haiku filters non-interactive candidates. The professor selects sections. Outputs:

- **PDF** — ReportLab with UO header, equations as matplotlib mathtext PNGs
- **Interactive HTML** — Sonnet reasoner + generator per section; Chart.js/canvas; `aplicar_rangos()` fixes slider bounds
- **Full presentation HTML** — theory sections plus embedded interactive blocks; lazy init via IntersectionObserver

## Input

- Curated Markdown (required)
- Original PDF/PPTX (optional) — reasoner uses it for realistic parameter ranges

## Key design decisions

- **Two-step HTML:** reasoner picks visualisation pattern, then generator builds HTML — more stable than a single prompt.
- **No system LaTeX:** matplotlib `mathtext` for PDF equations.
- **`generar_bloque_con_visualizacion()`:** public entry for app-unificada when the professor already chose a pattern in the DB.

## Running (unified app)

```bash
cd ..   # monorepo root TFG/
pip install -r agente-presentacion/requirements.txt
streamlit run app-unificada/app.py
```

PDF generation does not require the API. Interactive HTML requires `ANTHROPIC_API_KEY` in `agente-presentacion/.env` or shared env.

## Dependencies

- `anthropic` — Haiku (filter) and Sonnet (reasoner, HTML, SVG)
- `reportlab`, `markdown`, `matplotlib` — PDF pipeline
- `pdfplumber`, `python-pptx` — optional source context extraction
- `streamlit` — UI (via app-unificada)
- `python-dotenv`

See [`CLAUDE.md`](CLAUDE.md) for prompts, patterns, and validation tools.
