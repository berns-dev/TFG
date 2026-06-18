# TFG — Suite de Agentes Docentes

**Universidad de Oviedo · EPI Gijón · Grado en Ingeniería Mecánica**
**Autor:** Bernardo | **Tutor:** Miguel

---

## Descripción del proyecto

Monorepo con tres agentes de IA con arquitectura de **pipeline suave**: cada agente
produce un Markdown que alimenta al siguiente, pero sin acoplamiento de código. Cada
agente puede ejecutarse de forma independiente si el profesor ya dispone del input en
el formato correcto.

**Principio rector (Organizador y Contenido):** Transforman, nunca inventan. El output solo puede contener información explícitamente presente en el material de entrada.

**Excepción documentada (Presentación — HTML interactivo):** el texto descriptivo y los insights provienen del Markdown, pero la implementación de las ecuaciones en el código de visualización usa el conocimiento de ingeniería del modelo libremente. La distinción es: el modelo puede saber física, no puede saber qué dijo el profesor.

---

## Los tres agentes

| Agente | Subcarpeta | Función |
|--------|-----------|---------|
| Organizador | `agente-organizador/` | Extrae distribución temática y horas lectivas de la guía docente |
| Contenido | `agente-contenido/` | Convierte PDF/PPTX a Markdown estructurado y curado por tema; calibra extensión y profundidad según las horas del bloque (output del Organizador, opcional) |
| Presentación | `agente-presentacion/` | Genera tres salidas desde el Markdown curado: PDF con plantilla institucional UO, HTML interactivo por pestañas, y HTML de presentación completa del tema |

Cada subcarpeta tiene su propio `CLAUDE.md` con el contexto específico de ese agente, su arquitectura de módulos, decisiones de implementación y limitaciones documentadas. **Lee siempre el `CLAUDE.md` del agente correspondiente antes de modificar su código.**

---

## Arquitectura — pipeline suave

Los agentes se conectan a través de archivos Markdown, no a través de código. Esto los
distingue del pipeline encadenado original (descartado): en ese diseño los agentes se
llamaban entre sí en código y un error upstream se propagaba downstream. Aquí el fallo
de un agente no rompe los demás — el siguiente simplemente no tiene su input.

El Agente Contenido usa el `.md` del Organizador para conocer el bloque temático y la
densidad horaria del material que está procesando. Es técnicamente opcional pero
necesario para que el output esté calibrado por tema. El Agente Presentación necesita
el `.md` curado del Contenido — es su único input requerido.

## Contrato de formato entre agentes

El Agente Organizador produce un Markdown con la distribución temática. El encabezado
canónico de cada bloque es:

```
## Bloque N — Nombre del bloque · Xh
```

Este es el contrato que el Agente Contenido lee con `parse_organization_md()` (patrón
`^##\s+Bloque\s+\d+\s+—\s+(.+?)\s*·\s*([\d,.]+)h`). Un archivo que no siga este
formato exacto no será parseado correctamente por el Agente Contenido.

**Nota:** la tabla de subbloques usa `| Subtema | Evidencia | Origen |` (sin horas por
subtema — las horas viven solo en el encabezado del bloque). Formatos legados con
columna Horas siguen parseándose. El Agente Contenido usa `Evidencia` para segmentar
el material; si falta, los subbloques quedan en estado `pendiente`.

---

## Fuentes de verdad únicas por agente (sin duplicación)

Cada agente tiene **una sola implementación** de su lógica de negocio. `app-unificada`
importa siempre desde las carpetas de cada agente — no duplica código.

### Organizador → `agente-organizador/parser.py`

Toda la lógica de cálculo y transformación vive aquí (módulo importable, sin Streamlit):
`extraer_horas_docencia`, `normalizar_horas_output`, `contar_bloques_output`,
`construir_nombre_descarga`, `parsear_bloques_desde_markdown`,
`parsear_bloques_organizador`, `regenerar_markdown_desde_bloques`.

`app-unificada` lo carga vía `_cargar_modulos_agente` (`_org_parser`) y lo usa
directamente. Detalle en `agente-organizador/CLAUDE.md`.

### Contenido → `agente-contenido/pipeline.py`

La orquestación del pipeline (chunk → classify en paralelo → assemble → validate)
vive en `pipeline.py` como función importable `procesar_segmento()`. Tanto el
standalone (`agente-contenido/app.py`) como `app-unificada` la usan:

- Standalone: `_process_subbloque()` llama a `procesar_segmento()` y envuelve
  el resultado en `SubbloqueResult` con avisos Streamlit.
- App-unificada: `_cnt_curar_subbloque()` llama a `procesar_segmento()` y
  extrae la fidelidad media para guardar en BD.

El markdown que produce `procesar_segmento()` usa `assemble_subbloque_body()` —
cuerpo sin frontmatter YAML, con H1 del nombre del subbloque. Esto es igual en
ambas interfaces y es lo que el profesor ve en el editor de texto de la app.

### Presentación → `agente-presentacion/generador_html.py`

El bucle de generación HTML (reintentos, `aplicar_rangos`, `validar_bloque_html`)
vive en `_generar_bloque()`. `app-unificada` no duplica ese bucle: usa
`generar_bloque_con_visualizacion(elemento, visualizacion)`, función pública que
recibe el dict `visualizacion` ya construido desde BD (sin volver a llamar al
razonador, porque el patrón ya lo eligió el profesor) y delega en `_generar_bloque`.

La distinción razonador vs. sin razonador se expresa como un parámetro opcional
`visualizacion: dict | None = None` en `_generar_bloque`: si se pasa, se omite
el paso del razonador; si no, el flujo normal del standalone lo computa.

La edición de la organización en **app-unificada** es una vista única interactiva
(tabla por bloque/subbloque); el standalone conserva el editor en expander. En ambas
solo en fase de revisión; una vez cerrada/confirmada la organización
(en la unificada, al confirmarla se persiste a BD para Contenido), la estructura
queda congelada y se ocultan tanto la edición manual como el refinamiento por prompt.

---

## Workflow entre agentes

```
[Guía docente PDF] ──┐
                     ├──► agente-organizador ──► [Distribución temática .md]
[Materiales PDF/PPTX]┘                                    │
                                                          │
                     ┌────────────────────────────────────┘
                     │    + [Material del tema PDF/PPTX]
                     ▼
              agente-contenido ──► [Markdown curado por tema]
                                              │
                                              ▼
                                  agente-presentacion
                                  ├──► [PDF institucional UO]
                                  ├──► [HTML interactivo por pestañas]
                                  └──► [HTML presentación completa]
```

---

## Stack tecnológico común

- **API:** Anthropic directo — nunca OpenRouter ni otros proveedores
  - `claude-haiku-4-5-20251001` — tareas mecánicas (clasificación, extracción)
  - `claude-sonnet-4-5` — razonamiento, contenido matemático, generación compleja
- **UI:** Streamlit (`layout="wide"`) con identidad visual compartida:
  - Tipografía: Playfair Display + DM Sans (Google Fonts CDN)
  - Acento: `#185FA5` (fijo, identidad de marca)
  - Dark/light mode: JS `sync()` en iframes, `var(--background-color)` en estilos Streamlit
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX)
- **PDF generado:** `reportlab` (puro Python, sin GTK)
- **HTML interactivo:** Chart.js + MathJax (CDN)
- **Credenciales:** `.env` en cada subcarpeta + `python-dotenv`

---

## Reglas de desarrollo

- La API usada es Anthropic directo. Nunca uses OpenRouter en este proyecto.
- Los modelos válidos son `claude-haiku-4-5-20251001` y `claude-sonnet-4-5`.
- Cada agente tiene su `.cursorrules` con restricciones específicas de ese agente. Léelas antes de modificar cualquier archivo de código.
- No modificar `SYSTEM_PROMPT` en `agente-contenido/classifier.py` sin consenso explícito del usuario.
- No modificar `PROMPT_GENERADOR_HTML`, `PROMPT_RAZONADOR_VISUALIZACION` ni `PROMPT_DETECTOR_INTERACTIVIDAD` en `agente-presentacion/prompts.py` sin consenso explícito.
- El código determinista (extracción de horas, clasificación de archivos, detección de ecuaciones) no se reemplaza por LLM sin justificación documentada.

---

## Estructura del repositorio

```
TFG/
├── README.md                     ← README principal del proyecto
├── CLAUDE.md                     ← este archivo — contexto global para Claude Code
├── shared/
│   └── ui_hero.py                ← render_hero() compartido entre los tres agentes
├── database/
│   ├── CLAUDE.md                 ← esquema SQLite, migraciones, APIs de progreso
│   ├── db.py                     ← motor SQLite (esquema v2, init, progreso, CRUD)
│   └── validar_esquema.py        ← script de validación del esquema (no producto)
├── app-unificada/
│   └── app.py                    ← app Streamlit unificada (todos los agentes + BD).
│                                    Importa desde los módulos de cada agente vía
│                                    _cargar_modulos_agente(); no duplica lógica.
├── data/
│   └── tfg.db                    ← base de datos SQLite (generado, no versionado)
├── agente-organizador/
│   ├── CLAUDE.md                 ← contexto específico del Agente Organizador
│   ├── README.md
│   ├── app.py                    ← UI standalone (solo interfaz; importa de parser.py)
│   ├── agente.py
│   ├── parser.py                 ← FUENTE DE VERDAD importable: toda la lógica pura
│   │                                (horas, normalización, conteo, parseo/serialización)
│   ├── prompts.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── .gitignore
│   └── .cursorrules
├── agente-contenido/
│   ├── CLAUDE.md                 ← contexto específico del Agente Contenido
│   ├── README.md
│   ├── app.py
│   ├── classifier.py
│   ├── chunker.py
│   ├── extractor.py
│   ├── cleaner.py
│   ├── assembler.py
│   ├── validator.py
│   ├── segmentor.py              ← segmentación de texto por subbloque (evidencia estructural)
│   ├── subblock_state.py         ← SubbloqueResult, calcular_progreso_bloque/asignatura
│   ├── pipeline.py               ← FUENTE DE VERDAD importable: procesar_segmento()
│   │                                (chunk→classify en paralelo→assemble→validate)
│   │                                Usada por app.py standalone y app-unificada
│   ├── tools/
│   │   ├── validate_pdf.py       ← debug CLI (extract → chunk, sin API)
│   │   └── validate_subbloques.py ← validación pipeline de subbloques (sin API)
│   ├── fixtures/
│   │   └── Tema_3_curado.md      ← artefacto de validación
│   ├── config.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── .gitignore
│   └── .cursorrules
└── agente-presentacion/
    ├── CLAUDE.md                 ← contexto específico del Agente Presentación
    ├── README.md
    ├── app.py
    ├── detector.py
    ├── generador_pdf.py
    ├── generador_html.py
    ├── generador_presentacion.py
    ├── prompts.py
    ├── config.py
    ├── tools/razonador_fixture.py   ← debug CLI del razonador (consume API)
    ├── requirements.txt
    ├── .env.example
    ├── .gitignore
    └── .cursorrules
```

---

## Base de datos compartida

La app unificada (`app-unificada/`) usa SQLite en `data/tfg.db`. El esquema vive en
`database/db.py`. Para el detalle completo del esquema y las APIs de progreso, ver
**`database/CLAUDE.md`**.

Resumen de las funciones de progreso (nunca almacenado, siempre calculado):
- `db.get_progreso_bloque(tema_id)` → `{total, aprobados, porcentaje}`
- `db.get_progreso_asignatura(asignatura_id)` → `{total, aprobados, porcentaje}`
- `db.get_desglose_progreso_asignatura(asignatura_id)` → lista por bloque

El progreso se calcula sobre `estado = 'aprobado'` en `contenido_subbloque`.
El contenido interactivo (`tiene_interactivo`) **no entra** en el cálculo de progreso.

### Valoración del profesor (granularidad por agente)

- **Organizador:** nota global 1-10 en `valoraciones_profesor` (una por asignatura).
- **Contenido:** nota 1-10 por sub-bloque en `contenido_subbloque.puntuacion_profesor`.
  Contenido no escribe en `valoraciones_profesor`.
- **Presentación (futuro):** por sub-bloque, mismo patrón que Contenido.

Detalle del esquema y APIs: **`database/CLAUDE.md`**.

---

## Estado del proyecto (2026-06-18)

| Agente/módulo | Estado | Validado con |
|---------------|--------|-------------|
| Organizador | Funcional — subbloques anclados a evidencia estructural; edición manual bloques/subbloques en **ambas interfaces** (standalone y app-unificada); fase cerrado/confirmado. Lógica pura centralizada en `parser.py` (fuente de verdad importable); `app-unificada` la consume sin duplicar | Oleohidráulica, Elementos de Máquinas, Tecnología de Materiales |
| Contenido | Funcional — granularidad de subbloque: segmentación por evidencia, generación por selección (cada sub-bloque = llamada API independiente), valoración 1-10 por sub-bloque, estados pendiente/generado/editado/aprobado | Temas 1 y 2 de Tecnología de Materiales (PDF) |
| Presentación | Funcional — 3 outputs (PDF institucional UO, HTML interactivo, HTML presentación completa); LaTeX con matplotlib mathtext | Tema 1 (Tec. Materiales), TEMA7 (Elementos de Máquinas) |
| Base de datos | Esquema v4 — jerarquía asignatura→bloque→subbloque + estado del ciclo de vida + progreso en tiempo real + valoración por agente | Tecnología de Materiales (script `database/validar_esquema.py`) |
