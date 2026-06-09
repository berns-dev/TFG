# Content Agent

Converts PDF and PPTX teaching materials into structured, classified Markdown faithful to the original, ready to feed into the Presentation Agent.

**Part of:** [AI Teaching Suite](../README.md) — Agent 2 of 3

---

## What it does

Receives one or more PDF or PPTX files for a topic. Extracts text, splits it into semantic chunks respecting page or slide boundaries, and classifies each chunk by function: theory, worked example, proposed exercise, table, or procedure. Chunks are processed in parallel and assembled into a single Markdown file with YAML frontmatter. A lexical fidelity validator checks that key technical terms from the source appear in the output (threshold: 0.85). Optionally accepts the Organiser Agent's `.md` to calibrate output depth proportionally to the hours assigned to the topic.

## Input

- Theory materials (one or more files): PDF or PPTX
- Thematic distribution from Organiser Agent (optional): Markdown (`.md`)

## Output

- Structured and curated Markdown per topic: `.md` with YAML frontmatter

The output includes `compatible_agente_organizador: true` in the frontmatter and can be used directly as input to the Presentation Agent.

## Key design decisions

- **Model routing by mathematical density:** `select_model()` in `classifier.py` uses a deterministic heuristic — symbol density, `d/dt`, `∫`, `Σ` patterns — to route chunks to Haiku (plain text) or Sonnet (mathematical content). This keeps API costs low without sacrificing quality on equations.
- **pdfplumber over PyMuPDF:** `pdfplumber` provides direct access to page-level text with position data, which is needed for the semantic chunking strategy that respects page boundaries. PyMuPDF was not evaluated for this project.
- **XML delimiters for robust parsing:** the model responds with strict `<TIPO>`, `<TITULO>`, `<IDIOMA>`, `<MARKDOWN>` delimiters. `_parse_delimited_response()` extracts content with a tolerant regex and retries up to three times if the response is malformed, making individual chunk failures non-fatal for the overall file.

## Running locally

```bash
cd agente-contenido
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
streamlit run app.py --server.port 8501
```

## Dependencies

- `anthropic` — Claude Haiku and Sonnet API calls
- `streamlit` — UI
- `pdfplumber` — PDF text extraction
- `python-pptx` — PPTX text extraction
- `python-dotenv` — credential loading
