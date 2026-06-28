"""Utilidades de texto compartidas entre agentes y app unificada."""

from __future__ import annotations

import re
import unicodedata


def slugify(nombre: str) -> str:
    """Convierte un nombre legible a slug para carpetas y anclas HTML."""
    s = unicodedata.normalize("NFD", nombre)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "elemento"


# ---------------------------------------------------------------------------
# Marcadores de ecuación del Agente Contenido
# ---------------------------------------------------------------------------

_ECUACION_PARCIAL_RE = re.compile(r"\[ECUACION_PARCIAL:\s*([^\]]*)\]")
_ECUACION_NO_EXTRAIBLE_RE = re.compile(r"\[ECUACION_NO_EXTRAIBLE\]")
_ECUACION_RECONSTRUIDA_RE = re.compile(r"\[ECUACION_RECONSTRUIDA:\s*([^\]]*)\]")
_ECUACION_INLINE_RE = re.compile(r"\[ECUACION\]")
_BLOCK_MATH_RE = re.compile(r"\$\$([\s\S]*?)\$\$")
_ALL_ECUACION_MARKERS_RE = re.compile(
    r"\[ECUACION_PARCIAL:\s*[^\]]*\]"
    r"|\[ECUACION_NO_EXTRAIBLE\]"
    r"|\[ECUACION_RECONSTRUIDA:\s*[^\]]*\]"
    r"|\[ECUACION\]"
)

_INVALID_INSIDE_BLOCK_MATH_RE = re.compile(
    r"(?:"
    r"#{1,6}\s"
    r"|\[FIGURA:"
    r"|\[TEXTO_ILEGIBLE\]"
    r"|\[ECUACION"
    r"|xx(?:PRES|ECUA)TOKEN\d+xx"
    r")",
)


def _strip_ecuacion_markers_from_expr(expr: str) -> str:
    """Quita marcadores del Agente Contenido dejando solo LaTeX."""
    expr = _ECUACION_INLINE_RE.sub("", expr)
    expr = _ECUACION_PARCIAL_RE.sub("", expr)
    expr = _ECUACION_NO_EXTRAIBLE_RE.sub("", expr)
    expr = _ECUACION_RECONSTRUIDA_RE.sub("", expr)
    return expr.strip()


def _markers_in_block(content: str) -> list[str]:
    return [m.group(0) for m in _ALL_ECUACION_MARKERS_RE.finditer(content)]


_PROSE_CONNECTOR_RE = re.compile(
    r"\b(donde|siendo|es\s+decir|mientras|adem[aá]s|figura|expresa|resulta|"
    r"tomamos|preciso|reemplazar|identifican|anteriormente|n[oó]tese)\b",
    re.IGNORECASE,
)


def _has_significant_prose(expr: str) -> bool:
    """Detecta prosa española mezclada con notación matemática."""
    sans_inline = re.sub(r"\$[^$\n]+\$", " ", expr)
    if _PROSE_CONNECTOR_RE.search(sans_inline):
        return True
    sans = re.sub(r"\\[a-zA-Z]+\*?(?:\{[^{}]*\})*", " ", sans_inline)
    sans = re.sub(r"[{ }_^\\=+\-*/().,\[\]0-9]", " ", sans)
    words = re.findall(r"[a-záéíóúñü]{4,}", sans, re.IGNORECASE)
    if len(words) >= 2:
        return True
    if "%" in sans_inline:
        return True
    if ";" in sans_inline and len(words) >= 1:
        return True
    return False


def _is_valid_display_math(expr: str) -> bool:
    """Heurística: el interior de ``$$...$$`` parece LaTeX, no prosa."""
    if not expr or _INVALID_INSIDE_BLOCK_MATH_RE.search(expr):
        return False
    sans_inline = re.sub(r"\$[^$\n]+\$", " ", expr)
    if _has_significant_prose(sans_inline) or _has_significant_prose(expr):
        return False
    check = sans_inline.strip() or expr.strip()
    if re.search(
        r"\\(?:frac|left|right|ln|sqrt|sum|int|sigma|varepsilon|Delta|eta|quad)",
        check,
    ):
        return True
    if re.search(r"[\\^_{}]", check) and re.search(r"[=+\-*/]", check):
        return True
    if re.search(r"[=+\-*/]", check) and len(check) < 180:
        return True
    return False


def _split_equation_prose_line(line: str) -> list[str]:
    """Separa una línea que empieza con fórmula y continúa con prosa."""
    line = line.strip()
    if not line:
        return []
    m = _PROSE_CONNECTOR_RE.search(line)
    if m and m.start() > 4:
        head = line[: m.start()].strip().rstrip(",")
        tail = line[m.start() :].strip()
        parts: list[str] = []
        if head and should_keep_as_display_math(head):
            parts.append(f"$${head}$$")
        elif head:
            parts.append(head)
        if tail:
            parts.append(tail)
        return parts
    if should_keep_as_display_math(line):
        return [f"$${line}$$"]
    return [line]


def split_mixed_display_math_block(content: str) -> str:
    """Descompone un bloque ``$$...$$`` inválido en fórmulas aisladas y prosa."""
    content = content.strip()
    if not content:
        return ""
    if should_keep_as_display_math(content):
        body = _strip_ecuacion_markers_from_expr(content) or content
        return f"$${body}$$"

    parts: list[str] = []
    for para in re.split(r"\n\s*\n", content):
        para = para.strip()
        if not para:
            continue
        flat = para.replace("\n", " ").strip()
        if should_keep_as_display_math(flat):
            body = _strip_ecuacion_markers_from_expr(flat) or flat
            parts.append(f"$${body}$$")
            continue
        lines = [ln.strip() for ln in para.split("\n") if ln.strip()]
        if len(lines) == 1:
            parts.extend(_split_equation_prose_line(lines[0]))
            continue
        if lines and should_keep_as_display_math(lines[0]):
            parts.append(f"$${lines[0]}$$")
            parts.append(" ".join(lines[1:]))
        else:
            parts.append(" ".join(lines))
    return "\n\n".join(parts)


def should_keep_as_display_math(content: str) -> bool:
    """True si el interior de un par ``$$...$$`` debe renderizarse como LaTeX."""
    if not content.strip():
        return False
    if _INVALID_INSIDE_BLOCK_MATH_RE.search(content):
        return False
    latex = _strip_ecuacion_markers_from_expr(content)
    candidate = latex if latex else content.strip()
    return _is_valid_display_math(candidate)


def _remove_lone_dollar_lines(text: str) -> str:
    """Quita líneas que solo contienen ``$$`` (delimitadores huérfanos)."""
    return re.sub(r"^\s*\$\$\s*$", "", text, flags=re.MULTILINE)


def _promote_bare_display_lines(text: str) -> str:
    """Envuelve en ``$$`` líneas que son solo una fórmula sin delimitadores."""
    lines = text.split("\n")
    promoted: list[str] = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("$$")
            and should_keep_as_display_math(stripped)
            and not _has_significant_prose(stripped)
        ):
            promoted.append(f"$${stripped}$$")
        else:
            promoted.append(line)
    return "\n".join(promoted)


def _strip_trailing_orphan_dollars(text: str) -> str:
    """Quita ``$$`` finales huérfanos en líneas con un solo delimitador."""
    lines: list[str] = []
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped.count("$$") == 1 and stripped.endswith("$$"):
            lines.append(stripped[:-2].rstrip())
        else:
            lines.append(line)
    return "\n".join(lines)


def _ensure_block_separation(text: str) -> str:
    """Separa prosa pegada a fórmulas en la misma línea."""
    lines_out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines_out.append(line)
            continue
        m = re.match(r"^(.+[:.])(\s*)(\$\$.+\$\$)$", stripped)
        if m:
            lines_out.extend([m.group(1).strip(), m.group(3)])
            continue
        m2 = re.match(r"^(.+[:.])(\s*)(\\.+)$", stripped)
        if m2:
            lines_out.extend([m2.group(1).strip(), m2.group(3)])
            continue
        m3 = re.search(r"[:.]\s*(\\)", stripped)
        if m3 and m3.start() > 0:
            head = stripped[: m3.start() + 1].strip()
            tail = stripped[m3.end() - 1 :].strip()
            lines_out.extend([head, tail])
            continue
        lines_out.append(line)
    return "\n".join(lines_out)


def prepare_display_math(text: str) -> str:
    """Normaliza y desempaqueta bloques ``$$...$$`` hasta quedar estables."""
    if "$$" not in text:
        return _promote_bare_display_lines(text)
    text = _remove_lone_dollar_lines(text)
    prev = None
    iterations = 0
    while prev != text and iterations < 8:
        prev = text
        text = resolve_display_math_blocks(text)
        text = sanitize_block_math(text)
        iterations += 1
    text = _strip_trailing_orphan_dollars(text)
    text = _ensure_block_separation(text)
    text = _promote_bare_display_lines(text)
    text = _remove_lone_dollar_lines(text)
    return text


def resolve_display_math_blocks(text: str) -> str:
    """Normaliza bloques ``$$...$$`` que envuelven marcadores de ecuación.

    - Si el bloque solo contiene marcadores → los saca fuera de ``$$`` para
      que el renderizador pueda mostrarlos como aviso visible.
    - Si mezcla marcadores y LaTeX (p. ej. ``$$[ECUACION] = C\\frac{...}$$``)
      → elimina solo los marcadores y conserva la fórmula.
    """
    if "$$" not in text:
        return text

    def repl(m: re.Match[str]) -> str:
        content = m.group(1)
        markers = _markers_in_block(content)
        latex = _strip_ecuacion_markers_from_expr(content)

        if markers:
            if not latex:
                return " " + " ".join(markers) + " "
            if not _is_valid_display_math(latex):
                return split_mixed_display_math_block(content)
            return f"$${latex}$$"

        if should_keep_as_display_math(content):
            body = latex if latex else content.strip()
            return f"$${body}$$"
        if content.strip():
            return split_mixed_display_math_block(content)
        return ""

    return _BLOCK_MATH_RE.sub(repl, text)


def tokenize_ecuacion_markers(
    text: str,
    placeholder_prefix: str,
) -> tuple[str, dict[str, dict[str, str]]]:
    """Sustituye marcadores de ecuación por tokens opacos antes del Markdown.

    Returns:
        (texto con tokens, {token: {"tipo": ..., "texto": ...}})
    """
    subs: dict[str, dict[str, str]] = {}
    counter = [0]

    def _key() -> str:
        key = f"{placeholder_prefix}{counter[0]}{placeholder_prefix}"
        counter[0] += 1
        return key

    def repl_parcial(m: re.Match[str]) -> str:
        key = _key()
        subs[key] = {"tipo": "parcial", "texto": m.group(1).strip()}
        return key

    def repl_no_extraible(_m: re.Match[str]) -> str:
        key = _key()
        subs[key] = {"tipo": "no_extraible", "texto": ""}
        return key

    def repl_reconstruida(m: re.Match[str]) -> str:
        key = _key()
        subs[key] = {"tipo": "reconstruida", "texto": m.group(1).strip()}
        return key

    def repl_inline(_m: re.Match[str]) -> str:
        key = _key()
        subs[key] = {"tipo": "inline", "texto": ""}
        return key

    text = _ECUACION_PARCIAL_RE.sub(repl_parcial, text)
    text = _ECUACION_NO_EXTRAIBLE_RE.sub(repl_no_extraible, text)
    text = _ECUACION_RECONSTRUIDA_RE.sub(repl_reconstruida, text)
    text = _ECUACION_INLINE_RE.sub(repl_inline, text)
    return text, subs


def _unwrap_block_math_pairs(text: str) -> str:
    """Una pasada: desempaqueta parejas $$...$$ cuyo interior no es solo LaTeX."""
    parts: list[str] = []
    i = 0
    while i < len(text):
        start = text.find("$$", i)
        if start == -1:
            parts.append(text[i:])
            break
        if start > i:
            parts.append(text[i:start])
        end = text.find("$$", start + 2)
        if end == -1:
            parts.append(text[start + 2 :])
            break
        content = text[start + 2 : end]
        if not should_keep_as_display_math(content):
            line_end = text.find("\n", end)
            if line_end == -1:
                line_end = len(text)
            line = text[end:line_end]
            # El siguiente $$ abre un bloque completo en la misma línea ($$…$$)
            if line.count("$$") >= 2:
                if content.strip():
                    parts.append(split_mixed_display_math_block(content))
                i = end
                continue
            if content.strip():
                parts.append(split_mixed_display_math_block(content))
            i = end + 2
            continue
        parts.append(f"$${content}$$")
        i = end + 2
    return "".join(parts)


def _strip_orphan_math_delimiters(text: str) -> str:
    """Elimina ``$$`` sueltos que no forman un bloque de LaTeX válido."""
    if "$$" not in text:
        return text
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("$$", i):
            end = text.find("$$", i + 2)
            if end == -1:
                i += 2
                continue
            inner = text[i + 2 : end]
            if should_keep_as_display_math(inner):
                out.append(f"$${inner}$$")
                i = end + 2
                continue
            line_end = text.find("\n", end)
            if line_end == -1:
                line_end = len(text)
            line = text[end:line_end]
            if line.count("$$") >= 2:
                if inner.strip():
                    out.append(split_mixed_display_math_block(inner))
                i = end
                continue
            if inner.strip():
                out.append(split_mixed_display_math_block(inner))
            i = end + 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def sanitize_block_math(text: str) -> str:
    """Evita que delimitadores $$...$$ envuelvan prosa o encabezados Markdown."""
    if "$$" not in text:
        return text

    prev = None
    iterations = 0
    while prev != text and iterations < 8:
        prev = text
        text = _unwrap_block_math_pairs(text)
        iterations += 1

    text = re.sub(
        r"\$\$\s*\n+(?=#{1,6}\s|\[FIGURA:|\[TEXTO_ILEGIBLE\]|\[ECUACION)",
        "",
        text,
    )

    while text.count("$$") % 2 != 0 and re.search(r"\$\$\s*$", text):
        text = re.sub(r"\$\$\s*$", "", text, count=1)

    return text


def promote_bare_display_lines(text: str) -> str:
    """API pública: envuelve líneas sueltas de LaTeX en ``$$...$$``."""
    return _promote_bare_display_lines(text)


def normalize_for_matching(text: str) -> str:
    """Normaliza texto para comparación léxica (fidelidad, cobertura)."""
    t = unicodedata.normalize("NFD", text or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("\u00a0", " ")
    for ch in "–—−":
        t = t.replace(ch, "-")
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
