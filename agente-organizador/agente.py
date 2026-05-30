import os

import anthropic
from dotenv import load_dotenv

SYSTEM_PROMPT = (
    "Eres un asistente especializado en organización docente para asignaturas "
    "de ingeniería universitaria. Tu única función es extraer y organizar "
    "información basándote exclusivamente en los documentos proporcionados por "
    "el profesor. No inventas contenido ni añades información que no esté "
    "presente en los materiales."
)

load_dotenv()
# La API key se carga desde .env en la variable ANTHROPIC_API_KEY.
_api_key = os.getenv("ANTHROPIC_API_KEY")

if not _api_key:
    raise ValueError("No se ha encontrado ANTHROPIC_API_KEY en el entorno o en el archivo .env.")

client = anthropic.Anthropic(api_key=_api_key)


def ejecutar_agente(prompt: str) -> str:
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
