#!/usr/bin/env python3
"""Validación del cleaner (modo completo y ligero)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleaner import clean_extracted_text

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


def _fake_slides(title: str, n: int = 8) -> str:
    blocks = []
    for i in range(1, n + 1):
        blocks.append(
            f"[PAGINA {i}]\n{title}\nContenido técnico de la diapositiva {i}."
        )
    return "\n\n".join(blocks)


def test_headings_survive_frequency_filter() -> None:
    print("\n[1] Headings #/##/### no se eliminan por frecuencia")
    raw = _fake_slides("### 1ª parte. Frenos")
    out = clean_extracted_text(raw, filename="Frenos_2025.pdf", light=False)
    check("conserva heading", "### 1ª parte. Frenos" in out)
    check("conserva contenido", "diapositiva 8" in out)


def test_plain_titles_dropped_in_full_mode() -> None:
    print("\n[2] Títulos repetidos sin prefijo sí se filtran en modo completo")
    raw = _fake_slides("1ª parte. Frenos")
    out = clean_extracted_text(raw, filename="Frenos_2025.pdf", light=False)
    check("elimina título repetido", "1ª parte. Frenos" not in out)
    check("conserva cuerpo", "diapositiva 3" in out)


def test_light_mode_skips_frequency() -> None:
    print("\n[3] Modo ligero conserva títulos repetidos")
    raw = _fake_slides("1ª parte. Frenos")
    out = clean_extracted_text(raw, filename="Frenos_2025.pdf", light=True)
    check("conserva título repetido", out.count("1ª parte. Frenos") == 8)


def test_light_mode_still_drops_page_numbers() -> None:
    print("\n[4] Modo ligero sigue eliminando pies de página numéricos")
    raw = "[PAGINA 1]\nTexto útil.\n42\n\n[PAGINA 2]\nMás texto.\n43"
    out = clean_extracted_text(raw, light=True)
    check("sin número suelto 42", "42" not in out.split())
    check("conserva texto", "Texto útil" in out and "Más texto" in out)


def test_equation_shard_salvage() -> None:
    print("\n[5] Fragmentos de ecuacion -> marcador recuperable")
    raw = (
        "[PAGINA 1]\n"
        "n e d s a u q R F = m u N\n"
        "Párrafo normal con varias palabras legibles en contexto."
    )
    out = clean_extracted_text(raw, light=True)
    check(
        "marca ecuación",
        "[ECUACION_PARCIAL:" in out or "[ECUACION_NO_EXTRAIBLE]" in out,
    )
    check("conserva párrafo", "Párrafo normal" in out)


def test_equation_marker_not_frequency_dropped() -> None:
    print("\n[6] Marcadores de ecuación no se eliminan por frecuencia")
    blocks = []
    for i in range(1, 7):
        blocks.append(
            f"[PAGINA {i}]\n[ECUACION_PARCIAL: F = mu N]\nTexto {i}."
        )
    raw = "\n\n".join(blocks)
    out = clean_extracted_text(raw, filename="doc.pdf", light=False)
    check("conserva marcadores", out.count("[ECUACION_PARCIAL:") == 6)


def test_glyph_header_filter_light_mode() -> None:
    print("\n[7] Modo ligero elimina glifos de cabecera repetidos")
    blocks = []
    for i in range(1, 11):
        blocks.append(
            f"[PAGINA {i}]\n"
            "s a\n"
            "n i\n"
            "uq\n"
            "## Materiales de friccion\n"
            f"Contenido real de la diapositiva {i}."
        )
    raw = "\n\n".join(blocks)
    out = clean_extracted_text(raw, light=True)
    check("sin glifo sa", "s a" not in out)
    check("sin glifo ni", "n i" not in out)
    check("sin glifo uq", all(ln.strip() != "uq" for ln in out.splitlines()))
    check("conserva heading", "## Materiales de friccion" in out)
    check("conserva cuerpo", "diapositiva 10" in out)


def test_glyph_line_not_dropped_if_rare() -> None:
    print("\n[8] Glifos en pocas paginas no se eliminan")
    blocks = []
    for i in range(1, 11):
        extra = "xy\n" if i <= 2 else ""
        blocks.append(f"[PAGINA {i}]\n{extra}Texto estable en pagina {i}.")
    raw = "\n\n".join(blocks)
    out = clean_extracted_text(raw, light=True)
    check("conserva glifo raro", out.count("xy") == 2)


def main() -> int:
    print("=== validate_cleaner ===")
    test_headings_survive_frequency_filter()
    test_plain_titles_dropped_in_full_mode()
    test_light_mode_skips_frequency()
    test_light_mode_still_drops_page_numbers()
    test_equation_shard_salvage()
    test_equation_marker_not_frequency_dropped()
    test_glyph_header_filter_light_mode()
    test_glyph_line_not_dropped_if_rare()
    ok = sum(1 for _, passed in _results if passed)
    print(f"\n=== {ok}/{len(_results)} OK ===")
    return 0 if ok == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
