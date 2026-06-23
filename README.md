# AI Teaching Suite — Augmented Engineering Methodologies

![Python](https://img.shields.io/badge/python-3.10+-blue) ![Anthropic](https://img.shields.io/badge/Anthropic-Claude-orange) ![University](https://img.shields.io/badge/University_of_Oviedo-Final_Project-darkblue)

Three AI agents that turn a professor's existing course material (PDFs, PowerPoint decks, the official course guide) into structured Markdown, an institutional PDF, and an interactive presentation, without inventing content that isn't in the source.

**Bachelor's Final Project (TFG)**, Mechanical Engineering, University of Oviedo (EPI Gijón), 2026.

---

## The problem

Preparing a university course means reconciling years of accumulated slides, PDFs exported from old PowerPoint files, and a course guide whose structure rarely matches the material as it actually exists. Reorganizing all of that means extracting text, matching content to teaching hours, reformatting equations, and keeping track of what's already been reviewed. None of that requires pedagogical judgment, but a professor still does it by hand, because no tool reads engineering material (equations, tables, structure) faithfully enough to be trusted with it.

This project tests whether an LLM-based system can take over that mechanical layer end to end while leaving every decision that requires judgment (what to keep, what's pedagogically sound, what to publish) to the professor.

## What it does

```
[Course guide PDF] ──┐
                     ├──► Organiser ──► blocks + subtopics (planning checklist)
[Materials PDF/PPTX]┘              │
                                   ▼
              Content ──► one curated Markdown per block
                                   │
                                   ▼
              Presentation ──► prompt workshop → institutional PDF + full HTML
```

| Agent | Role |
|-------|------|
| **Organiser** | Reads the course guide and theory materials, proposes thematic blocks, subtopics (each backed by a verifiable reference: a numbered section, a slide title, an index entry) and teaching hours. |
| **Content** | Converts the PDF/PPTX of a block into one faithful Markdown document. Flags missing or unreadable content instead of filling gaps, and checks its output against the Organiser's subtopics as a coverage checklist. |
| **Presentation** | Lets the professor describe a visualisation in plain language, for example "a stress-strain curve with a slider for Young's modulus," previews it live, refines it on request, then exports an institutional PDF and a full presentation page with the approved visualisations placed next to the text they illustrate. |

**Single entry point:** [`app-unificada/app.py`](app-unificada/app.py): one Streamlit app, one SQLite database ([`database/db.py`](database/db.py), schema v8), shared by the three agents.

## Engineering decisions worth reading

The interesting part of this project isn't the LLM calls. It's the decisions around them.

The first version called each agent directly from the next in code. A single extraction failure in stage one would silently propagate downstream, and the generator would fill the resulting gaps with invented content to keep the document looking coherent: exactly what the "transform, don't invent" rule forbids. The fix wasn't more validation between stages. It was removing the coupling. Each agent is now a standalone Python module; the output of one is consumed by the next through a Markdown file and a shared database, never through a function call. A failure in one agent doesn't block the other two.

Not every task gets an LLM call. Teaching-hour extraction, file classification, subtopic quality filtering, and lexical-fidelity validation are plain deterministic Python: faster, free, and auditable. The model is reserved for tasks that need real interpretation, like deciding curricular structure, transcribing equations, or choosing a slider's physical range. Model selection itself follows the same cost logic: two Claude tiers are used by task, not by default. Haiku handles extraction and reformatting at roughly a tenth of Sonnet's cost with no measurable quality loss for that work; Sonnet is reserved for sustained reasoning such as curricular cardinality, dense mathematical notation, and engineering judgment. In the Content agent this routing happens per text chunk, based on a deterministic symbol-density heuristic, not per document.

The system's core rule is that nothing appears in the output unless it's explicit in the source material. There is one deliberate, documented exception: when the Presentation agent implements an equation as an interactive chart, the model may use general engineering knowledge to choose a physically sensible slider range (grain size for Hall-Petch runs 1 to 100 µm, for instance), because restricting that decision to the source material doesn't remove the risk of invention, it just hides it as an arbitrary numeric range instead. The descriptive text and the relationship being shown still come exclusively from the professor's Markdown.

The three agents talk to each other through Markdown and nothing else, no intermediate JSON or XML schema. A model can navigate `#`/`##` headers on its own, a professor can read and edit the file directly, and any agent can be used standalone if its input is already in the right format. The same logic shaped the move to a single UI: three separate Streamlit apps worked, but gave nobody a way to see which blocks of a subject were approved, pending, or scored. A single app over a shared SQLite database fixed that without merging the agents' code; each module is still imported in isolation, with no agent calling another's functions.

## Validation

Validated against real material from three Mechanical Engineering subjects at the University of Oviedo (fluid power, machine elements, materials technology), chosen to span different curricular structures, material formats, and vocabulary, including English-language slides.

- **Organiser**: exact teaching-hour match against the official course guide on all three subjects (0h discrepancy). Block count matched the guide exactly on two of three; the third is a documented granularity mismatch between the guide and the professor's own materials, surfaced as a visible warning rather than resolved silently.
- **Content**: lexical-fidelity scores of 0.83 to 0.89 on average across subjects (0.85 pass threshold), with a traceable cause for every block below threshold: either structural noise (repeated headers or footers misread as missing content) or a specific, identified content gap, never an unexplained drop.
- **Presentation**: 8 interactive sliders across the three subjects were functionally verified by loading the generated HTML in a browser, driving each control, and checking the displayed result against the source equation for direction and magnitude. All 8 matched. The one case where the implemented formula differs from the curated Markdown is the documented dimensional-consistency exception, not a transcription error.

Full methodology and per-block results are in the thesis (`memoria/06-resultados-y-validacion.md`, Spanish).

## Installation & run

From repo root (`TFG/`). Streamlit config in [`.streamlit/config.toml`](.streamlit/config.toml).

```bash
pip install -r requirements.txt
cp agente-contenido/.env.example agente-contenido/.env   # ANTHROPIC_API_KEY
cp agente-organizador/.env.example agente-organizador/.env
cp agente-presentacion/.env.example agente-presentacion/.env
streamlit run app-unificada/app.py
```

## Tech stack

Python, Streamlit, SQLite, Anthropic API (`claude-haiku-4-5`, `claude-sonnet-4-5`), PyMuPDF/pdfplumber/python-pptx for extraction, ReportLab and matplotlib for the institutional PDF, Chart.js and MathJax for interactive visualisations.

## Repository structure

```
app-unificada/        single Streamlit entry point + UI
agente-organizador/   course guide → thematic blocks, subtopics, hours
agente-contenido/      PDF/PPTX → faithful per-block Markdown
agente-presentacion/  Markdown → PDF + interactive HTML
database/             shared SQLite schema and access layer
shared/                common extraction/text utilities
```

Each `agente-*/README.md` documents that module in depth.

## Validation scripts

```bash
py -3 database/validar_esquema.py
cd agente-contenido && py -3 tools/validate_cleaner.py
```

## Status

The full pipeline works end to end through the unified app and has been run against real course material, not synthetic test cases. This is an academic project, not a production system. See each module's README for known limitations; PDFs exported from PowerPoint are the main source of degraded results (`agente-contenido/README.md`).
