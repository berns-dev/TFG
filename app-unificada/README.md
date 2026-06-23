# Unified app

The single Streamlit entry point for the three-agent teaching suite, backed by a shared SQLite database (schema v8).

## Why a single app over three independent ones

Each agent was originally its own Streamlit app, and the professor moved between them by downloading a Markdown file from one and uploading it to the next. That worked, but there was nowhere to see, across a real subject with anywhere from four to twelve thematic blocks, which blocks were approved, which were pending, or what score the professor had given each one. That state lived only in filenames, and vanished the moment the Streamlit session closed.

Unifying the interface didn't mean merging the agents' code. Each one is still a standalone Python module, loaded through an isolated import mechanism so that, for instance, `agente-contenido`'s `pipeline.py` and `agente-presentacion`'s equivalent module can't collide even if they happened to share a name. What changed is the handoff between agents: instead of a file the professor downloads and re-uploads, each agent's result is written to a table the next one reads directly.

## Run

From the monorepo root (`TFG/`). Streamlit config lives in [`.streamlit/config.toml`](../.streamlit/config.toml) (root of the repo only).

```bash
pip install -r requirements.txt
streamlit run app-unificada/app.py
```

Set `ANTHROPIC_API_KEY` in `agente-organizador/.env`, `agente-contenido/.env`, and/or `agente-presentacion/.env`, depending on which agents are in use.

## Architecture

`app.py` loads each agent's modules through `_cargar_modulos_agente()`, which keeps their namespaces isolated:

| View | Imports from |
|------|----------------|
| Organiser | `agente-organizador/parser.py`, `agente.py`, `org_prompts.py` |
| Content | `pipeline.py`, `coverage_checklist.py`, `extractor.py`, … |
| Presentation | `workshop.py`, `generador_presentacion.py`, `generador_pdf.py`, … |
| All | `database/db.py` |

State persists in `data/tfg.db`, migrated to schema v8 automatically on first run.

## Professor workflow

1. **Organiser** — upload the guide and theory files, review the proposed blocks and subtopics, confirm to the database.
2. **Content** — per block: generate a draft, check it against the coverage checklist, edit, approve the whole block.
3. **Presentation** — per block: describe a visualisation, preview and refine it, approve it anchored to a section, export PDF or the full presentation HTML.

See the local `CLAUDE.md` at the repo root for the full inter-agent contracts and development rules (not versioned in git).
