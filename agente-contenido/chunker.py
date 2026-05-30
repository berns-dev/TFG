"""Division de texto en chunks coherentes."""

from __future__ import annotations

import logging
import re

from config import CHUNK_CHAR_RATIO, CHUNK_TARGET_TOKENS

_LOGGER = logging.getLogger(__name__)


def _ensure_chunker_audit_handler() -> None:
    if _LOGGER.handlers:
        return
    _LOGGER.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False


_ensure_chunker_audit_handler()


_NUMBERED_HEADER_RE = re.compile(r"^\d+(?:\.\d+)*\.\s+\S")
_PAGE_SLIDE_HEADER_RE = re.compile(r"^\[(?:PAGINA|SLIDE)\s+\d+\]")
_SENTENCE_END_RE = re.compile(r'[.!?]["\'\)]*(?:\s|$)')
_SECTION_KEYWORDS = (
    "Chapter",
    "Section",
    "Topic",
    "Tema",
    "Capitulo",
    "Capítulo",
    "Seccion",
    "Sección",
    "Introduccion",
    "Introducción",
    "Introduction",
    "Summary",
    "Resumen",
    "Ejercicios",
    "Exercises",
    "Problems",
    "Ejemplos",
    "Examples",
)


def _is_markdown_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _iter_line_spans(text: str) -> list[tuple[int, int, str]]:
    parts = text.split("\n")
    spans: list[tuple[int, int, str]] = []
    off = 0
    for i, line in enumerate(parts):
        start = off
        off += len(line)
        spans.append((start, off, line))
        if i < len(parts) - 1:
            off += 1
    return spans


def _markdown_table_blocks(text: str) -> list[tuple[int, int]]:
    spans = _iter_line_spans(text)
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(spans)
    while i < n:
        _, _, line = spans[i]
        if not _is_markdown_table_line(line):
            i += 1
            continue
        j = i
        while j < n and _is_markdown_table_line(spans[j][2]):
            j += 1
        block_start = spans[i][0]
        last_ls, last_le, _ = spans[j - 1]
        end_exclusive = last_le
        if j - 1 < n - 1:
            end_exclusive = last_le + 1
        blocks.append((block_start, end_exclusive))
        i = j
    return blocks


def _extend_cut_past_markdown_table(
    text: str, chunk_start: int, cut_exclusive: int, hard_max_len: int
) -> int:
    """
    Si cut_exclusive cae dentro de un bloque de líneas consecutivas que empiezan por '|',
    devuelve el fin de ese bloque. Si eso supera hard_max_len para el trozo [chunk_start:],
    deja cut_exclusive y registra WARNING.
    """
    if cut_exclusive <= chunk_start or cut_exclusive > len(text):
        return cut_exclusive
    for block_start, block_end in _markdown_table_blocks(text):
        if block_start < cut_exclusive < block_end:
            extended = block_end
            if extended - chunk_start > hard_max_len:
                _LOGGER.warning(
                    "Corte dentro de tabla: extender al final del bloque superaría "
                    "2× CHUNK_TARGET_TOKENS (en chars aprox.); se mantiene el corte original."
                )
                return cut_exclusive
            return extended
    return cut_exclusive


def _extend_cut_to_sentence_end(
    para: str, start: int, proposed: int, hard_max_len: int, lookahead: int = 300
) -> int:
    """Extend proposed forward to end of current sentence if the cut falls mid-sentence.

    Does not move the cut if it already lands at a sentence boundary (., !, ?)
    or at a newline. Never extends past hard_max_len chars from start.
    """
    if proposed >= len(para):
        return proposed

    # Already at a sentence boundary: look at the non-whitespace chars just before the cut.
    tail = para[max(start, proposed - 10):proposed].rstrip()
    if tail and tail[-1] in ".!?":
        return proposed

    # A newline is an acceptable paragraph boundary — don't extend.
    if proposed > start and para[proposed - 1] == "\n":
        return proposed

    # Search forward for the next sentence end within lookahead chars.
    search_end = min(len(para), proposed + lookahead, start + hard_max_len)
    m = _SENTENCE_END_RE.search(para, proposed, search_end)
    if m:
        return m.end()

    return proposed


def _split_oversized_paragraph(para: str, max_chars: int) -> list[str]:
    """Parte un párrafo largo respetando tablas Markdown y límites duros."""
    hard = 2 * CHUNK_TARGET_TOKENS * CHUNK_CHAR_RATIO
    out: list[str] = []
    start = 0
    while start < len(para):
        proposed = min(start + max_chars, len(para))
        if proposed < len(para):
            last_nl = para.rfind("\n", start, proposed)
            if last_nl != -1 and last_nl >= start:
                proposed = last_nl + 1
        proposed = _extend_cut_past_markdown_table(
            para, start, proposed, hard_max_len=hard
        )
        proposed = _extend_cut_to_sentence_end(
            para, start, proposed, hard_max_len=hard
        )
        if proposed <= start:
            proposed = min(start + max_chars, len(para))
            if proposed <= start:
                proposed = min(start + 1, len(para))
        piece = para[start:proposed]
        if piece.strip():
            out.append(piece.strip())
        start = proposed
    return out if out else [para.strip()]


def _normalize_paragraphs_for_chunking(
    paragraphs: list[str], max_chars: int
) -> list[str]:
    expanded: list[str] = []
    for para in paragraphs:
        p = para.strip()
        if not p:
            continue
        if len(p) <= max_chars:
            expanded.append(p)
        else:
            expanded.extend(_split_oversized_paragraph(p, max_chars))
    return expanded


def _split_large_section_by_paragraph(section: str, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in section.strip().split("\n\n") if p.strip()]
    paragraphs = _normalize_paragraphs_for_chunking(paragraphs, max_chars)
    if not paragraphs:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        add_len = len(para) + (2 if current else 0)
        if current and current_len + add_len > max_chars:
            chunk_text = "\n\n".join(current).strip()
            chunks.append(chunk_text)
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += add_len
    if current:
        chunks.append("\n\n".join(current).strip())
    return chunks


def _is_section_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _NUMBERED_HEADER_RE.match(stripped):
        return True
    if _PAGE_SLIDE_HEADER_RE.match(stripped):
        return True
    lowered = stripped.lower()
    if any(lowered.startswith(keyword.lower()) for keyword in _SECTION_KEYWORDS):
        return True
    if 4 < len(stripped) < 80 and stripped == stripped.upper() and "=" not in stripped:
        return True
    return False


def _split_into_semantic_sections(text: str) -> list[tuple[str | None, str]]:
    lines = text.splitlines()
    sections: list[tuple[str | None, str]] = []
    current_lines: list[str] = []
    current_header: str | None = None
    found_header = False

    for line in lines:
        stripped = line.strip()
        if _is_section_header(stripped):
            found_header = True
            if current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    sections.append((current_header, content))
            current_header = stripped
            current_lines = [stripped]
        else:
            current_lines.append(line)

    if current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_header, content))

    if not found_header:
        return []
    return sections


def _split_large_semantic_section(section: str, header: str | None, max_chars: int) -> list[str]:
    if not header:
        return _split_large_section_by_paragraph(section, max_chars)

    body = section.split("\n", 1)[1].strip() if "\n" in section else ""
    body_max_chars = max(400, max_chars - len(header) - 1)
    body_chunks = _split_large_section_by_paragraph(body, body_max_chars) if body else []
    if not body_chunks:
        return [header]
    return [f"{header}\n{chunk}".strip() for chunk in body_chunks]


def split_into_chunks(text: str, target_tokens: int | None = None) -> list[str]:
    """
    Divide texto en bloques cercanos a ~1500 tokens.
    Aproximacion: tokens * 4 chars.
    """
    clean = (text or "").strip()
    if not clean:
        return []

    tokens = target_tokens or CHUNK_TARGET_TOKENS
    max_chars = max(1000, tokens * CHUNK_CHAR_RATIO)

    semantic_sections = _split_into_semantic_sections(clean)
    if semantic_sections:
        chunks: list[str] = []
        current_parts: list[str] = []
        current_len = 0

        for header, section in semantic_sections:
            section_len = len(section)
            if header and current_parts and current_len >= 500:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = []
                current_len = 0

            if section_len > max_chars:
                if current_parts:
                    chunks.append("\n\n".join(current_parts).strip())
                    current_parts = []
                    current_len = 0
                chunks.extend(_split_large_semantic_section(section, header, max_chars))
                continue
            add_len = section_len + (2 if current_parts else 0)
            if current_parts and current_len + add_len > max_chars:
                chunks.append("\n\n".join(current_parts).strip())
                current_parts = [section]
                current_len = section_len
            else:
                current_parts.append(section)
                current_len += add_len
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
        return chunks

    paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
    paragraphs = _normalize_paragraphs_for_chunking(paragraphs, max_chars)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        add_len = len(para) + (2 if current else 0)
        if current and current_len + add_len > max_chars:
            chunks.append("\n\n".join(current).strip())
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += add_len

    if current:
        chunks.append("\n\n".join(current).strip())

    return chunks
