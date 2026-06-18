"""Extracción estructurada de PDF por jerarquía visual (tamaño/negrita de fuente).

Lógica alineada con el scan visual de `agente-organizador/parser.py` (SciPlore Xtract):
frecuencia de (fontname, size) → cuerpo; líneas con estilo dominante de título reciben
prefijos Markdown (# / ## / ###). Las secciones numeradas (3.1. Título) reciben ###.

Usado por el Agente Contenido; el Organizador puede reutilizar este módulo en el futuro.
"""

from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import BinaryIO

import pdfplumber

_NUMBERED_HEADER_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
_MATH_FONT_SUBSTR = ("math", "symbol", "dingbat", "ding")
_MIN_WORDS_DOCUMENT = 20
_MIN_WORDS_PAGE = 3
_MARGIN_FRAC = 0.06


def _round_sz(size: float | int | None) -> float:
    return round(float(size or 0) * 2) / 2


def _dominant_line_style(
    palabras_linea: list[dict],
) -> tuple[str, float, int, int] | None:
    """Estilo dominante de una línea: (fontname, size, n_dom, n_total)."""
    estilos: Counter[tuple[str, float]] = Counter()
    for w in palabras_linea:
        fn = (w.get("fontname") or "").strip()
        sz = _round_sz(w.get("size"))
        if fn and sz > 0:
            estilos[(fn, sz)] += 1
    if not estilos:
        return None
    (fn_dom, sz_dom), n_dom = estilos.most_common(1)[0]
    return fn_dom, sz_dom, n_dom, sum(estilos.values())


def is_visual_title_line(
    palabras_linea: list[dict],
    cuerpo_fn: str,
    cuerpo_sz: float,
) -> bool:
    """True si el estilo dominante de la línea es de título (≠ cuerpo)."""
    dom = _dominant_line_style(palabras_linea)
    if dom is None:
        return False
    fn_dom, sz_dom, n_dom, n_total = dom
    if n_dom < n_total * 0.7:
        return False
    if fn_dom == cuerpo_fn and sz_dom == cuerpo_sz:
        return False
    es_mayor = sz_dom > cuerpo_sz * 1.2
    fn_lower = fn_dom.lower()
    es_negrita = (
        fn_dom != cuerpo_fn
        and any(s in fn_lower for s in ("bold", "bd", "black", "heavy"))
        and sz_dom >= cuerpo_sz * 0.9
    )
    return es_mayor or es_negrita


def markdown_prefix_for_line(
    texto: str,
    palabras_linea: list[dict],
    cuerpo_fn: str,
    cuerpo_sz: float,
) -> str:
    """Prefijo Markdown (# / ## / ###) para una línea, o '' si es cuerpo."""
    t = (texto or "").strip()
    if not t:
        return ""

    if _NUMBERED_HEADER_RE.match(t):
        return "### "

    if len(t) > 120 or len(t.split()) > 18:
        return ""

    if not is_visual_title_line(palabras_linea, cuerpo_fn, cuerpo_sz):
        return ""

    dom = _dominant_line_style(palabras_linea)
    if dom is None:
        return ""
    _fn, sz_dom, _n_dom, _n_total = dom
    ratio = sz_dom / cuerpo_sz if cuerpo_sz > 0 else 1.0

    if ratio >= 1.45 and len(t) <= 100:
        return "# "
    if ratio >= 1.2:
        return "## " if len(t) <= 90 else "### "
    return "### "


def _detect_body_font(todas_palabras: list[dict]) -> tuple[str, float] | None:
    conteo: Counter[tuple[str, float]] = Counter()
    for p in todas_palabras:
        fn = (p.get("fontname") or "").strip()
        sz = _round_sz(p.get("size"))
        if fn and sz >= 7 and not any(s in fn.lower() for s in _MATH_FONT_SUBSTR):
            conteo[(fn, sz)] += 1
    if not conteo:
        return None
    return conteo.most_common(1)[0][0]


def _group_words_into_lines(
    palabras_pagina: list[dict],
) -> list[tuple[int, str, list[dict]]]:
    """Agrupa palabras en líneas: (y_bucket, texto, palabras_ordenadas)."""
    lineas_map: dict[int, list[dict]] = defaultdict(list)
    for p in palabras_pagina:
        y_bucket = int(round(float(p.get("top") or 0)))
        lineas_map[y_bucket].append(p)

    result: list[tuple[int, str, list[dict]]] = []
    for y_bucket in sorted(lineas_map):
        pals_ord = sorted(lineas_map[y_bucket], key=lambda w: float(w.get("x0") or 0))
        texto = " ".join(w["text"] for w in pals_ord if w.get("text")).strip()
        if texto:
            result.append((y_bucket, texto, pals_ord))
    return result


def _page_to_markdown_lines(
    palabras_pagina: list[dict],
    altura_pag: float,
    cuerpo_fn: str,
    cuerpo_sz: float,
) -> list[str]:
    margen = altura_pag * _MARGIN_FRAC
    out: list[str] = []
    for y_bucket, texto, pals_ord in _group_words_into_lines(palabras_pagina):
        if y_bucket < margen or y_bucket > altura_pag - margen:
            continue
        prefix = markdown_prefix_for_line(texto, pals_ord, cuerpo_fn, cuerpo_sz)
        out.append(f"{prefix}{texto}" if prefix else texto)
    return out


def build_pdf_markdown(source: bytes | Path | str | BinaryIO) -> str | None:
    """Construye texto con [PAGINA N] y prefijos Markdown en títulos visuales.

    Returns:
        Documento extraído, o None si no hay metadatos de fuente suficientes
        (el caller debe usar extracción plana).
    """
    if isinstance(source, Path):
        pdf_io: BinaryIO | bytes = source.read_bytes()
    elif isinstance(source, str):
        pdf_io = Path(source).read_bytes()
    elif isinstance(source, bytes):
        pdf_io = source
    else:
        pdf_io = source.read()

    try:
        with pdfplumber.open(io.BytesIO(pdf_io) if isinstance(pdf_io, bytes) else pdf_io) as pdf:
            todas_palabras: list[dict] = []
            paginas_palabras: list[tuple[int, list[dict], float]] = []

            for npag, pagina in enumerate(pdf.pages, start=1):
                try:
                    palabras = pagina.extract_words(extra_attrs=["fontname", "size"]) or []
                except Exception:
                    palabras = []
                altura = float(pagina.height or 800.0)
                paginas_palabras.append((npag, palabras, altura))
                todas_palabras.extend(palabras)

            if len(todas_palabras) < _MIN_WORDS_DOCUMENT:
                return None

            cuerpo = _detect_body_font(todas_palabras)
            if cuerpo is None:
                return None
            cuerpo_fn, cuerpo_sz = cuerpo

            parts: list[str] = []
            for npag, palabras, altura in paginas_palabras:
                header = f"[PAGINA {npag}]"
                if len(palabras) < _MIN_WORDS_PAGE:
                    try:
                        plain = pdf.pages[npag - 1].extract_text() or ""
                    except Exception:
                        plain = ""
                    body = plain.strip()
                else:
                    lines = _page_to_markdown_lines(palabras, altura, cuerpo_fn, cuerpo_sz)
                    body = "\n".join(lines).strip()
                    if not body:
                        try:
                            body = (pdf.pages[npag - 1].extract_text() or "").strip()
                        except Exception:
                            body = ""

                if body:
                    parts.append(f"{header}\n{body}")
                else:
                    parts.append(f"{header}\n[TEXTO_ILEGIBLE]")

            return "\n\n".join(parts).strip() if parts else None
    except Exception:
        return None
