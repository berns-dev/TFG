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
- Temas 1 y 2 de Tecnología de Materiales (PDF)
- Frenos (PDF exportado desde PowerPoint) — extracción PyMuPDF + cleaner ligero
- PPTX nativo: soporte en `extractor.py`; validación sistemática pendiente
- Tests sin API: `validate_split_monotono.py`, `validate_cleaner.py`, `validate_pdf_enriched.py`

**Punto de entrada UI:** `app-unificada/app.py` (no hay `app.py` standalone en este agente).

Limitación documentada: los PDFs exportados desde PowerPoint siguen siendo peores que el
PPTX nativo (orden de lectura, ecuaciones). La UI avisa cuando el nombre sugiere origen PPT.
Preferir PPTX cuando exista.

---

## Stack técnico

- **UI:** integrada en `app-unificada/app.py` (vista Contenido)
- **API:** Anthropic directo
  - `claude-haiku-4-5-20251001` — chunks sin densidad matemática alta
  - `claude-sonnet-4-5` — chunks con ecuaciones, notación matemática densa
- **Extracción PDF** (`extractor.py` + `shared/pdf_enriched.py`):
  1. **PyMuPDF** (`build_pdf_markdown_pymupdf`) — primario; mejor decodificación math y orden de lectura
  2. **pdfplumber enriquecido** (`build_pdf_markdown`) — fallback
  3. **pdfplumber plano** — último recurso
- **Limpieza** (`cleaner.py`): modo **ligero** en PDF enriquecido (sin filtro de frecuencia
  estructural; sí regex + glifos de cabecera 1–2 chars repetidos en ≥80% páginas);
  modo **completo** en extracción plana y PPTX. Headings `#`/`##`/`###` nunca se eliminan
  por frecuencia. Ecuaciones corruptas → `[ECUACION_PARCIAL: …]` / `[ECUACION_NO_EXTRAIBLE]`.
- **PPTX:** `python-pptx` vía `extractor.py`
- **Credenciales:** `agente-contenido/.env` + `python-dotenv`

---

## Arquitectura de archivos

```
extractor.py        — extract_text(); cadena pymupdf → pdfplumber → plano; PPTX
cleaner.py          — clean_extracted_text(light=…); filtro de glifos repetidos
classifier.py       — selección de modelo, SYSTEM_PROMPT, classify_and_format()
chunker.py          — split_into_chunks() — chunking semántico
split_monotono.py   — split_monotono() — reparto del markdown curado por subtema
subblock_state.py   — SubbloqueResult, calcular_progreso_bloque/asignatura()
assembler.py        — assemble_markdown(), assemble_subbloque_body(), …
validator.py        — validate_items() — validador de fidelidad léxica
pipeline.py         — procesar_bloque(), procesar_segmento()
cnt_config.py       — constantes: modelos, thresholds, MAX_WORKERS
../shared/pdf_enriched.py — build_pdf_markdown_pymupdf(), build_pdf_markdown()
tools/validate_split_monotono.py
tools/validate_cleaner.py
tools/validate_pdf_enriched.py
tools/validate_subbloques.py
tools/validate_pdf.py       — debug CLI (extract → chunk, sin API)
fixtures/                   — artefactos de validación (Tema_3_curado.md)
```

---

## Flujo principal (app-unificada)

1. **Extracción** — `extract_text()` de todos los PDF/PPTX del bloque (rutas en BD desde Organizador).
2. **Curado del bloque** — `procesar_bloque(texto, horas_bloque)` → un markdown con frontmatter (API).
3. **Reparto** — `split_monotono(markdown, subtemas_bd)` → N fragmentos; preview con anclas y confianza.
4. **Confirmación** — «Confirmar reparto» → cada fragmento en `contenido_subbloque.markdown_borrador`.
5. **Revisión** — el profesor edita, puntúa (1–10) y aprueba por subtema (`generado` → `aprobado`).

### Extracción PDF (detalle)

```
PDF → build_pdf_markdown_pymupdf()     [prefijos #/##/###, spans math]
  → _clean_page_blocks(light=True)     [cleaner ligero + glifos]
  → fallback build_pdf_markdown()      [pdfplumber enriquecido]
  → fallback _extract_pdf_plain()      [pdfplumber + cleaner completo]
```

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

## Input de organización (opcional en scripts; vía BD en app-unificada)

El bloque y sus subtemas llegan desde SQLite (generados por el Organizador). Para parsear
un `.md` del Organizador fuera de la app, usar `parsear_bloques_organizador()` en
`agente-organizador/parser.py` o la lógica equivalente en `app-unificada/app.py`.

Patrón de bloque: `^##\s+Bloque\s+\d+\s+—\s+(.+?)\s*·\s*([\d,.]+)h`

Tabla de subtemas: `| Subtema | Evidencia | Origen |` (sin horas por subtema).

---

## App unificada — vista Contenido

Flujo del profesor sobre un bloque temático (datos en SQLite):

1. **Índice** de sub-bloques con estado (sin borrador / en revisión / aprobado con nota).
2. **Generar borrador del bloque** — una pasada API sobre todo el material + reparto monótono;
   vista previa con anclas, confianza y avisos de `requiere_revision`.
3. **Confirmar reparto** — persiste borradores en `contenido_subbloque`.
4. **Revisión** — expanders por subtema; edición, slider 1–10, «Confirmar y valorar».

**Valoración:** nota por sub-bloque en `contenido_subbloque.puntuacion_profesor`. La tabla
`valoraciones_profesor` es solo para el Organizador. Ver `database/CLAUDE.md`.

---

## Interfaz e identidad visual

La UI vive en `app-unificada/app.py` (pestaña/vista Contenido). Identidad compartida:
Playfair Display + DM Sans, acento `#185FA5`, layout `wide`. Aviso visible si el material
parece PDF exportado desde PowerPoint.

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

1. **PDFs exportados desde PowerPoint:** peor que PPTX nativo (orden, ecuaciones). PyMuPDF y el
   cleaner mitigan pero no eliminan el problema. Aviso en UI; preferir PPTX.
2. **Subíndices químicos:** pueden perderse según fuente y extractor (pdfplumber peor que pymupdf en algunos casos).
3. **Chunking en posición no ideal:** `[TEXTO_ILEGIBLE]` puede aparecer por partición a mitad de contexto.
4. **Rate limit 429 Haiku:** concurrencia alta con muchos chunks puede agotar el límite de output/min.
5. **Reparto monótono:** si un subtema no tiene ancla en el markdown curado, el fragmento queda débil
   (`requiere_revision` en preview); el profesor corrige en revisión. No hay segmentación PDF por evidencia
   (eliminada junio 2026).
6. **Ecuaciones:** pymupdf emite `[ECUACION]` en spans ilegibles; el cleaner emite `[ECUACION_PARCIAL]`.
   El LLM no completa fórmulas por conocimiento general (principio de fidelidad).

---

## Configuración de modelos

```
MODEL_FAST:  claude-haiku-4-5-20251001  — chunks sin densidad matemática alta
MODEL_SMART: claude-sonnet-4-5          — chunks con ecuaciones o notación densa
```

Ver `.cursorrules` para restricciones adicionales de desarrollo.
