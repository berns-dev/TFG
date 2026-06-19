import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from org_config import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)

load_dotenv(Path(__file__).parent / ".env")

MODEL = MODEL_SMART
_MAX_RETRIES = 2

SYSTEM_PROMPT = (
    "Eres un asistente especializado en organización docente para asignaturas "
    "de ingeniería universitaria. Tu única función es extraer y organizar "
    "información basándote exclusivamente en los documentos proporcionados por "
    "el profesor. No inventas contenido ni añades información que no esté "
    "presente en los materiales."
)

_anthropic_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "No se ha encontrado ANTHROPIC_API_KEY en el entorno o en el archivo .env."
        )
    _anthropic_client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )
    return _anthropic_client


def ejecutar_agente(prompt: str) -> tuple[str, str]:
    """Ejecuta el agente y devuelve (texto_respuesta, stop_reason)."""
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
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
