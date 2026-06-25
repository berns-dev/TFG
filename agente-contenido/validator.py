"""Verificacion de fidelidad post-procesado."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from cnt_config import FIDELITY_THRESHOLD

_MONOREPO_ROOT = Path(__file__).resolve().parent.parent
if str(_MONOREPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_MONOREPO_ROOT))

from shared.text_utils import normalize_for_matching  # noqa: E402

_STOPWORDS = {
    "para",
    "entre",
    "desde",
    "hasta",
    "sobre",
    "como",
    "donde",
    "cuando",
    "porque",
    "segun",
    "esto",
    "esta",
    "estas",
    "estos",
    "tambien",
    "puede",
    "pueden",
    "deber",
    "deben",
    "tener",
    "tiene",
    "their",
    "with",
    "from",
    "that",
    "this",
    "pagina",
    "slide",
}

# Marcadores estructurales/internos que el agente omite a propósito en el output
_STRUCTURAL_MARKER_RE = re.compile(
    r"\[(?:PAGINA|SLIDE)\s+\d+\]|\[TEXTO_ILEGIBLE\]|\[FIGURA[^\]]*\]"
    r"|\[ECUACION_PARCIAL:[^\]]*\]|\[ECUACION_NO_EXTRAIBLE\]|\[ECUACION_RECONSTRUIDA:[^\]]*\]",
    re.IGNORECASE,
)


def extract_key_terms(text: str) -> list[str]:
    """Extrae terminos alfanumericos relevantes (len > 4, sin stopwords)."""
    tokens = re.findall(r"[A-Za-z0-9_À-ÿ]+", text or "")
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        norm = normalize_for_matching(token)
        if len(norm) <= 4 or norm in _STOPWORDS:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        terms.append(token)
    return terms


def _term_present_in_output(term: str, output_norm: str) -> bool:
    """Comprueba presencia del término en el output con normalización simétrica."""
    term_norm = normalize_for_matching(term)
    if not term_norm or len(term_norm) <= 4:
        return True
    if term_norm in output_norm:
        return True
    # Subcadena sin espacios (p. ej. guión tipográfico partido en el PDF)
    compact_out = output_norm.replace(" ", "")
    compact_term = term_norm.replace(" ", "")
    return bool(compact_term and compact_term in compact_out)


def validate_fidelity(original_chunk: str, markdown_output: str) -> dict[str, Any]:
    """
    Comprueba que terminos tecnicos del input aparecen en el output curado.

    Usa normalización Unicode simétrica (NFD, guiones, NBSP) en ambos lados
    antes del matching léxico.
    """
    chunk_sin_marcadores = _STRUCTURAL_MARKER_RE.sub(" ", original_chunk or "")
    original_terms = extract_key_terms(chunk_sin_marcadores)
    output_norm = normalize_for_matching(markdown_output or "")
    missing = [t for t in original_terms if not _term_present_in_output(t, output_norm)]
    coverage = 1 - len(missing) / max(len(original_terms), 1)
    return {
        "coverage_score": round(coverage, 3),
        "missing_terms": missing[:10],
        "passed": coverage >= FIDELITY_THRESHOLD,
    }


def validate_items(
    items: list[dict[str, Any]],
    original_chunks: list[str] | None = None,
) -> dict[str, Any]:
    """
    Valida estructura minima del resultado del clasificador.
    No altera contenido.
    """
    errors: list[str] = []
    required_keys = {"tipo", "titulo_detectado", "contenido_markdown"}
    fidelity_reports: list[dict[str, Any]] = []

    for idx, item in enumerate(items, start=1):
        missing = required_keys - set(item.keys())
        if missing:
            errors.append(f"Bloque {idx}: faltan claves {sorted(missing)}")
        if not isinstance(item.get("contenido_markdown", ""), str):
            errors.append(f"Bloque {idx}: contenido_markdown no es string")
        if item.get("titulo_detectado") is not None and not isinstance(
            item.get("titulo_detectado"), str
        ):
            errors.append(f"Bloque {idx}: titulo_detectado no es string/null")
        if original_chunks and idx - 1 < len(original_chunks):
            fidelity = validate_fidelity(
                original_chunk=original_chunks[idx - 1],
                markdown_output=str(item.get("contenido_markdown", "")),
            )
            fidelity_reports.append({"bloque": idx, **fidelity})

    fidelity_ok = all(r.get("passed", False) for r in fidelity_reports) if fidelity_reports else True
    return {
        "ok": (not errors) and fidelity_ok,
        "errores": errors,
        "fidelity": fidelity_reports,
    }
