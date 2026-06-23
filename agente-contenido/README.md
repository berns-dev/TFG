# Content Agent

Converts PDF and PPTX teaching materials into one faithful Markdown document per thematic block, ready for the professor to review.

**Part of:** [AI Teaching Suite](../README.md), agent 2 of 3
**UI:** [`app-unificada/app.py`](../app-unificada/app.py)

---

## What it does

For each thematic block, the agent extracts text from the linked PDF/PPTX files, curates the entire block in one pass with no compression or expansion based on how many teaching hours it has, and checks the result against the Organiser's subtopics as a coverage checklist rather than splitting the document by them. The professor reviews the full block in an editor, edits if needed, and approves it.

Fidelity is enforced, not assumed: a lexical validator checks that key terms from the source survive into the output (0.85 threshold), and anything the extractor genuinely couldn't recover is marked, not silently dropped.

## Input

- Theory materials: PDF or PPTX (paths come from the database)
- Organiser subtopics: used only as a coverage checklist, never to split the Markdown

## Output

- One Markdown document per block, stored in `contenido_tema` with states `pendiente → generado → editado → aprobado`
- Consumed directly by the Presentation agent

## The PDF extraction chain, and why it has three links

Most PDFs in this domain are machine-generated but not well-structured, especially when they're PowerPoint exported as PDF: PowerPoint composes each slide with positioned text boxes, and exporting drops the visual order in favor of creation order, so the text comes out scrambled relative to how a person reads the slide. The extraction chain tries PyMuPDF first (better at decoding math notation and reading order), falls back to an enriched pdfplumber pass, and falls back again to a plain pdfplumber extraction as a last resort. Native PPTX skips all of this; it's the more reliable input when it's available.

Equations that the extractor can't decode (Symbol/Math fonts from a PowerPoint export, mostly) are marked `[ECUACION_PARCIAL]` or `[ECUACION_NO_EXTRAIBLE]` rather than skipped silently. There's one narrow, deliberate exception to the "never invent" rule here: if the surrounding text in that same fragment names the formula and defines its variables, the model may reconstruct the equation, but it must label it `[ECUACION_RECONSTRUIDA: justification]` so the professor knows to verify it. Any ambiguity, and the original marker stays untouched.

## Key modules

- `pipeline.py` — `procesar_bloque()`, the main entry point
- `coverage_checklist.py` — `verificar_cobertura()`
- `extractor.py` — PyMuPDF → pdfplumber → plain text; PPTX
- `classifier.py` — model routing and the fidelity system prompt
- `split_monotono.py` — legacy deterministic splitter, kept for tests, not used in the unified UI

## Key design decisions

- **Model routing by symbol density, not by document.** Each text chunk is classified independently: above a 0.02 math-symbol density, or matching patterns like `d/dt`, `∫`, `Σ`, it goes to Sonnet; otherwise Haiku. Validated against real materials where Hollomon, Ramberg-Osgood, Weibull, and Von Mises equations all routed correctly to Sonnet.
- **No hour-density calibration.** An earlier version stretched or compressed the curated text to match the block's teaching hours. It was dropped: it conflated two separate questions (what the material says, and how much class time the block has) and produced no reliable signal for what to expand versus summarize.
- **Coverage checklist, not segmentation.** The Organiser's subtopics flag what might be missing; they never cut the document into pieces.

## Validation scripts (no API required)

```bash
cd agente-contenido
python tools/validate_cleaner.py
python tools/validate_pdf_enriched.py
python tools/validate_split_monotono.py   # legacy module
```

## Known limitation

PDFs exported from PowerPoint remain worse than native PPTX for reading order and equations, even with PyMuPDF as the primary extractor. The UI warns when a filename suggests that origin; native PPTX is preferable whenever the professor has it.

See [`CLAUDE.md`](CLAUDE.md) for the full architecture (not versioned in the public repo).
