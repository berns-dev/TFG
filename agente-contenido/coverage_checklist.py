"""Checklist de cobertura: apartados del Organizador vs markdown curado del bloque."""

from __future__ import annotations

import re
import unicodedata


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_STOPWORDS = frozenset({
    "de", "la", "el", "los", "las", "y", "en", "del", "al", "un", "una", "por", "con",
})


def _tokens_significativos(nombre: str) -> list[str]:
    norm = _normalizar(nombre)
    return [w for w in norm.split() if len(w) > 2 and w not in _STOPWORDS]


def contar_marcadores(markdown: str) -> dict:
    """Cuenta marcadores de extracción incompleta en el markdown curado.

    Returns:
        Dict con claves ecuacion, ecuacion_parcial, texto_ilegible, figura,
        total_problemas (suma de los tres primeros).
    """
    texto = markdown or ""
    ecuacion = len(re.findall(r"\[ECUACION\]", texto))
    ecuacion_parcial = len(re.findall(r"\[ECUACION_PARCIAL:[^\]]+\]", texto))
    texto_ilegible = len(re.findall(r"\[TEXTO_ILEGIBLE\]", texto))
    figura = len(re.findall(r"\[FIGURA:[^\]]+\]", texto))
    return {
        "ecuacion": ecuacion,
        "ecuacion_parcial": ecuacion_parcial,
        "texto_ilegible": texto_ilegible,
        "figura": figura,
        "total_problemas": ecuacion + ecuacion_parcial + texto_ilegible,
    }


def verificar_cobertura(markdown: str, apartados: list[dict]) -> list[dict]:
    """Comprueba si cada apartado del Organizador aparece reflejado en el MD curado.

    Args:
        markdown: Markdown completo del bloque.
        apartados: Filas de subbloques del Organizador ({nombre, ...}).

    Returns:
        Lista de {nombre, cubierto, detalle}.
    """
    md_norm = _normalizar(markdown)
    resultados: list[dict] = []

    for ap in apartados:
        nombre = (ap.get("nombre") or "").strip()
        if not nombre:
            continue
        tokens = _tokens_significativos(nombre)
        if not tokens:
            resultados.append({
                "nombre": nombre,
                "cubierto": True,
                "detalle": "Sin términos evaluables",
            })
            continue
        encontrados = sum(1 for t in tokens if t in md_norm)
        umbral = max(1, (len(tokens) + 1) // 2)
        cubierto = encontrados >= umbral
        if cubierto:
            detalle = "Detectado en el contenido curado"
        else:
            detalle = (
                f"Solo {encontrados}/{len(tokens)} términos clave "
                f"({', '.join(tokens)})"
            )
        resultados.append({
            "nombre": nombre,
            "cubierto": cubierto,
            "detalle": detalle,
        })

    return resultados
