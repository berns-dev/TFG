# Agente Presentación — Agente 03 de la suite TFG

Detecta el contenido matemático del Markdown curado por el Agente Contenido y genera dos formatos de presentación: un PDF académico con tipografía y paginación estructurada, o una página HTML interactiva con sliders y gráficas en tiempo real.

---

## Qué hace

Recibe el Markdown estructurado producido por el Agente Contenido. Detecta automáticamente las secciones que contienen ecuaciones LaTeX, relaciones paramétricas y tablas numéricas, agrupando el contenido por encabezado de sección. El profesor selecciona qué secciones incluir en el material de salida mediante checkboxes. El agente genera el formato elegido: un PDF académico con ecuaciones renderizadas en monospace y pie de página paginado, o una página HTML autocontenida con sliders para cada variable de entrada, gráficas Chart.js actualizadas en tiempo real e interpretación dinámica del resultado.

---

## Principio de fidelidad

El agente extrae y reformatea. No inventa. La explicación y la interpretación de cada panel interactivo se construyen exclusivamente a partir del contexto proporcionado en el Markdown de entrada.

---

## Arquitectura

```
app.py              — UI Streamlit, sidebar con PDF, área principal con detección y HTML
detector.py         — detección 100% regex de secciones con contenido matemático
generador_pdf.py    — pipeline Markdown → PDF con ReportLab (puro Python)
generador_html.py   — pipeline elementos → HTML interactivo con Sonnet + ThreadPoolExecutor
prompts.py          — PROMPT_GENERADOR_HTML, PROMPT_DETECTOR_INTERACTIVIDAD, constructores
config.py           — constantes y carga de variables de entorno desde .env
```

---

## Flujo de trabajo

1. El profesor sube el `.md` generado por el Agente Contenido.
2. Pulsa **Detectar elementos**: `detectar_elementos()` agrupa el contenido matemático por sección y muestra un checkbox por sección.
3. El profesor selecciona las secciones que quiere incluir.
4. Elige el formato de salida:
   - **PDF completo** (sidebar, sin selección necesaria): `generar_pdf()` genera un PDF A4 con ReportLab.
   - **HTML interactivo** (área principal, con selección): `generar_html()` llama a Sonnet en paralelo para generar un bloque HTML por sección seleccionada y los ensambla en una página con pestañas CSS.

---

## Inputs y outputs

| Tipo | Descripción | Formato |
|------|-------------|---------|
| Input | Markdown curado del Agente Contenido | Markdown (`.md`) |
| Output | Documento académico paginado | PDF (`.pdf`) |
| Output | Página web interactiva con sliders y gráficas | HTML (`.html`) |

---

## Instalación y uso

```bash
pip install -r requirements.txt
cp .env.example .env   # añadir ANTHROPIC_API_KEY en .env
streamlit run app.py --server.port 8500
```

La `ANTHROPIC_API_KEY` es necesaria únicamente para generar el HTML interactivo (llamadas a Sonnet). El PDF se genera sin llamadas a la API.

---

## Selección de modelo

| Modelo | Tarea |
|--------|-------|
| `claude-sonnet-4-5` | Generación de bloques HTML interactivos (JS, sliders, Chart.js) |
| `claude-haiku-4-5-20251001` | Definido para desambiguación futura en `detector.py`; no cableado en la versión actual |

---

## Limitaciones conocidas

- **LaTeX no renderizado en PDF:** las ecuaciones aparecen en monospace con borde azul acento. ReportLab no tiene renderizador LaTeX nativo; añadir uno requeriría dependencias externas del sistema.
- **Haiku no integrado en el detector:** la detección es 100% determinista por regex. Las secciones sin encabezado usan los primeros tokens del contexto como nombre. La integración de Haiku para casos ambiguos está documentada como TODO en `detector.py`.
- **Rate limit en HTML interactivo:** con muchos elementos seleccionados, las cuatro llamadas paralelas a Sonnet pueden agotar el rate limit. El panel de error por elemento hace el fallo visible sin abortar el resto de la página.
- **Detección de tablas:** el umbral del 40% de celdas numéricas puede excluir tablas mixtas (texto + números).
