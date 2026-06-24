"""Taller de visualizaciones: generación y refinamiento desde prompt del profesor."""

from __future__ import annotations

import logging
import re
import time

import anthropic

from generador_html import _is_valid_html, _slug, validar_bloque_html
from prs_config import ANTHROPIC_API_KEY, MODEL_SMART, REQUEST_TIMEOUT_SECONDS
from prs_prompts import (
    PROMPT_TALLER_GENERADOR,
    PROMPT_TALLER_RAZONADOR,
    PROMPT_TALLER_REFINADOR,
    build_taller_generador_message,
    build_taller_razonador_message,
    build_taller_refinador_message,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_MAX_TOKENS = 8192
_MAX_TOKENS_RAZONADOR = 1024


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


def _llamar_sonnet(
    system: str, user_message: str, max_tokens: int = _MAX_TOKENS
) -> str:
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL_SMART,
                max_tokens=max_tokens,
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


def _razonar_instruccion(
    instruccion: str,
    markdown_bloque: str,
    texto_original: str | None = None,
) -> str:
    """Razonamiento previo (Sonnet): concepto, fórmula, consistencia, mapeo física-movimiento.

    Devuelve cadena vacía si la llamada falla — el generador sigue
    funcionando sin este contexto extra (degradación elegante, mismo
    criterio que el resto del agente ante fallos de API).
    """
    try:
        user_msg = build_taller_razonador_message(
            instruccion, markdown_bloque, texto_original
        )
        razonamiento = _llamar_sonnet(
            PROMPT_TALLER_RAZONADOR, user_msg, max_tokens=_MAX_TOKENS_RAZONADOR
        )
        logger.info("[TALLER] Razonamiento previo: %s", razonamiento[:500])
        return razonamiento
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TALLER] Razonamiento previo falló: %s", exc)
        return ""


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
    razonamiento = _razonar_instruccion(instruccion, markdown_bloque, texto_original)
    system = PROMPT_TALLER_GENERADOR.replace("{slug}", slug)
    user_msg = build_taller_generador_message(
        slug, instruccion, markdown_bloque, texto_original, razonamiento
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


def sugerir_seccion_ancla(instruccion: str, opciones: list[str]) -> str:
    """Sugiere la opción de ancla (sección o figura) que mejor coincide con el prompt.

    Las opciones pueden incluir headings ##/### y marcadores [FIGURA: ...].
    Para figuras, el matching ignora el prefijo [FIGURA: ] y usa la descripción.
    """
    if not opciones:
        return ""
    inst_norm = instruccion.lower()
    mejor = ""
    mejor_score = 0
    for opcion in opciones:
        if opcion.startswith("[FIGURA:") and opcion.endswith("]"):
            texto = opcion[8:-1].strip()
        else:
            texto = opcion
        texto_low = texto.lower()
        if texto_low in inst_norm or any(w in inst_norm for w in texto_low.split() if len(w) > 3):
            score = len(texto_low)
            if score > mejor_score:
                mejor_score = score
                mejor = opcion
    return mejor or opciones[0]
