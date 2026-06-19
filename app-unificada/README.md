# App unificada

Single Streamlit entry point for the three-agent teaching suite and shared SQLite database (schema v7).

## Run

From monorepo root (`TFG/`). Streamlit config: [`.streamlit/config.toml`](../.streamlit/config.toml) (solo en la raíz del repo).

```bash
pip install -r requirements.txt
streamlit run app-unificada/app.py
```

Configure `ANTHROPIC_API_KEY` in `agente-organizador/.env`, `agente-contenido/.env` and/or `agente-presentacion/.env`.

## Architecture

`app.py` loads agent modules via `_cargar_modulos_agente()`:

| View | Imports from |
|------|----------------|
| Organiser | `agente-organizador/parser.py`, `agente.py`, `org_prompts.py` |
| Content | `pipeline.py`, `coverage_checklist.py`, `extractor.py`, … |
| Presentation | `workshop.py`, `generador_presentacion.py`, `generador_pdf.py`, … |
| All | `database/db.py` |

Persistence: `data/tfg.db` (migrated to v7 on first run).

## Professor workflow

1. **Organiser** — subject, guide, theory files → blocks/subtopics in DB.
2. **Content** — per block: generate draft → coverage checklist → edit → approve (`contenido_tema`).
3. **Presentation** — per block: prompt workshop → preview/refine → approve visualisations → export PDF / full HTML.

See local `CLAUDE.md` at repo root for contracts and development rules (not versioned in git).
