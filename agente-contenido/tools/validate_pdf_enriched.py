#!/usr/bin/env python3
"""Tests unitarios de shared/pdf_enriched.py (sin PDF real)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.pdf_enriched import (  # noqa: E402
    is_visual_title_line,
    markdown_prefix_for_line,
)

_PASS = "[OK]"
_FAIL = "[FAIL]"
_results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    sym = _PASS if ok else _FAIL
    line = f"  {sym} {name}"
    if detail:
        line += f" | {detail}"
    print(line)
    _results.append((name, ok))


def _words(fn: str, sz: float, text: str) -> list[dict]:
    return [
        {"fontname": fn, "size": sz, "text": tok}
        for tok in text.split()
    ]


def test_numbered_section() -> None:
    print("\n[1] Seccion numerada -> ###")
    pals = _words("Arial", 12.0, "3.1. Defectos y dislocaciones")
    p = markdown_prefix_for_line("3.1. Defectos y dislocaciones", pals, "Arial", 10.0)
    check("prefijo ###", p == "### ")


def test_body_line() -> None:
    print("\n[2] Linea de cuerpo -> sin prefijo")
    pals = _words("Arial", 10.0, "Texto corrido del párrafo")
    p = markdown_prefix_for_line("Texto corrido del párrafo", pals, "Arial", 10.0)
    check("sin prefijo", p == "")


def test_large_title() -> None:
    print("\n[3] Titulo grande -> # o ##")
    pals = _words("Arial-Bold", 18.0, "Endurecimiento por solución sólida")
    p = markdown_prefix_for_line(
        "Endurecimiento por solución sólida", pals, "Arial", 10.0
    )
    check("tiene prefijo heading", p in ("# ", "## ", "### "))


def test_bold_subtitle() -> None:
    print("\n[4] Negrita moderada -> heading")
    pals = _words("Arial-Bold", 11.0, "Nota importante")
    check(
        "is_visual_title_line",
        is_visual_title_line(pals, "Arial", 10.0),
    )
    p = markdown_prefix_for_line("Nota importante", pals, "Arial", 10.0)
    check("prefijo no vacío", bool(p))


def test_long_line_not_heading() -> None:
    print("\n[5] Linea larga en negrita -> cuerpo")
    texto = "x " * 80
    pals = _words("Arial-Bold", 14.0, texto)
    p = markdown_prefix_for_line(texto.strip(), pals, "Arial", 10.0)
    check("sin prefijo por longitud", p == "")


def main() -> int:
    print("=== validate_pdf_enriched ===")
    test_numbered_section()
    test_body_line()
    test_large_title()
    test_bold_subtitle()
    test_long_line_not_heading()
    ok = sum(1 for _, p in _results if p)
    print(f"\n=== {ok}/{len(_results)} OK ===")
    return 0 if ok == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
