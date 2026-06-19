"""Metadatos de presentación (curso/código) — no persistidos en BD."""

from __future__ import annotations

# Mapeo opcional; el resto usa valores por defecto del grado.
_CURSO_POR_ASIGNATURA: dict[str, tuple[str, str]] = {
    "Tecnología de Materiales": ("2º GITI", "GITI101"),
    "Elementos de Máquinas": ("3º GIM", "GIM301"),
    "Oleohidráulica y Neumática": ("3º GIM", "GIM302"),
}

_PIPELINE_SUBFIJO = {
    "Organizador": "Estructura curricular",
    "Contenido": "Curación y revisión",
    "Presentación": "Visualizaciones",
}

def curso_codigo(nombre_asignatura: str) -> tuple[str, str]:
    return _CURSO_POR_ASIGNATURA.get(nombre_asignatura, ("Grado IME", "EPI Gijón"))


def curso_codigo_topbar(nombre_asignatura: str) -> str:
    curso, codigo = curso_codigo(nombre_asignatura)
    return f"{curso} · {codigo}"


def curso_sidebar(nombre_asignatura: str) -> str:
    curso, _ = curso_codigo(nombre_asignatura)
    return curso


def pipeline_subfijo(vista: str) -> str:
    return _PIPELINE_SUBFIJO.get(vista, "")


def barra_progreso_html(pct: int, completo: bool = False, claro: bool = False) -> str:
    pct = max(0, min(100, pct))
    color = "#3FAE6B" if completo and pct >= 100 else "#3D8BD4"
    clase = "sd-asig-bar claro" if claro else "sd-asig-bar"
    return (
        f'<div class="{clase}"><div class="fill" style="width:{pct}%;background:{color};"></div></div>'
    )
