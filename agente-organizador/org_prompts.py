import re


def detectar_idioma(textos: list[str]) -> str:
    palabras_es = {
        "de", "la", "el", "y", "en", "los", "las", "para", "con", "una",
        "un", "por", "del", "que", "tema", "teoria", "horas", "bloque", "subtema",
    }
    palabras_en = {
        "the", "and", "of", "to", "in", "for", "with", "is", "are", "on",
        "from", "this", "that", "topic", "theory", "hours", "block", "section", "subtopic",
    }

    total_es = 0
    total_en = 0

    for texto in textos:
        muestra = (texto or "")[:500].lower()
        tokens = re.findall(r"[a-zA-Záéíóúñü]+", muestra)
        if not tokens:
            continue

        total_es += sum(1 for token in tokens if token in palabras_es)
        total_en += sum(1 for token in tokens if token in palabras_en)

    total_detectado = total_es + total_en
    if total_detectado == 0:
        return "spanish"

    porcentaje_en = total_en / total_detectado
    return "english" if porcentaje_en > 0.60 else "spanish"


def construir_prompt(
    texto_guia: str,
    textos_teoria: list[str],
    textos_contexto: list[str],
    horas_totales: int | None = None,
    horas_laboratorio: int = 0,
    subtemas_por_material: list[list[dict]] | None = None,
) -> tuple[str, str]:
    materiales_teoria_formateados = []
    for indice, texto in enumerate(textos_teoria, start=1):
        bloque = f"=== TEORÍA {indice} ===\n{texto}"
        if subtemas_por_material and indice - 1 < len(subtemas_por_material):
            lista_sub = subtemas_por_material[indice - 1]
            if lista_sub:
                lineas_sub = "\n".join(
                    f"- {s['nombre']} [Evidencia: {s.get('evidencia', '—')}] [{s['origen']}]"
                    for s in lista_sub
                )
                bloque += (
                    f"\n\nSUBTEMAS CONFIRMADOS PARA ESTA TEORÍA (lista cerrada):\n"
                    f"{lineas_sub}\n"
                    f"Usa EXACTAMENTE estos subtemas, en este orden, en la tabla del bloque "
                    f"correspondiente. No añadas ni elimines ninguno."
                )
        materiales_teoria_formateados.append(bloque)

    materiales_contexto_formateados = []
    for indice, texto in enumerate(textos_contexto, start=1):
        materiales_contexto_formateados.append(f"=== CONTEXTO {indice} ===\n{texto}")

    bloque_teoria = "\n\n".join(materiales_teoria_formateados).strip()
    bloque_contexto = "\n\n".join(materiales_contexto_formateados).strip() or "[VACÍO]"

    n_bloques = len(textos_teoria)

    if horas_totales is not None:
        instruccion_horas = (
            f"DISTRIBUCIÓN DE HORAS — RESTRICCIÓN ABSOLUTA:\n"
            f"La guía docente indica {horas_totales}h lectivas (TE + PA) para distribuir "
            f"entre los {n_bloques} bloques. Repártelas de forma proporcional al volumen "
            f"de material de cada bloque (páginas o slides). Todos los bloques deben "
            f"recibir al menos 0.5h.\n"
            f"La suma de horas de todos los bloques debe ser EXACTAMENTE {horas_totales}h. "
            f"Antes de responder, verifica internamente que la suma cuadra y ajusta si es necesario."
        )
    else:
        instruccion_horas = (
            "DISTRIBUCIÓN DE HORAS: La guía docente no especifica las horas totales. "
            "Distribuye de forma proporcional al volumen de material de cada bloque."
        )
    instruccion_cardinalidad = (
        f"RESTRICCIÓN DE CARDINALIDAD — PRIORIDAD MÁXIMA:\n"
        f"La guía docente es la referencia autoritativa para la ESTRUCTURA de bloques\n"
        f"(qué es un bloque y cuántos existen). Los materiales de teoría son fuente\n"
        f"de CONTENIDO de cada bloque, no de estructura.\n"
        f"El número de bloques en el output debe ser EXACTAMENTE {n_bloques},\n"
        f"igual al número de archivos de teoría proporcionados.\n"
        f"\n"
        f"REGLA ANTI-FRAGMENTACIÓN: Si la guía docente describe una sección que tiene\n"
        f"horas asignadas dentro de un tema mayor (por ejemplo, una modalidad de fractura,\n"
        f"un tipo de ensayo o cualquier otro subtópico con horas propias), esa sección\n"
        f"es un SUBTEMA dentro del bloque al que pertenece en los materiales de teoría.\n"
        f"NUNCA la eleves a bloque independiente.\n"
        f"Un subtópico con horas propias en la guía docente sigue siendo un SUBTEMA,\n"
        f"no un bloque. La guía docente desglosa horas por subtemas; eso no los convierte\n"
        f"en bloques independientes.\n"
        f"\n"
        f"AUTOVERIFICACIÓN OBLIGATORIA ANTES DE RESPONDER:\n"
        f"Cuenta el número de encabezados '## Bloque N' en tu respuesta.\n"
        f"Debe ser exactamente {n_bloques}.\n"
        f"Si el recuento da un número distinto, reorganiza el output antes de enviarlo."
    )

    instruccion_orden = (
        f"RESTRICCIÓN DE ORDEN Y NUMERACIÓN — PRIORIDAD MÁXIMA:\n"
        f"La guía docente define no solo cuántos bloques existen, sino también su\n"
        f"ORDEN y su NUMERACIÓN. Debes respetar ambos exactamente.\n"
        f"\n"
        f"1. ORDEN DE APARICIÓN: Los bloques deben aparecer en el output en el MISMO\n"
        f"   orden en que los temas figuran en la guía docente, de principio a fin.\n"
        f"   El primer tema de la guía es el primer bloque del output; el último\n"
        f"   tema de la guía es el último bloque del output.\n"
        f"   NO ordenes los bloques por el orden de los materiales de teoría\n"
        f"   (=== TEORÍA 1, 2, 3... ===): ese orden es accidental (depende de cómo\n"
        f"   se subieron los archivos) y NO debe determinar el orden de los bloques.\n"
        f"   El orden lo manda SIEMPRE la guía docente.\n"
        f"\n"
        f"2. NUMERACIÓN: Si la guía docente numera sus temas (por ejemplo 'Tema 3',\n"
        f"   'Unidad 3', 'Bloque 3', 'Tema III'), el número N de cada '## Bloque N'\n"
        f"   debe coincidir con el número que ese tema tiene en la guía docente,\n"
        f"   convertido a cifra arábiga. Si la guía llama 'Tema 3' a un tema, su\n"
        f"   encabezado debe ser '## Bloque 3 — ...', no el número de posición que\n"
        f"   ocupe entre los materiales subidos.\n"
        f"   Solo si la guía docente NO numera sus temas usarás una numeración\n"
        f"   secuencial 1, 2, 3... siguiendo el orden de aparición en la guía.\n"
        f"\n"
        f"AUTOVERIFICACIÓN DE ORDEN ANTES DE RESPONDER:\n"
        f"Recorre la guía docente de arriba abajo y comprueba que tus bloques\n"
        f"aparecen en ese mismo orden y con ese mismo número de tema.\n"
        f"Si algún bloque está fuera de orden o renumerado, corrígelo antes de enviar."
    )

    idioma = detectar_idioma(textos_teoria)
    if idioma == "english":
        instruccion_idioma = (
            "LANGUAGE INSTRUCTION: The theory materials are in English.\n"
            "You MUST write your entire response in English, including all\n"
            "table headers, labels, and justifications."
        )
    else:
        instruccion_idioma = (
            "INSTRUCCIÓN DE IDIOMA: Los materiales de teoría están en español.\n"
            "Debes escribir toda tu respuesta en español."
        )

    if subtemas_por_material:
        instruccion_subtemas = (
            "2) Usa ÚNICAMENTE los subtemas listados bajo «SUBTEMAS CONFIRMADOS» en cada "
            "material de teoría. No añadas, elimines ni renombres ninguno.\n"
            "   - Si la lista SUBTEMAS CONFIRMADOS de un material está VACÍA, el modelo NO "
            "puede inferir subtemas libremente: crea UN único subtema con el nombre completo "
            "del bloque, escribe "
            "\"Sin señal verificable\" en la columna Evidencia y \"Fallback\" en Origen."
        )
        formato_tabla_subtemas = (
            "  | Subtema | Evidencia | Origen |\n"
            "  |---------|-----------|--------|\n"
            "  | {subtema} | {evidencia} | {origen} |"
        )
        instruccion_columna_subtemas = (
            "- La columna \"Evidencia\" copia el texto entre corchetes [Evidencia: ...] de "
            "la lista «SUBTEMAS CONFIRMADOS» para ese subtema. Si el subtema fue añadido "
            "manualmente por el profesor (origen Manual), escribe \"Manual (profesor)\". "
            "Si no hay señal verificable (fallback), escribe \"Sin señal verificable\".\n"
            "- La columna \"Origen\" copia exactamente el valor [Detectado] o [Manual] de "
            "la lista. Para el caso de fallback usa \"Fallback\". No modifiques estos valores.\n"
            "- NO incluyas columna de horas por subtema. Las horas se asignan SOLO en el "
            "encabezado del bloque (## Bloque N — Nombre · Xh).\n"
            "- Estas reglas aplican igual en la primera generación y en todos los refinamientos."
        )
    else:
        instruccion_subtemas = (
            "2) Para cada bloque temático, identifica subtemas que aparezcan EXPLÍCITAMENTE "
            "como títulos de sección, apartados numerados o títulos de diapositiva en los "
            "materiales del profesor. Si para algún bloque no hay señales estructurales "
            "claras y verificables, crea UN único subtema con el nombre del bloque completo "
            "y escribe \"Sin señal verificable\" en la columna Evidencia."
        )
        formato_tabla_subtemas = (
            "  | Subtema | Evidencia |\n"
            "  |---------|-----------|\n"
            "  | {subtema} | {referencia estructural o 'Sin señal verificable'} |"
        )
        instruccion_columna_subtemas = (
            "- La columna \"Evidencia\" debe ser la referencia estructural verificable que "
            "justifica el subtema: número de sección (e.g. 'Sección 3.2'), título de "
            "diapositiva (e.g. 'Slide 5'), o 'Sin señal verificable' si no hay señal clara.\n"
            "- Si no hay señal clara en el material, escribe \"Sin señal verificable\". "
            "El sistema puede completar evidencia determinista al confirmar la organización.\n"
            "- NUNCA infieras subtemas solo por similitud temática ni uses conteos de "
            "páginas/slides como única justificación en esta columna.\n"
            "- NO incluyas columna de horas por subtema. Las horas se asignan SOLO en el "
            "encabezado del bloque (## Bloque N — Nombre · Xh).\n"
            "- Estas reglas aplican igual en la primera generación y en todos los refinamientos."
        )

    prompt = f"""
{instruccion_idioma}

Instrucciones obligatorias:
1) Identifica los bloques temáticos y sus horas SOLO a partir del texto de la guía docente.
{instruccion_subtemas}
3) Asigna las horas de cada bloque en su encabezado (## Bloque N — Nombre · Xh) de forma
proporcional al volumen de material de ese bloque. NO repartas horas entre subtemas en la tabla.

IMPORTANTE: Los materiales de contexto/outline son solo orientativos. 
Los subtemas deben extraerse ÚNICAMENTE de los materiales de teoría. 
Si un término aparece solo en el outline pero no en los materiales de 
teoría, NO lo incluyas como subtema.

RESTRICCIÓN DE BLOQUE: Los subtemas de cada bloque provienen 
exclusivamente de los materiales de teoría de ese bloque. No puedes 
asignar a un bloque subtemas que aparezcan en los materiales de otro.

RESTRICCIÓN CRÍTICA: No puedes añadir, inferir ni inventar ningún tema,
subtema o concepto que no aparezca textualmente en los documentos
proporcionados.

{instruccion_horas}

{instruccion_cardinalidad}

{instruccion_orden}

Formato de salida:
- Devuelve el resultado en Markdown.
- Debes seguir LITERALMENTE esta plantilla de salida (mismos encabezados, orden y estructura):
  # DISTRIBUCIÓN TEMÁTICA — {{NOMBRE_ASIGNATURA}}

  **Horas lectivas disponibles:** {{TOTAL}}h ({{TE}}h TE + {{PA}}h PA) | **Prácticas de laboratorio:** {{PL}}h *(informativo)*

  ---

  ## Bloque {{N}} — {{NOMBRE_BLOQUE}} · {{HORAS_BLOQUE}}h

{formato_tabla_subtemas}

  *(repetir para cada bloque)*

  ---

  > 🔬 Prácticas de laboratorio: {{PL}}h (sesiones prácticas, no incluidas en la distribución temática)
- No añadas ninguna sección fuera de esa plantilla.
- Prohibido incluir: análisis previos, conteos de páginas/slides, cálculos intermedios, verificaciones finales, tablas de verificación, notas de ajuste o cualquier texto adicional.
- El único contenido permitido es el que cabe dentro de la plantilla anterior.
{instruccion_columna_subtemas}
- Todos los valores numéricos de horas deben usar punto decimal (.) y nunca coma (,), solo en las horas totales de cada bloque (encabezado ## Bloque N · Xh).
- Si necesitas ajustar horas para cuadrar, hazlo internamente y no muestres esos ajustes en el output.

Texto de la guía docente:
{texto_guia}

## MATERIALES DE TEORÍA (fuente principal de subtemas):
{bloque_teoria}

## MATERIALES DE CONTEXTO/OUTLINE (solo para orientación general, 
NO usar para extraer subtemas ni horas):
{bloque_contexto}

NOTA INFORMATIVA (PL): La guía docente indica {horas_laboratorio}h de prácticas de laboratorio.
Estas horas NO se incluyen en la distribución temática de bloques y subtemas.
""".strip()

    return prompt, idioma


def construir_prompt_guia_first(
    texto_guia: str,
    estructura_guia: list[dict],
    textos_teoria: list[str],
    textos_contexto: list[str] | None = None,
    horas_totales: int | None = None,
    horas_laboratorio: int = 0,
) -> tuple[str, str]:
    """Prompt con la estructura de bloques+subtemas TOMADA DE LA GUÍA DOCENTE.

    A diferencia de ``construir_prompt`` (donde el nº de bloques se anclaba al nº
    de archivos de teoría y el LLM estructuraba los subtemas a partir del
    material), aquí la guía docente es la fuente autoritativa de la estructura:
    número de bloques, orden, numeración y subtemas vienen de ``estructura_guia``
    (extraída de forma determinista por ``parser.extraer_estructura_guia`` +
    fallback por material para los bloques que la guía no subdivide).

    El LLM solo: (1) reparte las horas por bloque de forma proporcional al
    volumen de material, y (2) escribe el Markdown con el formato canónico,
    copiando la estructura y la evidencia que se le entrega. No infiere ni añade
    bloques ni subtemas.

    ``estructura_guia`` es una lista de dicts ``{numero, nombre, subtemas}`` donde
    cada subtema es ``{nombre, evidencia, origen}``.
    """
    textos_contexto = textos_contexto or []
    idioma = detectar_idioma(textos_teoria or [texto_guia])
    if idioma == "english":
        instruccion_idioma = (
            "LANGUAGE INSTRUCTION: Write your entire response in English "
            "(headers, labels, justifications). Keep block and subtopic names "
            "exactly as given below."
        )
    else:
        instruccion_idioma = (
            "INSTRUCCIÓN DE IDIOMA: Escribe toda tu respuesta en español. "
            "Conserva los nombres de bloque y subtema exactamente como se dan abajo."
        )

    n_bloques = len(estructura_guia)

    # Estructura autoritativa, bloque a bloque, con su lista cerrada de subtemas.
    # Cada subtema se da como tres campos separados por « ‖ » para que el modelo
    # los copie a las tres columnas SIN corchetes, comillas ni etiquetas.
    lineas_estructura: list[str] = []
    for b in estructura_guia:
        num = b.get("numero")
        encabezado = f"Bloque {num} — {b['nombre']}" if num is not None else f"Bloque — {b['nombre']}"
        lineas_estructura.append(encabezado)
        subtemas = b.get("subtemas") or []
        if subtemas:
            for s in subtemas:
                ev = s.get("evidencia") or "Guía docente"
                origen = s.get("origen") or "Guía docente"
                lineas_estructura.append(
                    f"    subtema={s['nombre']} ‖ evidencia={ev} ‖ origen={origen}"
                )
        else:
            lineas_estructura.append(
                "    [SIN SUBTEMAS EN LA GUÍA: crea UN único subtema cuyo nombre "
                "es el nombre completo del bloque; evidencia=Sin señal verificable; "
                "origen=Fallback]"
            )
    bloque_estructura = "\n".join(lineas_estructura)

    if horas_totales is not None:
        instruccion_horas = (
            f"DISTRIBUCIÓN DE HORAS — RESTRICCIÓN ABSOLUTA:\n"
            f"La guía docente indica {horas_totales}h lectivas (TE + PA) para repartir "
            f"entre los {n_bloques} bloques. Repártelas de forma proporcional al volumen "
            f"de material de cada bloque (páginas/slides). Mínimo 0.5h por bloque. "
            f"La suma debe ser EXACTAMENTE {horas_totales}h; verifica internamente antes de responder."
        )
    else:
        instruccion_horas = (
            "DISTRIBUCIÓN DE HORAS: La guía no especifica las horas totales. "
            "Reparte de forma proporcional al volumen de material de cada bloque."
        )

    materiales_teoria_formateados = [
        f"=== TEORÍA {i} ===\n{t}" for i, t in enumerate(textos_teoria, start=1)
    ]
    bloque_teoria = "\n\n".join(materiales_teoria_formateados).strip() or "[VACÍO]"
    materiales_contexto_formateados = [
        f"=== CONTEXTO {i} ===\n{t}" for i, t in enumerate(textos_contexto, start=1)
    ]
    bloque_contexto = "\n\n".join(materiales_contexto_formateados).strip() or "[VACÍO]"

    prompt = f"""
{instruccion_idioma}

CONTEXTO: La estructura temática (bloques y subtemas) ya está RESUELTA a partir de
la guía docente. Tu tarea es reproducirla en el formato canónico y repartir las horas.

ESTRUCTURA AUTORITATIVA DE LA GUÍA DOCENTE — REPRODÚCELA EXACTAMENTE:
{bloque_estructura}

RESTRICCIONES — PRIORIDAD MÁXIMA:
1. Debes generar EXACTAMENTE {n_bloques} bloques, en este mismo orden y con esta
   misma numeración. No añadas, elimines, fusiones ni reordenes bloques.
2. Los subtemas de cada bloque son los listados arriba (lista cerrada). No añadas,
   elimines ni renombres ninguno. Copia su Evidencia y su Origen tal cual.
3. Para un bloque marcado «[SIN SUBTEMAS EN LA GUÍA]», crea UN único subtema con el
   nombre completo del bloque, Evidencia "Sin señal verificable", Origen "Fallback".
4. No puedes inventar contenido: todo bloque/subtema sale de la estructura de arriba.

{instruccion_horas}

Formato de salida:
- Devuelve el resultado en Markdown siguiendo LITERALMENTE esta plantilla:
  # DISTRIBUCIÓN TEMÁTICA — {{NOMBRE_ASIGNATURA}}

  **Horas lectivas disponibles:** {{TOTAL}}h ({{TE}}h TE + {{PA}}h PA) | **Prácticas de laboratorio:** {{PL}}h *(informativo)*

  ---

  ## Bloque {{N}} — {{NOMBRE_BLOQUE}} · {{HORAS_BLOQUE}}h

  | Subtema | Evidencia | Origen |
  |---------|-----------|--------|
  | {{subtema}} | {{evidencia}} | {{origen}} |

  *(repetir para cada bloque)*

  ---

  > 🔬 Prácticas de laboratorio: {{PL}}h (sesiones prácticas, no incluidas en la distribución temática)
- No añadas ninguna sección, análisis, conteo ni verificación fuera de esa plantilla.
- Cada subtema de la estructura viene como «subtema=… ‖ evidencia=… ‖ origen=…».
  Rellena la columna Subtema con el valor de «subtema=», la columna Evidencia con el
  valor de «evidencia=» y la columna Origen con el valor de «origen=». Copia los valores
  TAL CUAL, SIN las etiquetas «subtema=/evidencia=/origen=», SIN corchetes y SIN comillas.
- Las horas usan punto decimal (.) y solo aparecen en el encabezado del bloque.

El NOMBRE de la asignatura y las horas se toman de la guía docente:
{texto_guia}

## MATERIALES DE TEORÍA (solo para estimar el volumen/horas de cada bloque):
{bloque_teoria}

## MATERIALES DE CONTEXTO (orientativo):
{bloque_contexto}

NOTA INFORMATIVA (PL): La guía docente indica {horas_laboratorio}h de prácticas de laboratorio,
no incluidas en la distribución temática.
""".strip()

    return prompt, idioma


def construir_prompt_solo_guia(
    texto_guia: str,
    horas_totales: int | None = None,
    horas_laboratorio: int = 0,
    subtemas_guia: list[str] | None = None,
) -> tuple[str, str]:
    """Prompt de fallback cuando ningún material de teoría aporta texto extraíble.

    Caso real: PDFs de diapositivas escaneadas/imagen de los que el extractor no
    obtiene texto. En ese escenario la guía docente es la ÚNICA fuente: define la
    estructura de bloques (sección Contenidos), su orden, su numeración y los
    subtemas. No hay número de archivos al que anclar la cardinalidad, así que la
    manda íntegramente la guía.

    Mantiene el principio rector (transforma, nunca inventa): el modelo solo puede
    usar lo que aparece textualmente en la guía docente.
    """
    idioma = detectar_idioma([texto_guia])
    if idioma == "english":
        instruccion_idioma = (
            "LANGUAGE INSTRUCTION: The teaching guide is in English.\n"
            "You MUST write your entire response in English."
        )
    else:
        instruccion_idioma = (
            "INSTRUCCIÓN DE IDIOMA: La guía docente está en español.\n"
            "Debes escribir toda tu respuesta en español."
        )

    if horas_totales is not None:
        instruccion_horas = (
            f"DISTRIBUCIÓN DE HORAS — RESTRICCIÓN ABSOLUTA:\n"
            f"La guía docente indica {horas_totales}h lectivas (TE + PA) para distribuir "
            f"entre los bloques temáticos. Repártelas de forma proporcional a la "
            f"extensión que cada bloque ocupa en la sección Contenidos de la guía. "
            f"Todos los bloques deben recibir al menos 0.5h.\n"
            f"La suma de horas de todos los bloques debe ser EXACTAMENTE {horas_totales}h. "
            f"Antes de responder, verifica internamente que la suma cuadra y ajusta si es necesario."
        )
    else:
        instruccion_horas = (
            "DISTRIBUCIÓN DE HORAS: La guía docente no especifica las horas totales. "
            "Distribuye de forma proporcional a la extensión de cada bloque en la guía."
        )

    if subtemas_guia:
        lineas_sub = "\n".join(f"- {s}" for s in subtemas_guia)
        bloque_subtemas_guia = (
            "SUBTEMAS DETECTADOS EN LA SECCIÓN CONTENIDOS DE LA GUÍA "
            "(referencia de cobertura):\n"
            f"{lineas_sub}\n"
            "Agrúpalos bajo el bloque temático al que pertenecen según la propia guía. "
            "No añadas subtemas que no figuren en este listado o en el texto de la guía."
        )
    else:
        bloque_subtemas_guia = "[Sin subtemas detectados automáticamente en la guía]"

    instruccion_estructura = (
        "RESTRICCIÓN DE ESTRUCTURA — PRIORIDAD MÁXIMA:\n"
        "NO se ha podido extraer texto de los materiales de teoría (probablemente "
        "PDFs de diapositivas escaneadas o basadas en imagen). Por tanto, la guía "
        "docente es la ÚNICA fuente, tanto de estructura como de contenido.\n"
        "\n"
        "1. BLOQUES: Identifica los bloques temáticos EXCLUSIVAMENTE a partir de la "
        "sección Contenidos de la guía docente. El número de bloques, su orden y su "
        "numeración los determina la guía, no ninguna otra fuente.\n"
        "2. NUMERACIÓN: Si la guía numera sus temas (Tema 3, Unidad 3, Bloque III…), "
        "el número N de cada '## Bloque N' debe coincidir con esa numeración, en cifra "
        "arábiga. Si no los numera, usa numeración secuencial por orden de aparición.\n"
        "3. SUBTEMAS: Cada subtema debe figurar textualmente en la guía docente. "
        "Como Evidencia, indica la referencia de la guía (p. ej. 'Guía docente — "
        "Contenidos'). Origen siempre 'Guía docente'.\n"
        "4. Si un bloque de la guía no tiene subtemas desglosados, crea un único "
        "subtema con el nombre completo del bloque y Evidencia 'Guía docente'."
    )

    prompt = f"""
{instruccion_idioma}

CONTEXTO: Generación de la distribución temática SOLO a partir de la guía docente.

Instrucciones obligatorias:
1) Identifica los bloques temáticos, su orden y sus horas a partir de la guía docente.
2) {instruccion_estructura}
3) Asigna las horas de cada bloque en su encabezado (## Bloque N — Nombre · Xh).
   NO repartas horas entre subtemas en la tabla.

RESTRICCIÓN CRÍTICA: No puedes añadir, inferir ni inventar ningún tema, subtema o
concepto que no aparezca textualmente en la guía docente.

{instruccion_horas}

Formato de salida:
- Devuelve el resultado en Markdown.
- Debes seguir LITERALMENTE esta plantilla de salida (mismos encabezados, orden y estructura):
  # DISTRIBUCIÓN TEMÁTICA — {{NOMBRE_ASIGNATURA}}

  **Horas lectivas disponibles:** {{TOTAL}}h ({{TE}}h TE + {{PA}}h PA) | **Prácticas de laboratorio:** {{PL}}h *(informativo)*

  ---

  ## Bloque {{N}} — {{NOMBRE_BLOQUE}} · {{HORAS_BLOQUE}}h

  | Subtema | Evidencia | Origen |
  |---------|-----------|--------|
  | {{subtema}} | Guía docente | Guía docente |

  *(repetir para cada bloque)*

  ---

  > 🔬 Prácticas de laboratorio: {{PL}}h (sesiones prácticas, no incluidas en la distribución temática)
- No añadas ninguna sección fuera de esa plantilla.
- Prohibido incluir: análisis previos, conteos, cálculos intermedios, verificaciones finales, notas de ajuste o cualquier texto adicional.
- Todos los valores numéricos de horas deben usar punto decimal (.) y nunca coma (,), solo en las horas totales de cada bloque (encabezado ## Bloque N · Xh).
- Si necesitas ajustar horas para cuadrar, hazlo internamente y no muestres esos ajustes en el output.

Texto de la guía docente:
{texto_guia}

{bloque_subtemas_guia}

NOTA INFORMATIVA (PL): La guía docente indica {horas_laboratorio}h de prácticas de laboratorio.
Estas horas NO se incluyen en la distribución temática de bloques y subtemas.
""".strip()

    return prompt, idioma


def construir_prompt_refinamiento(
    output_previo: str,
    feedback_previo: list[str],
    horas_totales: int | None = None,
) -> str:
    """Prompt ligero para iteraciones de refinamiento con feedback del profesor.

    No incluye los materiales originales: parte del output ya generado,
    que tiene la estructura correcta. Solo aplica el ajuste solicitado.
    El último ítem de feedback_previo es el ajuste a aplicar en esta iteración;
    los anteriores ya están incorporados en output_previo.
    """
    ultimo_feedback = feedback_previo[-1] if feedback_previo else ""

    if horas_totales is not None:
        restriccion_horas = (
            f"\nRESTRICCIÓN DE HORAS: la suma total de todos los bloques (encabezados ## Bloque N · Xh) "
            f"debe seguir siendo exactamente {horas_totales}h. Si el ajuste modifica las horas de "
            f"un bloque, redistribuye la diferencia de forma proporcional entre los demás bloques "
            f"para que el total no varíe. No asignes horas a nivel de subtema en la tabla."
        )
    else:
        restriccion_horas = ""

    prompt = f"""A continuación se muestra la organización temática actual, que ya incorpora los ajustes anteriores del profesor:

{output_previo}

El profesor solicita el siguiente ajuste adicional:
"{ultimo_feedback}"

INSTRUCCIONES — APLICA ÚNICAMENTE EL CAMBIO SOLICITADO:
1. No modifiques ningún bloque, subtema, nombre ni valor de columna que el profesor
   no haya mencionado explícitamente en el ajuste.{restriccion_horas}
2. Devuelve el documento completo conservando el formato Markdown exacto del original
   (mismas columnas, mismos encabezados, mismo orden de bloques).
3. No añadas texto adicional fuera de la plantilla existente.
4. Todos los valores numéricos de horas usan punto decimal (.) nunca coma (,).
5. Preserva los valores de las columnas Evidencia y Origen tal como están.
   No inventes ni cambies referencias estructurales.""".strip()

    return prompt
