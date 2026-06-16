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
    horas_totales: int = None,
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
                    f"- {s['nombre']} [{s['origen']}]" for s in lista_sub
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

    if horas_totales is not None:
        instruccion_horas = (
            "DISTRIBUCIÓN DE HORAS: La guía docente de esta asignatura indica\n"
            f"{horas_totales}h lectivas totales (clases expositivas + prácticas de aula), pero no especifica\n"
            "la distribución por bloques temáticos. ESE ES TU TRABAJO:\n"
            f"distribuye las {horas_totales}h entre los bloques de forma\n"
            "proporcional al volumen de material que encuentres en los\n"
            "materiales de teoría (número de slides o páginas por bloque).\n"
            "Justifica el reparto en la columna correspondiente.\n"
            f"La suma de todas las horas asignadas debe ser exactamente {horas_totales}h."
        )
    else:
        instruccion_horas = (
            "DISTRIBUCIÓN DE HORAS: La guía docente no especifica las horas\n"
            "por bloque. Distribuye las horas de forma proporcional al volumen\n"
            "de material. Indica la distribución propuesta en el output."
        )

    if horas_totales is not None:
        instruccion_restriccion_total = (
            "RESTRICCIÓN ABSOLUTA DE HORAS: La suma de TODAS las horas\n"
            f"asignadas a TODOS los bloques debe ser EXACTAMENTE {horas_totales}h.\n"
            "No puede ser ni una hora más ni una hora menos.\n"
            "Antes de responder, suma todas las horas asignadas y verifica que\n"
            f"el total es exactamente {horas_totales}h.\n"
            "Si el total no cuadra, redistribuye hasta que cuadre.\n"
            "Esta restricción tiene prioridad sobre cualquier otra consideración."
        )
        instruccion_bloques_sin_material = (
            "BLOQUES SIN MATERIAL: Si para algún bloque temático identificado\n"
            "en la guía docente no encuentras material de teoría suficiente,\n"
            "NO escribas [MATERIAL INSUFICIENTE]. En su lugar:\n"
            "1. Asigna las horas de ese bloque de forma proporcional a los\n"
            "   bloques que sí tienen material\n"
            "2. Indica en la columna de justificación: 'Horas redistribuidas\n"
            "   desde bloque sin material disponible'\n"
            f"La suma total sigue siendo exactamente {horas_totales}h."
        )
    else:
        instruccion_restriccion_total = ""
        instruccion_bloques_sin_material = ""

    n_bloques = len(textos_teoria)
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
            "material de teoría. No añadas, elimines ni renombres ninguno. Si un material "
            "no tiene subtemas confirmados, indica [MATERIAL SIN SUBTEMAS] en la tabla."
        )
        formato_tabla_subtemas = (
            "  | Subtema | Horas | Origen |\n"
            "  |---------|-------|--------|\n"
            "  | {subtema} | {horas} | {origen} |"
        )
        instruccion_columna_subtemas = (
            "- La columna \"Origen\" copia exactamente el valor [Detectado] o [Manual] que "
            "aparece junto a cada subtema en la lista «SUBTEMAS CONFIRMADOS» del material. "
            "No modifiques estos valores.\n"
            "- Estas reglas aplican igual en la primera generación y en todos los refinamientos."
        )
    else:
        instruccion_subtemas = (
            "2) Para cada bloque temático, identifica subtemas que aparezcan EXPLÍCITAMENTE "
            "como títulos de sección o apartados en los materiales del profesor."
        )
        formato_tabla_subtemas = (
            "  | Subtema | Horas | Justificación |\n"
            "  |---------|-------|---------------|\n"
            "  | {subtema} | {horas} | {una frase corta} |"
        )
        instruccion_columna_subtemas = (
            "- La columna \"Justificación\" debe ser siempre una frase corta descriptiva "
            "del contenido del subtema, nunca un párrafo.\n"
            "- La \"Justificación\" nunca puede ser un conteo de páginas/slides ni una "
            "referencia al material fuente (por ejemplo: \"2 páginas en teoría\", \"3 slides\", "
            "\"según el PDF\").\n"
            "- Estas reglas de formato, incluida la regla de \"Justificación\", aplican igual "
            "en la primera generación y en todas las regeneraciones con feedback del profesor."
        )

    prompt = f"""
{instruccion_idioma}

Instrucciones obligatorias:
1) Identifica los bloques temáticos y sus horas SOLO a partir del texto de la guía docente.
{instruccion_subtemas}
3) Distribuye las horas de cada bloque de forma proporcional entre sus subtemas según el número de slides o páginas dedicadas a cada subtema en los materiales.
4) Si en los materiales no hay suficiente información para un bloque, indícalo de forma explícita.

IMPORTANTE: Los materiales de contexto/outline son solo orientativos. 
Los subtemas deben extraerse ÚNICAMENTE de los materiales de teoría. 
Si un término aparece solo en el outline pero no en los materiales de 
teoría, NO lo incluyas como subtema.

RESTRICCIÓN DE BLOQUE: Los subtemas de cada bloque provienen 
exclusivamente de los materiales de teoría de ese bloque. No puedes 
asignar a un bloque subtemas que aparezcan en los materiales de otro.

RESTRICCIÓN CRÍTICA: No puedes añadir, inferir ni inventar ningún tema, 
subtema o concepto que no aparezca textualmente en los documentos 
proporcionados. Si el material de un bloque es insuficiente para 
identificar subtemas, indica explícitamente: [MATERIAL INSUFICIENTE].

{instruccion_horas}

{instruccion_restriccion_total}

{instruccion_bloques_sin_material}

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
- Todos los valores numéricos de horas deben usar punto decimal (.) y nunca coma (,), tanto en las horas de subtemas como en las horas totales de cada bloque.
- La suma de horas de todos los bloques debe ser EXACTAMENTE igual a las horas disponibles.
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
            f"\nRESTRICCIÓN DE HORAS: la suma total de todos los bloques debe seguir\n"
            f"siendo exactamente {horas_totales}h. Si el ajuste modifica las horas de\n"
            f"un bloque o subtema, redistribuye la diferencia de forma proporcional\n"
            f"entre los demás para que el total no varíe."
        )
    else:
        restriccion_horas = ""

    prompt = f"""A continuación se muestra la organización temática actual, que ya incorpora los ajustes anteriores del profesor:

{output_previo}

El profesor solicita el siguiente ajuste adicional:
"{ultimo_feedback}"

INSTRUCCIONES — APLICA ÚNICAMENTE EL CAMBIO SOLICITADO:
1. No modifiques ningún bloque, subtema, nombre ni justificación que el profesor
   no haya mencionado explícitamente en el ajuste.{restriccion_horas}
2. Devuelve el documento completo con el mismo formato Markdown.
3. No añadas texto adicional fuera de la plantilla existente.
4. Todos los valores numéricos de horas usan punto decimal (.) nunca coma (,).
5. La columna "Justificación" sigue siendo siempre una frase corta descriptiva,
   nunca un conteo de páginas ni una referencia al material fuente.""".strip()

    return prompt
