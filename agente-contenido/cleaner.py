"""Limpieza determinista de texto extraido desde PDF/PPTX."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

# Logger de módulo: permite activar nivel INFO en despliegue sin prints acoplados a Streamlit,
# y auditar líneas borradas por frecuencia sin cambiar la lógica de limpieza.
_LOGGER = logging.getLogger(__name__)


def _ensure_cleaner_audit_handler() -> None:
    """
    Un handler explícito a stderr: en Streamlit el root logger suele quedar en WARNING
    y los mensajes INFO no serían visibles para auditar el cleaner sin tocar config global.
    Idempotente para no duplicar handlers en recargas del mismo proceso.
    """
    if _LOGGER.handlers:
        return
    _LOGGER.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.propagate = False


_ensure_cleaner_audit_handler()

_BOUNDARY_RE = re.compile(r"(?=^\[(?:PAGINA|SLIDE)\s+\d+\])", re.MULTILINE)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*$")
_FILLER_RE = re.compile(r"^\s*[-–—=_\.·•]{3,}\s*$")
_URL_ONLY_RE = re.compile(r"^\s*https?://\S+\s*$", flags=re.IGNORECASE)
_SLIDE_META_RE = re.compile(r"^\s*(?:Slide|Diapositiva)\s+\d+\s*$", flags=re.IGNORECASE)
_MARKER_RE = re.compile(r"^\s*\[(?:PAGINA|SLIDE)\s+\d+\]\s*$")
_UNIT_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|[kMGT]?W|[kMGT]?Pa|bar|psi|kg|g|mg|m|cm|mm|km|s|min|h|Hz|N|J|V|A|K|C)\b", re.IGNORECASE)
_MULTISPACE_RE = re.compile(r"(\S)[ \t]{2,}(\S)")
_MULTINEWLINES_RE = re.compile(r"\n{3,}")
_EQ_EXPR_RE = re.compile(r"=\s*\S")
_DIGIT_LETTER_RE = re.compile(r"(?i)(?:\d+\s*[a-záéíóúñ]|[a-záéíóúñ]+\s*\d+)")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ0-9]+")
_HEADING_PREFIX_RE = re.compile(r"^#{1,4}\s+\S")
_EQUATION_MARKER_RE = re.compile(
    r"^\[(?:ECUACION_PARCIAL|ECUACION_NO_EXTRAIBLE|TEXTO_ILEGIBLE)\b"
)
_MATH_CORRUPT_RE = re.compile(r"[ð¼½¾¿¡»›þÿ]|[^\x00-\x7F].*[^\x00-\x7F].*[^\x00-\x7F]")
_SALVAGE_TOKEN_RE = re.compile(
    r"^[\d.,+\-*/=^_{}\\()]+$|^[A-Za-zÀ-ÿ]{1,4}$|^\d+(?:[.,]\d+)?\s*(?:%|[kMGT]?W|[kMGT]?Pa|bar|psi|kg|g|mg|m|cm|mm|km|s|min|h|Hz|N|J|V|A|K|°C|°)$",
    re.IGNORECASE,
)


def _is_markdown_heading(line: str) -> bool:
    return bool(_HEADING_PREFIX_RE.match(line.strip()))


def _is_technical_line(line: str) -> bool:
    if "\t" in line or "|" in line:
        return True
    if "$" in line:
        return True
    lowered = line.lower()
    if "\\frac" in lowered or "\\int" in lowered or "\\sum" in lowered:
        return True
    if _EQ_EXPR_RE.search(line):
        return True
    if _UNIT_RE.search(line):
        return True
    return False


def _split_sections(clean: str) -> list[str]:
    if re.search(r"^\[(?:PAGINA|SLIDE)\s+\d+\]", clean, flags=re.MULTILINE):
        return [s.strip() for s in _BOUNDARY_RE.split(clean) if s.strip()]
    return [clean]


def _is_glyph_soup_line(line: str) -> bool:
    """Linea compuesta solo por tokens de 1-2 caracteres (cabecera PPT exportada)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _is_markdown_heading(stripped) or _EQUATION_MARKER_RE.match(stripped):
        return False
    if any(ch in stripped for ch in "=$#|"):
        return False
    if _is_technical_line(stripped):
        return False
    tokens = stripped.split()
    if not tokens:
        return False
    return all(len(tok) <= 2 for tok in tokens)


def _compute_repeated_glyph_lines(
    sections: list[str],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """
    Glifos de cabecera repetidos en >= 80% de secciones [PAGINA]/[SLIDE].

    Solo candidatas lineas 100% tokenizadas en trozos de 1-2 caracteres.
    """
    total = len(sections)
    if total < 2:
        return set(), {}
    counts: dict[str, int] = {}
    for section in sections:
        seen_in_section: set[str] = set()
        for raw_line in section.split("\n"):
            line = raw_line.strip()
            if _MARKER_RE.match(line) or not _is_glyph_soup_line(line):
                continue
            seen_in_section.add(line)
        for line in seen_in_section:
            counts[line] = counts.get(line, 0) + 1

    noise_lines: set[str] = set()
    detail: dict[str, dict[str, Any]] = {}
    for line, count in counts.items():
        if count * 5 < total * 4:
            continue
        key = line.lower()
        noise_lines.add(key)
        detail[key] = {
            "count": count,
            "ratio": count / total,
            "sections_total": total,
            "example": line,
        }
    return noise_lines, detail


def _should_preserve_from_frequency(line: str) -> bool:
    if _is_markdown_heading(line):
        return True
    if _EQUATION_MARKER_RE.match(line.strip()):
        return True
    if _DIGIT_LETTER_RE.search(line):
        return True
    words = {w.lower() for w in _WORD_RE.findall(line)}
    if len(words) > 3:
        return True
    if any(ch in line for ch in (":", ",", ";", "(", ")")):
        return True
    return False


def _compute_structural_noise(
    sections: list[str], filename: str = ""
) -> tuple[set[str], dict[str, dict[str, Any]], str]:
    """
    Calcula líneas candidatas a ruido estructural (repetidas en la mayoría de secciones).

    Devuelve también `frequency_detail` indexado por línea en minúsculas: al borrar,
    registramos ratio = apariciones_en_secciones_distintas / total_secciones sin tocar
    el umbral (sigue siendo count > total * 0.60), solo hacemos visible el criterio.
    """
    total = len(sections)
    if total == 0:
        return set(), {}, ""
    stem_lower = Path(filename).stem.strip().lower() if filename else ""
    counts: dict[str, int] = {}
    for section in sections:
        seen_in_section: set[str] = set()
        for raw_line in section.split("\n"):
            line = raw_line.strip()
            if (
                not line
                or len(line) > 60
                or _MARKER_RE.match(line)
                or _is_markdown_heading(line)
                or _is_technical_line(line)
                or _should_preserve_from_frequency(line)
            ):
                continue
            seen_in_section.add(line)
        for line in seen_in_section:
            counts[line] = counts.get(line, 0) + 1

    threshold = total * 0.60
    noise_lines: set[str] = set()
    frequency_detail: dict[str, dict[str, Any]] = {}
    for line, count in counts.items():
        if count > threshold:
            key = line.lower()
            noise_lines.add(key)
            frequency_detail[key] = {
                "count": count,
                "ratio": count / total,
                "sections_total": total,
                "threshold_exclusive": threshold,
                "example": line,
            }
    if stem_lower:
        noise_lines.add(stem_lower)
    return noise_lines, frequency_detail, stem_lower


def _is_equation_shard_line(line: str) -> bool:
    """Detecta fragmentos de ecuación rotos (fuentes Symbol/Math en PDF exportado)."""
    stripped = line.strip()
    if not stripped or _is_markdown_heading(stripped) or _EQUATION_MARKER_RE.match(stripped):
        return False
    if _is_technical_line(stripped) and _EQ_EXPR_RE.search(stripped):
        words = [w for w in _WORD_RE.findall(stripped) if len(w) > 3]
        if len(words) >= 2:
            return False
    tokens = stripped.split()
    if len(tokens) < 4:
        return False
    short_tokens = sum(1 for t in tokens if len(t) <= 2)
    long_words = sum(1 for t in tokens if len(t) > 6 and t.isalpha())
    if long_words >= 2:
        return False
    if short_tokens / len(tokens) >= 0.55:
        return True
    if _MATH_CORRUPT_RE.search(stripped) and short_tokens >= 3:
        return True
    spaced_letters = re.findall(r"\b[A-Za-záéíóúñ]\s+[A-Za-záéíóúñ]\s+[A-Za-záéíóúñ]", stripped)
    if len(spaced_letters) >= 2:
        return True
    return False


def _salvage_equation_line(line: str) -> str:
    """Conserva símbolos/números legibles de una ecuación corrupta."""
    tokens = line.split()
    kept: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        candidate = tok.strip(".,;:")
        if not candidate or candidate in seen:
            continue
        if _SALVAGE_TOKEN_RE.match(candidate):
            kept.append(candidate)
            seen.add(candidate)
        elif len(candidate) == 1 and candidate.isalpha():
            kept.append(candidate)
            seen.add(candidate)
    snippet = " ".join(kept[:48]).strip()
    if len(snippet) >= 2:
        return f"[ECUACION_PARCIAL: {snippet}]"
    return "[ECUACION_NO_EXTRAIBLE]"


def clean_extracted_text(text: str, filename: str = "", *, light: bool = False) -> str:
    """Elimina ruido tipico de OCR/extraccion manteniendo contenido tecnico.

    ``light=True``: regex (pies, URLs, rellenos) + filtro de glifos de cabecera
    repetidos (tokens 1-2 chars en >= 80% de paginas); sin frecuencia estructural
    general. Pensado para extraccion PDF enriquecida con prefijos #/##/###.
    """
    _ensure_cleaner_audit_handler()
    chars_entrada = len(text or "")
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not clean.strip():
        _LOGGER.info("[CLEANER] Entrada: %s chars → Salida: 0 chars", chars_entrada)
        _LOGGER.info("[CLEANER] Líneas eliminadas por frecuencia: 0")
        _LOGGER.info("[CLEANER] Líneas eliminadas por glifos: 0")
        _LOGGER.info("[CLEANER] Líneas eliminadas por regex: 0")
        return ""

    sections = _split_sections(clean)
    repeated_glyph_lines: set[str] = set()
    glyph_detail: dict[str, dict[str, Any]] = {}
    if light:
        structural_noise_lines: set[str] = set()
        frequency_detail: dict[str, dict[str, Any]] = {}
        stem_lower = Path(filename).stem.strip().lower() if filename else ""
        repeated_glyph_lines, glyph_detail = _compute_repeated_glyph_lines(sections)
        if repeated_glyph_lines:
            _LOGGER.info(
                "[CLEANER] Modo ligero: %s lineas de glifos repetidos (>=80%% paginas)",
                len(repeated_glyph_lines),
            )
        else:
            _LOGGER.info("[CLEANER] Modo ligero (sin filtro de frecuencia estructural)")
    else:
        structural_noise_lines, frequency_detail, stem_lower = _compute_structural_noise(
            sections, filename=filename
        )
    cleaned_lines: list[str] = []
    n_eliminadas_frecuencia = 0
    n_eliminadas_regex = 0
    n_eliminadas_glifos = 0

    for raw_line in clean.split("\n"):
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue

        if _MARKER_RE.match(line):
            cleaned_lines.append(line)
            continue

        is_technical = _is_technical_line(line)

        should_drop = False
        if not is_technical:
            if _PAGE_NUMBER_RE.match(line):
                should_drop = True
                n_eliminadas_regex += 1
            elif _FILLER_RE.match(line):
                should_drop = True
                n_eliminadas_regex += 1
            elif _URL_ONLY_RE.match(line):
                should_drop = True
                n_eliminadas_regex += 1
            elif _SLIDE_META_RE.match(line):
                should_drop = True
                n_eliminadas_regex += 1
            elif (
                light
                and not _is_markdown_heading(line)
                and line.lower() in repeated_glyph_lines
            ):
                should_drop = True
                n_eliminadas_glifos += 1
                lk = line.lower()
                meta = glyph_detail.get(lk)
                if meta is not None:
                    _LOGGER.info(
                        "Eliminada por glifos repetidos: ratio=%.4f (%d/%d secciones); "
                        "repr=%r ejemplo=%r",
                        float(meta["ratio"]),
                        int(meta["count"]),
                        int(meta["sections_total"]),
                        line,
                        meta["example"],
                    )
            elif (
                not light
                and not _is_markdown_heading(line)
                and len(line) <= 60
                and line.lower() in structural_noise_lines
            ):
                should_drop = True
                n_eliminadas_frecuencia += 1
                lk = line.lower()
                meta = frequency_detail.get(lk)
                if meta is not None:
                    # ratio = veces que la línea aparece en secciones distintas / total de secciones
                    _LOGGER.info(
                        "Eliminada por frecuencia estructural: ratio=%.4f (%d/%d secciones); "
                        "umbral estricto count > %.3f (total*0.60). repr línea actual=%r ejemplo_canónico=%r",
                        float(meta["ratio"]),
                        int(meta["count"]),
                        int(meta["sections_total"]),
                        float(meta["threshold_exclusive"]),
                        line,
                        meta["example"],
                    )
                elif stem_lower and lk == stem_lower:
                    _LOGGER.info(
                        "Eliminada por coincidencia con stem del nombre de archivo (regla "
                        "adicional al conteo por sección): repr=%r stem=%r",
                        line,
                        stem_lower,
                    )
                else:
                    _LOGGER.info(
                        "Eliminada por conjunto de ruido estructural sin metadatos de "
                        "frecuencia (caso residual): repr=%r",
                        line,
                    )

        if should_drop:
            continue

        if _is_equation_shard_line(line):
            normalized = _salvage_equation_line(line)
        else:
            normalized = _MULTISPACE_RE.sub(r"\1 \2", line)
        cleaned_lines.append(normalized)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = _MULTINEWLINES_RE.sub("\n\n", cleaned_text)
    resultado = cleaned_text.strip()
    _LOGGER.info(
        "[CLEANER] Entrada: %s chars → Salida: %s chars", chars_entrada, len(resultado)
    )
    _LOGGER.info("[CLEANER] Líneas eliminadas por frecuencia: %s", n_eliminadas_frecuencia)
    _LOGGER.info("[CLEANER] Líneas eliminadas por glifos: %s", n_eliminadas_glifos)
    _LOGGER.info("[CLEANER] Líneas eliminadas por regex: %s", n_eliminadas_regex)
    return resultado
