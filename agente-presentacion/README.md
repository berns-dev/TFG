# Presentation Agent

Turns the curated block Markdown into an institutional PDF and a full interactive presentation, built through a prompt workshop instead of a fixed template.

**Part of:** [AI Teaching Suite](../README.md), agent 3 of 3
**UI:** [`app-unificada/app.py`](../app-unificada/app.py)

---

## What it does

For each block, the professor describes a visualisation in plain language ("a stress-strain curve with a slider for Young's modulus"), gets a live preview embedded in the app, and refines it with follow-up prompts until it's right. Approving a visualisation anchors it to a specific section of the Markdown. The agent then exports a PDF with the university's institutional template and a full presentation HTML that places theory and approved visualisations side by side, in the order the document actually presents them.

## From automatic detection to a workshop

The first version of this agent was fully automatic: a regex detector found mathematical sections in the Markdown, a reasoning step picked one of seven visualisation patterns, a generator produced the HTML, and the professor's only input was a checkbox to include or skip what the detector had already found. It worked, but it boxed the professor into whatever the detector happened to notice. If they wanted a visualisation of a relationship the detector hadn't flagged, there was no way to ask for it.

The redesign keeps the same underlying physics-implementation logic but inverts who decides what gets visualised: the professor describes it, the model builds it. The regex-based detector that used to find candidate elements automatically was removed from the codebase once the workshop replaced it; the seven-pattern reasoner and generator it used to call are still in `generador_html.py`, but nothing in the app calls them anymore. The workshop's own prompts generate directly from the professor's instruction, with no pattern selection step.

## Input

- Curated block Markdown from the Content agent (`contenido_tema`)
- Optionally, the original PDF/PPTX text, used to ground slider ranges in the professor's own material when available

## Output

- **PDF** — ReportLab institutional template, no external dependencies (no LaTeX install required)
- **Full presentation HTML** — a scrollable document with a sidebar, theory sections, and interactive blocks embedded exactly where they're anchored

## The one documented exception to "never invent"

Everywhere else in the system, content in the output must trace back to the professor's material. Here it doesn't, by design, but only for one narrow thing: the implementation of an equation as a chart. The descriptive text and the relationship being shown still come exclusively from the Markdown; what the model decides on its own is how the curve behaves and what range a slider should cover, using general engineering knowledge (grain size for Hall-Petch runs roughly 1 to 100 µm, for instance). Forcing that decision to come only from the Markdown was tried first and produced sliders with arbitrary, sometimes physically meaningless ranges, since most course material never states them explicitly. That's a subtler form of invention than an extra sentence of text, and harder to catch on review.

## Key modules

- `workshop.py` — `generar_desde_instruccion()`, `refinar_html()`
- `generador_presentacion.py` — `generar_presentacion_con_fragmentos()`
- `generador_pdf.py` — `generar_pdf()`
- `generador_html.py` — seven-pattern reasoner and generator, unused since the detector that fed it was removed; kept for reference

## Running

```bash
streamlit run app-unificada/app.py
```

Requires `ANTHROPIC_API_KEY` in `agente-presentacion/.env` for the workshop.

See [`CLAUDE.md`](CLAUDE.md) for the full prompt design and architecture (not versioned in the public repo).
