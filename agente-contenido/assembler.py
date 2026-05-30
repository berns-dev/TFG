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


def _normalize(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _strip_h1_lines(markdown: str, idioma: str | None = None) -> str:
    """Quita H1 y H2 estándar para evitar duplicados en el ensamblado."""
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
    section_blocks: list[str] = []
    previous_tipo: str | None = None

    for item in items:
        tipo = str(item.get("tipo", "mixto"))
        raw_body = str(item.get("contenido_markdown", "")).strip()
        body = _strip_h1_lines(raw_body, idioma=idioma_doc)
        if not body:
            continue

        encabezado = names.get(tipo, names["mixto"])
        if previous_tipo is None or tipo != previous_tipo:
            if section_blocks:
                section_blocks.append("---")
            section_blocks.append(encabezado)
            section_blocks.append("")
        section_blocks.append(body)
        section_blocks.append("")
        previous_tipo = tipo

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


def unified_download_filename(stems: list[str]) -> str:
    """Nombre de archivo para el .md unificado (varios archivos). Prefijo común o material_curado."""
    if len(stems) < 2:
        return "material_curado.md"
    cp = os.path.commonprefix(stems).rstrip("_-")
    if cp:
        return f"{cp}_completo_curado.md"
    return "material_curado.md"
