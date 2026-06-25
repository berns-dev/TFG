"""Cliente Anthropic con reintentos y timeout unificados."""

from __future__ import annotations

import time
from typing import Any

import anthropic

_MAX_RETRIES = 2


def extract_text_from_message(message: object) -> tuple[str, str]:
    """Extrae texto y stop_reason de una respuesta de messages.create."""
    content = getattr(message, "content", None)
    if not content:
        raise RuntimeError("La API devolvió una respuesta sin contenido.")
    block = content[0]
    text = getattr(block, "text", None)
    if not isinstance(text, str):
        raise RuntimeError(
            f"La API no devolvió un bloque de texto (tipo={type(block).__name__})."
        )
    stop_reason = getattr(message, "stop_reason", None) or ""
    return text, stop_reason


def call_messages(
    client: anthropic.Anthropic,
    *,
    model: str,
    max_tokens: int,
    messages: list[dict[str, Any]],
    system: str | None = None,
    timeout: float | None = None,
) -> tuple[str, str]:
    """Llama a messages.create con reintentos ante errores transitorios de API."""
    last_exc: Exception | None = None
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if timeout is not None:
        kwargs["timeout"] = timeout

    for attempt in range(_MAX_RETRIES + 1):
        try:
            message = client.messages.create(**kwargs)
            return extract_text_from_message(message)
        except anthropic.RateLimitError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(30 * (attempt + 1))
                continue
            raise
        except (
            anthropic.APIConnectionError,
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
