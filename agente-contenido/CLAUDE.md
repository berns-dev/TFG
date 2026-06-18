# Agente Contenido — Estado del proyecto

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-18

---

## Propósito

Convierte PDFs y PPTXs de material docente a Markdown estructurado y fiel al original. Incluye validador de fidelidad léxica (umbral 0.85), chunking semántico, selección de modelo por heurística y protocolo XML para parseo robusto.

**Granularidad de procesamiento (app-unificada):**
1. Curado del **bloque completo** — `procesar_bloque()` con las **horas del bloque** (no por subtema).
2. Reparto monótono — `split_monotono()` divide el markdown curado usando **nombres y orden** de los subtemas del Organizador (vía BD). La `evidencia` refuerza el emparejamiento de títulos. Sin llamadas a la API.
3. El profesor revisa el preview del reparto, confirma, y cura/aprueba **por subtema**.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output.

---

## Estado

Funcional. Validado con:
- Temas 1 y 2 de Tecnología de Materiales (PDFs con texto extraíble)
- Validación con PPTX reales: pendiente
- Pipeline de reparto monótono: `tools/validate_split_monotono.py` (15 checks)

Limitación documentada: Los PDFs exportados desde PowerPoint contienen texto extraíble, pero sin orden de lectura coherente — los cuadros de texto de cada diapositiva se depositan en el PDF en orden de edición, no visual. Decisión adoptada: aviso visible en UI cuando el nombre del archivo sugiere origen PowerPoint, recomendar PPTX nativo.

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para uploads)
- **API:** Anthropic directo
  - `claude-haiku-4-5-20251001` — chunks sin densidad matemática alta
  - `claude-sonnet-4-5` — chunks con ecuaciones, notación matemática densa
- **Extracción:** `pdfplumber` (PDF enriquecido vía `shared/pdf_enriched.py` + fallback plano), `python-pptx` (PPTX) vía `extractor.py`
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
classifier.py       — selección de modelo, SYSTEM_PROMPT, classify_and_format()
chunker.py          — split_into_chunks() — chunking semántico
extractor.py        — extract_text() para PDF (enriquecido + fallback) y PPTX
split_monotono.py   — split_monotono() — reparto del markdown curado por subtema
subblock_state.py   — SubbloqueResult, calcular_progreso_bloque/asignatura()
assembler.py        — assemble_markdown(), assemble_subbloque_body(), …
validator.py        — validate_items() — validador de fidelidad léxica
pipeline.py         — procesar_bloque(), procesar_segmento()
cnt_config.py       — constantes: modelos, thresholds, MAX_WORKERS
tools/validate_split_monotono.py — validación del reparto (sin API)
tools/validate_subbloques.py     — parseo Organizador + ensamblado + progreso
fixtures/           — artefactos de validación (Tema_3_curado.md)
```

---

## Flujo principal (app-unificada)

1. **Extracción** — `extract_text()` de todos los PDF/PPTX del bloque. PDF: `shared/pdf_enriched.build_pdf_markdown()` añade `#`/`##`/`###` según tamaño/negrita; si no hay metadatos de fuente, extracción plana.
2. **Curado del bloque** — `procesar_bloque(texto, horas_bloque)` → un markdown con frontmatter
3. **Reparto** — `split_monotono(markdown, subtemas_bd)` → N fragmentos (preview en UI)
4. **Confirmación** — persistir cada fragmento en `contenido_subbloque.markdown_borrador`
5. **Revisión** — el profesor edita y aprueba por subtema (estados `generado` → `aprobado`)

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
Cuando se cura un bloque, las **horas del bloque temático** (no por subtema) se inyectan
como prefijo del user message vía `_DENSITY_CONTEXT_TMPL`. Si `tema_horas is None`, el
chunk se envía sin prefijo de densidad.

---

## Reparto monótono (`split_monotono.py`)

`split_monotono(markdown_bloque, subtemas) → SplitResult`

- Empareja nombres de subtemas (BD / Organizador) con headings `#`–`####` del markdown curado.
- Restricción **monótona**: anclas en orden documental (evita reasignar por referencias cruzadas).
- `evidencia` (`Sección X.X`) refuerza el match; no segmenta PDF bruto.
- Confianza por fragmento + `requiere_revision` para la UI de preview.
- Validación: `tools/validate_split_monotono.py`.

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
