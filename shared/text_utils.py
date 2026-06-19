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
