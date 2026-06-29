# Plantillas de formato

Esta carpeta recoge, como archivos independientes, las plantillas de formato que cada agente produce y que los demás módulos del sistema parsean. Documentan el contrato entre agentes descrito en `CLAUDE.md` (sección "Contrato entre agentes") y en el Anexo B de la memoria del TFG (`memoria/anexos/B-analisis-requisitos-del-sistema.md`).

No son código ejecutable ni se importan desde ningún agente: son la referencia legible de un formato que, en el código real, vive embebido en los prompts (`org_prompts.py`, `classifier.py`, `prs_prompts.py`) y en las funciones de ensamblado (`assembler.py`, `generador_presentacion.py`). Si el formato de salida de un agente cambia, esta carpeta debe actualizarse junto con el código.

- `organizador/distribucion_tematica.md` — salida del Agente Organizador.
- `contenido/bloque_con_subbloques.md` — salida del Agente Contenido, con subbloques del Organizador.
- `contenido/bloque_pipeline_clasico.md` — salida del Agente Contenido, sin subbloques (pipeline clásico).
- `presentacion/bloque_html_interactivo.js` — convención de bloque HTML/JS del Agente Presentación.
