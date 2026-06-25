#!/usr/bin/env python3
"""Validación de señales del parser del Organizador (sin llamadas a la API)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parser import (  # noqa: E402
    extraer_candidatos_con_evidencia,
    extraer_titulos_visuales_pdf,
    normalizar_horas_output,
)

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


def test_sin_ancla_horaria() -> None:
    print("\n[1] normalizar_horas_output sin ancla horaria")
    md = "## Bloque 1 — Introducción · 5h\n\n### 1.1 Tema\n"
    out, info = normalizar_horas_output(md, 0)
    check("devuelve info sin_ancla_horaria", info is not None and info.get("motivo") == "sin_ancla_horaria")
    check("markdown sin cambios", out == md)


def test_titulos_visuales_estados() -> None:
    print("\n[2] extraer_titulos_visuales_pdf distingue estados")
    titulos_vacio, estado_vacio = extraer_titulos_visuales_pdf(b"")
    check("bytes vacios -> sin_metadatos", estado_vacio == "sin_metadatos" and titulos_vacio == [])

    # PDF mínimo sin texto útil (solo cabecera)
    pdf_min = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    titulos_pdf, estado_pdf = extraer_titulos_visuales_pdf(pdf_min)
    check(
        "PDF sin palabras -> sin_metadatos",
        estado_pdf == "sin_metadatos" and titulos_pdf == [],
        f"estado={estado_pdf}",
    )


def test_numeracion_cascada() -> None:
    print("\n[3] extraer_candidatos_con_evidencia con numeración ruidosa")
    texto = (
        "1.1 Título válido uno\n"
        "1.2 Título válido dos\n"
        "1.3 Además, de acuerdo con la tabla del ejemplo anterior...\n"
        "Figura 4.5 Esquema general\n"
    )
    cands = extraer_candidatos_con_evidencia(texto, "tema.pdf", b"")
    check("numeración gana con >=2 válidos", len(cands) >= 2, f"n={len(cands)}")
    fuentes = {c.get("fuente") for c in cands}
    check("fuente numeracion presente", "numeracion" in fuentes, str(fuentes))


def main() -> int:
    print("=== validate_parser_signals ===")
    test_sin_ancla_horaria()
    test_titulos_visuales_estados()
    test_numeracion_cascada()
    ok = sum(1 for _, passed in _results if passed)
    total = len(_results)
    print(f"\n=== {ok}/{total} OK ===")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
