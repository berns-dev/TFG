"""Taller de visualizaciones: generación y refinamiento desde prompt del profesor."""

from __future__ import annotations

import re
import time

import anthropic

from generador_html import _is_valid_html, _slug, validar_bloque_html
from prs_config import ANTHROPIC_API_KEY, MODEL_SMART, REQUEST_TIMEOUT_SECONDS
from prs_prompts import (
    PROMPT_TALLER_GENERADOR,
    PROMPT_TALLER_REFINADOR,
    build_taller_generador_message,
    build_taller_refinador_message,
)

_MAX_RETRIES = 2
_MAX_TOKENS = 8192


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )


def _limpiar_respuesta_html(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    return raw


def _llamar_sonnet(system: str, user_message: str) -> str:
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL_SMART,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            return _limpiar_respuesta_html(response.content[0].text)
        except (
            anthropic.APIConnectionError,
            anthropic.RateLimitError,
            anthropic.APIError,
        ) as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(2**attempt)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("No se pudo obtener respuesta del modelo")


def generar_desde_instruccion(
    instruccion: str,
    markdown_bloque: str,
    titulo: str = "Visualización",
    texto_original: str | None = None,
) -> tuple[str, str]:
    """Genera un fragmento HTML interactivo desde el prompt del profesor.

    Returns:
        (slug, html_fragment)
    """
    slug = _slug(titulo or instruccion[:40])
    system = PROMPT_TALLER_GENERADOR.replace("{slug}", slug)
    user_msg = build_taller_generador_message(
        slug, instruccion, markdown_bloque, texto_original
    )
    raw = _llamar_sonnet(system, user_msg)
    if not _is_valid_html(raw):
        raise ValueError("La respuesta del modelo no parece HTML válido.")
    ok, motivo = validar_bloque_html(raw, slug, requiere_autoarranque=True)
    if not ok:
        raise ValueError(f"HTML generado inválido: {motivo}")
    return slug, raw


def refinar_html(
    html_actual: str,
    instruccion: str,
    slug: str,
) -> str:
    """Refina un fragmento HTML existente según una nueva instrucción del profesor."""
    system = PROMPT_TALLER_REFINADOR.replace("{slug}", slug)
    user_msg = build_taller_refinador_message(slug, html_actual, instruccion)
    raw = _llamar_sonnet(system, user_msg)
    if not _is_valid_html(raw):
        raise ValueError("La respuesta del modelo no parece HTML válido.")
    ok, motivo = validar_bloque_html(raw, slug, requiere_autoarranque=True)
    if not ok:
        raise ValueError(f"HTML refinado inválido: {motivo}")
    return raw


def sugerir_seccion_ancla(instruccion: str, headings: list[str]) -> str:
    """Sugiere el heading del MD que mejor coincide con el prompt."""
    if not headings:
        return ""
    inst_norm = instruccion.lower()
    mejor = ""
    mejor_score = 0
    for h in headings:
        h_low = h.lower()
        if h_low in inst_norm or any(w in inst_norm for w in h_low.split() if len(w) > 3):
            score = len(h_low)
            if score > mejor_score:
                mejor_score = score
                mejor = h
    return mejor or headings[0]
