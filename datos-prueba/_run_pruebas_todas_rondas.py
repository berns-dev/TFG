"""Ejecuta las 3 rondas de prueba offline y compara métricas clave."""
from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from pathlib import Path

logging.disable(logging.CRITICAL)

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-organizador"))
sys.path.insert(0, str(RAIZ / "agente-contenido"))

import parser as org_parser  # noqa: E402
from chunker import split_into_chunks  # noqa: E402
from extractor import extract_text as cnt_extract_text  # noqa: E402

DATOS = Path(__file__).resolve().parent

RONDAS = [
    {
        "ronda": 1,
        "casos": [
            {"asignatura": "Elementos", "carpeta": "Elementos de maquinas", "teoria": "Frenos_2025.pdf"},
            {"asignatura": "Oleohidráulica", "carpeta": "Oleohidraulica", "teoria": "OyN_C1_Hyd_and_Pneu_technologies.pdf"},
            {"asignatura": "Tec. Materiales", "carpeta": "Tecnologia de materiales", "teoria": "Tema 6.pdf"},
        ],
    },
    {
        "ronda": 2,
        "casos": [
            {"asignatura": "Elementos", "carpeta": "Elementos de maquinas", "teoria": "Cojinetes_2025.pdf"},
            {"asignatura": "Oleohidráulica", "carpeta": "Oleohidraulica", "teoria": "OyN_C2_Hydraulic_Components_part_I.pdf"},
            {"asignatura": "Tec. Materiales", "carpeta": "Tecnologia de materiales", "teoria": "Tema 2.pdf"},
        ],
    },
    {
        "ronda": 3,
        "casos": [
            {"asignatura": "Elementos", "carpeta": "Elementos de maquinas", "teoria": "Resortes_2025.pdf"},
            {"asignatura": "Oleohidráulica", "carpeta": "Oleohidraulica", "teoria": "OyN_C3_Pneumatics_part_I.pdf"},
            {"asignatura": "Tec. Materiales", "carpeta": "Tecnologia de materiales", "teoria": "Tema 4.pdf"},
        ],
    },
]


def _probar_teoria(carpeta: str, teoria: str) -> dict:
    ruta = DATOS / carpeta / teoria
    out: dict = {"archivo": teoria, "ok": True}
    try:
        raw = ruta.read_bytes()
        texto_org = org_parser.extraer_texto(raw, ruta.name)
        num = org_parser._extraer_candidatos_numeracion(texto_org)
        visual = list(org_parser.extraer_titulos_visuales_pdf(raw))
        fusion = org_parser.extraer_candidatos_con_evidencia(texto_org, ruta.name, raw)

        texto_cnt = cnt_extract_text(str(ruta)) or ""
        headings = [ln.strip() for ln in texto_cnt.splitlines() if ln.strip().startswith("#")]
        chunks = split_into_chunks(texto_cnt)

        prefijos_dup = {}
        for c in num:
            m = re.search(r"Secci[oó]n\s+([\d.]+)", c.get("evidencia", ""), re.I)
            if m:
                prefijos_dup.setdefault(m.group(1), []).append(c["nombre"])
        dups = {k: v for k, v in prefijos_dup.items() if len(v) > 1}

        out.update({
            "numeracion_n": len(num),
            "visual_n": len(visual),
            "fusion_n": len(fusion),
            "estrategia": (
                "numeracion" if len(num) >= org_parser._MIN_CANDIDATOS_NUMERACION
                else ("titulo_visual" if visual else "ninguna")
            ),
            "ratio_cnt_org": round(len(texto_cnt) / len(texto_org), 3) if texto_org else 0,
            "headings_n": len(headings),
            "temario_headings": sum(1 for h in headings if re.search(r"tema\s+\d", h.lower())),
            "chunks_n": len(chunks),
            "ilegible_n": texto_cnt.count("[TEXTO_ILEGIBLE]"),
            "numeracion_dups": len(dups),
            "fusion_muestra": [c["nombre"][:50] for c in fusion[:5]],
        })
    except Exception as exc:
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["traceback"] = traceback.format_exc()
    return out


def _probar_guia_elementos() -> dict:
    ruta = DATOS / "Elementos de maquinas" / "Guia docente - elementos de maquinas.pdf"
    raw = ruta.read_bytes()
    t = org_parser.extraer_texto(raw, ruta.name)
    subtemas = org_parser.extraer_subtemas_guia(t)
    return {
        "n_subtemas_guia": len(subtemas),
        "modo_prompt_libre": org_parser.modo_prompt_libre(t),
        "subtemas": subtemas,
    }


def main() -> None:
    informe = {"guia_elementos": _probar_guia_elementos(), "rondas": []}
    for bloque in RONDAS:
        ronda_out = {"ronda": bloque["ronda"], "casos": []}
        for caso in bloque["casos"]:
            ronda_out["casos"].append({
                "asignatura": caso["asignatura"],
                "teoria": _probar_teoria(caso["carpeta"], caso["teoria"]),
            })
        informe["rondas"].append(ronda_out)

    out = DATOS / "_resultados_post_fix.json"
    out.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
