# Metodologías de Ingeniería Aumentada — Suite de Agentes Docentes

TFG · Universidad de Oviedo · Escuela Politécnica de Ingeniería de Gijón · Grado en Ingeniería Mecánica

Este proyecto construye una suite de tres agentes de IA que transforma el material docente universitario — presentaciones, PDFs y guías docentes — en recursos estructurados, calibrados horariamente e interactivos, sin inventar ningún contenido que no esté en el original.

---

## El problema

Los profesores universitarios acumulan años de material docente en presentaciones de PowerPoint y documentos PDF. Ese material existe en formatos no reutilizables, sin estructura pedagógica explícita, sin distribución de carga horaria por subtema, y sin formatos interactivos para los alumnos. Reorganizarlo manualmente es costoso y requiere dedicación que compite con otras tareas del profesor.

---

## La solución — workflow entre agentes

```
[Guía docente PDF] ──┐
                     ├──► Agente Organizador ──► [Distribución temática .md]
[Materiales PDF/PPTX]┘                                        │
                                                              │
                     ┌────────────────────────────────────────┘
                     │    + [Material del tema PDF/PPTX]
                     ▼
              Agente Contenido ──► [Markdown curado por tema]
                                                │
                                                ▼
                                    Agente Presentación
                                    ├──► [PDF estructurado]
                                    └──► [HTML interactivo]
```

**Agente Organizador** recibe la guía docente y los materiales de teoría, detecta las horas lectivas (TE/PA/PL) y genera una distribución temática con bloques y subtemas proporcionales al tiempo disponible. Su output es un archivo `.md` con la estructura curricular de la asignatura.

**Agente Contenido** recibe ese `.md` opcional como contexto de densidad y uno o varios PDF/PPTX del tema. Convierte el material en Markdown estructurado y fiel al original, clasificando cada bloque como teoría, ejemplo resuelto, ejercicio propuesto, tabla o procedimiento. Su output es un `.md` curado por tema.

**Agente Presentación** recibe el Markdown curado y detecta las secciones con contenido matemático. El profesor selecciona qué secciones incluir y el agente genera un PDF académico (ReportLab) o una página HTML interactiva con sliders y gráficas Chart.js.

---

## Principio rector

Los tres agentes transforman, nunca inventan. El output de cada agente solo puede contener información explícitamente presente en el material de entrada. No se añade, infiere ni completa ningún contenido.

---

## Estructura del repositorio

| Agente | Función | Subcarpeta |
|--------|---------|------------|
| Organizador | Extrae distribución temática y horas de la guía docente | [`agente-organizador/`](agente-organizador/) |
| Contenido | Convierte PDF/PPTX a Markdown estructurado por tema | [`agente-contenido/`](agente-contenido/) |
| Presentación | Genera PDF académico o HTML interactivo desde Markdown | [`agente-presentacion/`](agente-presentacion/) |

---

## Requisitos e instalación

Cada agente tiene sus propias dependencias y se instala de forma independiente. Python 3.10+ recomendado.

```bash
# Agente Organizador
cd agente-organizador
pip install -r requirements.txt
cp .env.example .env   # o copy en Windows

# Agente Contenido
cd agente-contenido
pip install -r requirements.txt
cp .env.example .env

# Agente Presentación
cd agente-presentacion
pip install -r requirements.txt
cp .env.example .env
```

En cada `.env`, añade tu clave de API de Anthropic:

```env
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Cómo ejecutar la suite completa

Se recomienda lanzar los tres agentes en puertos distintos para poder usarlos en paralelo:

```bash
# Terminal 1 — Agente Organizador
cd agente-organizador
streamlit run app.py --server.port 8502

# Terminal 2 — Agente Contenido
cd agente-contenido
streamlit run app.py --server.port 8501

# Terminal 3 — Agente Presentación
cd agente-presentacion
streamlit run app.py --server.port 8500
```

Cada agente puede usarse de forma independiente. El workflow completo sigue el orden Organizador → Contenido → Presentación, pero ningún agente requiere el output de los anteriores para funcionar.

---

## Stack tecnológico

- **API:** Anthropic — `claude-haiku-4-5-20251001` y `claude-sonnet-4-5`
- **UI:** Streamlit
- **Extracción:** `pdfplumber` (PDF), `python-pptx` (PPTX)
- **PDF generado:** `reportlab` (puro Python, sin dependencias del sistema)
- **HTML interactivo:** Chart.js + MathJax (CDN)
- **Credenciales:** `.env` + `python-dotenv`
