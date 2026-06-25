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


def normalize_for_matching(text: str) -> str:
    """Normaliza texto para comparación léxica (fidelidad, cobertura).

    Aplica NFD sin diacríticos, unifica guiones tipográficos y NBSP, y colapsa
    espacios para que el matching no falle por artefactos de extracción PDF.
    """
    t = unicodedata.normalize("NFD", text or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("\u00a0", " ")
    for ch in "–—−":
        t = t.replace(ch, "-")
    t = t.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()
