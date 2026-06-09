# AI Teaching Suite — Augmented Engineering Methodologies

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Anthropic](https://img.shields.io/badge/Anthropic-Claude-orange) ![University](https://img.shields.io/badge/University_of_Oviedo-Final_Project-darkblue)

A suite of three AI agents that transforms university teaching materials — PDFs, PowerPoint files, and course guides — into structured, hour-calibrated, and interactive resources without adding any content not present in the originals.

---

## The Problem

University professors accumulate years of teaching material in PowerPoint and PDF formats. That material exists in non-reusable formats, with no explicit pedagogical structure, no per-topic hour distribution, and no interactive formats for students. Reorganising it manually is expensive and competes with everything else on a professor's plate.

---

## Solution — Agent Workflow

```
[Course guide PDF] ──┐
                     ├──► Organiser Agent ──► [Thematic distribution .md]
[Materials PDF/PPTX]┘                                     │
                                                          │
                     ┌────────────────────────────────────┘
                     │    + [Topic material PDF/PPTX]
                     ▼
              Content Agent ──► [Curated Markdown by topic]
                                              │
                                              ▼
                                  Presentation Agent
                                  ├──► [Structured PDF]
                                  └──► [Interactive HTML]
```

**Organiser Agent** receives the course guide and theory materials, detects teaching hours (lectures, seminars, lab sessions), and produces a thematic distribution with blocks, subtopics, and hours proportional to the available time. Output: a `.md` file with the subject's curricular structure.

**Content Agent** receives that `.md` as optional density context plus one or more PDF/PPTX files for the topic. It converts the material into structured Markdown faithful to the original, classifying each block as theory, worked example, exercise, table, or procedure. Output: a curated `.md` per topic.

**Presentation Agent** receives the curated Markdown, detects sections with mathematical content, and lets the professor select which sections to include. It then generates an academic PDF (ReportLab) or an interactive HTML page with sliders and Chart.js graphs.

---

## Core Principle

The three agents transform — they never invent. The output of each agent can only contain information explicitly present in the input material. Nothing is added, inferred, or completed. If a topic does not appear in the materials the professor uploaded, it does not appear in the output.

---

## Architecture

| Agent | Input | Output | Module |
|-------|-------|--------|--------|
| Organiser | Course guide (PDF) + theory materials (PDF/PPTX) | Thematic distribution with blocks and hours | [`agente-organizador/`](agente-organizador/) |
| Content | Topic materials (PDF/PPTX) + optional organiser `.md` | Structured and curated Markdown by topic | [`agente-contenido/`](agente-contenido/) |
| Presentation | Curated Markdown from Content Agent | Academic PDF + interactive HTML page | [`agente-presentacion/`](agente-presentacion/) |

---

## Tech Stack

- **API:** Anthropic — `claude-haiku-4-5-20251001` and `claude-sonnet-4-5`
- **UI:** Streamlit
- **Extraction:** `pdfplumber` (PDF), `python-pptx` (PPTX)
- **Generated PDF:** `reportlab` (pure Python, no system dependencies)
- **Interactive HTML:** Chart.js + MathJax (CDN)
- **Credentials:** `.env` per agent + `python-dotenv`

---

## Installation

Each agent has its own dependencies and is installed independently. Python 3.10+ recommended.

```bash
# Organiser Agent
cd agente-organizador
pip install -r requirements.txt
cp .env.example .env   # use 'copy' on Windows

# Content Agent
cd agente-contenido
pip install -r requirements.txt
cp .env.example .env

# Presentation Agent
cd agente-presentacion
pip install -r requirements.txt
cp .env.example .env
```

In each `.env`, add your Anthropic API key:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Running the Suite

Run each agent on a separate port to use them in parallel:

```bash
# Terminal 1 — Organiser Agent
cd agente-organizador
streamlit run app.py --server.port 8502

# Terminal 2 — Content Agent
cd agente-contenido
streamlit run app.py --server.port 8501

# Terminal 3 — Presentation Agent
cd agente-presentacion
streamlit run app.py --server.port 8500
```

Each agent can be used independently. The full workflow follows the order Organiser → Content → Presentation, but no agent requires the output of the previous one to function.

---

## Project Status

Built as a university final project (Bachelor's in Mechanical Engineering, University of Oviedo, 2026). Core pipeline is functional end-to-end. Not production-hardened — error handling and edge cases are intentionally minimal for academic scope.
