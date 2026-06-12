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
├── agente-organizador/
│   ├── CLAUDE.md                 ← contexto específico del Agente Organizador
│   ├── README.md
│   ├── app.py
│   ├── agente.py
│   ├── parser.py
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
│   ├── tools/
│   │   └── validate_pdf.py       ← debug CLI (extract → chunk, sin API)
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

## Estado del proyecto (2026-06-09)

| Agente | Estado | Validado con |
|--------|--------|-------------|
| Organizador | Funcional | Oleohidráulica, Elementos de Máquinas, Tecnología de Materiales |
| Contenido | Funcional — validado con PDF y PPTX | Temas 1 y 2 de Tecnología de Materiales (PDF) |
| Presentación | Funcional — 3 outputs (PDF institucional UO, HTML interactivo, HTML presentación completa); LaTeX con matplotlib mathtext | Tema 1 (Tec. Materiales), TEMA7 (Elementos de Máquinas) |
