# Agente Organizador — Estado del proyecto

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-07

---

## Propósito

Extrae temas, subtemas y distribución horaria de una asignatura a partir de la guía docente y los materiales de teoría. Produce un Markdown con la distribución temática y las horas asignadas por subtema.

**Principio rector:** Extrae y estructura. No inventa. Si algo no está en el material del profesor, no aparece en el output.

---

## Estado

**Funcional. Validado con tres asignaturas reales:**
- Oleohidráulica y Neumática
- Elementos de Máquinas
- Tecnología de Materiales

**Limitación documentada:** Los PDFs exportados desde PowerPoint contienen texto extraíble, pero sin orden de lectura coherente. PowerPoint deposita los cuadros de texto de cada diapositiva en el orden en que se crearon durante la edición, no en el orden visual. pdfplumber los extrae en ese orden interno y devuelve un flujo mezclado donde el agente no puede distinguir título de cuerpo. La guía docente no tiene este problema porque es un documento de flujo lineal. No hay aviso implementado para este caso en el Agente Organizador.

---

## Stack técnico

- **UI:** Streamlit (`layout="wide"`, sidebar para uploads)
- **API:** Anthropic directo — `claude-sonnet-4-5` (generación y refinamiento)
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX) vía `parser.py`
- **Credenciales:** `.env` + `python-dotenv`

---

## Arquitectura de archivos

```
app.py        — UI Streamlit + lógica de sesión + validación de cardinalidad
agente.py     — cliente Anthropic, ejecutar_agente()
parser.py     — extraer_texto(), clasificar_archivo()
prompts.py    — construir_prompt(), construir_prompt_refinamiento()
```

---

## Flujo principal

1. **Extracción** — `extraer_texto()` sobre guía docente y materiales de teoría
2. **Clasificación** — `clasificar_archivo()` separa "teoría" de "contexto/outline"
3. **Detección de horas** — `extraer_horas_docencia()` en `app.py`: extrae TE/PA/PL de la guía docente usando heurísticas deterministas (tablas MODALIDADES primero, texto libre como fallback)
4. **Generación** — `construir_prompt()` → `ejecutar_agente()` → Sonnet
5. **Validación de cardinalidad** — `contar_bloques_output()` compara `## Bloque N` en el output con `len(textos_teoria)`; si no coinciden, `st.warning` visible
6. **Refinamiento** — loop hasta 5 iteraciones; usa `construir_prompt_refinamiento()` (camino rápido, sin re-extraer documentos)

---

## Decisiones de implementación clave

### Selección de modelo
Sonnet para toda la generación y refinamiento. El razonamiento curricular requiere coherencia semántica que Haiku no garantiza con prompts de cardinalidad estricta.

### Código determinista para horas
`extraer_horas_docencia()` resuelve la extracción de TE/PA/PL con código Python puro, sin LLM. Dos estrategias:
1. **Estrategia 1 (preferente):** detecta tabla(s) MODALIDADES por cabecera y lee la columna Horas. Elige la ventana con mayor completitud y mayor confianza en la fila PA.
2. **Estrategia 2 (fallback):** búsqueda en texto libre, exige señales horarias explícitas para evitar confundir "sesiones" con horas.

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

`generar_organizacion()` bifurca entre **camino completo** (primera generación: extrae, clasifica, construye prompt completo) y **camino rápido** (refinamiento: solo `construir_prompt_refinamiento()` + `ejecutar_agente()`).

### Validación de cardinalidad post-generación (`app.py`)
`contar_bloques_output()` cuenta `^## ` con regex. `_validar_y_persistir()` la llama siempre tras generar o refinar:
- Si `n_generados != n_esperados` → `st.session_state["warning_cardinalidad"]` con recuento
- El warning se muestra en el área principal antes del output, describiendo la causa probable y qué acción tomar (usar campo de feedback para indicar qué bloque debe reintegrarse)

---

## Interfaz (estado actual)

### Identidad visual compartida con Agente Contenido
- **Tipografía:** Playfair Display (títulos, vía Google Fonts) + DM Sans (cuerpo)
- **Acento:** `#185FA5` (fijo, identidad de marca)
- **Fondos/textos:** variables CSS de Streamlit (`var(--background-color)`, `var(--secondary-background-color)`, `var(--text-color)`)
- **Bordes:** `rgba(128,128,128,0.2)` (adaptativos)

### Layout `layout="wide"`
- **Sidebar:** branding (Suite de Agentes / Agente Organizador) + steps 1-2-3 + file uploaders + botón "Generar organización"
- **Área principal:** hero `st.components.v1.html()` + expanders de validación + output + feedback loop

### Hero
`render_hero()` desde `shared/ui_hero.py`. Parámetros:
- `agent_number="01"`, `title_before="Organización "`, `title_keyword="curricular"`
- `steps=["Guía docente", "Materiales", "Propuesta"]`, `button_full_width=True`
- **Compatibilidad dark/light:** JS `sync()` en el iframe lee la luminancia del fondo del padre cada 800ms; aplica `.dark`/`.light` en `:root`; `@media(prefers-color-scheme:dark)` como fallback.

### Dark/light mode
- Iframes: detección JS de luminancia del padre + CSS custom properties (`:root` / `:root.dark`)
- `st.markdown` CSS: `var(--background-color)`, `var(--secondary-background-color)`, `rgba()` para bordes
- Colores fijos preservados: `#185FA5` (acento), `#E6F1FB`/`#185FA5` (badges numerados)

---

## Bug documentado y corregido: cardinalidad de bloques

**Bug (detectado 26/05/2026):** el agente generaba N+1 bloques cuando la guía docente listaba una subsección con horas propias (ej. "Fractura asistida por el medio ambiente" dentro del Tema 6 — Fatiga).

**Causa raíz:** el prompt no tenía restricción de cardinalidad explícita ni instrucción sobre qué constituye un bloque vs. un subtema.

**Fix (28/05/2026):**
- `instruccion_cardinalidad` reescrita con los tres refuerzos descritos arriba
- `contar_bloques_output()` + `_validar_y_persistir()` añadidos en `app.py`
- `st.warning` visible con recuento esperado/generado y guía de corrección

**Lección para la memoria:** las restricciones de conteo no pueden inferirse del contexto — deben ser explícitas. La autoverificación en el prompt ("cuenta tus propios encabezados antes de responder") es más efectiva que solo enunciar la restricción.

---

## Output format

Fuente de verdad: plantilla en `prompts.py` → `construir_prompt()`.

```markdown
# DISTRIBUCIÓN TEMÁTICA — {{NOMBRE_ASIGNATURA}}

**Horas lectivas disponibles:** {{TOTAL}}h ({{TE}}h TE + {{PA}}h PA) | **Prácticas de laboratorio:** {{PL}}h *(informativo)*

---

## Bloque {{N}} — {{NOMBRE_BLOQUE}} · {{HORAS_BLOQUE}}h

| Subtema | Horas | Justificación |
|---------|-------|---------------|
| {{subtema}} | {{horas}} | {{una frase corta}} |

*(repetir por bloque)*

---

> 🔬 Prácticas de laboratorio: {{PL}}h (sesiones prácticas, no incluidas en la distribución temática)
```

El Agente Contenido parsea bloques con `## Bloque N — … · Xh` (`parse_organization_md()` en `agente-contenido/app.py`).

El nombre del archivo de descarga se extrae de la guía docente con regex (`NOMBRE ... CÓDIGO`) → `Propuesta_[AsignaturaNombre].md`.

---

## Configuración del modelo

```
MODEL: claude-sonnet-4-5
# Haiku descartado para generación: el razonamiento de cardinalidad y la
# distribución horaria requieren consistencia semántica. Sonnet es obligatorio.
```

Ver `.cursorrules` para restricciones adicionales de desarrollo.
