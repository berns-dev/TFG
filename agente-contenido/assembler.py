"""Ensamblado del Markdown final."""

from __future__ import annotations

import os
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

SECTION_NAMES = {
    "es": {
        "teoria": "## Contenido teórico",
        "ejemplo_resuelto": "## Ejemplos resueltos",
        "ejercicio_propuesto": "## Ejercicios propuestos",
        "tabla": "## Tablas de referencia",
        "procedimiento": "## Procedimientos",
        "resumen": "## Resumen",
        "mixto": "## Contenido",
    },
    "en": {
        "teoria": "## Theory",
        "ejemplo_resuelto": "## Solved examples",
        "ejercicio_propuesto": "## Practice problems",
        "tabla": "## Reference tables",
        "procedimiento": "## Procedures",
        "resumen": "## Summary",
        "mixto": "## Content",
    },
}

# Orden canónico de las secciones en el documento ensamblado. Cada tipo aparece
# una sola vez; los cuerpos de todos los chunks de ese tipo se concatenan en el
# orden en que se extrajeron. Evita repetir el mismo H2 cada vez que la
# clasificación por chunk alterna de tipo (p. ej. 7× "## Theory").
#
# "mixto" no figura aquí a propósito: sus cuerpos se fusionan dentro de la
# sección de "teoria" (ver MERGE_INTO en assemble_markdown), por lo que el
# documento final no tiene una sección "## Contenido" / "## Content" separada.
CANONICAL_TYPE_ORDER = (
    "teoria",
    "procedimiento",
    "tabla",
    "ejemplo_resuelto",
    "ejercicio_propuesto",
    "resumen",
)

# Tipos que no generan sección propia: su cuerpo se vuelca en la sección del
# tipo destino, intercalado en orden de aparición con el resto de ese tipo.
MERGE_INTO = {"mixto": "teoria"}


def _normalize(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _strip_h1_lines(markdown: str, idioma: str | None = None) -> str:
    """Limpia los encabezados del cuerpo de un chunk antes del ensamblado:

    - Quita los H1 (`# `): el título del documento lo pone el ensamblador.
    - Quita los H2 canónicos: el ensamblador los re-emite una sola vez por tipo.
    - Degrada a H3 (`### `) cualquier H2 NO canónico que el modelo haya inventado
      dentro del cuerpo, para que quede como subsección y no compita visualmente
      con las secciones canónicas del documento.
    """
    if idioma in SECTION_NAMES:
        section_values = SECTION_NAMES[idioma].values()
    else:
        section_values = [v for lang in SECTION_NAMES.values() for v in lang.values()]
    normalized_h2 = {
        _normalize(v[3:].strip()) for v in section_values if v.startswith("## ")
    }

    lines = markdown.split("\n")
    kept: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if _normalize(title) in normalized_h2:
                continue
            kept.append(f"### {title}")
            continue
        kept.append(ln)
    return "\n".join(kept).strip()


def _body_after_frontmatter(md: str, idioma: str | None = None) -> str:
    """Todo lo que sigue al segundo '---' (fin del frontmatter YAML)."""
    stripped = md.strip()
    if not stripped.startswith("---"):
        return _strip_h1_lines(stripped, idioma=idioma)
    parts = stripped.split("---", 2)
    if len(parts) >= 3:
        body = parts[2].lstrip("\n")
        return _strip_h1_lines(body, idioma=idioma)
    return _strip_h1_lines(stripped, idioma=idioma)


def _remove_empty_sections(markdown: str) -> str:
    """Elimina secciones H2 sin contenido real y limpia separadores sobrantes."""
    lines = markdown.split("\n")
    h2_indexes = [i for i, line in enumerate(lines) if line.strip().startswith("## ")]
    if not h2_indexes:
        return markdown.strip()

    keep_mask = [True] * len(lines)
    for pos, start in enumerate(h2_indexes):
        end = h2_indexes[pos + 1] if pos + 1 < len(h2_indexes) else len(lines)
        section_body = lines[start + 1 : end]
        has_real_content = any(
            ln.strip() and ln.strip() != "---" for ln in section_body
        )
        if not has_real_content:
            for i in range(start, end):
                keep_mask[i] = False

    filtered = [ln for i, ln in enumerate(lines) if keep_mask[i]]
    cleaned: list[str] = []
    for ln in filtered:
        is_sep = ln.strip() == "---"
        if is_sep:
            if not cleaned:
                continue
            prev = cleaned[-1].strip()
            if prev in {"", "---"}:
                continue
        cleaned.append(ln)

    while cleaned and cleaned[-1].strip() in {"", "---"}:
        cleaned.pop()
    return "\n".join(cleaned).strip()


def _frontmatter_inner(md: str) -> str | None:
    """Texto entre el primer y el segundo ---."""
    stripped = md.strip()
    if not stripped.startswith("---"):
        return None
    parts = stripped.split("---", 2)
    if len(parts) >= 2:
        return parts[1].strip("\n")
    return None


def _parse_fm_field(fm_inner: str, field: str) -> str | None:
    prefix = f"{field}:"
    for line in fm_inner.split("\n"):
        s = line.strip()
        if s.startswith(prefix):
            return s[len(prefix) :].strip()
    return None


def assemble_markdown(items: list[dict[str, Any]], nombre_del_archivo: str) -> str:
    """
    Une los chunks procesados en un .md unico con secciones estandar y frontmatter.
    """
    tipos = [str(item.get("tipo", "mixto")) for item in items if item.get("tipo")]
    tipo_frecuente = Counter(tipos).most_common(1)[0][0] if tipos else "mixto"
    if len(set(tipos)) > 1:
        tipo_documento = "mixto"
    else:
        tipo_documento = tipo_frecuente

    tema_detectado = "No detectado"
    for item in items:
        titulo = item.get("titulo_detectado")
        if titulo is not None:
            tema_detectado = str(titulo)
            break

    idiomas = [str(item.get("idioma", "es")) for item in items if item.get("idioma")]
    idioma_doc = Counter(idiomas).most_common(1)[0][0] if idiomas else "es"
    if idioma_doc not in SECTION_NAMES:
        idioma_doc = "es"

    frontmatter = (
        "---\n"
        f"archivo_origen: {nombre_del_archivo}\n"
        f"tipo_documento: {tipo_documento}\n"
        f"tema_detectado: {tema_detectado}\n"
        f"idioma: {idioma_doc}\n"
        f"fecha_procesado: {date.today().isoformat()}\n"
        "compatible_agente_organizador: true\n"
        "---"
    )

    names = SECTION_NAMES[idioma_doc]

    # Agrupa los cuerpos por tipo preservando el orden de extracción dentro de
    # cada grupo. Así cada sección canónica se emite una única vez.
    bodies_by_tipo: dict[str, list[str]] = {}
    encounter_order: list[str] = []
    for item in items:
        tipo = str(item.get("tipo", "mixto"))
        body = _strip_h1_lines(
            str(item.get("contenido_markdown", "")).strip(), idioma=idioma_doc
        )
        if not body:
            continue
        # "mixto" (y cualquier otro tipo en MERGE_INTO) se vuelca en su tipo
        # destino. Como se respeta el orden de items, los cuerpos de teoria y
        # mixto quedan intercalados en orden de aparición.
        tipo = MERGE_INTO.get(tipo, tipo)
        if tipo not in bodies_by_tipo:
            bodies_by_tipo[tipo] = []
            encounter_order.append(tipo)
        bodies_by_tipo[tipo].append(body)

    # Orden canónico primero; cualquier tipo no contemplado se añade al final
    # en el orden en que apareció (defensivo: VALID_TYPES es cerrado).
    ordered_tipos = [t for t in CANONICAL_TYPE_ORDER if t in bodies_by_tipo]
    ordered_tipos += [t for t in encounter_order if t not in CANONICAL_TYPE_ORDER]

    section_blocks: list[str] = []
    for tipo in ordered_tipos:
        if section_blocks:
            section_blocks.append("---")
        section_blocks.append(names.get(tipo, names["mixto"]))
        section_blocks.append("")
        section_blocks.append("\n\n".join(bodies_by_tipo[tipo]))
        section_blocks.append("")

    body_sections = "\n".join(section_blocks).strip()

    h1_block = ""
    if tema_detectado != "No detectado":
        h1_block = f"# {tema_detectado}\n\n"

    if body_sections:
        full_body = _remove_empty_sections(f"{h1_block}{body_sections}".strip())
        return f"{frontmatter}\n\n{full_body}"
    if h1_block:
        return f"{frontmatter}\n\n{h1_block.strip()}"
    return frontmatter


def assemble_multiple(resultados: list[dict[str, Any]]) -> str:
    """
    Unifica varios .md ya generados (resultados de session_state) en un solo documento.
    Cada dict debe tener al menos: nombre, markdown, items.
    """
    if not resultados:
        return ""

    nombres = [str(r["nombre"]) for r in resultados]
    archivo_origen = " | ".join(nombres)

    all_tipos: list[str] = []
    all_idiomas: list[str] = []
    for r in resultados:
        for it in r.get("items") or []:
            all_tipos.append(str(it.get("tipo", "mixto")))
            all_idiomas.append(str(it.get("idioma", "es")))

    if len(set(all_tipos)) <= 1:
        tipo_documento = all_tipos[0] if all_tipos else "mixto"
    else:
        tipo_documento = "mixto"

    idioma = Counter(all_idiomas).most_common(1)[0][0] if all_idiomas else "es"
    if idioma not in SECTION_NAMES:
        idioma = "es"

    tema_detectado = "No detectado"
    for r in resultados:
        fm = _frontmatter_inner(str(r.get("markdown", "")))
        if fm:
            tema = _parse_fm_field(fm, "tema_detectado")
            if tema and tema != "No detectado":
                tema_detectado = tema
                break

    unified_fm = (
        "---\n"
        f"archivo_origen: {archivo_origen}\n"
        f"tipo_documento: {tipo_documento}\n"
        f"idioma: {idioma}\n"
        f"tema_detectado: {tema_detectado}\n"
        f"fecha_procesado: {date.today().isoformat()}\n"
        "compatible_agente_organizador: true\n"
        "---"
    )

    bodies = [
        _body_after_frontmatter(str(r.get("markdown", "")), idioma=idioma)
        for r in resultados
    ]

    h1 = f"# {tema_detectado}\n\n" if tema_detectado != "No detectado" else ""
    partes: list[str] = [f"{h1}{bodies[0].strip()}".strip()]
    for i in range(1, len(resultados)):
        nom = resultados[i]["nombre"]
        partes.append(f"---\n\n## {Path(nom).stem}\n\n{bodies[i].strip()}")

    cuerpo = _remove_empty_sections("\n\n".join(partes).strip())
    return f"{unified_fm}\n\n{cuerpo}"


def _strip_h1_from_body(body: str) -> str:
    """Elimina líneas de encabezado H1 (# pero no ##) de un cuerpo Markdown."""
    lines = body.split("\n")
    filtered = []
    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            continue
        filtered.append(ln)
    return "\n".join(filtered).strip()


def assemble_subbloque_body(
    items: list[dict[str, Any]],
    nombre_subbloque: str,
    nombre_del_archivo: str = "",
) -> str:
    """Ensambla el cuerpo Markdown de un subbloque (sin frontmatter YAML propio).

    Reutiliza assemble_markdown() para toda la lógica de secciones canónicas,
    luego extrae el cuerpo y sustituye el H1 detectado por el nombre del subbloque.
    """
    full_md = assemble_markdown(
        items, nombre_del_archivo=nombre_del_archivo or nombre_subbloque or "subbloque"
    )
    body = _body_after_frontmatter(full_md)
    body_no_h1 = _strip_h1_from_body(body)
    h1 = f"# {nombre_subbloque}\n\n" if nombre_subbloque else ""
    return (h1 + body_no_h1).strip()


def assemble_block_with_subbloques(
    subbloque_results: list[dict[str, Any]],
    nombre_del_archivo: str,
    nombre_bloque: str = "",
    bloque_horas: float = 0.0,
) -> str:
    """Ensambla el Markdown final de un bloque como secuencia de subbloques.

    Cada subbloque queda delimitado por marcadores HTML comment:
        <!-- SUBBLOQUE_INICIO: id="N" nombre="..." horas="X" estado="..." -->
        ...markdown del subbloque...
        <!-- SUBBLOQUE_FIN: id="N" -->

    Estos marcadores son invisibles al renderizar Markdown y permiten
    parsear el documento de forma fiable por subbloque mediante regex:
        re.findall(r'<!-- SUBBLOQUE_INICIO: (.*?) -->', md)

    El frontmatter YAML del bloque incluye los campos canónicos del Agente
    Contenido más los específicos del nivel bloque:
        bloque, bloque_horas, total_subbloques.
    """
    all_idiomas: list[str] = []
    for sb in subbloque_results:
        for item in sb.get("items", []):
            all_idiomas.append(str(item.get("idioma", "es")))
    idioma_doc = Counter(all_idiomas).most_common(1)[0][0] if all_idiomas else "es"
    if idioma_doc not in SECTION_NAMES:
        idioma_doc = "es"

    frontmatter = (
        "---\n"
        f"archivo_origen: {nombre_del_archivo}\n"
        f"bloque: {nombre_bloque}\n"
        f"bloque_horas: {bloque_horas}\n"
        f"idioma: {idioma_doc}\n"
        f"fecha_procesado: {date.today().isoformat()}\n"
        f"total_subbloques: {len(subbloque_results)}\n"
        "compatible_agente_organizador: true\n"
        "---"
    )

    sections: list[str] = []
    for i, sb in enumerate(subbloque_results):
        nombre = sb.get("nombre", f"Subbloque {i + 1}")
        horas = sb.get("horas", 0.0)
        estado = sb.get("estado", "pendiente")
        md = (sb.get("markdown") or "").strip()

        inicio = (
            f'<!-- SUBBLOQUE_INICIO: id="{i}" nombre="{nombre}" '
            f'horas="{horas}" estado="{estado}" -->'
        )
        body = md if md else "*Contenido pendiente de procesar.*"
        fin = f'<!-- SUBBLOQUE_FIN: id="{i}" -->'
        sections.append(f"{inicio}\n\n{body}\n\n{fin}")

    cuerpo = "\n\n---\n\n".join(sections)
    return f"{frontmatter}\n\n{cuerpo}"


def unified_download_filename(stems: list[str]) -> str:
    """Nombre de archivo para el .md unificado (varios archivos). Prefijo común o material_curado."""
    if len(stems) < 2:
        return "material_curado.md"
    cp = os.path.commonprefix(stems).rstrip("_-")
    if cp:
        return f"{cp}_completo_curado.md"
    return "material_curado.md"
