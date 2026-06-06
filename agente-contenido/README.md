# Agente Contenido — Agente 02 de la suite TFG

Convierte PDFs y PPTXs de material docente a Markdown estructurado, clasificado y fiel al original, listo para reutilizar en los siguientes agentes de la suite.

---

## Qué hace

Recibe uno o varios archivos PDF o PPTX con material de teoría de un tema. Extrae el texto, lo divide en fragmentos semánticos, clasifica cada fragmento según su función (teoría, ejemplo resuelto, ejercicio propuesto, tabla o procedimiento), y ensambla un único Markdown con estructura homogénea. Incluye un validador de fidelidad léxica que comprueba que los términos técnicos clave del original aparezcan en el output. Opcionalmente acepta el Markdown generado por el Agente Organizador para ajustar la profundidad del output según las horas lectivas asignadas al tema.

---

## Principio de fidelidad

El agente extrae y estructura. No inventa. El Markdown resultante no contiene ninguna información que no esté en los documentos de entrada. Si un fragmento es ilegible o ambiguo, se marca con `[TEXTO_ILEGIBLE]` o `[FIGURA: descripción]`.

---

## Arquitectura

```
app.py          — UI Streamlit, processing loop con ThreadPoolExecutor, resultados por archivo
classifier.py   — selección de modelo, SYSTEM_PROMPT, classify_and_format()
chunker.py      — split_into_chunks() — chunking semántico respetando límites de página/diapositiva
extractor.py    — extract_text() para PDF (pdfplumber) y PPTX (python-pptx)
cleaner.py      — normalización de artefactos de extracción
assembler.py    — assemble_markdown(), assemble_multiple(), unified_download_filename()
validator.py    — validate_items() — validador de fidelidad léxica (umbral 0.85)
config.py       — constantes: modelos, thresholds, MAX_WORKERS
tools/validate_pdf.py — utilidad de debug CLI (extract → chunk, sin API; no es producto)
fixtures/       — artefactos de validación (p. ej. Tema_3_curado.md)
```

---

## Flujo de trabajo

1. El profesor sube opcionalmente el `.md` del Agente Organizador y selecciona el bloque que corresponde al material que va a procesar.
2. Sube uno o varios PDF o PPTX con el material del tema.
3. `extract_text()` obtiene el texto de cada archivo en un archivo temporal.
4. `split_into_chunks()` divide el texto en fragmentos semánticos respetando los límites de página (PDF) o diapositiva (PPTX).
5. `classify_and_format()` se lanza en paralelo (hasta `MAX_WORKERS` llamadas concurrentes) para cada fragmento. Si un chunk falla, se registra un aviso y se inserta un marcador `[ERROR EN CHUNK N]` sin interrumpir el resto.
6. `assemble_markdown()` construye el Markdown final con frontmatter YAML.
7. `validate_items()` comprueba la fidelidad léxica y adjunta el reporte al resultado.

---

## Inputs y outputs

| Tipo | Descripción | Formato |
|------|-------------|---------|
| Input (opcional) | Distribución temática del Agente Organizador | Markdown (`.md`) |
| Input | Material del tema (uno o varios archivos) | PDF, PPTX |
| Output | Markdown estructurado y curado por tema | Markdown (`.md`) |

El Markdown generado incluye `compatible_agente_organizador: true` en el frontmatter y puede usarse directamente como input del Agente Presentación.

---

## Instalación y uso

```bash
pip install -r requirements.txt
cp .env.example .env   # añadir ANTHROPIC_API_KEY en .env
streamlit run app.py --server.port 8501
```

---

## Selección de modelo

| Modelo | Criterio |
|--------|---------|
| `claude-haiku-4-5-20251001` | Chunks sin densidad matemática alta (texto plano) |
| `claude-sonnet-4-5` | Chunks con densidad de símbolos > 0.02, o con patrones `d/dt`, `d²`, `∫`, `Σ` |

Validado: ecuaciones de Hollomon, Ramberg-Osgood, Weibull y Von Mises se enrutan correctamente a Sonnet.

---

## Herramientas de desarrollo

**`tools/validate_pdf.py`** — script CLI para depurar el pipeline de extracción y chunking sin llamadas a la API. No forma parte del producto Streamlit ni del entregable del TFG.

```bash
cd agente-contenido
python tools/validate_pdf.py "ruta/al/material.pdf"
python tools/validate_pdf.py "ruta/al/material.pptx"
```

**`fixtures/Tema_3_curado.md`** — output real del agente sobre Tecnología de Materiales (Tema 3), conservado como caso de prueba para validación y memoria del TFG.

---

## Limitaciones conocidas

- **PDFs exportados desde PPTX:** la exportación destruye la estructura semántica (jerarquía de viñetas, tablas). El agente detecta esta situación y muestra un aviso en la UI recomendando usar el PPTX original.
- **Subíndices químicos:** `pdfplumber` pierde subíndices (ZrO₂ → "ZrO"). Limitación de la biblioteca de extracción.
- **Chunking en límites no ideales:** `[TEXTO_ILEGIBLE]` puede aparecer por partición en mitad de contexto, no por fallo de extracción.
- **Rate limit de Haiku:** con muchos chunks en paralelo se puede agotar el límite de 10.000 tokens/min de Haiku. El marcador de error por chunk hace el fallo visible sin abortar el archivo completo.
