import sys
from pathlib import Path

import anthropic

from org_config import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)

_MONOREPO_ROOT = Path(__file__).resolve().parent.parent
if str(_MONOREPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_MONOREPO_ROOT))

from shared.anthropic_client import call_messages  # noqa: E402

MODEL = MODEL_SMART

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
    return call_messages(
        client,
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
