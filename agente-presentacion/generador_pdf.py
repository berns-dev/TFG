"""Generacion de PDF estructurado desde Markdown usando ReportLab.

Pipeline:
  1. Strip frontmatter YAML (---...---).
  2. Parsear el Markdown con la libreria 'markdown' de Python para obtener HTML.
  3. Recorrer el HTML con html.parser y convertir cada elemento a un
     Flowable de ReportLab (Paragraph, Spacer, Preformatted, HRFlowable).
  4. Las ecuaciones LaTeX ($$...$$ e inline $...$) se renderizan como
     imagenes PNG con matplotlib (mathtext) e incrustan en el PDF.
  5. ReportLab genera el PDF en memoria y devuelve bytes.

Dependencias: reportlab, markdown, matplotlib.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
from html.parser import HTMLParser
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

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
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
)
from reportlab.platypus.flowables import Flowable

_LATEX_DPI = 150

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
# Renderizado LaTeX → PNG (matplotlib mathtext, sin LaTeX del sistema)
# ---------------------------------------------------------------------------

def _latex_figsize(latex_str: str) -> tuple[float, float]:
    """Calcula figsize dinámico según la longitud de la expresión."""
    length = len(latex_str)
    width = min(10.0, max(3.0, 3.0 + length * 0.08))
    height = min(1.5, max(0.6, 0.6 + length * 0.01))
    return width, height


def render_latex_to_image(latex_str: str) -> io.BytesIO | None:
    """Renderiza una expresión LaTeX como PNG en memoria.

    Usa matplotlib mathtext (usetex=False); no requiere LaTeX instalado.
    Retorna BytesIO posicionado en 0, o None si el parseo falla.
    """
    try:
        fig_w, fig_h = _latex_figsize(latex_str)
        fig = Figure(figsize=(fig_w, fig_h))
        fig.patch.set_alpha(0)
        FigureCanvasAgg(fig)
        fig.text(
            0.5,
            0.5,
            f"${latex_str}$",
            ha="center",
            va="center",
            fontsize=12,
        )
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=_LATEX_DPI,
            transparent=True,
            bbox_inches="tight",
            pad_inches=0.05,
        )
        buf.seek(0)
        return buf
    except Exception:
        return None


def _scale_equation_image(img: Image, max_width: float) -> None:
    """Ajusta drawWidth/drawHeight de una Image de ReportLab respetando max_width."""
    w_pt = img.imageWidth * 72.0 / _LATEX_DPI
    h_pt = img.imageHeight * 72.0 / _LATEX_DPI
    if w_pt > max_width:
        scale = max_width / w_pt
        w_pt *= scale
        h_pt *= scale
    img.drawWidth = w_pt
    img.drawHeight = h_pt


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

    def __init__(self, latex_subs: dict[str, str], max_eq_width: float):
        super().__init__()
        self._subs = latex_subs
        self._max_eq_width = max_eq_width
        self.flowables: list[Flowable] = []
        self.temp_image_paths: list[str] = []

        self._tag_stack: list[str] = []       # block tag stack
        self._text_buf: list[str] = []         # current inline text buffer
        self._in_pre = False                   # inside <pre> or <code> block
        self._list_stack: list[str] = []       # "ul" / "ol" item tracking
        self._ol_counters: list[int] = []
        self._skip_tags = {"html", "body", "head"}
        self._block_latex_pattern = (
            rf"{re.escape(_BLOCK_PLACEHOLDER)}\d+"
            rf"{re.escape(_BLOCK_PLACEHOLDER)}"
        )
        self._inline_latex_pattern = (
            rf"{re.escape(_INLINE_PLACEHOLDER_START)}\d+"
            rf"{re.escape(_INLINE_PLACEHOLDER_END)}"
        )

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
            stripped = text.strip()
            if re.fullmatch(self._block_latex_pattern, stripped):
                expr = self._subs.get(stripped, stripped)
                self._add_block_equation(expr)
            elif re.search(self._block_latex_pattern, text):
                self._emit_mixed_paragraph(text, _ESTILOS["p"])
            elif text.strip():
                self.flowables.append(Paragraph(text, _ESTILOS["p"]))

    def _save_inline_image(self, buf: io.BytesIO) -> str:
        """Persist PNG en disco temporal para <img> inline de ReportLab."""
        fd, path = tempfile.mkstemp(suffix=".png")
        os.write(fd, buf.getvalue())
        os.close(fd)
        self.temp_image_paths.append(path)
        return path

    def _inline_latex_markup(self, expr: str) -> str:
        """Sustituye LaTeX inline por <img> o texto monoespaciado de respaldo."""
        buf = render_latex_to_image(expr)
        if buf is None:
            safe = self._escape(expr)
            return f'<font name="Courier" size="9">[{safe}]</font>'

        reader = ImageReader(buf)
        iw, ih = reader.getSize()
        w_pt = iw * 72.0 / _LATEX_DPI
        h_pt = ih * 72.0 / _LATEX_DPI
        target_h = 12.0
        scale = target_h / h_pt if h_pt else 1.0
        target_w = w_pt * scale
        path = self._save_inline_image(buf)
        return (
            f'<img src="{path}" width="{target_w:.1f}" height="{target_h}" '
            f'valign="middle"/>'
        )

    def _expand_inline_latex(self, text: str) -> str:
        """Replace inline latex placeholders with rendered images or fallback."""
        def repl(m: re.Match) -> str:
            key = m.group(0)
            expr = self._subs.get(key, key)
            return self._inline_latex_markup(expr)

        return re.sub(self._inline_latex_pattern, repl, text)

    def _emit_mixed_paragraph(
        self, text: str, style: ParagraphStyle
    ) -> None:
        """Emite párrafos intercalados con bloques display de ecuaciones."""
        parts = re.split(f"({self._block_latex_pattern})", text)
        for part in parts:
            if not part or not part.strip():
                continue
            if re.fullmatch(self._block_latex_pattern, part.strip()):
                expr = self._subs.get(part.strip(), part.strip())
                self._add_block_equation(expr)
            else:
                expanded = self._expand_inline_latex(part)
                if expanded.strip():
                    self.flowables.append(Paragraph(expanded, style))

    def _add_block_equation(self, expr: str) -> None:
        buf = render_latex_to_image(expr)
        self.flowables.append(Spacer(1, 6))
        if buf is not None:
            img = Image(buf)
            _scale_equation_image(img, self._max_eq_width)
            img.hAlign = "CENTER"
            self.flowables.append(img)
        else:
            safe = self._escape(expr)
            self.flowables.append(
                Paragraph(f"[{safe}]", _ESTILOS["ecuacion_bloque"])
            )
        self.flowables.append(Spacer(1, 6))

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

    LaTeX equations ($$...$$ and $...$) are rendered as PNG images via
    matplotlib mathtext and embedded in the PDF.

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
    margin = 2.5 * cm
    max_eq_width = 0.8 * (A4[0] - 2 * margin)
    parser = _MarkdownFlowableParser(latex_subs, max_eq_width)
    parser.feed(html)
    parser.close()
    flowables = parser.flowables

    if not flowables:
        flowables = [Paragraph("(Documento vacío)", _ESTILOS["p"])]

    # 4. Build PDF with ReportLab
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=2.0 * cm,  # extra for footer
    )
    doc.addPageTemplates([_make_page_template(doc, titulo)])
    try:
        doc.build(flowables)
    finally:
        for path in parser.temp_image_paths:
            try:
                os.remove(path)
            except OSError:
                pass

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
