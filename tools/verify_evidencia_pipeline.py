"""Valida propagación de evidencia y segmentación tras los cambios del pipeline."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agente-organizador"))
sys.path.insert(0, str(ROOT / "agente-contenido"))

from parser import (  # noqa: E402
    enriquecer_bloques_con_evidencia_detectada,
    evidencia_es_vacia,
    extraer_candidatos_con_evidencia,
    extraer_texto,
    parsear_bloques_organizador,
)
from extractor import extract_text  # noqa: E402
from segmentor import segment_text_by_subbloques  # noqa: E402

INPUTS = ROOT / "data" / "tecnologia-de-materiales" / "inputs"
MD_ORG = ROOT / "data" / "tecnologia-de-materiales" / "outputs" / "organizador" / "v1.md"


def main() -> None:
    if not MD_ORG.exists():
        print("SKIP: no existe", MD_ORG)
        return

    markdown = MD_ORG.read_text(encoding="utf-8")
    bloques = parsear_bloques_organizador(markdown)
    archivos, candidatos = [], []
    for pdf in sorted(INPUTS.glob("Tema *.pdf"), key=lambda p: int(p.stem.split()[-1])):
        data = pdf.read_bytes()
        texto = extraer_texto(data, pdf.name)
        archivos.append(pdf.name)
        candidatos.append(extraer_candidatos_con_evidencia(texto, pdf.name, data))

    enriquecidos = enriquecer_bloques_con_evidencia_detectada(bloques, candidatos, archivos)
    bloque1 = enriquecidos[0]
    print("=== Bloque 1 — evidencia enriquecida ===")
    print("archivo_origen:", bloque1.get("archivo_origen"))
    vacias = 0
    for sub in bloque1["subtemas"][:5]:
        ev = sub.get("evidencia", "")
        print(f"  {sub['nombre'][:45]:45} | {ev}")
        if evidencia_es_vacia(ev):
            vacias += 1
    print(f"subtemas con evidencia vacía (primeros 5): {vacias}/5")

    subs_meta = [
        {"nombre": s["nombre"], "evidencia": s["evidencia"]}
        for s in bloque1["subtemas"][:3]
    ]
    t1 = extract_text(str(INPUTS / "Tema 1.pdf"))
    segs = segment_text_by_subbloques(t1, subs_meta)
    print("\n=== Segmentación Tema 1 (3 primeros subbloques) ===")
    for sb, seg in segs:
        print(f"  {sb['nombre'][:42]:42} chars={len(seg.strip())}")


if __name__ == "__main__":
    main()
