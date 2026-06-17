"""Segmentación de texto extraído en bloques correspondientes a subbloques.

Usa el campo 'evidencia' de cada subbloque (producido por el Agente Organizador)
para localizar las fronteras en el texto extraído. Las evidencias pueden ser:
  - "Slide N"    → marcador [SLIDE N] inyectado por extractor.py (_extract_pptx)
  - "Sección X.X" → encabezado numerado "X.X. Título" detectado en el texto
  - "Sin señal verificable" → bloque sin subdivisión fiable; todo el texto al único subbloque
"""

from __future__ import annotations

import difflib
import re
import unicodedata

_SLIDE_EVIDENCIA_RE = re.compile(r"Slide\s+(\d+)", re.IGNORECASE)
_SECCION_EVIDENCIA_RE = re.compile(r"Secci[oó]n\s+([\d.]+)", re.IGNORECASE)
_PAGINA_EVIDENCIA_RE = re.compile(r"P[aá]gina\s+(\d+)", re.IGNORECASE)

_FALLBACK_EVIDENCIAS = frozenset(
    {
        "sin señal verificable",
        "sin senal verificable",
        "fallback",
        "sin señal",
        "sin senal",
        "",
        "—",
        "-",
        "–",
    }
)


def _evidencia_es_vacia(evidencia: str) -> bool:
    return (evidencia or "").strip().lower() in _FALLBACK_EVIDENCIAS


def _normalize_title(texto: str) -> str:
    s = (texto or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def _find_boundary_by_title(text: str, nombre: str, min_ratio: float = 0.85) -> int | None:
    """Localiza un encabezado por coincidencia con el nombre del sub-bloque.

    Solo se usa como red de seguridad cuando no hay evidencia estructural.
    Devuelve None si hay cero o varias coincidencias ambiguas.
    """
    target = _normalize_title(nombre)
    if len(target) < 4:
        return None

    candidatos: list[tuple[int, float]] = []
    for m in re.finditer(r"^(.+)$", text, re.MULTILINE):
        line = m.group(1).strip()
        if not line or len(line) > 150:
            continue
        norm = _normalize_title(line)
        if not norm:
            continue
        ratio = difflib.SequenceMatcher(None, norm, target).ratio()
        if ratio >= min_ratio:
            candidatos.append((m.start(), ratio))

    if not candidatos:
        return None
    candidatos.sort(key=lambda x: x[1], reverse=True)
    mejor_pos, mejor_ratio = candidatos[0]
    if len(candidatos) > 1 and candidatos[1][1] >= min_ratio - 0.05:
        return None
    return mejor_pos if mejor_ratio >= min_ratio else None


def _find_boundary_in_text(text: str, evidencia: str) -> int | None:
    """Devuelve la posición de inicio en `text` para la evidencia dada, o None."""
    ev_norm = evidencia.strip().lower()
    if ev_norm in _FALLBACK_EVIDENCIAS:
        return None

    # "Slide N" → [SLIDE N] inyectado por _extract_pptx
    m = _SLIDE_EVIDENCIA_RE.match(evidencia.strip())
    if m:
        num = m.group(1)
        pattern = re.compile(rf"^\[SLIDE\s+{re.escape(num)}\]", re.MULTILINE)
        found = pattern.search(text)
        return found.start() if found else None

    # "Sección X.X" → encabezado "X.X. Título" detectado por chunker
    m = _SECCION_EVIDENCIA_RE.match(evidencia.strip())
    if m:
        num = m.group(1)
        pattern = re.compile(rf"^{re.escape(num)}\.?\s+\S", re.MULTILINE)
        found = pattern.search(text)
        return found.start() if found else None

    # "Página N" → [PAGINA N] inyectado por _extract_pdf (raramente en evidencias)
    m = _PAGINA_EVIDENCIA_RE.match(evidencia.strip())
    if m:
        num = m.group(1)
        pattern = re.compile(rf"^\[PAGINA\s+{re.escape(num)}\]", re.MULTILINE)
        found = pattern.search(text)
        return found.start() if found else None

    return None


def segment_text_by_subbloques(
    text: str,
    subbloques: list[dict],
) -> list[tuple[dict, str]]:
    """Divide el texto extraído en segmentos para cada subbloque.

    Reglas:
    - Un único subbloque (incluyendo el fallback "Sin señal verificable"):
      recibe todo el texto.
    - Múltiples subbloques: cada uno recibe el tramo de texto desde su
      boundary hasta el boundary del siguiente. El texto antes del primer
      boundary se une al primer subbloque encontrado.
    - Subbloques cuya evidencia no se encuentra en el texto: reciben
      texto vacío y quedan con estado "pendiente" — el profesor puede
      editarlos manualmente.

    Retorna lista de (subbloque_meta, text_segment) en el mismo orden
    que la lista de entrada.
    """
    clean = (text or "").strip()
    if not subbloques:
        return []
    if len(subbloques) == 1:
        return [(subbloques[0], clean)]

    # Localizar boundaries en el texto
    found_boundaries: list[tuple[int, int]] = []  # (subbloque_idx, char_position)
    for i, sb in enumerate(subbloques):
        ev = sb.get("evidencia", "")
        pos = _find_boundary_in_text(clean, ev)
        if pos is None and _evidencia_es_vacia(ev):
            pos = _find_boundary_by_title(clean, sb.get("nombre", ""))
        if pos is not None:
            found_boundaries.append((i, pos))

    if not found_boundaries:
        # Sin ningún marcador reconocible: todo al primer subbloque
        result = []
        for i, sb in enumerate(subbloques):
            result.append((sb, clean if i == 0 else ""))
        return result

    # Ordenar por posición (defensivo: el Organizador los emite en orden)
    found_boundaries.sort(key=lambda x: x[1])

    text_len = len(clean)
    segments: dict[int, str] = {i: "" for i in range(len(subbloques))}

    for rank, (idx, pos) in enumerate(found_boundaries):
        end = found_boundaries[rank + 1][1] if rank + 1 < len(found_boundaries) else text_len
        segments[idx] = clean[pos:end].strip()

    # Texto antes del primer boundary → prepende al primer subbloque con boundary
    first_pos = found_boundaries[0][1]
    if first_pos > 0:
        prefix = clean[:first_pos].strip()
        if prefix:
            first_idx = found_boundaries[0][0]
            segments[first_idx] = (prefix + "\n\n" + segments[first_idx]).strip()

    return [(subbloques[i], segments[i]) for i in range(len(subbloques))]
