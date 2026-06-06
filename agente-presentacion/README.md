# Agente Presentación — Agente 03 de la suite TFG

Detecta el contenido matemático del Markdown curado por el Agente Contenido y genera dos formatos de presentación: un PDF académico con tipografía y paginación estructurada, o una página HTML interactiva con sliders y gráficas en tiempo real.

---

## Qué hace

Recibe el Markdown estructurado producido por el Agente Contenido. Detecta secciones con ecuaciones LaTeX, relaciones paramétricas y tablas numéricas (regex + filtro Haiku opcional fail-open). El profesor selecciona qué secciones exportar. Genera PDF académico (ReportLab + ecuaciones como imágenes matplotlib) o HTML interactivo con sliders y Chart.js.

---

## Principio de fidelidad

El agente extrae y reformatea. No inventa. La explicación y la interpretación de cada panel interactivo se construyen exclusivamente a partir del contexto proporcionado en el Markdown de entrada.

---

## Arquitectura

```
app.py              — UI Streamlit, sidebar con PDF, área principal con detección y HTML
detector.py         — regex + filtro Haiku (fail-open) + advertencias Sonnet (opt-in)
generador_pdf.py    — pipeline Markdown → PDF con ReportLab (ecuaciones vía matplotlib)
generador_html.py   — pipeline elementos → HTML interactivo con Sonnet + ThreadPoolExecutor
prompts.py          — prompts del sistema y constructores de mensajes
config.py           — constantes y carga de variables de entorno desde .env
```

---

## Flujo de trabajo

1. El profesor sube el `.md` generado por el Agente Contenido.
2. Opcional: marca «Analizar advertencias pedagógicas» si quiere avisos Sonnet antes del HTML (más créditos).
3. Pulsa **Detectar elementos**: regex agrupa por sección; Haiku filtra candidatos no interactivos (si la API falla, se conservan todos — fail-open).
4. El profesor selecciona las secciones con checkboxes.
5. Elige el formato de salida:
   - **PDF completo** (sidebar): `generar_pdf()` con ReportLab y ecuaciones renderizadas como PNG (matplotlib mathtext).
   - **HTML interactivo** (área principal): `generar_html()` genera un bloque por sección seleccionada.

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
| `claude-sonnet-4-5` | Bloques HTML, razonador de visualización, advertencias pedagógicas (opt-in) |
| `claude-haiku-4-5-20251001` | Filtro de interactividad tras regex (fail-open si la API falla) |

---

## Limitaciones conocidas

- **Ecuaciones en PDF:** renderizadas como imágenes PNG vía matplotlib mathtext (no LaTeX del sistema). Si falla el render, fallback a texto monospace con borde.
- **Haiku fail-open:** si el filtro Haiku falla (timeout, rate limit), se conservan todos los candidatos regex para no bloquear al profesor.
- **Advertencias pedagógicas:** desactivadas por defecto; activar la checkbox implica una llamada Sonnet por elemento detectado.
- **Rate limit en HTML interactivo:** con muchos elementos seleccionados, las llamadas paralelas a Sonnet pueden agotar el rate limit. El panel de error por elemento hace el fallo visible sin abortar el resto de la página.
- **Detección de tablas:** el umbral del 40% de celdas numéricas puede excluir tablas mixtas (texto + números).
