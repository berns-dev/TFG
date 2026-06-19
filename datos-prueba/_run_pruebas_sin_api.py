"""Pruebas offline (sin API) sobre datos-prueba — informe en stdout."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "agente-organizador"))
sys.path.insert(0, str(RAIZ / "agente-contenido"))
sys.path.insert(0, str(RAIZ))

import parser as org_parser  # noqa: E402
from extractor import extract_text as cnt_extract_text  # noqa: E402

DATOS = Path(__file__).resolve().parent

CASOS = [
    {
        "asignatura": "Elementos de Máquinas",
        "carpeta": "Elementos de maquinas",
        "guia": "Guia docente - elementos de maquinas.pdf",
        "teoria": "Frenos_2025.pdf",
    },
    {
        "asignatura": "Oleohidráulica y Neumática",
        "carpeta": "Oleohidraulica",
        "guia": "GUIA DOCENTE - oleohidraulica.pdf",
        "teoria": "OyN_C1_Hyd_and_Pneu_technologies.pdf",
    },
    {
        "asignatura": "Tecnología de Materiales",
        "carpeta": "Tecnologia de materiales",
        "guia": "Guia docente - tec. de materiales.pdf",
        "teoria": "Tema 6.pdf",
    },
]


def _leer_pdf(ruta: Path) -> bytes:
    return ruta.read_bytes()


def _probar_guia(caso: dict, base: Path) -> dict:
    ruta = base / caso["guia"]
    out: dict = {"archivo": caso["guia"], "ok": True, "errores": []}
    try:
        raw = _leer_pdf(ruta)
        texto = org_parser.extraer_texto(raw, ruta.name)
        out["chars_texto"] = len(texto)
        horas = org_parser.extraer_horas_docencia(texto)
        out["horas"] = horas
        te_pa = horas["horas_teoria"] + horas["horas_aula"]
        out["horas_te_pa_ok"] = te_pa > 0
        subtemas_guia = org_parser.extraer_subtemas_guia(texto)
        out["subtemas_guia"] = subtemas_guia[:12]
        out["n_subtemas_guia"] = len(subtemas_guia)
        out["modo_prompt_libre"] = org_parser.modo_prompt_libre(texto)
        out["categoria"] = org_parser.clasificar_archivo(ruta.name, texto)
    except Exception as exc:
        out["ok"] = False
        out["errores"].append(f"{type(exc).__name__}: {exc}")
    return out


def _desglosar_estrategias(texto: str, nombre: str, raw: bytes) -> dict:
  """Ejecuta cada estrategia por separado para diagnóstico."""
  num = org_parser._extraer_candidatos_numeracion(texto)
  visual: list = []
  slides: list = []
  ext = Path(nombre).suffix.lower()
  if ext == ".pdf":
      for item in org_parser.extraer_titulos_visuales_pdf(raw):
          visual.append({
              "nombre": item["titulo"],
              "evidencia": item["referencia"],
              "fuente": "titulo_visual",
          })
  elif ext == ".pptx":
      for item in org_parser.extraer_titulos_slides_pptx(raw):
          slides.append({
              "nombre": item["titulo"],
              "evidencia": item["referencia"],
              "fuente": "titulo_slide",
          })
  fusion = org_parser.extraer_candidatos_con_evidencia(texto, nombre, raw)
  return {
      "numeracion_n": len(num),
      "numeracion_muestra": num[:8],
      "visual_n": len(visual),
      "visual_muestra": visual[:8],
      "slides_n": len(slides),
      "fusion_n": len(fusion),
      "fusion": fusion[:15],
      "estrategia_efectiva": (
          "numeracion" if len(num) >= org_parser._MIN_CANDIDATOS_NUMERACION
          else ("titulo_slide" if slides and not visual else (
              "titulo_visual" if visual else (
                  "numeracion_parcial" if num else "ninguna"
              )
          ))
      ),
  }


def _probar_teoria(caso: dict, base: Path) -> dict:
    ruta = base / caso["teoria"]
    out: dict = {"archivo": caso["teoria"], "ok": True, "errores": []}
    try:
        raw = _leer_pdf(ruta)
        texto_org = org_parser.extraer_texto(raw, ruta.name)
        out["chars_texto_org"] = len(texto_org)
        out["clasificacion"] = org_parser.clasificar_archivo(ruta.name, texto_org)

        detalle = _desglosar_estrategias(texto_org, ruta.name, raw)
        out.update(detalle)

        lista = org_parser.detectar_candidatos_por_material(
            [texto_org], [ruta.name], [raw]
        )
        out["detectar_por_material_n"] = len(lista[0]) if lista else 0

        # Agente Contenido — extracción
        texto_cnt = cnt_extract_text(str(ruta))
        out["chars_texto_cnt"] = len(texto_cnt or "")
        out["cnt_tiene_ilegible"] = "[TEXTO_ILEGIBLE]" in (texto_cnt or "")
        out["cnt_tiene_ecuacion"] = "[ECUACION]" in (texto_cnt or "")
        headings = [
            ln.strip()
            for ln in (texto_cnt or "").splitlines()
            if ln.strip().startswith("#")
        ]
        out["cnt_headings_n"] = len(headings)
        out["cnt_headings_muestra"] = headings[:8]

        ratio = (out["chars_texto_cnt"] / out["chars_texto_org"]) if out["chars_texto_org"] else 0
        out["ratio_cnt_vs_org"] = round(ratio, 3)

    except Exception as exc:
        out["ok"] = False
        out["errores"].append(f"{type(exc).__name__}: {exc}")
        out["traceback"] = traceback.format_exc()
    return out


def main() -> None:
    informe: list[dict] = []
    for caso in CASOS:
        base = DATOS / caso["carpeta"]
        bloque = {
            "asignatura": caso["asignatura"],
            "guia": _probar_guia(caso, base),
            "teoria": _probar_teoria(caso, base),
        }
        informe.append(bloque)

    print(json.dumps(informe, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
