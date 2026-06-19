"""Pruebas offline ronda 2 — solo teoría (materiales distintos)."""
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

CASOS = [
    {
        "asignatura": "Elementos de Máquinas",
        "carpeta": "Elementos de maquinas",
        "teoria": "Cojinetes_2025.pdf",
        "ronda1": "Frenos_2025.pdf",
    },
    {
        "asignatura": "Oleohidráulica y Neumática",
        "carpeta": "Oleohidraulica",
        "teoria": "OyN_C2_Hydraulic_Components_part_I.pdf",
        "ronda1": "OyN_C1_Hyd_and_Pneu_technologies.pdf",
    },
    {
        "asignatura": "Tecnología de Materiales",
        "carpeta": "Tecnologia de materiales",
        "teoria": "Tema 2.pdf",
        "ronda1": "Tema 6.pdf",
    },
]


def _desglosar_estrategias(texto: str, nombre: str, raw: bytes) -> dict:
    num = org_parser._extraer_candidatos_numeracion(texto)
    visual: list[dict] = []
    if Path(nombre).suffix.lower() == ".pdf":
        for item in org_parser.extraer_titulos_visuales_pdf(raw):
            visual.append({
                "nombre": item["titulo"],
                "evidencia": item["referencia"],
                "fuente": "titulo_visual",
            })
    fusion = org_parser.extraer_candidatos_con_evidencia(texto, nombre, raw)
    return {
        "numeracion_n": len(num),
        "numeracion_muestra": num[:8],
        "visual_n": len(visual),
        "visual_muestra": visual[:8],
        "fusion_n": len(fusion),
        "fusion": fusion[:15],
        "estrategia_efectiva": (
            "numeracion"
            if len(num) >= org_parser._MIN_CANDIDATOS_NUMERACION
            else (
                "titulo_visual"
                if visual
                else ("numeracion_parcial" if num else "ninguna")
            )
        ),
    }


def _duplicados_numeracion(texto: str) -> dict[str, list[str]]:
    prefijos: dict[str, list[str]] = {}
    for c in org_parser._extraer_candidatos_numeracion(texto):
        m = re.search(r"Secci[oó]n\s+([\d.]+)", c.get("evidencia", ""), re.I)
        if m:
            prefijos.setdefault(m.group(1), []).append(c["nombre"])
    return {k: v for k, v in prefijos.items() if len(v) > 1}


def _probar_teoria(caso: dict, base: Path) -> dict:
    ruta = base / caso["teoria"]
    out: dict = {
        "archivo": caso["teoria"],
        "ronda1_archivo": caso["ronda1"],
        "ok": True,
        "errores": [],
    }
    try:
        raw = ruta.read_bytes()
        texto_org = org_parser.extraer_texto(raw, ruta.name)
        out["chars_texto_org"] = len(texto_org)
        out["clasificacion"] = org_parser.clasificar_archivo(ruta.name, texto_org)
        out.update(_desglosar_estrategias(texto_org, ruta.name, raw))

        lista = org_parser.detectar_candidatos_por_material(
            [texto_org], [ruta.name], [raw]
        )
        out["detectar_por_material_n"] = len(lista[0]) if lista else 0
        out["numeracion_duplicados_prefijo"] = _duplicados_numeracion(texto_org)

        texto_cnt = cnt_extract_text(str(ruta))
        out["chars_texto_cnt"] = len(texto_cnt or "")
        out["cnt_ilegible_n"] = (texto_cnt or "").count("[TEXTO_ILEGIBLE]")
        out["cnt_tiene_ilegible"] = out["cnt_ilegible_n"] > 0
        out["cnt_tiene_ecuacion"] = "[ECUACION]" in (texto_cnt or "")

        headings = [
            ln.strip()
            for ln in (texto_cnt or "").splitlines()
            if ln.strip().startswith("#")
        ]
        out["cnt_headings_n"] = len(headings)
        out["cnt_headings_muestra"] = headings[:10]
        out["cnt_headings_falsos_prosa"] = [
            h
            for h in headings
            if any(v in h.lower() for v in ("muestra", "figura", "tabla", "recuérd", "observe"))
        ][:6]
        out["cnt_headings_url"] = [h for h in headings if "http" in h.lower()][:5]
        out["cnt_headings_cortos"] = [h for h in headings if len(h.strip()) < 25][:8]

        chunks = split_into_chunks(texto_cnt or "")
        out["chunks_n"] = len(chunks)
        out["chunks_avg_chars"] = (
            sum(len(c) for c in chunks) // max(len(chunks), 1)
        )
        out["ratio_cnt_vs_org"] = (
            round(out["chars_texto_cnt"] / out["chars_texto_org"], 3)
            if out["chars_texto_org"]
            else 0
        )
    except Exception as exc:
        out["ok"] = False
        out["errores"].append(f"{type(exc).__name__}: {exc}")
        out["traceback"] = traceback.format_exc()
    return out


def main() -> None:
    informe = []
    for caso in CASOS:
        base = DATOS / caso["carpeta"]
        informe.append({
            "asignatura": caso["asignatura"],
            "teoria": _probar_teoria(caso, base),
        })
    print(json.dumps(informe, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
