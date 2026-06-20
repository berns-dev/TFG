#!/usr/bin/env python3
"""Validación del marcador [ECUACION_RECONSTRUIDA: ...] (sin llamadas a la API)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coverage_checklist import contar_marcadores
from validator import validate_fidelity

_PASS = "[OK]"
_FAIL = "[FAIL]"
_results: list[tuple[str, bool]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    symbol = _PASS if condition else _FAIL
    line = f"  {symbol} {name}"
    if detail:
        line += f" | {detail}"
    print(line)
    _results.append((name, condition))


def test_reconstruccion_no_penaliza_fidelidad() -> None:
    print("\n[1] Sustituir [ECUACION_PARCIAL] por [ECUACION_RECONSTRUIDA] no baja la fidelidad")
    original_chunk = (
        "La tension de fluencia sigue la ecuacion de Hollomon, donde K es el "
        "coeficiente de resistencia y n el exponente de endurecimiento.\n"
        "[ECUACION_PARCIAL: sigma K epsilon n]"
    )
    markdown_output = (
        "## Contenido teorico\n\n"
        "La tension de fluencia sigue la ecuacion de Hollomon, donde K es el "
        "coeficiente de resistencia y n el exponente de endurecimiento.\n\n"
        "[ECUACION_RECONSTRUIDA: nombre de la ecuacion y variables K, n definidas "
        "en el propio parrafo]\n"
        "$$\\sigma = K \\cdot \\varepsilon^n$$"
    )
    reporte = validate_fidelity(original_chunk, markdown_output)
    check(
        "cobertura no penalizada por el marcador sustituido",
        reporte["passed"],
        f"coverage_score={reporte['coverage_score']}",
    )
    check(
        "no marca 'ecuacion_parcial' como termino perdido",
        not any("ecuacion_parcial" in t.lower() for t in reporte["missing_terms"]),
    )


def test_marcador_original_sin_tocar_sigue_pasando() -> None:
    print("\n[2] Si el LLM no reconstruye (deja el marcador original), tampoco penaliza")
    original_chunk = "Formula no identificable en el material.\n[ECUACION_NO_EXTRAIBLE]"
    markdown_output = (
        "## Contenido teorico\n\nFormula no identificable en el material.\n\n"
        "[ECUACION_NO_EXTRAIBLE]"
    )
    reporte = validate_fidelity(original_chunk, markdown_output)
    check("cobertura completa con passthrough", reporte["coverage_score"] == 1.0)


def test_contar_marcadores_distingue_reconstruidas() -> None:
    print("\n[3] contar_marcadores separa reconstruidas de problemas sin resolver")
    markdown = (
        "[ECUACION_RECONSTRUIDA: justificacion A]\n$$a=b$$\n\n"
        "[ECUACION_PARCIAL: x y z]\n\n"
        "[TEXTO_ILEGIBLE]\n\n"
        "[ECUACION_RECONSTRUIDA: justificacion B]\n$$c=d$$"
    )
    resumen = contar_marcadores(markdown)
    check("ecuacion_reconstruida = 2", resumen["ecuacion_reconstruida"] == 2, str(resumen))
    check("requiere_revision = 2", resumen["requiere_revision"] == 2)
    check(
        "total_problemas no incluye las reconstruidas",
        resumen["total_problemas"] == 2,  # 1 ecuacion_parcial + 1 texto_ilegible
        str(resumen["total_problemas"]),
    )


def main() -> int:
    print("=== validate_equation_reconstruction ===")
    test_reconstruccion_no_penaliza_fidelidad()
    test_marcador_original_sin_tocar_sigue_pasando()
    test_contar_marcadores_distingue_reconstruidas()
    ok = sum(1 for _, passed in _results if passed)
    print(f"\n=== {ok}/{len(_results)} OK ===")
    return 0 if ok == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
