# Presentation Agent

Detects mathematical content in curated Markdown and generates three output formats: an academic PDF with rendered equations, an interactive HTML page with sliders and real-time graphs, and a full topic presentation that weaves the theory together with the interactive blocks. All HTML outputs share the institutional University of Oviedo header.

**Part of:** [AI Teaching Suite](../README.md) — Agent 3 of 3

---

## What it does

Receives the structured Markdown produced by the Content Agent. A regex pass detects LaTeX blocks, parametric relations, and numeric tables, grouping candidates by section. An optional Haiku filter discards non-interactive candidates (fail-open: if the API is unavailable, all regex matches are kept). The professor selects which sections to export. For PDF, ReportLab renders the full document with equations as matplotlib mathtext images. For interactive HTML, a two-step Sonnet pipeline — reasoner then generator — produces one self-contained panel per section, with Chart.js or canvas visualisations and MathJax-rendered equations.

## Input

- Curated Markdown from the Content Agent: `.md`
- Original PDF or PPTX material (optional): used by the reasoner to determine realistic parameter ranges

## Output

- Academic paginated document: PDF (`.pdf`)
- Self-contained interactive web page (tabbed panels): HTML (`.html`)
- Full topic presentation that integrates the theory with the interactive blocks: HTML (`.html`)

## Key design decisions

- **Two-step HTML generation (reasoner + generator):** a first Sonnet call decides whether a section is worth visualising and which of seven visualisation patterns fits (single curve, family of curves, criterion region, 2D map, trajectory, frequency response, and animated mechanism). A second Sonnet call generates the HTML for that specific pattern. Separating the reasoning step from the generation step produces more consistent output than a single prompt.
- **Parameter classification (family vs slider):** the reasoner classifies each secondary parameter as discrete/categorical (→ family of curves), continuous and sensitive (→ slider), or fixed/irrelevant (→ no control), which keeps the right comparison on screen and avoids decorative sliders. It is validated with `tools/razonador_fixture.py`.
- **`aplicar_rangos()` post-processing:** Sonnet receives correct slider ranges from the reasoner but occasionally ignores them during generation. A Python post-processing step overwrites `min`, `max`, and `value` attributes on all `input[type=range]` elements before the HTML is validated, correcting this inconsistency without retrying the API call.
- **PDF generation without system LaTeX:** equations are rendered as PNG images via `matplotlib.mathtext` (`usetex=False`), eliminating the need for a system LaTeX installation. If rendering fails, the equation falls back to monospace text inside a bordered box.

## Running locally

```bash
cd agente-presentacion
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
streamlit run app.py --server.port 8500
```

The `ANTHROPIC_API_KEY` is required only for interactive HTML generation (Sonnet calls). PDF generation runs entirely without API calls.

## Dependencies

- `anthropic` — Claude Haiku (interactivity filter) and Sonnet (reasoner, HTML generator)
- `streamlit` — UI
- `reportlab` — PDF generation
- `markdown` — Markdown-to-HTML conversion for PDF pipeline
- `matplotlib` — equation rendering as PNG images
- `pdfplumber` — optional extraction of professor's original PDF for range context
- `python-pptx` — optional extraction of professor's original PPTX for range context
- `python-dotenv` — credential loading
