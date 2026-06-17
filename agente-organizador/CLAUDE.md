# Agente Organizador — Estado del proyecto

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-17

---

## Propósito

Extrae temas, subbloques y distribución horaria de una asignatura a partir de la guía docente y los materiales de teoría. Produce un Markdown con la distribución temática y las horas asignadas por subbloque.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output. Cada subbloque propuesto debe poder justificarse señalando una referencia concreta del documento fuente.

---

## Estado

**Funcional. Validado con tres asignaturas reales:**
- Oleohidráulica y Neumática
- Elementos de Máquinas
- Tecnología de Materiales

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para uploads)
- **API:** Anthropic directo — `claude-sonnet-4-5` (generación y refinamiento)
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX) vía `parser.py`
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
app.py        — UI Streamlit + lógica de sesión + validación + edición manual
agente.py     — cliente Anthropic, ejecutar_agente()
parser.py     — extraer_texto(), clasificar_archivo(), señales estructurales
prompts.py    — construir_prompt(), construir_prompt_refinamiento()
```

---

## Flujo principal

1. **Extracción** — `extraer_texto()` sobre guía docente y materiales de teoría
2. **Clasificación** — `clasificar_archivo()` separa "teoría" de "contexto/outline"
3. **Detección de señales estructurales** — `extraer_candidatos_con_evidencia()` en `parser.py`:
   - Prioridad 1: secciones numeradas en el texto (`3.2. Título`) → evidencia = "Sección 3.2"
   - Prioridad 2 (solo PPTX): títulos de diapositiva → evidencia = "Slide N"
   - Fallback: si ninguna fuente ofrece señal verificable, retorna `[]`; el bloque se trata como un único subbloque
4. **Editor de subbloques** — interfaz de revisión (fase `"editar"`): el profesor ve las señales detectadas con su evidencia, edita la lista en un textarea, y confirma
5. **Detección de horas** — `extraer_horas_docencia()` en `app.py`
6. **Generación** — `construir_prompt()` → `ejecutar_agente()` → Sonnet
7. **Validación de cardinalidad** — `contar_bloques_output()` compara `## Bloque N` con `len(textos_teoria)`
8. **Refinamiento** — loop hasta 5 iteraciones; `construir_prompt_refinamiento()` (camino rápido)

---

## Subbloques con evidencia estructural (Objetivo 1)

### Prioridad de fuentes (estricta, no negociable)

1. **Guía docente** — si ya enumera subtemas/conceptos dentro de un bloque, se usa esa enumeración literal.
2. **Materiales de teoría — secciones numeradas** — encabezados con patrón `\d+(\.\d+)*\. Título` en el texto extraído. Evidencia: `"Sección X.X"`.
3. **Materiales de teoría — títulos de diapositiva PPTX** — placeholder `idx=0` o primera shape corta (<100 chars, sin saltos). Evidencia: `"Slide N"`. Solo se usa si no hay secciones numeradas.
4. **Fallback obligatorio** — si ninguna fuente ofrece señal suficientemente verificable, el bloque no se subdivide. Se crea un único subbloque igual al bloque completo y se marca `Evidencia = "Sin señal verificable"`. La interfaz muestra un aviso visible al profesor.

### Restricción de generación automática

El modelo nunca debe agrupar contenido por similitud temática libre. Cada subbloque propuesto debe justificarse señalando una evidencia concreta. Esto se aplica tanto en la generación inicial (vía `instruccion_subtemas` en `prompts.py`) como en los refinamientos.

### Flujo de evidencia

```
extraer_candidatos_con_evidencia()
  → [{nombre, evidencia, fuente}]  ← parser.py
  → editor_data[i]["candidatos_con_evidencia"]  ← app.py
  → mostrado en interfaz como referencia (read-only)
  → al confirmar: subtemas_confirmados[i] = [{nombre, origen, evidencia}]
  → construir_prompt(): "SUBTEMAS CONFIRMADOS: - nombre [Evidencia: X] [origen]"
  → LLM: columna Evidencia en la tabla de subbloques
  → output Markdown: | Subtema | Horas | Evidencia | Origen |
```

---

## Edición manual de la organización (Objetivo 2)

### Controles disponibles (solo en fase `"resultado"`)

- **Añadir subbloque** — texto + horas, dentro de un bloque existente. Origen = "Manual".
- **Eliminar subbloque** — botón 🗑 por subbloque.
- **Añadir bloque** — nombre; se añade con horas=0 y subbloques vacíos. Se numera como max+1.
- **Eliminar bloque** — botón 🗑 elimina bloque + todos sus subbloques.

La edición manual NO requiere verificación de señal estructural — refleja el criterio pedagógico del profesor. No aplica el principio de anclaje a evidencia del Objetivo 1.

### Coexistencia con refinamiento por prompt

Ambos mecanismos operan sobre el mismo estado:
- Edición manual → actualiza `organizacion_bloques` → regenera `ultimo_output` con `regenerar_markdown_desde_bloques()`
- Refinamiento por IA → recibe `ultimo_output` (post-edición si la hubo) → LLM genera nueva versión → `_validar_y_persistir()` → re-parsea a `organizacion_bloques`

Los dos mecanismos coexisten sin pisarse. El estado es siempre consistente.

---

## Fases de la aplicación

| Fase | Valor | Descripción |
|------|-------|-------------|
| Inicial | `None` | Sin archivos procesados |
| Edición de subbloques | `"editar"` | Después de `extraer_y_detectar()`. Muestra editor de subbloques con señales detectadas. No hay output aún. |
| Resultado | `"resultado"` | Después de `_validar_y_persistir()`. Muestra output + editor manual + refinamiento por IA + botón "Cerrar". |
| Cerrado | `"cerrado"` | Después de "Dar organización por cerrada". Output congelado. Sin edición. Solo descarga. |

**Restricción temporal de edición:** la edición (manual y por prompt) solo está disponible en fase `"resultado"`. En fase `"cerrado"` se muestran aviso informativo, output y descarga; los controles de edición no se renderizan.

---

## Decisiones de implementación clave

### Selección de modelo
Sonnet para toda la generación y refinamiento. El razonamiento curricular requiere coherencia semántica que Haiku no garantiza con prompts de cardinalidad estricta.

### Código determinista para horas
`extraer_horas_docencia()` resuelve la extracción de TE/PA/PL con código Python puro, sin LLM. Dos estrategias:
1. **Estrategia 1 (preferente):** detecta tabla(s) MODALIDADES por cabecera y lee la columna Horas. Elige la ventana con mayor completitud y mayor confianza en la fila PA.
2. **Estrategia 2 (fallback):** búsqueda en texto libre, exige señales horarias explícitas para evitar confundir "sesiones" con horas.

### Código determinista para señales estructurales
`extraer_candidatos_con_evidencia()` en `parser.py`. Prioridad estricta de fuentes (no negociable). No llama al LLM. Si retorna `[]`, el bloque es un único subbloque — el modelo nunca infiere subbloques libres para bloques sin señal.

### Parseo/serialización para edición manual
- `parsear_bloques_desde_markdown(markdown)` → `[{numero, nombre, horas, subtemas}]`
- `regenerar_markdown_desde_bloques(bloques, markdown_original)` → Markdown preservando cabecera y pie del original
- Formato serializado: `| Subtema | Horas | Origen |` (3 columnas, Origen = "Manual"/"Detectado")

### Restricción de cardinalidad en el prompt (`prompts.py`)
`instruccion_cardinalidad` tiene tres refuerzos desde la corrección del bug (28/05/2026):
1. **Autoridad estructural:** la guía docente define la estructura (qué es un bloque, cuántos existen); los materiales de teoría son fuente de contenido, no de estructura.
2. **Regla anti-fragmentación:** un subtópico con horas propias en la guía docente sigue siendo subtema dentro de su bloque — nunca bloque independiente.
3. **Autoverificación obligatoria:** el modelo debe contar sus propios encabezados `## Bloque N` antes de responder; si el recuento difiere de `n_bloques`, debe reorganizar.

### Loop de refinamiento optimizado (`prompts.py`)
`construir_prompt_refinamiento()` es un prompt ligero que:
- Toma el output previo como base (ya tiene la estructura correcta)
- Solo aplica el último ajuste de feedback
- No re-extrae documentos ni re-detecta horas
- Mantiene la restricción de suma de horas totales si `horas_totales` está disponible
- Instruye al modelo a preservar las columnas Evidencia y Origen tal como están

---

## Bug documentado y corregido: cardinalidad de bloques

**Bug (detectado 26/05/2026):** el agente generaba N+1 bloques cuando la guía docente listaba una subsección con horas propias.

**Fix (28/05/2026):** `instruccion_cardinalidad` reescrita con tres refuerzos; `contar_bloques_output()` + `_validar_y_persistir()` añadidos; `st.warning` visible.

---

## Output format

Fuente de verdad: plantilla en `prompts.py` → `construir_prompt()`.

**Con subbloques confirmados (flujo normal):**
```markdown
# DISTRIBUCIÓN TEMÁTICA — {NOMBRE_ASIGNATURA}

**Horas lectivas disponibles:** {TOTAL}h ({TE}h TE + {PA}h PA) | **Prácticas de laboratorio:** {PL}h *(informativo)*

---

## Bloque {N} — {NOMBRE_BLOQUE} · {HORAS_BLOQUE}h

| Subtema | Horas | Evidencia | Origen |
|---------|-------|----------|--------|
| {subtema} | {horas} | {Sección X.X / Slide N / Sin señal verificable} | {Detectado / Manual / Fallback} |

*(repetir por bloque)*

---

> 🔬 Prácticas de laboratorio: {PL}h (sesiones prácticas, no incluidas en la distribución temática)
```

**Sin subbloques confirmados (libre):**
La columna "Evidencia" contiene la referencia estructural detectada por el LLM (más susceptible a imprecisión; el flujo normal con confirmación es preferible).

**Contrato con el Agente Contenido:** El Agente Contenido parsea bloques con `## Bloque N — … · Xh` (`parse_organization_md()` en `agente-contenido/app.py`). El cambio de columnas en la tabla de subbloques NO rompe este contrato (el Agente Contenido no parsea las filas de la tabla).

---

## Interfaz (estado actual)

### Layout `layout="wide"`
- **Sidebar:** branding + steps 1-2-3 + file uploaders + botón "Generar organización"
- **Área principal:** hero + expanders de validación + editor de subbloques (fase "editar") + resultado con editor manual (fase "resultado") o vista congelada (fase "cerrado")

### Identidad visual compartida
- **Tipografía:** Playfair Display + DM Sans
- **Acento:** `#185FA5`
- **Fondos/textos:** variables CSS de Streamlit

---

## Configuración del modelo

```
MODEL: claude-sonnet-4-5
# Haiku descartado para generación: el razonamiento de cardinalidad y la
# distribución horaria requieren consistencia semántica. Sonnet es obligatorio.
```
