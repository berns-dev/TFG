"""Verifica segmentación con/sin evidencia y con uno vs todos los PDFs."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agente-organizador"))
sys.path.insert(0, str(ROOT / "agente-contenido"))

from parser import extraer_candidatos_con_evidencia, extraer_texto  # noqa: E402
from extractor import extract_text  # noqa: E402
from segmentor import segment_text_by_subbloques  # noqa: E402

INPUTS = ROOT / "data" / "tecnologia-de-materiales" / "inputs"
pdf1 = INPUTS / "Tema 1.pdf"

subs_sin_ev = [
    {"nombre": "PROPIEDADES MECANICAS FUNDAMENTALES", "evidencia": "—"},
    {"nombre": "Ensayo de tracción", "evidencia": "—"},
    {"nombre": "Curva tensión-deformación verdadera", "evidencia": "—"},
]

cands = extraer_candidatos_con_evidencia(
    extraer_texto(pdf1.read_bytes(), "Tema 1.pdf"), "Tema 1.pdf", None
)
subs_con_ev = [{"nombre": c["nombre"], "evidencia": c["evidencia"]} for c in cands[:3]]

t1 = extract_text(str(pdf1))
paths = sorted(INPUTS.glob("Tema *.pdf"), key=lambda p: int(p.stem.split()[-1]))
all_text = "\n\n".join(extract_text(str(p)) for p in paths)

cases = [
    ("Tema1 solo, sin evidencia BD", t1, subs_sin_ev),
    ("Tema1 solo, con evidencia detectada", t1, subs_con_ev),
    ("11 PDFs, sin evidencia BD", all_text, subs_sin_ev),
    ("11 PDFs, con evidencia Sección 1.1…", all_text, subs_con_ev),
]

for label, texto, subs in cases:
    segs = segment_text_by_subbloques(texto, subs)
    print("===", label, "===")
    for sb, seg in segs:
        ev = sb.get("evidencia", "")
        print(f"  {sb['nombre'][:42]:42} ev={ev[:14]:14} chars={len(seg.strip())}")
    print()
