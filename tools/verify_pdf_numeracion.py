"""Verificación puntual: numeración en PDFs Tec. Materiales vs regex del Organizador."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agente-organizador"))
sys.path.insert(0, str(ROOT / "agente-contenido"))

from parser import (  # noqa: E402
    _SUBTEMA_NUM_RE,
    es_subtema_valido,
    extraer_candidatos_con_evidencia,
    extraer_texto,
)
from extractor import extract_text  # noqa: E402

INPUTS = ROOT / "data" / "tecnologia-de-materiales" / "inputs"
PDFS = sorted(INPUTS.glob("Tema *.pdf"), key=lambda p: int(p.stem.split()[-1]))

SIN_PUNTO_RE = re.compile(r"^\d+(?:\.\d+)*\s+\S")
CON_PUNTO_OPCIONAL_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S")
TEMA_HEADER_RE = re.compile(r"^\d+\.\S")


def strip_num_prefix(line: str) -> str:
    return re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", line).strip()


def main() -> None:
    print("=" * 80)
    print("VERIFICACION PDFs Tecnologia de Materiales")
    print("Regex Organizador (_SUBTEMA_NUM_RE):", _SUBTEMA_NUM_RE.pattern)
    print("=" * 80)

    totals = {"cands": 0, "near_miss": 0, "org_match_lines": 0}

    for pdf in PDFS:
        n = pdf.name
        data = pdf.read_bytes()
        texto_org = extraer_texto(data, n)
        texto_cnt = extract_text(str(pdf))
        cands = extraer_candidatos_con_evidencia(texto_org, n, data)

        lines = [ln.strip() for ln in texto_org.splitlines() if ln.strip()]
        num_like = [ln for ln in lines if re.match(r"^\d", ln) and len(ln) < 120]
        org_matches = [ln for ln in lines if _SUBTEMA_NUM_RE.match(ln)]
        near_miss = [
            ln
            for ln in lines
            if SIN_PUNTO_RE.match(ln) and not _SUBTEMA_NUM_RE.match(ln)
        ]

        totals["cands"] += len(cands)
        totals["near_miss"] += len(near_miss)
        totals["org_match_lines"] += len(org_matches)

        print(f"\n### {n} ###")
        print(f"  extraer_texto (org): {len(texto_org)} chars")
        print(f"  extract_text (cnt):  {len(texto_cnt)} chars")
        print(f"  extraer_candidatos_con_evidencia: {len(cands)} candidatos")
        print(f"  lineas _SUBTEMA_NUM_RE match: {len(org_matches)}")
        print(f"  near_miss (sin punto SI, org NO): {len(near_miss)}")

        print(f"  Muestra lineas con digito inicial ({min(12, len(num_like))} de {len(num_like)}):")
        for ln in num_like[:12]:
            m_org = bool(_SUBTEMA_NUM_RE.match(ln))
            m_sin = bool(SIN_PUNTO_RE.match(ln))
            m_tema = bool(TEMA_HEADER_RE.match(ln))
            nombre = strip_num_prefix(ln) if (m_org or m_sin or m_tema) else ""
            valid = es_subtema_valido(nombre) if nombre else False
            if m_org:
                flag = "MATCH_org"
            elif m_sin:
                flag = "MATCH_sin_punto"
            elif m_tema:
                flag = "MATCH_tema_header"
            else:
                flag = "NO_MATCH"
            print(f"    [{flag} valid={valid}] {ln[:95]!r}")

        if cands:
            print("  Primeros candidatos:")
            for c in cands[:5]:
                print(f"    - {c['nombre']!r} | {c['evidencia']}")
        elif near_miss:
            print("  Near-miss (primeras 6):")
            for ln in near_miss[:6]:
                nombre = strip_num_prefix(ln)
                print(f"    valid={es_subtema_valido(nombre)} | {ln[:95]!r}")

    print("\n" + "=" * 80)
    print("RESUMEN GLOBAL")
    print(f"  Total candidatos extraer_candidatos_con_evidencia: {totals['cands']}")
    print(f"  Total lineas _SUBTEMA_NUM_RE match: {totals['org_match_lines']}")
    print(f"  Total near_miss (3.2 Titulo sin punto final): {totals['near_miss']}")

    print("\n" + "=" * 80)
    print("FOCO Tema 1.pdf")
    print("=" * 80)
    pdf1 = INPUTS / "Tema 1.pdf"
    t_org = extraer_texto(pdf1.read_bytes(), "Tema 1.pdf")
    t_cnt = extract_text(str(pdf1))
    needles = [
        "PROPIEDADES MECANICAS",
        "Ensayo de tracción",
        "Ensayo de traccion",
        "Curva tensión",
    ]
    for label, t in [("ORG", t_org), ("CNT", t_cnt)]:
        print(f"\n--- {label} ---")
        for needle in needles:
            idx = t.lower().find(needle.lower())
            if idx >= 0:
                snippet = t[max(0, idx - 50) : idx + 130]
                print(f"  {needle!r} @ {idx}:")
                print(f"    {snippet!r}")

    # Comparar segmentor boundary para Seccion 3.2 si existe
    print("\n--- Prueba boundary segmentor (patron Seccion X.X) ---")
    from segmentor import _find_boundary_in_text  # noqa: E402

    sys.path.insert(0, str(ROOT / "agente-contenido"))
    for ev in ["Sección 3.2", "Sección 1.1"]:
        pos_org = _find_boundary_in_text(t_org, ev)
        pos_cnt = _find_boundary_in_text(t_cnt, ev)
        print(f"  {ev}: org={pos_org}, cnt={pos_cnt}")


if __name__ == "__main__":
    main()
