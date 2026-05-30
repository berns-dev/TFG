# Agente Contenido — Estado del proyecto

**Repositorio:** `berns-dev/agente-contenido-tfg`
**Última actualización:** 2026-05-30

---

## Propósito

Convierte PDFs y PPTXs de material docente a Markdown estructurado y fiel al original. Incluye validador de fidelidad léxica (umbral 0.85), chunking semántico, selección de modelo por heurística y protocolo XML para parseo robusto.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output.

---

## Estado

**~90% implementado.**

- Validado parcialmente: Temas 1 y 2 de Tecnología de Materiales (PDFs con texto extraíble)
- Pendiente: validación end-to-end con PPTX reales
- Pendiente: decisión sobre reconstrucción posicional para PDFs exportados desde PowerPoint (aplazada a próxima reunión con tutor)

**Limitación documentada:** PDFs exportados desde PPTX destruyen la estructura semántica irreversiblemente. Decisión adoptada: tratar como formato degradado con aviso visible en UI, preferir PPTX nativo.

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para uploads)
- **API:** Anthropic directo
  - `claude-haiku-4-5-20251001` — chunks sin densidad matemática alta
  - `claude-sonnet-4-5` — chunks con ecuaciones, notación matemática densa
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX) vía `extractor.py`
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
app.py          — UI Streamlit + sidebar + processing loop
classifier.py   — selección de modelo, SYSTEM_PROMPT, classify_and_format()
chunker.py      — split_into_chunks() — chunking semántico
extractor.py    — extract_text() para PDF y PPTX
assembler.py    — assemble_markdown(), assemble_multiple(), unified_download_filename()
validator.py    — validate_items() — validador de fidelidad léxica
config.py       — constantes: modelos, thresholds, MAX_WORKERS
```

---

## Flujo principal

1. **Extracción** — `extract_text(tmp_path)` desde archivo temporal
2. **Chunking** — `split_into_chunks(text)` — partición semántica, respeta frases
3. **Clasificación paralela** — `ThreadPoolExecutor(MAX_WORKERS)` → `classify_and_format(chunk, tema_horas)` por chunk
4. **Ensamblado** — `assemble_markdown(items, nombre_del_archivo)` → Markdown con frontmatter YAML
5. **Validación** — `validate_items(items, original_chunks)` — fidelidad léxica, umbral 0.85

---

## Decisiones de implementación clave

### Selección de modelo (`classifier.py: select_model()`)
Heurística determinista por densidad de símbolos matemáticos:
- Si `symbol_density > 0.02` o hay patrones `d/dt`, `d²`, `∫`, `Σ` → `MODEL_SMART` (Sonnet)
- Chunks cortos (`< MIN_CHARS_FOR_SMART`) → `MODEL_FAST` (Haiku)
- Resto → `MODEL_FAST` (Haiku)

Validado: Hollomon, Ramberg-Osgood, Weibull, Von Mises correctamente enrutados a Sonnet.

### Protocolo XML para parseo (`classifier.py: SYSTEM_PROMPT`)
El modelo responde con delimitadores estrictos:
```
<TIPO>...</TIPO>
<TITULO>...</TITULO>
<IDIOMA>...</IDIOMA>
<MARKDOWN>...</MARKDOWN>
```
`_parse_delimited_response()` extrae el contenido con regex tolerante. Hasta 3 reintentos si `contenido_markdown` es vacío o `<TIPO>` ausente.

### SYSTEM_PROMPT (inmutable)
El SYSTEM_PROMPT no se modifica bajo ninguna circunstancia. Es la restricción de fidelidad del agente. Los contextos adicionales (densidad de horas) van exclusivamente en el user message. Ver sección "Contexto de densidad" abajo.

### Contexto de densidad (`classifier.py: _build_user_message()`)
Cuando el usuario sube un `.md` del Agente Organizador y selecciona un bloque, las horas totales del bloque se inyectan como prefijo del user message:

```
[CONTEXTO DE DENSIDAD: Este tema tiene asignadas {horas}h lectivas.
Ajusta la extensión y profundidad del markdown en proporción al tiempo disponible —
más horas implica mayor desarrollo, menos horas mayor síntesis.
Restricción absoluta: no añadas contenido ausente en el material.]

{chunk_text}
```

Implementado en `_DENSITY_CONTEXT_TMPL` + `_build_user_message(chunk_text, tema_horas)`. Si `tema_horas is None`, el user message es el chunk directamente — el agente opera exactamente igual que antes.

---

## Input de organización (nuevo, 28/05/2026)

### Sección 1 — Organización del tema (sidebar, opcional)
El usuario puede subir el `.md` generado por el Agente Organizador.

**`parse_organization_md(content: str) -> list[dict]`** en `app.py`:
- Patrón: `^#{1,3}\s+(.+?)\s*·\s*([\d,.]+)h` (re.MULTILINE)
- Devuelve lista de dicts `{"nombre": str, "horas": float}`

Si se detectan bloques, aparece un `st.selectbox` con las opciones `"Nombre (Xh)"` para que el usuario seleccione manualmente cuál corresponde al material que está subiendo. No hay matching automático por nombre de archivo — la selección manual evita errores silenciosos.

`tema_horas` y `bloque_seleccionado` se extraen del selectbox y quedan en scope en `main()`. Se pasan a `classify_and_format(chunk, tema_horas)` en el processing loop.

### Sección 2 — Material del tema (sidebar, obligatorio)
Uno o varios PDF/PPTX. Sin cambios respecto a la versión anterior.

---

## Interfaz (estado actual)

### Identidad visual compartida con Agente Organizador
- **Tipografía:** Playfair Display (títulos, vía Google Fonts) + DM Sans (cuerpo)
- **Acento:** `#185FA5` (fijo, identidad de marca)
- **Fondos/textos:** variables CSS de Streamlit (`var(--background-color)`, `var(--secondary-background-color)`, `var(--text-color)`)
- **Bordes:** `rgba(128,128,128,0.2)` (adaptativos)

### Layout `layout="wide"`
- **Sidebar:** branding (Suite de Agentes / Agente Contenido) + steps 1-2-3 + sección 1 con file uploader `.md` + selectbox + separador + sección 2 con file uploader PDF/PPTX + botón "Procesar"
- **Área principal:** hero `st.components.v1.html()` + warning PDF exportado + processing loop + resultados

El botón "Procesar" usa `key="procesar_btn"`. El trigger en el área principal es `st.session_state.get("procesar_btn")` (True solo en el run en que se pulsó).

### Hero (`_HERO_CONT_HTML`)
Componente iframe con:
- Eyebrow "Agente 02", título "Generación de *contenido*", descripción
- Workflow de tres pasos (Organización → Material → Procesar)
- **Compatibilidad dark/light:** JS `sync()` lee luminancia del fondo del padre cada 800ms; aplica `.dark`/`.light` en `:root`; `@media(prefers-color-scheme:dark)` como fallback. `body{background:transparent}` hereda el color del padre.

### Dark/light mode
- Iframes: detección JS de luminancia del padre + CSS custom properties (`:root` / `:root.dark`)
- `st.markdown` CSS: `var(--background-color)`, `var(--secondary-background-color)`, `rgba()` para bordes
- Sidebar inline styles: `var(--text-color)` con `opacity` para jerarquía de texto
- Colores fijos preservados: `#185FA5` (acento), `#E6F1FB`/`#185FA5` (badges numerados)

---

## Output format

```markdown
---
archivo_origen: nombre.pdf
tipo_documento: ...
idioma: es
tema_detectado: ...
fecha_procesado: YYYY-MM-DD
compatible_agente_organizador: true
---

## Contenido teórico

[contenido estructurado del primer chunk]

---

## Ejemplos resueltos

...
```

El campo `compatible_agente_organizador: true` en el frontmatter indica que el Agente Organizador puede consumir este output como alternativa a los PDFs originales.

---

## Limitaciones documentadas

1. **PDFs exportados desde PPTX:** estructura semántica destruida irreversiblemente. Aviso en UI. Preferir PPTX nativo.
2. **Subíndices químicos:** `pdfplumber` pierde subíndices (ZrO₂ → "ZrO"). Limitación de la biblioteca.
3. **Chunking en posición no ideal:** `[TEXTO_ILEGIBLE]` puede aparecer por partición a mitad de contexto, no por fallo de extracción.
4. **Rate limit 429 Haiku:** concurrencia puede agotar el límite de 10.000 tokens output/min de Haiku con muchos chunks. No es bug del agente.

---

## Configuración de modelos

```
MODEL_FAST:  claude-haiku-4-5-20251001  — chunks sin densidad matemática alta
MODEL_SMART: claude-sonnet-4-5          — chunks con ecuaciones o notación densa
```

Ver `.cursorrules` para restricciones adicionales de desarrollo.
