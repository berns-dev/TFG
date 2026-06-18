"""Extracción estructurada de PDF por jerarquía visual (tamaño/negrita de fuente).

Lógica alineada con el scan visual de `agente-organizador/parser.py` (SciPlore Xtract):
frecuencia de (fontname, size) → cuerpo; líneas con estilo dominante de título reciben
prefijos Markdown (# / ## / ###). Las secciones numeradas (3.1. Título) reciben ###.

Expone dos extractores:
- build_pdf_markdown_pymupdf(): usa pymupdf (fitz) — mejor decodificación de fuentes math.
- build_pdf_markdown(): usa pdfplumber — fallback cuando pymupdf no está disponible.

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
_MATH_FONT_SUBSTR = ("math", "symbol", "dingbat", "ding", "mtmi", "cmmi", "cmsy", "msam", "msbm")
_MIN_WORDS_DOCUMENT = 20
_MIN_WORDS_PAGE = 3
_MARGIN_FRAC = 0.06

# Rangos Unicode que indican garbage de fuentes math no decodificadas correctamente
_PUA_RANGES = [(0xE000, 0xF8FF), (0xF0000, 0xFFFFF)]
# Rangos que son símbolos math válidos y legibles (pymupdf los decodifica bien)
_MATH_UNICODE_VALID = [
    (0x0370, 0x03FF),   # Griego (α, β, σ, μ…)
    (0x2070, 0x209F),   # Superíndices/subíndices (², ³…)
    (0x2100, 0x214F),   # Símbolos tipo letra (℃, ℓ…)
    (0x2190, 0x21FF),   # Flechas
    (0x2200, 0x22FF),   # Operadores matemáticos (∑, ∫, ∂…)
    (0x2A00, 0x2AFF),   # Operadores matemáticos suplementarios
    (0x1D400, 0x1D7FF), # Mathematical Alphanumeric Symbols (𝑎, 𝛼…)
]


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


# ---------------------------------------------------------------------------
# Extractor pymupdf (fitz) — mejor decodificación de fuentes math
# ---------------------------------------------------------------------------

def _classify_math_text(text: str) -> str:
    """
    Dado el texto que pymupdf decodificó de un span con fuente math:
    - Si contiene chars PUA (ilegibles) → devuelve '[ECUACION]'
    - Si contiene símbolos math válidos (griegos, operadores…) → devuelve el texto tal cual
    - Si es texto ASCII normal en fuente math → devuelve el texto tal cual
    """
    has_pua = False
    has_valid_math = False
    for c in text:
        cp = ord(c)
        if any(lo <= cp <= hi for lo, hi in _PUA_RANGES):
            has_pua = True
        elif any(lo <= cp <= hi for lo, hi in _MATH_UNICODE_VALID):
            has_valid_math = True

    if has_pua and not has_valid_math:
        return "[ECUACION]"
    return text


def _prefix_from_span_styles(
    text: str,
    styles: list[tuple[str, float, int]],
    cuerpo_fn: str,
    cuerpo_sz: float,
) -> str:
    """Prefijo Markdown (# / ## / ###) a partir de estilos fitz (fontname, size, flags)."""
    t = (text or "").strip()
    if not t:
        return ""
    if _NUMBERED_HEADER_RE.match(t):
        return "### "
    if len(t) > 120 or len(t.split()) > 18:
        return ""
    if not styles:
        return ""

    style_counter: Counter[tuple[str, float]] = Counter()
    for fn, sz, _flags in styles:
        if fn and sz > 0:
            style_counter[(fn, sz)] += 1

    if not style_counter:
        return ""

    (fn_dom, sz_dom), _ = style_counter.most_common(1)[0]

    if fn_dom == cuerpo_fn and sz_dom == cuerpo_sz:
        return ""

    ratio = sz_dom / cuerpo_sz if cuerpo_sz > 0 else 1.0
    fn_lower = fn_dom.lower()
    es_mayor = ratio >= 1.2
    es_negrita = (
        fn_dom != cuerpo_fn
        and any(s in fn_lower for s in ("bold", "bd", "black", "heavy"))
        and sz_dom >= cuerpo_sz * 0.9
    )

    if not (es_mayor or es_negrita):
        # Comprobar flag bold de fitz (bit 4 = 16)
        flags_dom = next((f for fn, sz, f in styles if fn == fn_dom and sz == sz_dom), 0)
        if flags_dom & 16 and sz_dom >= cuerpo_sz * 0.9:
            es_negrita = True

    if not (es_mayor or es_negrita):
        return ""

    if ratio >= 1.45 and len(t) <= 100:
        return "# "
    if ratio >= 1.2:
        return "## " if len(t) <= 90 else "### "
    return "### "


def build_pdf_markdown_pymupdf(source: bytes | Path | str | BinaryIO) -> str | None:
    """
    Extracción con jerarquía visual usando pymupdf (fitz).

    Ventajas sobre pdfplumber: mejor decodificación de fuentes math (Symbol, Cambria Math,
    fuentes OpenType MATH), mejor orden de lectura en layouts complejos.

    Mismo formato de salida que build_pdf_markdown(): [PAGINA N]\\ncontent.
    Devuelve None si el documento no tiene texto extraíble o pymupdf no está disponible.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return None

    try:
        if isinstance(source, (str, Path)):
            doc = fitz.open(str(source))
        elif isinstance(source, bytes):
            doc = fitz.open(stream=source, filetype="pdf")
        else:
            data = source.read()
            doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return None

    if doc.page_count == 0:
        doc.close()
        return None

    try:
        # Primera pasada: detectar fuente de cuerpo (más frecuente, no math, ≥7pt)
        font_counter: Counter[tuple[str, float]] = Counter()
        all_chars = 0

        for page in doc:
            try:
                blocks = page.get_text("dict")["blocks"]
            except Exception:
                continue
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        fn = (span.get("font") or "").strip()
                        sz = _round_sz(span.get("size", 0))
                        text = span.get("text", "")
                        if not fn or sz < 7 or not text.strip():
                            continue
                        if any(s in fn.lower() for s in _MATH_FONT_SUBSTR):
                            continue
                        font_counter[(fn, sz)] += len(text)
                        all_chars += len(text)

        if all_chars < _MIN_WORDS_DOCUMENT or not font_counter:
            return None

        (cuerpo_fn, cuerpo_sz), _ = font_counter.most_common(1)[0]

        # Segunda pasada: construir markdown página a página
        parts: list[str] = []

        for npag, page in enumerate(doc, start=1):
            height = float(page.rect.height)
            margin = height * _MARGIN_FRAC

            try:
                blocks = page.get_text("dict")["blocks"]
            except Exception:
                parts.append(f"[PAGINA {npag}]\n[TEXTO_ILEGIBLE]")
                continue

            lines_out: list[str] = []

            for block in blocks:
                if block.get("type") != 0:
                    continue
                y0_block = block["bbox"][1]
                if y0_block < margin or y0_block > height - margin:
                    continue

                for line in block.get("lines", []):
                    y0_line = line["bbox"][1]
                    if y0_line < margin or y0_line > height - margin:
                        continue

                    parts_line: list[str] = []
                    styles_line: list[tuple[str, float, int]] = []

                    for span in line.get("spans", []):
                        fn = (span.get("font") or "").strip()
                        sz = _round_sz(span.get("size", 0))
                        flags = int(span.get("flags", 0))
                        text = span.get("text", "")

                        if not text.strip():
                            continue

                        is_math_font = fn and any(s in fn.lower() for s in _MATH_FONT_SUBSTR)

                        if is_math_font:
                            decoded = _classify_math_text(text)
                            parts_line.append(decoded)
                        else:
                            parts_line.append(text)

                        if fn and sz > 0:
                            styles_line.append((fn, sz, flags))

                    if not parts_line:
                        continue

                    line_text = " ".join(parts_line).strip()
                    # Colapsar espacios múltiples que pueden venir de la concatenación de spans
                    line_text = re.sub(r" {2,}", " ", line_text)
                    if not line_text:
                        continue

                    prefix = _prefix_from_span_styles(line_text, styles_line, cuerpo_fn, cuerpo_sz)
                    lines_out.append(f"{prefix}{line_text}" if prefix else line_text)

            body = "\n".join(lines_out).strip()
            parts.append(f"[PAGINA {npag}]\n{body}" if body else f"[PAGINA {npag}]\n[TEXTO_ILEGIBLE]")

        return "\n\n".join(parts).strip() if parts else None

    finally:
        doc.close()
