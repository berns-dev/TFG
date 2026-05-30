# Agente Organizador — Agente 01 de la suite TFG

Extrae la distribución temática y las horas lectivas de una asignatura a partir de la guía docente y los materiales de teoría, y produce un Markdown con bloques y subtemas con horas proporcionales.

---

## Qué hace

Recibe una guía docente en PDF y uno o varios materiales de teoría (PDF o PPTX). Detecta automáticamente las horas lectivas (teoría, prácticas de aula y laboratorio) mediante heurísticas deterministas sobre la guía docente. Con esos datos construye un prompt que envía a Sonnet, que genera una propuesta de organización curricular con bloques temáticos, subtemas y distribución de horas. El profesor puede revisar la propuesta, introducir observaciones en lenguaje natural y solicitar hasta cinco regeneraciones antes de descargar el resultado final en formato Markdown.

---

## Principio de fidelidad

El agente extrae y estructura. No inventa. Si un tema no aparece en los materiales aportados por el profesor, no aparece en el output.

---

## Arquitectura

```
app.py        — UI Streamlit, extracción de horas, validación de cardinalidad, loop de refinamiento
agente.py     — cliente Anthropic, ejecutar_agente()
parser.py     — extraer_texto() y clasificar_archivo() para PDF y PPTX
prompts.py    — construir_prompt() y construir_prompt_refinamiento()
```

---

## Flujo de trabajo

1. El profesor sube la guía docente (PDF) y los materiales de teoría (PDF/PPTX).
2. `extraer_texto()` obtiene el texto de cada documento.
3. `clasificar_archivo()` separa los archivos en "teoría" y "contexto/outline".
4. `extraer_horas_docencia()` detecta las horas TE/PA/PL de la guía mediante heurísticas deterministas (tablas MODALIDADES primero, texto libre como fallback).
5. `construir_prompt()` ensambla el prompt completo con los textos, las horas y la plantilla de output.
6. `ejecutar_agente()` llama a Sonnet y obtiene la propuesta.
7. `contar_bloques_output()` verifica que el número de bloques generados coincida con el número de archivos de teoría subidos; si no coincide, muestra un aviso visible.
8. El profesor puede refinar con feedback en lenguaje natural hasta cinco iteraciones; cada refinamiento usa `construir_prompt_refinamiento()` sin re-extraer los documentos.

---

## Inputs y outputs

| Tipo | Descripción | Formato |
|------|-------------|---------|
| Input | Guía docente de la asignatura | PDF |
| Input | Materiales de teoría (uno por tema) | PDF, PPTX |
| Output | Distribución temática con bloques, subtemas y horas | Markdown (`.md`) |

El Markdown generado sigue el formato `## Bloque N: Nombre · Xh` y puede usarse directamente como input del Agente Contenido.

---

## Instalación y uso

```bash
pip install -r requirements.txt
cp .env.example .env   # añadir ANTHROPIC_API_KEY en .env
streamlit run app.py --server.port 8502
```

---

## Selección de modelo

| Modelo | Tarea |
|--------|-------|
| `claude-sonnet-4-5` | Toda la generación y refinamiento |

Haiku fue descartado para este agente: la restricción de cardinalidad y la distribución horaria requieren consistencia semántica que Haiku no garantiza con prompts estrictos.

---

## Limitaciones conocidas

- **PDFs rasterizados desde PowerPoint:** el texto extraído es mínimo. La guía docente actúa como ancla estructural y compensa parcialmente, pero el resultado puede requerir más revisión.
- **Tablas complejas o escaneos en la guía:** la detección de horas puede devolver 0 si el formato no es reconocible por las heurísticas. Se muestra un aviso en la UI.
- **Cardinalidad:** si el agente genera más bloques de los esperados (subsecciones elevadas a bloque independiente), el warning de cardinalidad indica cuántos bloques se generaron frente a cuántos se esperaban y guía al profesor para corregirlo con feedback.
