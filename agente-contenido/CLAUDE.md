# Agente Contenido — Estado del proyecto

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-17

---

## Propósito

Convierte PDFs y PPTXs de material docente a Markdown estructurado y fiel al original. Incluye validador de fidelidad léxica (umbral 0.85), chunking semántico, selección de modelo por heurística y protocolo XML para parseo robusto.

**Granularidad de procesamiento:** cuando el profesor sube el `.md` del Agente Organizador, el agente lee los subbloques del bloque seleccionado (con sus evidencias estructurales), segmenta el texto del material en trozos correspondientes a cada subbloque, y genera un Markdown curado independiente por subbloque. El output final del bloque es un Markdown único con secciones identificables por subbloque.

Cuando el profesor aporta el `.md` del Agente Organizador, el agente lee las horas lectivas del subbloque seleccionado y calibra la extensión y profundidad del Markdown en proporción a ese tiempo. Esta información se inyecta como prefijo del user message (`_DENSITY_CONTEXT_TMPL` en `classifier.py`) sin alterar el SYSTEM_PROMPT ni el principio de no añadir contenido ausente en el material.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output.

---

## Estado

Funcional. Validado con:
- Temas 1 y 2 de Tecnología de Materiales (PDFs con texto extraíble)
- Validación con PPTX reales: pendiente
- Pipeline de subbloques: validado programáticamente (53/53 checks, `tools/validate_subbloques.py`)

Limitación documentada: Los PDFs exportados desde PowerPoint contienen texto extraíble, pero sin orden de lectura coherente — los cuadros de texto de cada diapositiva se depositan en el PDF en orden de edición, no visual. Decisión adoptada: aviso visible en UI cuando el nombre del archivo sugiere origen PowerPoint, recomendar PPTX nativo.

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
app.py              — UI Streamlit + sidebar + processing loop (por subbloque o clásico)
classifier.py       — selección de modelo, SYSTEM_PROMPT, classify_and_format()
chunker.py          — split_into_chunks() — chunking semántico
extractor.py        — extract_text() para PDF y PPTX
segmentor.py        — segment_text_by_subbloques() — segmentación por evidencia estructural
subblock_state.py   — SubbloqueResult, calcular_progreso_bloque/asignatura()
assembler.py        — assemble_markdown(), assemble_subbloque_body(),
                      assemble_block_with_subbloques(), assemble_multiple()
validator.py        — validate_items() — validador de fidelidad léxica
pipeline.py         — FUENTE DE VERDAD importable: procesar_segmento()
                      (chunk → classify paralelo → assemble_subbloque_body → validate)
                      Compartida entre app.py standalone y app-unificada
config.py           — constantes: modelos, thresholds, MAX_WORKERS
tools/validate_pdf.py        — debug CLI extract → chunk (no producto)
tools/validate_subbloques.py — validación de la pipeline de subbloques (sin API)
fixtures/           — artefactos de validación (Tema_3_curado.md)
```

---

## Flujo principal (con subbloques)

1. **Extracción** — `extract_text(tmp_path)` desde archivo temporal
2. **Segmentación** — `segment_text_by_subbloques(text, subbloques)` — divide el texto
   en segmentos correspondientes a cada subbloque del Organizador, usando las evidencias
   estructurales (`[SLIDE N]`, `^X.X. Título`) como marcadores de frontera
3. **Por cada subbloque:** chunking → clasificación paralela → ensamblado → validación
4. **Ensamblado del bloque** — `assemble_block_with_subbloques(...)` → Markdown con
   marcadores `<!-- SUBBLOQUE_INICIO/FIN: ... -->` que delimitan cada subbloque
5. **Progreso** — `calcular_progreso_bloque(sb_results)` → dict con total/aprobados/porcentaje

**Flujo clásico (sin subbloques):** si no hay `.md` del Organizador o el bloque
tiene un único subbloque fallback, el agente usa el pipeline original
(chunks del bloque completo → `assemble_markdown()`). El `session_state` siempre tiene
la misma estructura con un único subbloque envolviendo el resultado.

---

## Flujo principal (clásico, sin subbloques)

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
Cuando el usuario sube un `.md` del Agente Organizador y selecciona un bloque, las horas del **subbloque** (no del bloque completo) se inyectan como prefijo del user message:

```
[CONTEXTO DE DENSIDAD: Este tema tiene asignadas {horas}h lectivas.
Ajusta la extensión y profundidad del markdown en proporción al tiempo disponible —
más horas implica mayor desarrollo, menos horas mayor síntesis.
Restricción absoluta: no añadas contenido ausente en el material.]

{chunk_text}
```

Implementado en `_DENSITY_CONTEXT_TMPL` + `_build_user_message(chunk_text, tema_horas)`. Si `tema_horas is None`, el user message es el chunk directamente — el agente opera exactamente igual que antes.

---

## Segmentación de texto por subbloque (`segmentor.py`)

### Cómo funciona
`segment_text_by_subbloques(text, subbloques) → list[tuple[dict, str]]`

Para cada subbloque, usa el campo `evidencia` del Organizador para localizar su
frontera de inicio en el texto extraído:

| Tipo de evidencia | Qué busca en el texto |
|---|---|
| `"Slide N"` | `[SLIDE N]` (inyectado por `_extract_pptx`) |
| `"Sección X.X"` | `^X.X.?\s+\S` al inicio de línea (encabezado numerado) |
| `"Sin señal verificable"` | No segmenta; todo el texto va al único subbloque |

El texto antes del primer boundary encontrado se adjunta al primer subbloque (material introductorio).
Subbloques cuya evidencia no se localiza en el texto reciben segmento vacío y estado `pendiente`.

### Garantías
- Un único subbloque (incluido el fallback "Sin señal verificable"): recibe todo el texto. ✓
- Sin ningún boundary encontrado: primer subbloque recibe todo el texto; resto vacíos. ✓
- Los boundaries se ordenan por posición en el texto (defensivo). ✓
- Cuando un subbloque queda vacío por boundary no encontrado (evidencia no-fallback),
  `app.py` emite `st.warning()` indicando el nombre del subbloque y la referencia buscada. ✓

---

## Modelo de estados por subbloque (`subblock_state.py`)

```
pendiente  →  generado  →  aprobado
                 ↓              ↑
              editado  ─────────┘
```

| Estado | Significado |
|---|---|
| `pendiente` | Segmento vacío o error de extracción; el profesor edita manualmente |
| `generado` | La API produjo el Markdown; pendiente de revisión |
| `editado` | El profesor modificó el Markdown (sin nueva llamada a la API) |
| `aprobado` | El profesor aceptó el contenido (original o editado) |

**La UI que gestiona las transiciones de estado es una fase posterior.** El modelo de estados está implementado y expuesto en `session_state["resultados"][i]["subbloques"]`. Las transiciones `generado → editado → aprobado` las hará la futura interfaz de revisión.

---

## Formato de salida del bloque (con subbloques)

```markdown
---
archivo_origen: nombre.pdf
bloque: Nombre del bloque
bloque_horas: 8.0
idioma: es
fecha_procesado: YYYY-MM-DD
total_subbloques: 3
compatible_agente_organizador: true
---

<!-- SUBBLOQUE_INICIO: id="0" nombre="Defectos y dislocaciones" horas="3.0" estado="generado" -->

# Defectos y dislocaciones

## Contenido teórico

[contenido curado del subbloque 0]

<!-- SUBBLOQUE_FIN: id="0" -->

---

<!-- SUBBLOQUE_INICIO: id="1" nombre="Mecanismos de endurecimiento" horas="3.0" estado="pendiente" -->

*Contenido pendiente de procesar.*

<!-- SUBBLOQUE_FIN: id="1" -->
```

Los comentarios HTML son invisibles al renderizar Markdown. Para parsear subbloques:
```python
import re
inicios = re.findall(r'<!-- SUBBLOQUE_INICIO: (.*?) -->', md)
cuerpos = re.findall(r'<!-- SUBBLOQUE_INICIO:.*?-->\s*(.*?)\s*<!-- SUBBLOQUE_FIN:.*?-->', md, re.DOTALL)
```

### Contrato del frontmatter — campos presentes por pipeline

| Campo | Pipeline con subbloques | Pipeline clásico |
|---|---|---|
| `archivo_origen` | ✓ siempre | ✓ siempre |
| `idioma` | ✓ siempre | ✓ siempre |
| `fecha_procesado` | ✓ siempre | ✓ siempre |
| `compatible_agente_organizador` | ✓ siempre | ✓ siempre |
| `bloque` | ✓ siempre | — ausente |
| `bloque_horas` | ✓ siempre | — ausente |
| `total_subbloques` | ✓ siempre | **— ausente** |
| `tipo_documento` | — ausente | ✓ siempre |
| `tema_detectado` | — ausente | ✓ siempre |

**`total_subbloques` es un campo opcional** — solo está presente cuando el bloque se
procesó con la pipeline de subbloques (bloque_subbloques disponible desde el .md del
Organizador). El pipeline clásico produce un frontmatter distinto con `tipo_documento`
y `tema_detectado`. Cualquier código que consuma el Markdown de este agente **debe
comprobar la presencia de `total_subbloques` antes de usarlo**, sin asumir que existe.

---

## Estructura de `session_state["resultados"]`

```python
{
    "nombre": "archivo.pdf",          # nombre del archivo subido
    "stem": "archivo",
    "markdown": "---\n...",           # Markdown completo del bloque (con marcadores)
    "subbloques": [                   # lista de SubbloqueResult.to_dict()
        {
            "nombre": "Defectos y dislocaciones",
            "horas": 3.0,
            "evidencia": "Sección 3.1",
            "origen": "Detectado",
            "estado": "generado",     # pendiente|generado|editado|aprobado
            "markdown": "# Defectos...",  # Markdown curado del subbloque
            "items": [...],           # chunks clasificados
            "validacion": {...},      # reporte de fidelidad
        },
        ...
    ],
    "progreso": {                     # calculado por calcular_progreso_bloque()
        "total": 3,
        "aprobados": 0,
        "porcentaje": 0.0,
    },
    "items": [...],                   # todos los items agregados (compat. clásico)
    "validacion": {...},              # reporte agregado de todos los subbloques
    "error": None,
}
```

**Compatibilidad:** sin subbloques del Organizador, el resultado tiene la misma
estructura pero con `subbloques` de longitud 1 (un único subbloque envuelve todo el
bloque), preservando el contrato de la interfaz hacia código futuro.

---

## Cálculo de progreso (`subblock_state.py`)

```python
from subblock_state import calcular_progreso_bloque, calcular_progreso_asignatura, SubbloqueResult

# Progreso de un bloque (a partir de la lista de SubbloqueResult):
progreso = calcular_progreso_bloque(sb_results)
# → {"total": 3, "aprobados": 1, "porcentaje": 33.3}

# Progreso de toda la asignatura (todos los subbloques de todos los bloques procesados):
todos = [sb for res in session_state["resultados"] for sb in res["subbloques_objects"]]
progreso_global = calcular_progreso_asignatura(todos)
```

**Nota:** `calcular_progreso_asignatura` recibe una lista plana de `SubbloqueResult`.
La UI que agrege los resultados de varios bloques debe construir esa lista.

---

## Input de organización (sidebar, opcional)

### Sección 1 — Organización del tema

El usuario puede subir el `.md` generado por el Agente Organizador.

**`parse_organization_md(content: str) -> list[dict]`** en `app.py`:
- Patrón bloque: `^##\s+Bloque\s+\d+\s+—\s+(.+?)\s*·\s*([\d,.]+)h` (re.MULTILINE)
- Por cada bloque, parsea la tabla de subbloques (`_parse_subbloques_table()`)
- Soporta tablas de 4 columnas (`| Subtema | Horas | Evidencia | Origen |`) y
  3 columnas (`| Subtema | Horas | Origen |`, flujo post-edición manual)
- Devuelve lista de dicts `{"nombre": str, "horas": float, "subbloques": list[dict]}`

El selectbox muestra las opciones `"Nombre (Xh)"` para que el usuario seleccione
manualmente cuál corresponde al material. No hay matching automático por nombre de
archivo. Si el bloque tiene subbloques, se muestra el recuento en el sidebar.

### Sección 2 — Material del tema (sidebar, obligatorio)
Uno o varios PDF/PPTX. Sin cambios respecto a la versión anterior.

---

## App unificada — vista Contenido (`app-unificada/app.py`)

Flujo de trabajo del profesor sobre un bloque temático:

1. **Índice** de sub-bloques con estado (pendiente / en revisión / aprobado con nota y % modificación).
2. **Generación por selección:** checkboxes solo en sub-bloques sin borrador previo + botón
   «Generar seleccionados (N)». Cada sub-bloque marcado dispara **su propia** llamada a la API
   (segmentación por evidencia independiente). No se regeneran los que ya tienen borrador.
3. **Revisión paralela:** todos los sub-bloques en estado `generado`/`editado` quedan abiertos
   a la vez; el profesor confirma y puntúa cada uno en el orden que prefiera.
4. **Confirmación:** slider 1-10 + «Confirmar y valorar» → `puntuacion_profesor` en
   `contenido_subbloque` (no en `valoraciones_profesor`).

**Valoración:** Contenido puntúa por sub-bloque. La tabla global `valoraciones_profesor` es solo
para el Organizador (zoom out curricular). Ver `database/CLAUDE.md` — no unificar sin decisión explícita.

---

## Interfaz (estado actual)

### Identidad visual compartida con Agente Organizador
- **Tipografía:** Playfair Display (títulos, vía Google Fonts) + DM Sans (cuerpo)
- **Acento:** `#185FA5` (fijo, identidad de marca)
- **Fondos/textos:** variables CSS de Streamlit (`var(--background-color)`, `var(--secondary-background-color)`, `var(--text-color)`)
- **Bordes:** `rgba(128,128,128,0.2)` (adaptativos)

### Layout `layout="wide"`
- **Sidebar:** branding (Suite de Agentes / Agente Contenido) + steps 1-2-3 + sección 1 con file uploader `.md` + selectbox (+ caption con n.º subbloques) + separador + sección 2 con file uploader PDF/PPTX + botón "Procesar"
- **Área principal:** hero + warning PDF exportado + processing loop + resultados

### Métricas en resultados
- Con subbloques: `Subbloques (n)` + `Aprobados (X/n, %)` + resumen de estados
- Sin subbloques (clásico): `Bloques totales (n)` + resumen de tipos

---

## Output format (clásico, sin subbloques)

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

[todos los chunks de teoría y mixtos, en orden de aparición]

---

## Ejemplos resueltos

...
```

Ver sección "Formato de salida del bloque (con subbloques)" para el nuevo formato.

---

## Ensamblado por secciones canónicas (`assembler.py`)

`assemble_markdown()` agrupa los cuerpos de los chunks por tipo y emite cada
sección `##` **una sola vez**, en orden canónico fijo. Reglas:

- **`mixto` se fusiona con `teoria`.** Los chunks clasificados como `mixto` no
  generan sección propia; su contenido se vuelca dentro de `## Contenido teórico`
  / `## Theory`, intercalado en orden de aparición con el resto de la teoría.
- **Secciones `##` canónicas principales (máximo 5):**
  `## Contenido teórico` / `## Theory` (teoría + mixto),
  `## Tablas de referencia` / `## Reference tables`,
  `## Ejemplos resueltos` / `## Solved examples`,
  `## Ejercicios propuestos` / `## Practice problems`,
  `## Resumen` / `## Summary`.
- **H2 no canónicos.** Cualquier `##` que el modelo emita con un nombre fuera de
  la tabla canónica se degrada a `###`.

**Nuevas funciones en `assembler.py`:**

- `assemble_subbloque_body(items, nombre_subbloque, nombre_del_archivo)`:
  llama a `assemble_markdown()` internamente, luego extrae el cuerpo (sin
  frontmatter, sin H1) y prepone el H1 del nombre del subbloque. Preserva los
  H2 canónicos. Usa `_strip_frontmatter_only()` (no `_body_after_frontmatter()`
  que también eliminaría los H2).

- `assemble_block_with_subbloques(subbloque_results, nombre_del_archivo, nombre_bloque, bloque_horas)`:
  genera el Markdown completo del bloque con frontmatter específico y secciones
  delimitadas por `<!-- SUBBLOQUE_INICIO/FIN: ... -->`.

---

## Limitaciones documentadas

1. **PDFs exportados desde PowerPoint:** texto extraíble pero sin orden de lectura coherente (cuadros depositados en orden de edición, no visual). Aviso en UI. Preferir PPTX nativo.
2. **Subíndices químicos:** `pdfplumber` pierde subíndices (ZrO₂ → "ZrO"). Limitación de la biblioteca.
3. **Chunking en posición no ideal:** `[TEXTO_ILEGIBLE]` puede aparecer por partición a mitad de contexto, no por fallo de extracción.
4. **Rate limit 429 Haiku:** concurrencia puede agotar el límite de 10.000 tokens output/min de Haiku con muchos chunks. No es bug del agente.
5. **Segmentación parcial:** si la evidencia de un subbloque no se encuentra en el texto (p. ej., las señales estructurales del material no coinciden exactamente con las del Organizador), ese subbloque queda con estado `pendiente` y texto vacío. La UI emite un `st.warning()` indicando qué referencia concreta no se localizó. El profesor puede editarlo manualmente.

---

## Configuración de modelos

```
MODEL_FAST:  claude-haiku-4-5-20251001  — chunks sin densidad matemática alta
MODEL_SMART: claude-sonnet-4-5          — chunks con ecuaciones o notación densa
```

Ver `.cursorrules` para restricciones adicionales de desarrollo.
