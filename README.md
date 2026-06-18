# AI Teaching Suite — Augmented Engineering Methodologies

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Anthropic](https://img.shields.io/badge/Anthropic-Claude-orange) ![University](https://img.shields.io/badge/University_of_Oviedo-Final_Project-darkblue)

A suite of three AI agents that transforms university teaching materials — PDFs, PowerPoint files, and course guides — into structured, hour-calibrated, and interactive resources. The agents transform material; they do not invent content not present in the originals.

**Bachelor's Final Project (TFG)** — Mechanical Engineering, University of Oviedo (EPI Gijón), 2026.

---

## The Problem

Professors accumulate years of teaching material in PowerPoint and PDF. That content lacks explicit pedagogical structure, per-topic hour distribution, and reusable interactive formats. Reorganising it manually is slow and competes with other duties.

---

## Solution — Unified App + Three Agents

```
[Course guide PDF] ──┐
                     ├──► Organiser ──► SQLite + distribution .md
[Materials PDF/PPTX]┘              │
                                   ▼
              Content (block curation + split) ──► curated Markdown per subtopic
                                              │
                                              ▼
                              Presentation ──► PDF + interactive HTML + full presentation HTML
```

| Agent | Role | Module |
|-------|------|--------|
| **Organiser** | Extracts teaching hours and thematic blocks/subtopics from the course guide and theory files | [`agente-organizador/`](agente-organizador/) |
| **Content** | Converts PDF/PPTX to faithful structured Markdown; curates **whole blocks** then splits by subtopic | [`agente-contenido/`](agente-contenido/) |
| **Presentation** | Generates institutional PDF, tabbed interactive HTML, and full-topic presentation HTML | [`agente-presentacion/`](agente-presentacion/) |

**Single UI:** [`app-unificada/app.py`](app-unificada/app.py) — one Streamlit app for all three agents, backed by SQLite ([`database/db.py`](database/db.py)). Standalone `app.py` per agent was removed (June 2026).

---

## Core Principle

Organiser and Content agents **transform, never invent**. Presentation’s interactive HTML may use engineering knowledge to *implement* visualisations, but descriptive text must come from the curated Markdown.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | Anthropic — `claude-haiku-4-5-20251001`, `claude-sonnet-4-5` |
| UI | Streamlit (`app-unificada`) |
| Persistence | SQLite (`data/tfg.db`) |
| PDF extraction (Content) | **PyMuPDF** (primary) → pdfplumber (fallback) via [`shared/pdf_enriched.py`](shared/pdf_enriched.py) |
| PDF extraction (Organiser) | pdfplumber |
| PPTX | python-pptx |
| Generated PDF | ReportLab + matplotlib mathtext |
| Interactive HTML | Chart.js + MathJax (CDN) |

---

## Installation

Python 3.10+ recommended. From the monorepo root (`TFG/`):

```bash
pip install -r agente-organizador/requirements.txt
pip install -r agente-contenido/requirements.txt
pip install -r agente-presentacion/requirements.txt

cp agente-contenido/.env.example agente-contenido/.env
cp agente-organizador/.env.example agente-organizador/.env
# Add ANTHROPIC_API_KEY=sk-ant-... to each .env as needed
```

---

## Running

```bash
streamlit run app-unificada/app.py
```

Typical workflow inside the app:

1. **Organiser** — create subject, upload guide + theory files, generate/review distribution, persist to DB.
2. **Content** — per block: «Generar borrador del bloque» → preview split → confirm → review/approve subtopics.
3. **Presentation** — select curated Markdown, detect interactive sections, export PDF/HTML.

Each agent’s logic remains importable without the UI for tests and scripts.

---

## Documentation

| Document | Purpose |
|----------|---------|
| [`CLAUDE.md`](CLAUDE.md) | Global context for AI assistants — architecture, contracts, rules |
| [`agente-*/CLAUDE.md`](agente-organizador/) | Per-agent technical detail |
| [`database/CLAUDE.md`](database/CLAUDE.md) | SQLite schema and progress APIs |
| [`agente-*/README.md`](agente-contenido/) | Human-readable agent summaries |
| [`app-unificada/README.md`](app-unificada/README.md) | Unified Streamlit app |

---

## Project Status

Core pipeline is functional end-to-end through the unified app. Validated with several real subjects (including Technology of Materials and Brakes/Frenos). Not production-hardened — scope is academic.
