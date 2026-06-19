"""Configuración del Agente Organizador (paridad con cnt_config / prs_config)."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL_SMART = os.getenv("MODEL_SMART", "claude-sonnet-4-5")
MAX_TOKENS = int(os.getenv("ORG_MAX_TOKENS", "8192"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))
