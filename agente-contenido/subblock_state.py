"""Modelo de estado por subbloque para el Agente Contenido.

Cada subbloque procesado tiene un estado que la UI (fase posterior) puede
leer y mutar. El ciclo de vida es:

    pendiente  →  generado  →  aprobado
                     ↓              ↑
                  editado  ─────────┘

- pendiente: texto vacío o error en extracción; el profesor debe editar manualmente.
- generado:  la API produjo el Markdown; pendiente de revisión del profesor.
- editado:   el profesor modificó el Markdown sin nueva llamada a la API.
- aprobado:  el profesor aceptó el contenido (original o editado).

El progreso (aprobados / total) se calcula sobre esta lista de estados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EstadoSubbloque = Literal["pendiente", "generado", "editado", "aprobado"]


@dataclass
class SubbloqueResult:
    """Resultado de procesamiento de un subbloque, con su estado de revisión."""

    nombre: str
    horas: float
    evidencia: str
    origen: str
    estado: EstadoSubbloque
    markdown: str
    items: list[dict[str, Any]] = field(default_factory=list)
    validacion: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nombre": self.nombre,
            "horas": self.horas,
            "evidencia": self.evidencia,
            "origen": self.origen,
            "estado": self.estado,
            "markdown": self.markdown,
            "items": self.items,
            "validacion": self.validacion,
        }


def calcular_progreso_bloque(subbloques: list[SubbloqueResult]) -> dict[str, Any]:
    """Progreso de un bloque: aprobados / total subbloques."""
    total = len(subbloques)
    aprobados = sum(1 for sb in subbloques if sb.estado == "aprobado")
    return {
        "total": total,
        "aprobados": aprobados,
        "porcentaje": round(aprobados / max(total, 1) * 100, 1),
    }


def calcular_progreso_asignatura(
    todos_subbloques: list[SubbloqueResult],
) -> dict[str, Any]:
    """Progreso global: aprobados / total subbloques de todos los bloques procesados."""
    total = len(todos_subbloques)
    aprobados = sum(1 for sb in todos_subbloques if sb.estado == "aprobado")
    return {
        "total": total,
        "aprobados": aprobados,
        "porcentaje": round(aprobados / max(total, 1) * 100, 1),
    }
