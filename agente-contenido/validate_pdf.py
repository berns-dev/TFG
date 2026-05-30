"""
Validación local del pipeline extract → clean → chunk (sin API).

Uso:
  python validate_pdf.py "ruta/archivo.pdf"
  python validate_pdf.py "ruta/archivo.pptx"

Requiere ejecutarse desde la raíz del proyecto o con PYTHONPATH apuntando a ella.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# Raíz del proyecto = directorio de este script
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chunker import split_into_chunks  # noqa: E402
from extractor import extract_text  # noqa: E402

_PAGE_MARK_RE = re.compile(
    r"^\[(?P<kind>PAGINA|SLIDE)\s+(?P<num>\d+)\]\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def _split_pages_or_slides(text: str) -> list[tuple[str, str]]:
    """Trocea por marcadores [PAGINA n] / [SLIDE n] (mismo criterio que cleaner._split_sections)."""
    text = (text or "").strip()
    if not text:
        return []
    matches = list(_PAGE_MARK_RE.finditer(text))
    if not matches:
        return [("(sin marcador)", text)]
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        label = m.group(0).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        blocks.append((label, body))
    return blocks


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except OSError:
                pass


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(self.format(record))
        except Exception:
            self.handleError(record)


def main() -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Valida extractor → cleaner → chunker sobre PDF o PPTX (sin API)."
    )
    parser.add_argument(
        "documento",
        type=Path,
        help="Ruta a un .pdf o .pptx",
    )
    args = parser.parse_args()
    path: Path = args.documento.expanduser().resolve()
    if not path.is_file():
        print(f"No existe el archivo: {path}", file=sys.stderr)
        return 2
    suf = path.suffix.lower()
    if suf not in (".pdf", ".pptx"):
        print("El archivo debe ser .pdf o .pptx", file=sys.stderr)
        return 2

    cleaner_log = logging.getLogger("cleaner")
    cleaner_log.setLevel(logging.INFO)
    list_handler = _ListHandler()
    fmt = logging.Formatter("%(levelname)s %(name)s: %(message)s")
    list_handler.setFormatter(fmt)
    # Quitar handlers del cleaner (p. ej. StreamHandler del import) para que los INFO
    # no vayan a stderr mezclados con stdout al usar 2>&1 en PowerShell.
    saved_handlers = list(cleaner_log.handlers)
    for h in saved_handlers:
        cleaner_log.removeHandler(h)
    cleaner_log.addHandler(list_handler)

    try:
        # extract_text aplica clean_extracted_text internamente página/slide a página/slide.
        # No hay un paso de limpieza separado: extracción y limpieza son una sola fase.
        print("=== 1) extractor.extract_text (extracción + limpieza integrada) ===")
        extracted = extract_text(str(path))
        print(f"(longitud total tras extracción y limpieza, chars: {len(extracted)})")
    finally:
        cleaner_log.removeHandler(list_handler)
        for h in saved_handlers:
            cleaner_log.addHandler(h)

    print("\n=== Primeras 3 páginas / diapositivas (texto ya limpio) ===")
    blocks = _split_pages_or_slides(extracted)
    for label, body in blocks[:3]:
        print("-" * 60)
        print(label)
        print("-" * 60)
        print(body if body else "(vacío)")
        print()

    print("=== Log del cleaner (INFO: líneas por frecuencia y ratio) ===")
    freq_lines = [r for r in list_handler.records if "frecuencia" in r.lower()]
    if not list_handler.records:
        print("(sin registros INFO del logger cleaner en esta ejecución)")
    else:
        for line in list_handler.records:
            print(line)
    print(f"\n(Resumen: {len(freq_lines)} mensajes relacionados con frecuencia estructural)")

    print("\n=== 2) chunker.split_into_chunks ===")
    chunks = split_into_chunks(extracted)
    n = len(chunks)
    if n == 0:
        print("0 chunks")
    else:
        sizes = [len(c) for c in chunks]
        mean = sum(sizes) / n
        print(f"Chunks totales: {n}")
        print(f"Tamaño medio (caracteres): {mean:.1f}")
        print(f"Mín / máx (caracteres): {min(sizes)} / {max(sizes)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
