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
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as _pdf_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table as _Table,
)
from reportlab.platypus.flowables import Flowable
from reportlab.platypus.tables import TableStyle as _TableStyle

_LATEX_DPI = 150

# ---------------------------------------------------------------------------
# Colores de la plantilla institucional
# ---------------------------------------------------------------------------

_AZUL = colors.HexColor("#003366")          # acento institucional UO
_NEGRO = colors.HexColor("#1A1A1A")         # cuerpo de texto
_GRIS_OSCURO = colors.HexColor("#333333")   # H4 y niveles inferiores
_GRIS_FONDO = colors.HexColor("#F7F5F0")    # fondo de código/ecuación fallback
_GRIS_BORDE = colors.HexColor("#D3D1C7")
_GRIS_PIE = colors.HexColor("#666666")
_GRIS_LINEA_PIE = colors.HexColor("#CCCCCC")
_TABLA_FILA_PAR = colors.HexColor("#F5F7FA")
_FIG_FONDO = colors.HexColor("#F0F0F0")
_FIG_TEXTO = colors.HexColor("#888888")

# ---------------------------------------------------------------------------
# Fuentes: Arial del sistema si está disponible; Helvetica como fallback
# (Helvetica viene incluida en ReportLab sin dependencias)
# ---------------------------------------------------------------------------

_FUENTES = {
    "base": "Helvetica",
    "bold": "Helvetica-Bold",
    "italic": "Helvetica-Oblique",
    "bolditalic": "Helvetica-BoldOblique",
}


def _registrar_arial() -> None:
    """Registra Arial desde el sistema si las cuatro variantes existen."""
    rutas = {
        "base": ("Arial", r"C:\Windows\Fonts\arial.ttf"),
        "bold": ("Arial-Bold", r"C:\Windows\Fonts\arialbd.ttf"),
        "italic": ("Arial-Italic", r"C:\Windows\Fonts\ariali.ttf"),
        "bolditalic": ("Arial-BoldItalic", r"C:\Windows\Fonts\arialbi.ttf"),
    }
    if not all(os.path.exists(ruta) for _, ruta in rutas.values()):
        return
    try:
        for clave, (nombre, ruta) in rutas.items():
            pdfmetrics.registerFont(TTFont(nombre, ruta))
            _FUENTES[clave] = nombre
    except Exception:
        # Cualquier problema con las TTF → Helvetica, sin bloquear
        _FUENTES.update({
            "base": "Helvetica",
            "bold": "Helvetica-Bold",
            "italic": "Helvetica-Oblique",
            "bolditalic": "Helvetica-BoldOblique",
        })


_registrar_arial()

# ---------------------------------------------------------------------------
# Logo de la Universidad de Oviedo (assets/logo_uniovi.png)
# ---------------------------------------------------------------------------

_LOGO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets", "logo_uniovi.png"
)
_LOGO_FALLBACK_TEXTO = "Universidad de Oviedo | EPI Gijón"


def _cargar_logo() -> ImageReader | None:
    """ImageReader del logo si existe y es legible; None en caso contrario.

    Nunca lanza: si el logo falta o está corrupto se usa el fallback de
    texto en la cabecera. No bloquear el pipeline por este motivo.
    """
    try:
        if os.path.exists(_LOGO_PATH):
            reader = ImageReader(_LOGO_PATH)
            reader.getSize()  # valida que el PNG es legible
            return reader
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# Estilos de párrafo
# ---------------------------------------------------------------------------

_ESTILOS: dict[str, ParagraphStyle] = {
    "h1": ParagraphStyle(
        "H1",
        fontName=_FUENTES["bold"],
        fontSize=20,
        textColor=_AZUL,
        leading=26,
        spaceBefore=0,
        spaceAfter=16,
        alignment=TA_LEFT,
    ),
    "h2": ParagraphStyle(
        "H2",
        fontName=_FUENTES["bold"],
        fontSize=14,
        textColor=_AZUL,
        leading=18,
        spaceBefore=20,
        spaceAfter=2,  # la línea separadora aporta los 8pt restantes
        alignment=TA_LEFT,
    ),
    "h3": ParagraphStyle(
        "H3",
        fontName=_FUENTES["bold"],
        fontSize=11.5,
        textColor=_NEGRO,
        leading=15,
        spaceBefore=14,
        spaceAfter=6,
        alignment=TA_LEFT,
    ),
    "h4": ParagraphStyle(
        "H4",
        fontName=_FUENTES["bolditalic"],
        fontSize=10.5,
        textColor=_GRIS_OSCURO,
        leading=13,
        spaceBefore=10,
        spaceAfter=4,
        alignment=TA_LEFT,
    ),
    "p": ParagraphStyle(
        "Normal",
        fontName=_FUENTES["base"],
        fontSize=10.5,
        textColor=_NEGRO,
        leading=14.7,  # interlineado 1.4
        spaceBefore=0,
        spaceAfter=8,
        alignment=TA_JUSTIFY,
    ),
    "li": ParagraphStyle(
        "ListItem",
        fontName=_FUENTES["base"],
        fontSize=10.5,
        textColor=_NEGRO,
        leading=14.7,
        spaceBefore=0,
        spaceAfter=3,
        leftIndent=0.5 * cm,
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
    "blockquote": ParagraphStyle(
        "Blockquote",
        fontName=_FUENTES["italic"],
        fontSize=10,
        textColor=_GRIS_OSCURO,
        leading=14,
        leftIndent=20,
        spaceBefore=4,
        spaceAfter=4,
    ),
}


# ---------------------------------------------------------------------------
# Placeholder de figura ([FIGURA: ...])
# ---------------------------------------------------------------------------

class _FiguraPlaceholder(Flowable):
    """Rectángulo gris con la descripción de la figura del material original."""

    _ALTURA = 60

    def __init__(self, descripcion: str):
        super().__init__()
        self._descripcion = descripcion.strip()
        self.height = self._ALTURA

    def wrap(self, avail_w: float, avail_h: float):
        self.width = avail_w
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(_FIG_FONDO)
        c.setStrokeColor(_GRIS_LINEA_PIE)
        c.setLineWidth(0.5)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=1)

        c.setFillColor(_GRIS_PIE)
        c.setFont(_FUENTES["italic"], 9)
        c.drawCentredString(self.width / 2, self.height - 18, "[Figura]")

        if self._descripcion:
            c.setFillColor(_FIG_TEXTO)
            c.setFont(_FUENTES["base"], 8.5)
            lineas = simpleSplit(
                self._descripcion, _FUENTES["base"], 8.5, self.width - 24
            )[:2]
            y = self.height - 34
            for linea in lineas:
                c.drawCentredString(self.width / 2, y, linea)
                y -= 12


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
_FIGURA_RE = re.compile(r"\[FIGURA:\s*([^\]]*)\]")
_TEXTO_ILEGIBLE_RE = re.compile(r"\[TEXTO_ILEGIBLE\]")
_FRONTMATTER_RE = re.compile(r"^---\n([\s\S]*?)\n---\n")
_TEMA_DETECTADO_RE = re.compile(r"^tema_detectado:\s*(.+)$", re.MULTILINE)
_H1_MD_RE = re.compile(r"^#\s+(?!#)(.+)$", re.MULTILINE)

_FIGURA_PLACEHOLDER = "XXFIGPLHXX"


def _extraer_asignatura(markdown_text: str, fallback: str) -> str:
    """Nombre de la asignatura: tema_detectado del frontmatter, o el H1.

    Args:
        markdown_text: Markdown completo, con frontmatter si existe.
        fallback: Valor si no hay ni frontmatter ni H1 (p. ej. el título).
    """
    m_fm = _FRONTMATTER_RE.match(markdown_text.lstrip())
    if m_fm:
        m = _TEMA_DETECTADO_RE.search(m_fm.group(1))
        if m:
            return m.group(1).strip()
    m = _H1_MD_RE.search(markdown_text)
    if m:
        return m.group(1).strip()
    return fallback

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

    def __init__(
        self,
        latex_subs: dict[str, str],
        content_width: float,
        figura_subs: dict[str, str] | None = None,
    ):
        super().__init__()
        self._subs = latex_subs
        self._figura_subs = figura_subs or {}
        self._content_width = content_width
        # Ecuaciones display: máximo 70% de la columna de texto, centradas
        self._max_eq_width = 0.7 * content_width
        self._h2_visto = False
        self.flowables: list[Flowable] = []
        self.temp_image_paths: list[str] = []

        self._tag_stack: list[str] = []       # block tag stack
        self._text_buf: list[str] = []         # current inline text buffer
        self._in_pre = False                   # inside <pre> or <code> block
        self._list_stack: list[str] = []       # "ul" / "ol" item tracking
        self._ol_counters: list[int] = []
        self._skip_tags = {"html", "body", "head"}

        # Table state
        self._table_data: list[list[str]] = []
        self._table_has_header: list[bool] = []
        self._current_row_cells: list[str] = []
        self._current_row_is_header = False
        self._current_cell_parts: list[str] = []
        self._in_cell = False
        self._block_latex_pattern = (
            rf"{re.escape(_BLOCK_PLACEHOLDER)}\d+"
            rf"{re.escape(_BLOCK_PLACEHOLDER)}"
        )
        self._inline_latex_pattern = (
            rf"{re.escape(_INLINE_PLACEHOLDER_START)}\d+"
            rf"{re.escape(_INLINE_PLACEHOLDER_END)}"
        )
        self._figura_pattern = (
            rf"{re.escape(_FIGURA_PLACEHOLDER)}\d+"
            rf"{re.escape(_FIGURA_PLACEHOLDER)}"
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
            if block == "h2":
                # Salto de página antes de cada H2 excepto el primero,
                # y línea separadora institucional debajo del título.
                if self._h2_visto:
                    self.flowables.append(PageBreak())
                self._h2_visto = True
                self.flowables.append(Paragraph(text, _ESTILOS["h2"]))
                self.flowables.append(
                    HRFlowable(
                        width="100%",
                        thickness=1,
                        color=_AZUL,
                        spaceBefore=0,
                        spaceAfter=8,
                    )
                )
            else:
                style = _ESTILOS.get(block, _ESTILOS["p"])
                self.flowables.append(Paragraph(text, style))

        elif block == "li":
            in_ol = self._list_stack and self._list_stack[-1] == "ol"
            if in_ol:
                n = self._ol_counters[-1] if self._ol_counters else 1
                bullet = f'<font color="#003366">{n}.</font>'
            else:
                bullet = '<font color="#003366">•</font>'
            self.flowables.append(
                Paragraph(f"{bullet}&nbsp;&nbsp;{text}", _ESTILOS["li"])
            )

        elif block == "blockquote":
            self.flowables.append(Paragraph(text, _ESTILOS["blockquote"]))

        elif block in ("td", "th"):
            if self._in_cell and text:
                self._current_cell_parts.append(text)

        else:
            stripped = text.strip()
            if re.fullmatch(self._figura_pattern, stripped):
                descripcion = self._figura_subs.get(stripped, "")
                self.flowables.append(Spacer(1, 10))
                self.flowables.append(_FiguraPlaceholder(descripcion))
                self.flowables.append(Spacer(1, 10))
            elif re.fullmatch(self._block_latex_pattern, stripped):
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

    def _build_table(self) -> None:
        """Build a ReportLab Table from accumulated rows and add to flowables."""
        if not self._table_data:
            return

        num_cols = max(len(row) for row in self._table_data)
        if num_cols == 0:
            return

        # Ancho: 100% de la columna de texto disponible
        col_width = self._content_width / num_cols
        col_widths = [col_width] * num_cols

        _hdr_style = ParagraphStyle(
            "TblHdr",
            fontName=_FUENTES["bold"],
            fontSize=9.5,
            textColor=colors.white,
            leading=12,
        )
        _cell_style = ParagraphStyle(
            "TblCell",
            fontName=_FUENTES["base"],
            fontSize=9.5,
            textColor=_NEGRO,
            leading=12,
        )

        table_content = []
        for row_idx, row in enumerate(self._table_data):
            is_hdr = (row_idx < len(self._table_has_header)
                      and self._table_has_header[row_idx])
            style = _hdr_style if is_hdr else _cell_style
            padded = list(row) + [""] * (num_cols - len(row))
            table_content.append(
                [Paragraph(cell or "&nbsp;", style) for cell in padded[:num_cols]]
            )

        style_cmds: list = [
            ("INNERGRID", (0, 0), (-1, -1), 0.4, _GRIS_LINEA_PIE),
            ("BOX", (0, 0), (-1, -1), 0.75, _AZUL),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        fila_datos = 0
        for row_idx, is_hdr in enumerate(self._table_has_header):
            if is_hdr:
                style_cmds.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), _AZUL)
                )
            else:
                fila_datos += 1
                if fila_datos % 2 == 0:  # filas pares: #F5F7FA
                    style_cmds.append(
                        ("BACKGROUND", (0, row_idx), (-1, row_idx),
                         _TABLA_FILA_PAR)
                    )

        # repeatRows: la cabecera se repite en cada página (cubre el caso
        # exigido de tablas con más de 15 filas)
        num_header_rows = sum(1 for h in self._table_has_header if h)
        tbl = _Table(table_content, colWidths=col_widths,
                     repeatRows=num_header_rows)
        tbl.setStyle(_TableStyle(style_cmds))
        self.flowables.append(Spacer(1, 8))
        self.flowables.append(tbl)
        self.flowables.append(Spacer(1, 8))

    def _add_block_equation(self, expr: str) -> None:
        buf = render_latex_to_image(expr)
        self.flowables.append(Spacer(1, 14))
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
        self.flowables.append(Spacer(1, 14))

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
            if not self._list_stack:  # solo la lista exterior añade espacio
                self.flowables.append(Spacer(1, 6))
            self._list_stack.append(tag)
            if tag == "ol":
                self._ol_counters.append(0)
            self._tag_stack.append(tag)
            return

        # Table-specific handlers — must come before the generic _BLOCK_TAGS branch
        if tag == "table":
            self._flush()
            self._table_data = []
            self._table_has_header = []
            self._tag_stack.append(tag)
            return

        if tag == "tr":
            self._flush()
            self._current_row_cells = []
            self._current_row_is_header = False
            self._tag_stack.append(tag)
            return

        if tag in ("th", "td"):
            self._flush()
            self._in_cell = True
            self._current_cell_parts = []
            if tag == "th":
                self._current_row_is_header = True
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
            if not self._list_stack:  # cierre de la lista exterior
                self.flowables.append(Spacer(1, 6))
            return

        # Table-specific handlers — must come before the generic _BLOCK_TAGS branch
        if tag in ("td", "th"):
            self._flush()
            cell_text = " ".join(self._current_cell_parts).strip()
            self._current_row_cells.append(cell_text)
            self._current_cell_parts = []
            self._in_cell = False
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
            return

        if tag == "tr":
            self._flush()
            if self._current_row_cells:
                self._table_data.append(list(self._current_row_cells))
                self._table_has_header.append(self._current_row_is_header)
            self._current_row_cells = []
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
            return

        if tag == "table":
            self._flush()
            if self._table_data:
                self._build_table()
            self._table_data = []
            self._table_has_header = []
            if self._tag_stack and self._tag_stack[-1] == tag:
                self._tag_stack.pop()
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
# Cabecera (todas las páginas) y pie de página con total real (NumberedCanvas)
# ---------------------------------------------------------------------------

_CABECERA_ALTO = 1.5 * cm  # altura reservada desde el borde superior


def _dibujar_cabecera(canvas, doc: BaseDocTemplate) -> None:
    """Cabecera institucional: logo UO (o fallback de texto) + asignatura.

    El logo se dibuja con altura 1.25cm preservando proporción. Si el
    archivo no está disponible o falla su lectura, fallback de texto —
    nunca se lanza una excepción por este motivo.
    """
    canvas.saveState()
    borde_inferior = A4[1] - _CABECERA_ALTO

    logo = _cargar_logo()
    if logo is not None:
        try:
            iw, ih = logo.getSize()
            alto = 1.25 * cm
            ancho = iw * alto / ih if ih else alto
            canvas.drawImage(
                logo,
                doc.leftMargin,
                borde_inferior + 0.1 * cm,
                width=ancho,
                height=alto,
                mask="auto",
            )
        except Exception:
            logo = None
    if logo is None:
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_AZUL)
        canvas.drawString(
            doc.leftMargin, borde_inferior + 0.45 * cm, _LOGO_FALLBACK_TEXTO
        )

    canvas.setFont("Helvetica", 10)
    canvas.setFillColor(_AZUL)
    canvas.drawRightString(
        A4[0] - doc.rightMargin,
        borde_inferior + 0.45 * cm,
        doc._asignatura_pdf,
    )

    canvas.setStrokeColor(_AZUL)
    canvas.setLineWidth(1.5)
    canvas.line(doc.leftMargin, borde_inferior,
                A4[0] - doc.rightMargin, borde_inferior)
    canvas.restoreState()


def _make_page_template(doc: BaseDocTemplate) -> PageTemplate:
    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="normal",
    )

    def _on_page(canvas, doc_ref):
        # Cabecera institucional en TODAS las páginas, incluida la primera.
        # El pie lo dibuja _NumberedCanvas en save() para conocer el total.
        _dibujar_cabecera(canvas, doc)

    return PageTemplate(id="main", frames=[frame], onPage=_on_page)


def _numbered_canvas_factory(
    asignatura: str, left_margin: float, right_margin: float
):
    """Canvas de dos fases: difiere el pie hasta conocer el total de páginas.

    Patrón NumberedCanvas estándar de ReportLab: showPage() acumula el
    estado de cada página; save() las reemite dibujando el pie
    "[asignatura] | Universidad de Oviedo | Página X de N" con el N real.
    Nunca se muestra "?" como total.
    """

    class _NumberedCanvas(_pdf_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_states: list[dict] = []

        def showPage(self):  # noqa: N802 (API de ReportLab)
            self._saved_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved_states)
            for state in self._saved_states:
                self.__dict__.update(state)
                self._dibujar_pie(total)
                super().showPage()
            super().save()

        def _dibujar_pie(self, total: int) -> None:
            self.saveState()
            self.setStrokeColor(_GRIS_LINEA_PIE)
            self.setLineWidth(0.5)
            self.line(left_margin, 1.5 * cm, A4[0] - right_margin, 1.5 * cm)
            self.setFont("Helvetica", 8)
            self.setFillColor(_GRIS_PIE)
            self.drawCentredString(
                A4[0] / 2,
                1.1 * cm,
                f"{asignatura} | Universidad de Oviedo | "
                f"Página {self._pageNumber} de {total}",
            )
            self.restoreState()

    return _NumberedCanvas


# ---------------------------------------------------------------------------
# Pre-proceso del Markdown
# ---------------------------------------------------------------------------

def _strip_frontmatter(markdown_text: str) -> str:
    """Elimina por completo el bloque frontmatter YAML inicial (--- ... ---).

    Robusto frente a CRLF/LF y espacios finales en las líneas delimitadoras,
    para que ningún campo YAML del Agente Contenido (archivo_origen,
    tipo_documento, tema_detectado, idioma, fecha_procesado,
    compatible_agente_organizador) llegue a renderizarse en el PDF. Si no hay
    frontmatter, el texto se devuelve intacto y el H1 sigue siendo lo primero.
    """
    candidato = markdown_text.lstrip()
    m = re.match(
        r"---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)",
        candidato,
    )
    if m:
        return candidato[m.end():]
    return markdown_text


def _preprocess_md(
    markdown_text: str,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Strip frontmatter, protect FIGURA/TEXTO_ILEGIBLE tags, protect LaTeX."""
    # Strip YAML frontmatter (robusto a CRLF/LF; ver _strip_frontmatter)
    text = _strip_frontmatter(markdown_text)

    # [FIGURA: ...] → token; el parser lo convierte en _FiguraPlaceholder
    figura_subs: dict[str, str] = {}

    def repl_figura(m: re.Match) -> str:
        key = f"{_FIGURA_PLACEHOLDER}{len(figura_subs)}{_FIGURA_PLACEHOLDER}"
        figura_subs[key] = m.group(1).strip()
        return f"\n\n{key}\n\n"

    text = _FIGURA_RE.sub(repl_figura, text)
    text = re.sub(r"\[ECUACION_PARCIAL:[^\]]+\]", "", text)
    text = re.sub(r"\[ECUACION\]", "", text)
    # Replace [TEXTO_ILEGIBLE] with a visible italic blockquote so the professor
    # can see exactly where gaps exist in the original material.
    text = _TEXTO_ILEGIBLE_RE.sub(
        "\n\n> *[Contenido no legible en el material original]*\n\n", text
    )

    # Protect LaTeX from the markdown parser
    text, subs = _protect_latex(text)
    return text, subs, figura_subs


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
    if not _MD_AVAILABLE:
        raise RuntimeError(
            "El paquete 'markdown' no está disponible. "
            "Verifica que está incluido en requirements.txt e instalado en el entorno."
        )

    if not (markdown_text or "").strip():
        raise ValueError("El markdown está vacío — no hay contenido para exportar a PDF.")

    # 1. Pre-process markdown (antes del strip: la asignatura sale del
    #    frontmatter tema_detectado, o del H1 si no hay metadata)
    asignatura = _extraer_asignatura(markdown_text, titulo)
    processed, latex_subs, figura_subs = _preprocess_md(markdown_text)

    # 2. Markdown → HTML
    html = _md_lib.markdown(
        processed,
        extensions=["tables", "fenced_code"],
    )

    # 3. HTML → Flowables
    margen_izq = 2.5 * cm
    margen_der = 2.0 * cm
    content_width = A4[0] - margen_izq - margen_der
    parser = _MarkdownFlowableParser(latex_subs, content_width, figura_subs)
    parser.feed(html)
    parser.close()
    flowables = parser.flowables

    if not flowables:
        raise ValueError(
            "No se pudo extraer contenido del markdown para generar el PDF."
        )

    # 4. Build PDF with ReportLab
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=margen_izq,
        rightMargin=margen_der,
        topMargin=2.5 * cm,
        bottomMargin=2.0 * cm,
        title=asignatura,
        author="Universidad de Oviedo",
    )
    doc._asignatura_pdf = asignatura  # leído por _dibujar_cabecera
    doc.addPageTemplates([_make_page_template(doc)])
    try:
        doc.build(
            flowables,
            canvasmaker=_numbered_canvas_factory(
                asignatura, margen_izq, margen_der
            ),
        )
    finally:
        for path in parser.temp_image_paths:
            try:
                os.remove(path)
            except OSError:
                pass

    buf.seek(0)
    return buf.read()
