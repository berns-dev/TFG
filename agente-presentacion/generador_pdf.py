"""Generacion de PDF estructurado desde Markdown usando ReportLab.

Pipeline:
  1. Strip frontmatter YAML (---...---).
  2. Parsear el Markdown con la libreria 'markdown' de Python para obtener HTML.
  3. Recorrer el HTML con html.parser y convertir cada elemento a un
     Flowable de ReportLab (Paragraph, Spacer, Preformatted, HRFlowable).
  4. Las ecuaciones LaTeX ($$...$$ e inline $...$) se renderizan como
     bloques monoespaciados con fondo gris y borde izquierdo azul.
  5. ReportLab genera el PDF en memoria y devuelve bytes.

Dependencias: reportlab, markdown (ambas puras Python, sin GTK).
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from typing import Any

try:
    import markdown as _md_lib
    _MD_AVAILABLE = True
except ImportError:
    _md_lib = None  # type: ignore[assignment]
    _MD_AVAILABLE = False

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
)
from reportlab.platypus.flowables import Flowable

# ---------------------------------------------------------------------------
# Colores de la paleta
# ---------------------------------------------------------------------------

_AZUL = colors.HexColor("#185FA5")
_NEGRO = colors.HexColor("#2C2C2A")
_GRIS_OSCURO = colors.HexColor("#444441")
_GRIS_FONDO = colors.HexColor("#F7F5F0")
_GRIS_BORDE = colors.HexColor("#D3D1C7")

# ---------------------------------------------------------------------------
# Estilos de párrafo
# ---------------------------------------------------------------------------

_base = getSampleStyleSheet()

_ESTILOS: dict[str, ParagraphStyle] = {
    "h1": ParagraphStyle(
        "H1",
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=_AZUL,
        leading=24,
        spaceBefore=20,
        spaceAfter=6,
        alignment=TA_LEFT,
    ),
    "h2": ParagraphStyle(
        "H2",
        fontName="Helvetica-Bold",
        fontSize=14,
        textColor=_NEGRO,
        leading=18,
        spaceBefore=14,
        spaceAfter=4,
        alignment=TA_LEFT,
    ),
    "h3": ParagraphStyle(
        "H3",
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=_GRIS_OSCURO,
        leading=16,
        spaceBefore=10,
        spaceAfter=3,
        alignment=TA_LEFT,
    ),
    "h4": ParagraphStyle(
        "H4",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=_GRIS_OSCURO,
        leading=14,
        spaceBefore=8,
        spaceAfter=2,
        alignment=TA_LEFT,
    ),
    "p": ParagraphStyle(
        "Normal",
        fontName="Helvetica",
        fontSize=10,
        textColor=_NEGRO,
        leading=14,
        spaceBefore=0,
        spaceAfter=5,
        alignment=TA_JUSTIFY,
    ),
    "li": ParagraphStyle(
        "ListItem",
        fontName="Helvetica",
        fontSize=10,
        textColor=_NEGRO,
        leading=14,
        spaceBefore=0,
        spaceAfter=2,
        leftIndent=16,
        bulletIndent=6,
        alignment=TA_LEFT,
    ),
    "code": ParagraphStyle(
        "Code",
        fontName="Courier",
        fontSize=9,
        textColor=_NEGRO,
        leading=13,
        spaceBefore=4,
        spaceAfter=4,
        backColor=_GRIS_FONDO,
        leftIndent=10,
        rightIndent=4,
        alignment=TA_LEFT,
    ),
    "ecuacion_bloque": ParagraphStyle(
        "EcuacionBloque",
        fontName="Courier",
        fontSize=9,
        textColor=_NEGRO,
        leading=14,
        spaceBefore=6,
        spaceAfter=6,
        backColor=_GRIS_FONDO,
        leftIndent=14,
        rightIndent=4,
        alignment=TA_CENTER,
    ),
    "ecuacion_inline": ParagraphStyle(
        "EcuacionInline",
        fontName="Courier",
        fontSize=9,
        textColor=_NEGRO,
        leading=12,
        backColor=_GRIS_FONDO,
    ),
    "blockquote": ParagraphStyle(
        "Blockquote",
        fontName="Helvetica-Oblique",
        fontSize=10,
        textColor=_GRIS_OSCURO,
        leading=14,
        leftIndent=20,
        spaceBefore=4,
        spaceAfter=4,
    ),
    "figura": ParagraphStyle(
        "Figura",
        fontName="Helvetica-Oblique",
        fontSize=9,
        textColor=_GRIS_OSCURO,
        leading=12,
        spaceBefore=2,
        spaceAfter=4,
        alignment=TA_CENTER,
    ),
}


# ---------------------------------------------------------------------------
# Borde izquierdo para bloques de código/ecuación
# ---------------------------------------------------------------------------

class _LeftBorderBox(Flowable):
    """Flowable that draws a left accent border and a background fill."""

    def __init__(self, inner: Flowable, border_color: Any = _AZUL,
                 bg_color: Any = _GRIS_FONDO, border_width: float = 3):
        super().__init__()
        self._inner = inner
        self._border_color = border_color
        self._bg_color = bg_color
        self._border_width = border_width

    def wrap(self, avail_w: float, avail_h: float):
        w, h = self._inner.wrap(avail_w - self._border_width - 4, avail_h)
        self.width = avail_w
        self.height = h + 8  # vertical padding
        return self.width, self.height

    def draw(self):
        c = self.canv
        pad = 4
        h = self.height
        # Background
        c.setFillColor(self._bg_color)
        c.rect(self._border_width + 2, 0, self.width - self._border_width - 2, h,
               fill=1, stroke=0)
        # Left border
        c.setFillColor(self._border_color)
        c.rect(0, 0, self._border_width, h, fill=1, stroke=0)
        # Draw inner flowable
        c.saveState()
        c.translate(self._border_width + 6, pad)
        self._inner.drawOn(c, 0, 0)
        c.restoreState()


# ---------------------------------------------------------------------------
# Regex pre-proceso de LaTeX antes del parseo HTML
# ---------------------------------------------------------------------------

_BLOCK_LATEX_RE = re.compile(r"\$\$([\s\S]+?)\$\$")
_INLINE_LATEX_RE = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)")
_FIGURA_RE = re.compile(r"\[FIGURA:[^\]]*\]")
_TEXTO_ILEGIBLE_RE = re.compile(r"\[TEXTO_ILEGIBLE\]")

# Placeholder tokens that won't be mangled by the markdown parser
_BLOCK_PLACEHOLDER = "XXLATEXBLKXX"
_INLINE_PLACEHOLDER_START = "XXLATEXINLSTARTXX"
_INLINE_PLACEHOLDER_END = "XXLATEXINLENDXX"


def _protect_latex(text: str) -> tuple[str, dict[str, str]]:
    """Replace LaTeX blocks with safe placeholders before markdown parsing."""
    subs: dict[str, str] = {}
    counter = [0]

    def repl_block(m: re.Match) -> str:
        key = f"{_BLOCK_PLACEHOLDER}{counter[0]}{_BLOCK_PLACEHOLDER}"
        subs[key] = m.group(1).strip()
        counter[0] += 1
        return key

    def repl_inline(m: re.Match) -> str:
        key = (f"{_INLINE_PLACEHOLDER_START}{counter[0]}"
               f"{_INLINE_PLACEHOLDER_END}")
        subs[key] = m.group(1).strip()
        counter[0] += 1
        return key

    text = _BLOCK_LATEX_RE.sub(repl_block, text)
    text = _INLINE_LATEX_RE.sub(repl_inline, text)
    return text, subs


# ---------------------------------------------------------------------------
# HTML parser → lista de Flowables
# ---------------------------------------------------------------------------

class _MarkdownFlowableParser(HTMLParser):
    """Walk the HTML produced by the markdown library and build ReportLab
    Flowables. State machine: tracks current block tag and inline text."""

    # Inline tags whose content we collect as text
    _INLINE_TAGS = {"strong", "em", "code", "a", "span", "sup", "sub"}
    # Block tags that flush previous text
    _BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6",
                   "ul", "ol", "li", "blockquote", "pre",
                   "hr", "table", "thead", "tbody", "tr", "th", "td",
                   "div", "section"}

    def __init__(self, latex_subs: dict[str, str]):
        super().__init__()
        self._subs = latex_subs
        self.flowables: list[Flowable] = []

        self._tag_stack: list[str] = []       # block tag stack
        self._text_buf: list[str] = []         # current inline text buffer
        self._in_pre = False                   # inside <pre> or <code> block
        self._list_stack: list[str] = []       # "ul" / "ol" item tracking
        self._ol_counters: list[int] = []
        self._skip_tags = {"html", "body", "head"}

    # ── helpers ──────────────────────────────────────────────────────────────

    def _current_block(self) -> str:
        for t in reversed(self._tag_stack):
            if t in self._BLOCK_TAGS:
                return t
        return "p"

    def _flush(self) -> None:
        """Convert accumulated text buffer to a Flowable and clear buffer."""
        text = "".join(self._text_buf).strip()
        self._text_buf = []
        if not text:
            return

        block = self._current_block()

        # Pre / code block
        if self._in_pre or block in ("pre",):
            inner = Preformatted(text, style=_ESTILOS["code"])
            self.flowables.append(_LeftBorderBox(inner))
            return

        # Expand latex placeholders inside inline text (Rich text)
        text = self._expand_inline_latex(text)

        if block in ("h1", "h2", "h3", "h4"):
            style = _ESTILOS.get(block, _ESTILOS["p"])
            self.flowables.append(Paragraph(text, style))

        elif block == "li":
            in_ol = self._list_stack and self._list_stack[-1] == "ol"
            if in_ol:
                n = self._ol_counters[-1] if self._ol_counters else 1
                bullet = f"{n}."
            else:
                bullet = "•"
            self.flowables.append(
                Paragraph(f"{bullet}&nbsp;&nbsp;{text}", _ESTILOS["li"])
            )

        elif block == "blockquote":
            self.flowables.append(Paragraph(text, _ESTILOS["blockquote"]))

        elif block == "td" or block == "th":
            # Tables: just render as indented paragraphs for now
            style = _ESTILOS["p"]
            self.flowables.append(Paragraph(text, style))

        else:
            # Check if this text is purely a latex block placeholder
            stripped = text.strip()
            blk_match = re.fullmatch(
                rf"{_BLOCK_PLACEHOLDER}(\d+){_BLOCK_PLACEHOLDER}", stripped
            )
            if blk_match:
                expr = self._subs.get(stripped, stripped)
                self._add_block_equation(expr)
            else:
                # Normal paragraph — expand block latex placeholders too
                text = self._expand_block_latex(text)
                if text.strip():
                    self.flowables.append(Paragraph(text, _ESTILOS["p"]))

    def _expand_inline_latex(self, text: str) -> str:
        """Replace inline latex placeholders with monospace markup."""
        def repl(m: re.Match) -> str:
            key = m.group(0)
            expr = self._subs.get(key, key)
            safe = self._escape(expr)
            return f'<font name="Courier" size="9">${safe}$</font>'

        pattern = (
            rf"{re.escape(_INLINE_PLACEHOLDER_START)}\d+"
            rf"{re.escape(_INLINE_PLACEHOLDER_END)}"
        )
        return re.sub(pattern, repl, text)

    def _expand_block_latex(self, text: str) -> str:
        """Replace block latex placeholders in paragraphs."""
        pattern = (
            rf"{re.escape(_BLOCK_PLACEHOLDER)}\d+"
            rf"{re.escape(_BLOCK_PLACEHOLDER)}"
        )
        def repl(m: re.Match) -> str:
            key = m.group(0)
            expr = self._subs.get(key, key)
            safe = self._escape(expr)
            return f'<font name="Courier" size="9">$${safe}$$</font>'
        return re.sub(pattern, repl, text)

    def _add_block_equation(self, expr: str) -> None:
        safe = self._escape(expr)
        display = f"$$ {safe} $$"
        inner = Paragraph(display, _ESTILOS["ecuacion_bloque"])
        self.flowables.append(Spacer(1, 2))
        self.flowables.append(_LeftBorderBox(inner))
        self.flowables.append(Spacer(1, 2))

    @staticmethod
    def _escape(text: str) -> str:
        """Escape HTML special chars for ReportLab Paragraph markup."""
        return (text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

    # ── HTMLParser callbacks ──────────────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            return

        if tag == "hr":
            self._flush()
            self.flowables.append(
                HRFlowable(width="100%", thickness=0.5, color=_GRIS_BORDE,
                           spaceAfter=6, spaceBefore=6)
            )
            return

        if tag == "br":
            self._text_buf.append("\n")
            return

        if tag == "pre":
            self._flush()
            self._in_pre = True
            self._tag_stack.append(tag)
            return

        if tag in ("ul", "ol"):
            self._flush()
            self._list_stack.append(tag)
            if tag == "ol":
                self._ol_counters.append(0)
            self._tag_stack.append(tag)
            return

        if tag in self._BLOCK_TAGS:
            self._flush()
            self._tag_stack.append(tag)
            if tag == "li" and self._list_stack and self._list_stack[-1] == "ol":
                if self._ol_counters:
                    self._ol_counters[-1] += 1
            return

        # Inline tags: emit markup into text buffer
        if tag == "strong":
            self._text_buf.append("<b>")
        elif tag == "em":
            self._text_buf.append("<i>")
        elif tag == "code" and not self._in_pre:
            self._text_buf.append(
                '<font name="Courier" size="9" backColor="#F7F5F0">'
            )

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            return

        if tag == "pre":
            self._flush()
            self._in_pre = False
            if self._tag_stack and self._tag_stack[-1] == "pre":
                self._tag_stack.pop()
            return

        if tag in ("ul", "ol"):
            self._flush()
            if self._list_stack and self._list_stack[-1] == tag:
                self._list_stack.pop()
            if tag == "ol" and self._ol_counters:
                self._ol_counters.pop()
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
            self.flowables.append(Spacer(1, 3))
            return

        if tag in self._BLOCK_TAGS:
            self._flush()
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
            return

        # Inline close tags
        if tag == "strong":
            self._text_buf.append("</b>")
        elif tag == "em":
            self._text_buf.append("</i>")
        elif tag == "code" and not self._in_pre:
            self._text_buf.append("</font>")

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self._text_buf.append(data)
        else:
            # Escape HTML chars but preserve markup we've already added
            safe = (data
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
            self._text_buf.append(safe)

    def handle_entityref(self, name: str) -> None:
        self._text_buf.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._text_buf.append(f"&#{name};")

    def close(self) -> None:
        self._flush()
        super().close()


# ---------------------------------------------------------------------------
# Pie de página
# ---------------------------------------------------------------------------

def _make_page_template(doc: BaseDocTemplate, titulo: str) -> PageTemplate:
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="normal",
    )

    def _on_page(canvas, doc_ref):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#888780"))
        page_str = f"{titulo}  —  {doc_ref.page}"
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, page_str)
        canvas.setStrokeColor(_GRIS_BORDE)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 1.5 * cm,
                    A4[0] - doc.rightMargin, 1.5 * cm)
        canvas.restoreState()

    return PageTemplate(id="main", frames=[frame], onPage=_on_page)


# ---------------------------------------------------------------------------
# Pre-proceso del Markdown
# ---------------------------------------------------------------------------

def _preprocess_md(markdown_text: str) -> tuple[str, dict[str, str]]:
    """Strip frontmatter, protect FIGURA/TEXTO_ILEGIBLE tags, protect LaTeX."""
    # Strip YAML frontmatter
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", markdown_text.lstrip(), count=1)

    # Turn [FIGURA: ...] into italicised captions
    text = _FIGURA_RE.sub(
        lambda m: "\n\n*" + m.group(0)[1:-1] + "*\n\n", text
    )
    # Replace [TEXTO_ILEGIBLE] with a visible italic blockquote so the professor
    # can see exactly where gaps exist in the original material.
    text = _TEXTO_ILEGIBLE_RE.sub(
        "\n\n> *[Contenido no legible en el material original]*\n\n", text
    )

    # Protect LaTeX from the markdown parser
    text, subs = _protect_latex(text)
    return text, subs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generar_pdf(markdown_text: str, titulo: str = "Material docente") -> bytes:
    """Generate a structured PDF from markdown text using ReportLab.

    LaTeX equations ($$...$$  and $...$) are rendered as monospaced blocks
    with a blue left-border accent. No external rendering engine needed.

    Args:
        markdown_text: Full markdown content (output from Agente Contenido).
        titulo: Document title shown in the page footer.

    Returns:
        PDF content as bytes.

    Raises:
        RuntimeError: If the markdown library is not available.
    """
    if not _MD_AVAILABLE or _md_lib is None:
        raise RuntimeError(
            "La libreria 'markdown' no esta disponible. "
            "Instalala con: pip install markdown"
        )

    # 1. Pre-process markdown
    processed, latex_subs = _preprocess_md(markdown_text)

    # 2. Markdown → HTML
    html = _md_lib.markdown(
        processed,
        extensions=["tables", "fenced_code"],
    )

    # 3. HTML → Flowables
    parser = _MarkdownFlowableParser(latex_subs)
    parser.feed(html)
    parser.close()
    flowables = parser.flowables

    if not flowables:
        flowables = [Paragraph("(Documento vacío)", _ESTILOS["p"])]

    # 4. Build PDF with ReportLab
    buf = io.BytesIO()
    margin = 2.5 * cm
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=2.0 * cm,  # extra for footer
    )
    doc.addPageTemplates([_make_page_template(doc, titulo)])
    doc.build(flowables)

    buf.seek(0)
    return buf.read()


def generar_html_academico(markdown_text: str, titulo: str = "Material docente") -> str:
    """Fallback: return a simple HTML rendering of the markdown (no PDF).

    Uses the same preprocessing (frontmatter strip, LaTeX placeholder) but
    emits HTML instead of PDF. Provided for environments where even ReportLab
    is unavailable; not normally called since ReportLab is pure Python.

    Args:
        markdown_text: Full markdown content.
        titulo: Document title for the <title> tag.

    Returns:
        Complete HTML string.
    """
    if not _MD_AVAILABLE or _md_lib is None:
        raise RuntimeError("La libreria 'markdown' no esta disponible.")

    processed, subs = _preprocess_md(markdown_text)
    # Re-expand latex placeholders as monospace spans in HTML output
    def expand_block(m: re.Match) -> str:
        key = m.group(0)
        expr = subs.get(key, key)
        return (
            f'<div style="font-family:monospace;background:#F7F5F0;'
            f'border-left:3px solid #185FA5;padding:6px 12px;margin:8px 0;">'
            f'$$ {expr} $$</div>'
        )
    def expand_inline(m: re.Match) -> str:
        key = m.group(0)
        expr = subs.get(key, key)
        return f'<code>${expr}$</code>'

    html_body = _md_lib.markdown(processed, extensions=["tables", "fenced_code"])
    blk_pat = rf"{re.escape(_BLOCK_PLACEHOLDER)}\d+{re.escape(_BLOCK_PLACEHOLDER)}"
    inl_pat = (rf"{re.escape(_INLINE_PLACEHOLDER_START)}\d+"
               rf"{re.escape(_INLINE_PLACEHOLDER_END)}")
    html_body = re.sub(blk_pat, expand_block, html_body)
    html_body = re.sub(inl_pat, expand_inline, html_body)

    esc_titulo = titulo.replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<!DOCTYPE html><html lang='es'><head>"
        f"<meta charset='UTF-8'><title>{esc_titulo}</title>"
        "<style>body{font-family:sans-serif;max-width:860px;margin:2rem auto;"
        "padding:0 1.5rem;color:#2C2C2A;line-height:1.6}"
        "h1{color:#185FA5}h2,h3{color:#2C2C2A}"
        "code{background:#F7F5F0;padding:2px 4px;font-size:.9em}"
        "table{border-collapse:collapse;width:100%}"
        "th{background:#185FA5;color:#fff;padding:4px 8px}"
        "td{padding:4px 8px;border-bottom:1px solid #D3D1C7}</style>"
        f"</head><body><h1>{esc_titulo}</h1>{html_body}</body></html>"
    )
