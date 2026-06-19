"""Utilidades compartidas de la app unificada (sin dependencia de Streamlit)."""

import os
from pathlib import Path

from shared.text_utils import slugify


def preparar_carpetas_asignatura(raiz_monorepo: str, slug: str) -> None:
    """Crea la estructura de carpetas estándar para una asignatura nueva."""
    base = Path(raiz_monorepo) / "data" / slug
    (base / "inputs").mkdir(parents=True, exist_ok=True)
    (base / "outputs" / "organizador").mkdir(parents=True, exist_ok=True)


def fichero_existe(ruta_disco: str) -> bool:
    return bool(ruta_disco) and os.path.isfile(ruta_disco)


def formatear_fecha_relativa(fecha_iso: str | None) -> tuple[str, str | None]:
    """Devuelve (texto_corto, texto_relativo) para una marca temporal SQLite."""
    if not fecha_iso:
        return "—", None
    from datetime import datetime

    try:
        dt = datetime.strptime(fecha_iso, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return fecha_iso, None
    corto = f"{dt.day} {dt.strftime('%b, %H:%M')}"
    delta_s = int((datetime.now() - dt).total_seconds())
    if delta_s < 60:
        relativo = "ahora mismo"
    elif delta_s < 3600:
        relativo = f"hace {delta_s // 60} min"
    elif delta_s < 86400:
        relativo = f"hace {delta_s // 3600}h"
    else:
        dias = delta_s // 86400
        relativo = f"hace {dias} día{'s' if dias != 1 else ''}"
    return corto, relativo
