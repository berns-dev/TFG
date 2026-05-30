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


def _should_preserve_from_frequency(line: str) -> bool:
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


def clean_extracted_text(text: str, filename: str = "") -> str:
    """Elimina ruido tipico de OCR/extraccion manteniendo contenido tecnico."""
    _ensure_cleaner_audit_handler()
    chars_entrada = len(text or "")
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not clean.strip():
        _LOGGER.info("[CLEANER] Entrada: %s chars → Salida: 0 chars", chars_entrada)
        _LOGGER.info("[CLEANER] Líneas eliminadas por frecuencia: 0")
        _LOGGER.info("[CLEANER] Líneas eliminadas por regex: 0")
        return ""

    sections = _split_sections(clean)
    structural_noise_lines, frequency_detail, stem_lower = _compute_structural_noise(
        sections, filename=filename
    )
    cleaned_lines: list[str] = []
    n_eliminadas_frecuencia = 0
    n_eliminadas_regex = 0

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
            elif len(line) <= 60 and line.lower() in structural_noise_lines:
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

        normalized = _MULTISPACE_RE.sub(r"\1 \2", line)
        cleaned_lines.append(normalized)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = _MULTINEWLINES_RE.sub("\n\n", cleaned_text)
    resultado = cleaned_text.strip()
    _LOGGER.info(
        "[CLEANER] Entrada: %s chars → Salida: %s chars", chars_entrada, len(resultado)
    )
    _LOGGER.info("[CLEANER] Líneas eliminadas por frecuencia: %s", n_eliminadas_frecuencia)
    _LOGGER.info("[CLEANER] Líneas eliminadas por regex: %s", n_eliminadas_regex)
    return resultado
