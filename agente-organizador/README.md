# Organiser Agent

Extracts thematic structure and teaching hours from a course guide and theory materials, and produces a Markdown distribution with blocks, subtopics, and hour allocations.

**Part of:** [AI Teaching Suite](../README.md) — Agent 1 of 3  
**UI:** [`app-unificada/app.py`](../app-unificada/app.py) (no standalone Streamlit app)

---

## What it does

Receives a course guide (PDF) and one or more theory files (PDF or PPTX). Deterministic heuristics extract lecture, seminar, and lab hours from the guide. Claude Sonnet produces a curricular organisation with topic blocks and subtopics anchored to structural evidence in the materials. The professor reviews, refines in natural language, and persists the result to SQLite.

## Input

- Course guide: PDF
- Theory materials (typically one file per topic): PDF or PPTX

## Output

- Thematic distribution Markdown: `## Bloque N — Name · Xh` with subtopic table (`| Subtema | Evidencia | Origen |`)
- Rows in `database/db.py` (asignatura, temas, subbloques) for Content and Presentation

## Key design decisions

- **Deterministic hour extraction:** `extraer_horas_docencia()` in `parser.py` — not LLM — for auditable hour counts.
- **Sonnet only:** curricular organisation needs strict cardinality; Haiku was discarded for this step.
- **Structural evidence:** subtopics must cite detectable signals (section numbers, slides, visual titles).
- **Pure logic in `parser.py`:** imported by app-unificada via `_cargar_modulos_agente`; no duplicated helpers in the UI layer.

## Running (unified app)

```bash
cd ..   # monorepo root TFG/
pip install -r agente-organizador/requirements.txt
cp agente-organizador/.env.example agente-organizador/.env
streamlit run app-unificada/app.py
```

## Dependencies

- `anthropic` — Claude Sonnet
- `pdfplumber` — PDF text and font metadata (Organiser does not use PyMuPDF)
- `python-pptx` — PPTX extraction
- `streamlit` — UI (via app-unificada)
- `python-dotenv` — credentials

See [`CLAUDE.md`](CLAUDE.md) for detection strategies and parser API.
