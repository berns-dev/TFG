"""Configuracion central para Agente_presentacion."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Modelos — mismo esquema que el resto de la suite
MODEL_FAST = os.getenv("MODEL_FAST", "claude-haiku-4-5-20251001")   # detector ambiguos
MODEL_SMART = os.getenv("MODEL_SMART", "claude-sonnet-4-5")          # generador HTML

REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))

# Detección de elementos
MIN_LATEX_CHARS = int(os.getenv("MIN_LATEX_CHARS", "3"))
# Mínimo de variables distintas para clasificar una ecuación como 'relacion'
MIN_VARIABLES_FOR_RELACION = int(os.getenv("MIN_VARIABLES_FOR_RELACION", "2"))
# Caracteres a extraer como contexto circundante (antes y después del elemento)
CONTEXTO_CHARS = int(os.getenv("CONTEXTO_CHARS", "350"))
