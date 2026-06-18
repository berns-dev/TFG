# TFG — Suite de Agentes Docentes

**Universidad de Oviedo · EPI Gijón · Grado en Ingeniería Mecánica**
**Autor:** Bernardo | **Tutor:** Miguel
**Última actualización:** 2026-06-18

---

## Descripción del proyecto

Monorepo con tres agentes de IA con arquitectura de **pipeline suave**: cada agente
produce un Markdown que alimenta al siguiente, pero sin acoplamiento de código. Cada
agente puede ejecutarse de forma independiente si el profesor ya dispone del input en
el formato correcto.

**Principio rector (Organizador y Contenido):** Transforman, nunca inventan. El output solo puede contener información explícitamente presente en el material de entrada.

**Excepción documentada (Presentación — HTML interactivo):** el texto descriptivo y los insights provienen del Markdown, pero la implementación de las ecuaciones en el código de visualización usa el conocimiento de ingeniería del modelo libremente.

---

## Los tres agentes

| Agente | Subcarpeta | Función |
|--------|-----------|---------|
| Organizador | `agente-organizador/` | Extrae distribución temática, horas y apartados de la guía docente |
| Contenido | `agente-contenido/` | Convierte PDF/PPTX a un Markdown fiel por bloque temático completo |
| Presentación | `agente-presentacion/` | PDF institucional + taller de visualizaciones interactivas + HTML presentación completa |

---

## Arquitectura — pipeline suave (junio 2026)

```
[Guía docente + materiales] → Organizador → bloques + apartados (BD)
                                      │
                                      ▼ checklist de cobertura (no partición)
              materiales del bloque → Contenido → 1 MD/bloque (contenido_tema)
                                      │
                                      ▼ prompts iterativos + anclas
                              Presentación → visualizacion_interactiva + export PDF/HTML
```

- **Organizador:** los apartados validados por el profesor sirven de **guía** (horas de planificación + checklist de cobertura). No segmentan el markdown curado.
- **Contenido:** `procesar_bloque()` extrae y estructura **todo** el material del bloque **sin calibrar extensión por horas**.
- **Presentación:** taller por bloque — prompt libre → preview → refinar → aprobar con ancla a sección del MD → ensamblar presentación completa.

---

## Contrato entre agentes

**Organizador → BD:** bloques (`temas`) + apartados (`subbloques`) con evidencia y horas a nivel de bloque.

**Contenido → BD:** `contenido_tema` — un markdown por bloque (`pendiente` → `generado` → `editado` → `aprobado`).

**Presentación → BD:** `visualizacion_interactiva` — fragmentos HTML aprobados con `seccion_ancla` y `orden`.

El encabezado canónico del Organizador sigue siendo `## Bloque N — Nombre · Xh` para parseo y persistencia en BD.

---

## Fuentes de verdad por agente

### Organizador → `agente-organizador/parser.py`
Lógica pura: horas, señales estructurales, parseo de bloques/subtemas.

### Contenido → `agente-contenido/pipeline.py` + `coverage_checklist.py` + `extractor.py`
- **Extracción:** PyMuPDF → pdfplumber → plano; PPTX nativo.
- **Curado:** `procesar_bloque()` — bloque completo, **sin densidad horaria**.
- **Cobertura:** `verificar_cobertura()` — apartados del Organizador vs MD curado.
- **UI:** generar → editar → aprobar un bloque en `contenido_tema`.

### Presentación → `workshop.py` + `generador_presentacion.py` + `generador_pdf.py`
- **Taller:** `generar_desde_instruccion()`, `refinar_html()` — prompts del profesor.
- **Ensamblaje:** `generar_presentacion_con_fragmentos()` — teoría + visualizaciones ancladas.
- **Legado:** `generador_html.py`, `detector.py` — pipeline por detector/razonador (módulos, no UI principal).

---

## Stack tecnológico común

- **API:** Anthropic — `claude-haiku-4-5-20251001`, `claude-sonnet-4-5`
- **UI:** Streamlit (`app-unificada/app.py`)
- **BD:** SQLite v7 (`database/db.py`)
- **PDF extracción (Contenido):** PyMuPDF → pdfplumber
- **PDF generado:** ReportLab + matplotlib mathtext
- **HTML interactivo:** Chart.js + MathJax (CDN)

---

## Estructura del repositorio

```
TFG/
├── CLAUDE.md
├── database/
│   ├── db.py                 ← esquema v7
│   └── validar_esquema.py
├── app-unificada/app.py
├── agente-organizador/
├── agente-contenido/
│   ├── pipeline.py
│   ├── coverage_checklist.py
│   ├── split_monotono.py     ← legado (tests); fuera del flujo UI
│   └── ...
└── agente-presentacion/
    ├── workshop.py
    ├── generador_presentacion.py
    └── ...
```

---

## Arranque

```bash
cd TFG
pip install -r agente-organizador/requirements.txt
pip install -r agente-contenido/requirements.txt
pip install -r agente-presentacion/requirements.txt
streamlit run app-unificada/app.py
```

Flujo típico: Organizador → Contenido (bloque + checklist) → Presentación (taller + export).

---

## Base de datos — progreso (v7)

- `get_progreso_bloque(tema_id)` — 1 si `contenido_tema.estado = 'aprobado'`
- `get_progreso_asignatura(asignatura_id)` — bloques aprobados / total bloques
- Valoración Contenido: `contenido_tema.puntuacion_profesor` (1-10 por bloque)
- Valoración Organizador: `valoraciones_profesor` (global por asignatura)

Detalle: **`database/CLAUDE.md`**.

---

## Estado del proyecto

| Agente/módulo | Estado |
|---------------|--------|
| Organizador | Funcional — apartados con evidencia; horas solo a nivel bloque |
| Contenido | Funcional — MD por bloque + checklist; sin reparto monótono en UI |
| Presentación | Funcional — taller iterativo + `generar_presentacion_con_fragmentos` |
| Base de datos | Esquema v7 — `contenido_tema`, `visualizacion_interactiva` |
