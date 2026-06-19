# AI Teaching Suite — Augmented Engineering Methodologies

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Anthropic](https://img.shields.io/badge/Anthropic-Claude-orange) ![University](https://img.shields.io/badge/University_of_Oviedo-Final_Project-darkblue)

A suite of three AI agents that transforms university teaching materials into structured, faithful Markdown and interactive presentation outputs. The agents transform material; they do not invent content not present in the originals.

**Bachelor's Final Project (TFG)** — Mechanical Engineering, University of Oviedo (EPI Gijón), 2026.

---

## Solution — Unified App + Three Agents

```
[Course guide PDF] ──┐
                     ├──► Organiser ──► blocks + subtopics (planning checklist)
[Materials PDF/PPTX]┘              │
                                   ▼
              Content ──► one curated Markdown per block (contenido_tema)
                                   │
                                   ▼
              Presentation ──► prompt workshop → approved interactives → PDF + full HTML
```

| Agent | Role |
|-------|------|
| **Organiser** | Thematic blocks, hours, subtopics with evidence (professor validates) |
| **Content** | Faithful block-level Markdown; coverage checklist vs Organiser subtopics |
| **Presentation** | Iterative prompt workshop + institutional PDF + full presentation HTML |

**Single UI:** [`app-unificada/app.py`](app-unificada/app.py) — SQLite [`database/db.py`](database/db.py) schema v7.

---

## Professor workflow

1. **Organiser** — upload guide + theory files → review blocks/subtopics → confirm to DB.
2. **Content** — per block: generate draft → review coverage checklist → edit → approve whole block.
3. **Presentation** — per block: describe visualisations in natural language → preview → refine → approve with section anchor → export PDF / full presentation HTML.

---

## Installation & run

```bash
pip install -r requirements.txt
cp agente-contenido/.env.example agente-contenido/.env   # ANTHROPIC_API_KEY
cp agente-organizador/.env.example agente-organizador/.env
cp agente-presentacion/.env.example agente-presentacion/.env
streamlit run app-unificada/app.py
```

---

## Documentation

| Document | Purpose |
|----------|---------|
| [`CLAUDE.md`](CLAUDE.md) | Architecture, contracts, development rules |
| [`agente-*/CLAUDE.md`](agente-organizador/) | Per-agent technical detail |
| [`database/CLAUDE.md`](database/CLAUDE.md) | SQLite schema v8 |
| [`app-unificada/README.md`](app-unificada/README.md) | Unified Streamlit app |

---

## Validation

```bash
py -3 database/validar_esquema.py
cd agente-contenido && py -3 tools/validate_cleaner.py
```

Core pipeline is functional end-to-end through the unified app. Academic scope — not production-hardened.
