# Organiser Agent

Extracts the thematic structure and teaching hours from a course guide and theory materials, and produces a Markdown file with topic blocks, subtopics, and proportional hour allocations.

**Part of:** [AI Teaching Suite](../README.md) — Agent 1 of 3

---

## What it does

Receives a course guide (PDF) and one or more theory files (PDF or PPTX). Deterministic heuristics extract lecture, seminar, and lab hours from the guide. Those hours feed a prompt sent to Claude Sonnet, which produces a curricular organisation with topic blocks and subtopics. The professor can review the proposal, provide feedback in natural language, and request up to five regenerations before downloading the final Markdown. A cardinality check verifies that the number of generated blocks matches the number of uploaded theory files, and surfaces a warning in the UI if they diverge.

## Input

- Course guide: PDF
- Theory materials (one file per topic): PDF or PPTX

## Output

- Thematic distribution with blocks, subtopics, and hours: Markdown (`.md`)

The output follows a fixed template defined in `prompts.py` and can be used directly as input to the Content Agent. The Content Agent's parser expects block headings in the form `## Bloque N — Name · Xh`.

## Key design decisions

- **Deterministic hour extraction over LLM:** `extraer_horas_docencia()` extracts TE/PA/PL hours from the course guide with Python heuristics (table detection first, free-text fallback), not via API. This avoids hallucinated hour counts and keeps the extraction auditable.
- **Sonnet only, no Haiku:** curricular organisation requires strict cardinality and semantic consistency across blocks. Haiku was evaluated and discarded because it did not reliably respect the block-count constraint when prompts were strict.
- **Refinement without re-extraction:** `construir_prompt_refinamiento()` is a lightweight prompt that takes the previous output as base and applies only the latest feedback, without re-extracting documents or re-detecting hours.

## Running locally

```bash
cd agente-organizador
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
streamlit run app.py --server.port 8502
```

## Dependencies

- `anthropic` — Claude Sonnet API calls
- `streamlit` — UI
- `pdfplumber` — PDF text extraction
- `python-pptx` — PPTX text extraction
- `python-dotenv` — credential loading
