# -*- coding: utf-8 -*-
"""Mini-fixture de validación del razonador de visualización.

Ejecuta el razonador (Sonnet) sobre un conjunto de casos canónicos y muestra el
patrón elegido y la separación familia / sliders / descartados. Aplica
heurísticas SUAVES (no asserts estrictos: el razonador es estocástico y cada
caso cuesta una llamada a la API) para señalar regresiones obvias, p. ej. un
slider decorativo o una poda excesiva (un caso explorable que se queda sin
ningún control).

Cobertura de los tres tipos de parámetro (paso 2 del razonador):
  - Hall-Petch      → constantes fijas (F): CURVA_SIMPLE sin sliders.
  - Caudal Q(P_i,P_s) → familia discreta (D) + reescalado (F): FAMILIA, S descartado.
  - Gay-Lussac      → parámetro continuo explorable (C): CURVA_SIMPLE con slider.
  - σ por material  → familia categórica (D no numérica): FAMILIA_CURVAS.

Uso:
    py tools/razonador_fixture.py             # 1 pasada por caso
    py tools/razonador_fixture.py --repeat 3  # 3 pasadas (estabilidad)
    py tools/razonador_fixture.py --caso hall # filtra casos por subcadena

Herramienta de desarrollo: NO forma parte del pipeline y consume créditos de
API (como tools/validate_pdf.py del Agente Contenido).
"""
from __future__ import annotations

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import anthropic

from config import ANTHROPIC_API_KEY, REQUEST_TIMEOUT_SECONDS
from generador_html import _razonar_visualizacion


def _n(s: str | None) -> str:
    return (s or "").lower()


# ---------------------------------------------------------------------------
# Heurísticas suaves de comprobación: (ok, motivo_si_falla)
# ---------------------------------------------------------------------------

def chk_hallpetch(v: dict) -> tuple[bool, str]:
    sl = _n(v.get("PARAMETROS_SLIDER"))
    if "k_y" in sl or "ky" in sl or "sigma" in sl:
        return False, "k_y/σ_0 como slider (deberían quedar fijos / descartados)"
    return True, ""


def chk_caudal(v: dict) -> tuple[bool, str]:
    fam = _n(v.get("PARAMETRO_FAMILIA"))
    sl = _n(v.get("PARAMETROS_SLIDER"))
    desc = _n(v.get("SLIDERS_DESCARTADOS"))
    if "p_s" in sl or "ps" in sl:
        return False, "P_s aparece como slider en vez de como familia"
    if "p_s" not in fam and "ps" not in fam:
        return False, "P_s no está marcado como PARAMETRO_FAMILIA"
    if "s" not in desc:
        return False, "S (reescala) no está en SLIDERS_DESCARTADOS"
    return True, ""


def chk_continuo(v: dict) -> tuple[bool, str]:
    sl = _n(v.get("PARAMETROS_SLIDER")).strip()
    fam = _n(v.get("PARAMETRO_FAMILIA")).strip()
    sin_familia = (not fam) or fam == "ninguno"
    if not sl and sin_familia:
        return False, "poda excesiva: caso explorable sin slider ni familia"
    return True, ""


def chk_material(v: dict) -> tuple[bool, str]:
    fam = _n(v.get("PARAMETRO_FAMILIA")).strip()
    if not fam or fam == "ninguno":
        return False, "se esperaba familia categórica (material), no la hay"
    return True, ""


CASOS = [
    {
        "nombre": "Hall-Petch (constantes fijas)",
        "expresion": r"\sigma_y = \sigma_0 + \frac{k_y}{\sqrt{d}}",
        "contexto": (
            "El límite elástico aumenta al reducir el tamaño de grano d. sigma_0 "
            "es la tensión de fricción de la red y k_y una constante del material "
            "(coeficiente de Hall-Petch). Para el acero suave sigma_0 ~ 70 MPa y "
            "k_y ~ 0.74 MPa·m^0.5."
        ),
        "variables_entrada": [
            {"nombre": "d", "unidades": "um"},
            {"nombre": "k_y", "unidades": "MPa·m^0.5"},
            {"nombre": "sigma_0", "unidades": "MPa"},
        ],
        "variable_salida": {"nombre": "sigma_y", "unidades": "MPa"},
        "esperado": "CURVA_SIMPLE; k_y y sigma_0 descartados (fijos). Sin sliders decorativos.",
        "check": chk_hallpetch,
    },
    {
        "nombre": "Caudal Q(P_i, P_s) (familia + reescala)",
        "expresion": r"Q = 22.2 \, S \sqrt{P_s + 1.013} \sqrt{P_i - P_s}",
        "contexto": (
            "Relación entre la presión de entrada P_i y la de salida P_s (en bar) "
            "y el caudal Q (l/min) para una sección equivalente S (mm^2) de un "
            "elemento neumático. Existe flujo si P_i > P_s. La sección S escala el "
            "caudal de forma lineal. Presiones típicas 0-10 bar."
        ),
        "variables_entrada": [
            {"nombre": "P_i", "unidades": "bar"},
            {"nombre": "P_s", "unidades": "bar"},
            {"nombre": "S", "unidades": "mm^2"},
        ],
        "variable_salida": {"nombre": "Q", "unidades": "l/min"},
        "esperado": "FAMILIA_CURVAS con P_s como familia discreta; S descartado (reescala).",
        "check": chk_caudal,
    },
    {
        "nombre": "Gay-Lussac (parámetro continuo)",
        "expresion": r"V = V_0 (1 + \alpha T)",
        "contexto": (
            "A presión constante el volumen de un gas varía linealmente con la "
            "temperatura. alpha = 1/273 K^-1 es el coeficiente de dilatación "
            "(constante del gas). El volumen inicial V_0 depende del recipiente y "
            "el alumno explora cómo cambia la recta al variarlo. Rango -50 a 150 C."
        ),
        "variables_entrada": [
            {"nombre": "T", "unidades": "C"},
            {"nombre": "V_0", "unidades": "L"},
            {"nombre": "alpha", "unidades": "1/K"},
        ],
        "variable_salida": {"nombre": "V", "unidades": "L"},
        "esperado": "CURVA_SIMPLE con slider V_0 (continuo); alpha fijo. No debe quedarse sin control.",
        "check": chk_continuo,
    },
    {
        "nombre": "Tension-deformacion por material (familia categorica)",
        "expresion": r"\sigma = E \varepsilon",
        "contexto": (
            "En la zona elástica la tensión es proporcional a la deformación con "
            "pendiente el módulo de Young E. Para comparar el comportamiento de "
            "varios materiales (acero E=210 GPa, aluminio E=70 GPa, titanio "
            "E=110 GPa) se representan sus rectas en el mismo diagrama."
        ),
        "variables_entrada": [
            {"nombre": "epsilon", "unidades": "-"},
            {"nombre": "E", "unidades": "GPa"},
        ],
        "variable_salida": {"nombre": "sigma", "unidades": "MPa"},
        "esperado": "FAMILIA_CURVAS con material/E como familia categórica.",
        "check": chk_material,
    },
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Mini-fixture del razonador de visualización.")
    ap.add_argument("--repeat", type=int, default=1, help="pasadas por caso (estabilidad)")
    ap.add_argument("--caso", default="", help="filtra casos por subcadena del nombre")
    args = ap.parse_args()

    if not ANTHROPIC_API_KEY:
        print("ERROR: falta ANTHROPIC_API_KEY en el .env")
        sys.exit(1)

    client = anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY, timeout=float(REQUEST_TIMEOUT_SECONDS)
    )
    casos = [c for c in CASOS if args.caso.lower() in c["nombre"].lower()]

    total = revisar = 0
    for c in casos:
        print("=" * 76)
        print(c["nombre"])
        print("  esperado:", c["esperado"])
        for i in range(args.repeat):
            try:
                v = _razonar_visualizacion(c, client)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i + 1}] ERROR: {exc}")
                continue
            ok, motivo = c["check"](v)
            total += 1
            if not ok:
                revisar += 1
            flag = "OK     " if ok else "REVISAR"
            desc = (v.get("SLIDERS_DESCARTADOS") or "").replace("\n", " | ")
            print(
                f"  [{i + 1}] {flag} | PATRON={v.get('PATRON')}"
                f" | FAMILIA={v.get('PARAMETRO_FAMILIA')!r}"
                f" | SLIDERS={v.get('PARAMETROS_SLIDER')!r}"
                f" | DESCARTADOS={desc[:70]!r}"
            )
            if not ok:
                print("         →", motivo)
    print("=" * 76)
    print(f"Resumen: {total - revisar}/{total} OK, {revisar} a revisar.")


if __name__ == "__main__":
    main()
