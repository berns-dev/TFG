# App unificada

Single Streamlit entry point for the three-agent teaching suite and shared SQLite database.

## Run

From monorepo root (`TFG/`):

```bash
pip install -r agente-organizador/requirements.txt
pip install -r agente-contenido/requirements.txt
pip install -r agente-presentacion/requirements.txt
streamlit run app-unificada/app.py
```

Configure `ANTHROPIC_API_KEY` in `agente-organizador/.env` and/or `agente-contenido/.env` as needed.

## Architecture

`app.py` does **not** duplicate agent business logic. It loads modules via `_cargar_modulos_agente()`:

| View | Imports from |
|------|----------------|
| Organiser | `agente-organizador/parser.py`, `agente.py`, `org_prompts.py` |
| Content | `agente-contenido/pipeline.py`, `extractor.py`, `split_monotono.py`, … |
| Presentation | `agente-presentacion/generador_*.py`, `detector.py` |
| All | `database/db.py` |

Persistence: `data/tfg.db` (created on first run).

## Professor workflow

1. **Organiser** — subject, course guide, theory files → blocks/subtopics in DB.
2. **Content** — per block: generate draft → preview split → confirm → review subtopics.
3. **Presentation** — curated Markdown → PDF / interactive HTML / full presentation.

See [`../CLAUDE.md`](../CLAUDE.md) for contracts between agents and development rules.
