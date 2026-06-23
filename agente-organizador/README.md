# Organiser Agent

Reads a course guide and theory materials, and proposes a thematic distribution: which blocks exist, what subtopics each one contains, and how many teaching hours go to each block.

**Part of:** [AI Teaching Suite](../README.md), agent 1 of 3
**UI:** [`app-unificada/app.py`](../app-unificada/app.py) (no standalone Streamlit app)

---

## What it does

Given a course guide (PDF) and one or more theory files (PDF or PPTX), the agent extracts teaching hours from the guide with deterministic code, detects subtopic candidates anchored to structural evidence in the materials, and asks Claude Sonnet to assemble a curricular distribution that respects the guide's own block structure. The professor reviews the result, refines it in natural language, and confirms it; the confirmed structure is what the Content agent later uses as a coverage checklist.

The agent never invents a subtopic. Every candidate must point to something verifiable: a numbered section, a slide title, or an index entry. If none of those exist for a given block, the agent doesn't guess: it leaves the block undivided and says so.

## Input

- Course guide: PDF
- Theory materials (typically one file per topic): PDF or PPTX

## Output

- Thematic distribution Markdown: `## Bloque N — Name · Xh` with a subtopic table (`| Subtema | Evidencia | Origen |`)
- Rows in `database/db.py` (`asignatura`, `temas`, `subbloques`) consumed by the Content and Presentation agents

## Why this is harder than it looks

Course guides at the same university don't share a format: one lists hours per block in a detailed table, another gives only the subject total. PDFs exported from PowerPoint have no reliable reading order, so naive heading detection picks up administrative boilerplate ("Identification of the subject," "Assessment criteria") right alongside real subtopics, and the occasional sentence fragment that happens to start with a number. Both problems showed up against real course material, not in testing, and both are handled with deterministic filters rather than asking the model to "be careful": a subtopic quality filter discards known administrative sections and prose fragments before they ever reach the prompt, and a three-strategy cascade (numbered sections → slide titles → visual scan for an index page or font-size contrast) falls back gracefully when the preferred signal isn't there.

## Key design decisions

- **Deterministic hour extraction.** `extraer_horas_docencia()` in `parser.py`, not the model, parses the official hours table. An early version let the model read the guide directly and it confused total credit hours with classroom hours, off by a factor of more than two.
- **Sonnet only, including refinement.** Curricular organisation needs strict cardinality (the model must not invent or merge blocks); Haiku didn't hold that consistency reliably enough across iterations.
- **Structural evidence over semantic grouping.** Subtopics must cite a detectable signal, never a "these seem related" judgment call from the model.
- **Pure logic lives in `parser.py`.** No Streamlit dependency, so `app-unificada` imports it directly via `_cargar_modulos_agente`; there's no duplicated copy of this logic in the UI layer.

## Running (unified app)

```bash
cd ..   # monorepo root TFG/
pip install -r agente-organizador/requirements.txt
cp agente-organizador/.env.example agente-organizador/.env
streamlit run app-unificada/app.py
```

## Dependencies

- `anthropic` — Claude Sonnet
- `pdfplumber` — PDF text and font metadata (this agent does not use PyMuPDF)
- `python-pptx` — PPTX extraction
- `streamlit` — UI (via app-unificada)
- `python-dotenv` — credentials

See [`CLAUDE.md`](CLAUDE.md) for the full detection cascade and parser API (not versioned in the public repo).
