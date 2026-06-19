"""Cliente Anthropic con reintentos y timeout unificados."""

from __future__ import annotations

import time
from typing import Any

import anthropic

_MAX_RETRIES = 2


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
            texto = message.content[0].text
            stop_reason = getattr(message, "stop_reason", None) or ""
            return texto, stop_reason
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
