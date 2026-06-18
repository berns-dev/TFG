"""Reparto monótono de un markdown curado de bloque en fragmentos por subtema.

Usa nombres y orden de los subtemas del Organizador (vía BD). No llama a la API.
Las horas lectivas del bloque no intervienen aquí — solo estructura y posición.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from assembler import SECTION_NAMES, _frontmatter_inner, _parse_fm_field

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_SECCION_EVIDENCIA_RE = re.compile(r"Secci[oó]n\s+([\d.]+)", re.IGNORECASE)

ConfianzaNivel = Literal["alta", "media", "baja", "sin_ancla"]

UMBRAL_MATCH_DEFAULT = 0.78
UMBRAL_CONFIANZA_BAJA = 0.65


def _normalize_title(texto: str) -> str:
    s = (texto or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


_CANONICAL_H2_NORM: set[str] = set()
for _lang_sections in SECTION_NAMES.values():
    for _h2 in _lang_sections.values():
        if _h2.startswith("## "):
            _CANONICAL_H2_NORM.add(_normalize_title(_h2[3:].strip()))


def _strip_frontmatter(md: str) -> tuple[str, str | None]:
    """Devuelve (cuerpo, tema_detectado del frontmatter o None)."""
    stripped = (md or "").strip()
    tema: str | None = None
    fm = _frontmatter_inner(stripped)
    if fm:
        tema = _parse_fm_field(fm, "tema_detectado")
    if not stripped.startswith("---"):
        return stripped, tema
    parts = stripped.split("---", 2)
    if len(parts) >= 3:
        return parts[2].lstrip("\n"), tema
    return stripped, tema


@dataclass
class Heading:
    pos: int
    nivel: int
    texto: str
    norm: str


@dataclass
class SplitFragment:
    subbloque_id: int
    nombre: str
    markdown: str
    offset_inicio: int
    offset_fin: int
    ancla_texto: str | None
    ancla_score: float
    confianza: ConfianzaNivel
    avisos: list[str] = field(default_factory=list)


@dataclass
class SplitResult:
    fragmentos: list[SplitFragment]
    markdown_bloque: str
    confianza_global: float
    requiere_revision: bool


def _extract_headings(cuerpo: str, tema_detectado: str | None) -> list[Heading]:
    headings: list[Heading] = []
    tema_norm = _normalize_title(tema_detectado or "")
    offset = 0
    for line in cuerpo.splitlines(keepends=True):
        m = _HEADING_RE.match(line.strip())
        if m:
            nivel = len(m.group(1))
            texto = m.group(2).strip()
            norm = _normalize_title(texto)
            if nivel == 1 and tema_norm and norm == tema_norm:
                offset += len(line)
                continue
            if norm == _normalize_title("Notas del presentador"):
                offset += len(line)
                continue
            if nivel == 2 and norm in _CANONICAL_H2_NORM:
                offset += len(line)
                continue
            headings.append(
                Heading(pos=offset, nivel=nivel, texto=texto, norm=norm)
            )
        offset += len(line)
    return headings


def _score_match(nombre_subtema: str, evidencia: str, heading: Heading) -> float:
    target = _normalize_title(nombre_subtema)
    if not target:
        return 0.0
    base = difflib.SequenceMatcher(None, target, heading.norm).ratio()
    bonus = 0.0
    if target in heading.norm or heading.norm in target:
        bonus += 0.15
    m = _SECCION_EVIDENCIA_RE.match((evidencia or "").strip())
    if m:
        num = m.group(1)
        if re.match(rf"^{re.escape(num)}\b", heading.texto.strip()):
            bonus += 0.15
    if heading.nivel == 1 and base > 0.6:
        bonus += 0.10
    elif heading.nivel == 3 and base > 0.6:
        bonus += 0.05
    return min(1.0, base + bonus)


def _confianza_nivel(score: float, tiene_ancla: bool) -> ConfianzaNivel:
    if not tiene_ancla:
        return "sin_ancla"
    if score >= UMBRAL_MATCH_DEFAULT:
        return "alta"
    if score >= UMBRAL_CONFIANZA_BAJA:
        return "media"
    return "baja"


def _assign_anchors_greedy(
    subtemas: list[dict[str, Any]],
    headings: list[Heading],
    umbral_match: float,
) -> list[tuple[int | None, float, str | None]]:
    """Por cada subtema: (índice heading o None, score, texto ancla)."""
    prev_pos = -1
    result: list[tuple[int | None, float, str | None]] = []
    for subtema in subtemas:
        nombre = str(subtema.get("nombre") or "")
        evidencia = str(subtema.get("evidencia") or "")
        best_idx: int | None = None
        best_score = 0.0
        best_text: str | None = None
        for j, h in enumerate(headings):
            if h.pos <= prev_pos:
                continue
            sc = _score_match(nombre, evidencia, h)
            if sc >= umbral_match and sc > best_score:
                best_score = sc
                best_idx = j
                best_text = h.texto
        if best_idx is not None:
            prev_pos = headings[best_idx].pos
        result.append((best_idx, best_score, best_text))
    return result


def _compute_starts(
    n: int,
    anchor_pos: list[int | None],
    length: int,
) -> list[int]:
    """Posición de inicio de cada subtema (n elementos); el último límite es length."""
    starts: list[int | None] = [None] * n
    for i in range(n):
        if anchor_pos[i] is not None:
            starts[i] = anchor_pos[i]

    if not any(s is not None for s in starts):
        return [0] * n

    if starts[0] is None:
        starts[0] = 0

    anchored_indices = [i for i in range(n) if starts[i] is not None]

    for k in range(len(anchored_indices) - 1):
        i0 = anchored_indices[k]
        i1 = anchored_indices[k + 1]
        p0 = starts[i0]
        p1 = starts[i1]
        assert p0 is not None and p1 is not None
        gap_count = i1 - i0
        if gap_count <= 1:
            continue
        for g in range(1, gap_count):
            idx = i0 + g
            if starts[idx] is None:
                starts[idx] = p0 + (p1 - p0) * g // gap_count

    last_anchored = anchored_indices[-1]
    for i in range(last_anchored + 1, n):
        if starts[i] is None:
            prev = starts[i - 1] if starts[i - 1] is not None else 0
            remaining = n - last_anchored
            span = max(1, i - last_anchored)
            starts[i] = prev + (length - (starts[last_anchored] or 0)) * span // remaining

    for i in range(n):
        if starts[i] is None:
            starts[i] = starts[i - 1] if i > 0 else 0

    return [int(s) for s in starts]


def split_monotono(
    markdown_bloque: str,
    subtemas: list[dict[str, Any]],
    *,
    umbral_match: float = UMBRAL_MATCH_DEFAULT,
) -> SplitResult:
    """Divide el markdown curado del bloque en un fragmento por subtema (orden monótono).

    Args:
        markdown_bloque: Markdown completo del bloque (con frontmatter).
        subtemas: filas ordenadas con al menos id, nombre, orden, evidencia.
        umbral_match: similitud mínima nombre↔heading para ancla.

    Returns:
        SplitResult con fragmentos listos para persistir como borrador por subtema.
    """
    ordenados = sorted(subtemas, key=lambda s: (s.get("orden") or 0, s.get("id") or 0))
    cuerpo, tema_detectado = _strip_frontmatter(markdown_bloque)
    cuerpo = cuerpo or ""
    length = len(cuerpo)

    if not ordenados:
        return SplitResult(
            fragmentos=[],
            markdown_bloque=markdown_bloque,
            confianza_global=0.0,
            requiere_revision=True,
        )

    if not cuerpo.strip():
        fragmentos = [
            SplitFragment(
                subbloque_id=int(s["id"]),
                nombre=str(s.get("nombre") or ""),
                markdown=f"# {s.get('nombre', '')}\n\n*Sin contenido.*",
                offset_inicio=0,
                offset_fin=0,
                ancla_texto=None,
                ancla_score=0.0,
                confianza="sin_ancla",
                avisos=["El markdown del bloque está vacío."],
            )
            for s in ordenados
        ]
        return SplitResult(
            fragmentos=fragmentos,
            markdown_bloque=markdown_bloque,
            confianza_global=0.0,
            requiere_revision=True,
        )

    headings = _extract_headings(cuerpo, tema_detectado)
    assignments = _assign_anchors_greedy(ordenados, headings, umbral_match)

    anchor_pos: list[int | None] = [None] * len(ordenados)
    anchor_scores: list[float] = [0.0] * len(ordenados)
    anchor_texts: list[str | None] = [None] * len(ordenados)
    for i, (h_idx, score, text) in enumerate(assignments):
        if h_idx is not None:
            anchor_pos[i] = headings[h_idx].pos
            anchor_scores[i] = score
            anchor_texts[i] = text

    starts = _compute_starts(len(ordenados), anchor_pos, length)
    ends = starts[1:] + [length]

    fragmentos: list[SplitFragment] = []
    scores_sum = 0.0
    requiere_revision = False

    for i, subtema in enumerate(ordenados):
        start = starts[i]
        end = max(start, ends[i])
        slice_text = cuerpo[start:end].strip()
        nombre = str(subtema.get("nombre") or "")
        tiene_ancla = anchor_pos[i] is not None
        score = anchor_scores[i] if tiene_ancla else 0.0
        conf = _confianza_nivel(score, tiene_ancla)
        avisos: list[str] = []

        if not tiene_ancla:
            avisos.append(
                f"No se localizó título para «{nombre}»; contenido inferido por posición."
            )
            requiere_revision = True
        elif conf == "baja":
            avisos.append(
                f"Coincidencia débil ({score:.2f}) entre «{nombre}» y «{anchor_texts[i]}»."
            )
            requiere_revision = True

        if i == 0 and anchor_pos[0] is not None and anchor_pos[0] > 0:
            intro = cuerpo[0 : anchor_pos[0]].strip()
            if intro and intro not in slice_text:
                slice_text = f"{intro}\n\n{slice_text}".strip()

        if slice_text:
            md_fragment = f"# {nombre}\n\n{slice_text}"
        else:
            md_fragment = f"# {nombre}\n\n*Sin contenido detectado para este apartado.*"
            if tiene_ancla:
                avisos.append("Ancla encontrada pero el tramo asignado está vacío.")
                requiere_revision = True

        scores_sum += score
        fragmentos.append(
            SplitFragment(
                subbloque_id=int(subtema["id"]),
                nombre=nombre,
                markdown=md_fragment,
                offset_inicio=start,
                offset_fin=end,
                ancla_texto=anchor_texts[i],
                ancla_score=round(score, 3),
                confianza=conf,
                avisos=avisos,
            )
        )

    confianza_global = round(scores_sum / max(len(ordenados), 1), 3)

    return SplitResult(
        fragmentos=fragmentos,
        markdown_bloque=markdown_bloque,
        confianza_global=confianza_global,
        requiere_revision=requiere_revision,
    )
