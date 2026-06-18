#!/usr/bin/env python3
"""Validación de la pipeline de subbloques sin llamadas a la API.

Ejecutar desde agente-contenido/:
    python tools/validate_subbloques.py

Comprueba:
1. Parseo de subbloques desde .md del Organizador (tablas de 3 y 4 columnas)
2. Reparto monotono (ver también tools/validate_split_monotono.py)
3. Ensamblado del Markdown por bloque con marcadores SUBBLOQUE_INICIO/FIN
4. Cálculo de progreso (aprobados/total) con estados simulados
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Asegurar imports desde agente-contenido/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assembler import assemble_block_with_subbloques
from split_monotono import split_monotono
from subblock_state import SubbloqueResult, calcular_progreso_asignatura, calcular_progreso_bloque

# ── Utilidades de test ────────────────────────────────────────────────────────

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


# ── 1. Parseo del .md del Organizador ────────────────────────────────────────

ORG_MD_4COL = """\
# DISTRIBUCIÓN TEMÁTICA — Tecnología de Materiales

## Bloque 1 — Microestructura y endurecimiento · 8h

| Subtema | Horas | Evidencia | Origen |
|---------|-------|----------|--------|
| Defectos y dislocaciones | 3.0 | Sección 3.1 | Detectado |
| Mecanismos de endurecimiento | 3.0 | Sección 3.2 | Detectado |
| Fractura y fatiga | 2.0 | Sección 3.3 | Detectado |

## Bloque 2 — Tratamientos térmicos · 6h

| Subtema | Horas | Evidencia | Origen |
|---------|-------|----------|--------|
| Templado y revenido | 3.0 | Slide 12 | Detectado |
| Recocido y normalizado | 3.0 | Slide 18 | Detectado |
"""

ORG_MD_3COL = """\
## Bloque 3 — Aleaciones ligeras · 4h

| Subtema | Horas | Origen |
|---------|-------|--------|
| Aluminio | 2.0 | Manual |
| Titanio | 2.0 | Manual |
"""

ORG_MD_FALLBACK = """\
## Bloque 4 — Polímeros · 3h

| Subtema | Horas | Evidencia | Origen |
|---------|-------|----------|--------|
| Polímeros | 3.0 | Sin señal verificable | Fallback |
"""


def test_parseo_org_md() -> None:
    print("\n[1] Parseo del .md del Agente Organizador")
    _org_root = Path(__file__).resolve().parent.parent.parent / "agente-organizador"
    if str(_org_root) not in sys.path:
        sys.path.insert(0, str(_org_root))
    from parser import parse_organization_md

    bloques = parse_organization_md(ORG_MD_4COL + "\n" + ORG_MD_3COL + "\n" + ORG_MD_FALLBACK)

    check("Detecta 4 bloques", len(bloques) == 4, f"encontrados: {len(bloques)}")

    b1 = bloques[0]
    check("Bloque 1: nombre correcto", b1["nombre"] == "Microestructura y endurecimiento")
    check("Bloque 1: horas correctas", b1["horas"] == 8.0)
    check("Bloque 1: 3 subbloques (4 cols)", len(b1["subbloques"]) == 3)

    sb1 = b1["subbloques"][0]
    check("Sub1 nombre", sb1["nombre"] == "Defectos y dislocaciones")
    # Horas por subtema: el parser unificado deja 0.0 (solo aplica a nivel de bloque).
    check("Sub1 horas (bloque aplica densidad)", sb1["horas"] == 0.0)
    check("Sub1 evidencia", sb1["evidencia"] == "Sección 3.1")
    check("Sub1 origen", sb1["origen"] == "Detectado")

    b3 = bloques[2]
    check("Bloque 3: 2 subbloques (3 cols sin Evidencia)", len(b3["subbloques"]) == 2)
    sb3 = b3["subbloques"][0]
    check("Sub3 nombre", sb3["nombre"] == "Aluminio")
    check("Sub3 evidencia vacía en tabla 3-col", sb3["evidencia"] == "")

    b4 = bloques[3]
    check("Bloque 4 fallback: 1 subbloque", len(b4["subbloques"]) == 1)
    check(
        "Bloque 4 fallback: evidencia Sin señal",
        "sin señal" in b4["subbloques"][0]["evidencia"].lower(),
    )


# ── 2. Reparto monótono (sustituye segmentación de PDF bruto) ─────────────────

def test_split_monotono_basico() -> None:
    print("\n[2] Reparto monótono sobre markdown curado")
    md = """---
tema_detectado: Tema
---

### Alpha

Contenido A.

### Beta

Contenido B.
"""
    subs = [
        {"id": 1, "nombre": "Alpha", "orden": 1, "evidencia": ""},
        {"id": 2, "nombre": "Beta", "orden": 2, "evidencia": ""},
    ]
    r = split_monotono(md, subs)
    check("2 fragmentos", len(r.fragmentos) == 2)
    check("alpha en frag 1", "Contenido A" in r.fragmentos[0].markdown)
    check("beta en frag 2", "Contenido B" in r.fragmentos[1].markdown)


# ── 3. Ensamblado con marcadores SUBBLOQUE_INICIO/FIN ───────────────────────

def test_ensamblado() -> None:
    print("\n[3] Ensamblado del Markdown con marcadores de subbloque")

    items_dummy = [
        {
            "tipo": "teoria",
            "titulo_detectado": "Defectos",
            "idioma": "es",
            "contenido_markdown": "## Contenido teórico\n\nTexto de defectos.",
        }
    ]
    sb_list = [
        {
            "nombre": "Defectos y dislocaciones",
            "horas": 3.0,
            "evidencia": "Sección 3.1",
            "origen": "Detectado",
            "estado": "generado",
            "markdown": "# Defectos y dislocaciones\n\n## Contenido teórico\n\nTexto.",
            "items": items_dummy,
            "validacion": {"ok": True, "errores": [], "fidelity": []},
        },
        {
            "nombre": "Mecanismos de endurecimiento",
            "horas": 3.0,
            "evidencia": "Sección 3.2",
            "origen": "Detectado",
            "estado": "pendiente",
            "markdown": "",
            "items": [],
            "validacion": {"ok": True, "errores": [], "fidelity": []},
        },
    ]

    md = assemble_block_with_subbloques(
        sb_list,
        nombre_del_archivo="Tema3.pdf",
        nombre_bloque="Microestructura y endurecimiento",
        bloque_horas=8.0,
    )

    check("Contiene frontmatter YAML", md.startswith("---"))
    check("Contiene bloque:", 'bloque: Microestructura' in md)
    check("Contiene total_subbloques: 2", "total_subbloques: 2" in md)

    # Verificar marcadores
    inicios = re.findall(r'<!-- SUBBLOQUE_INICIO: (.*?) -->', md)
    fines = re.findall(r'<!-- SUBBLOQUE_FIN: (.*?) -->', md)
    check("2 marcadores INICIO", len(inicios) == 2, f"encontrados: {len(inicios)}")
    check("2 marcadores FIN", len(fines) == 2, f"encontrados: {len(fines)}")
    check('INICIO 0 contiene nombre="Defectos', 'nombre="Defectos' in inicios[0])
    check('INICIO 0 contiene estado="generado"', 'estado="generado"' in inicios[0])
    check('INICIO 1 contiene estado="pendiente"', 'estado="pendiente"' in inicios[1])
    check("Subbloque pendiente tiene placeholder", "*Contenido pendiente de procesar.*" in md)

    # Verificar que el Markdown es seccionable: se puede extraer cada cuerpo
    sb_bodies = re.findall(
        r'<!-- SUBBLOQUE_INICIO:.*?-->\s*(.*?)\s*<!-- SUBBLOQUE_FIN:.*?-->',
        md,
        re.DOTALL,
    )
    check("Se pueden extraer 2 cuerpos de subbloque", len(sb_bodies) == 2)
    check("Cuerpo 0 contiene texto real", "Defectos" in sb_bodies[0])


# ── 4. Cálculo de progreso ────────────────────────────────────────────────────

def test_progreso() -> None:
    print("\n[4] Cálculo de progreso (aprobados/total)")

    sb_a = SubbloqueResult(
        nombre="Sub A", horas=3.0, evidencia="Sección 3.1", origen="Detectado",
        estado="aprobado", markdown="...", items=[], validacion={},
    )
    sb_b = SubbloqueResult(
        nombre="Sub B", horas=3.0, evidencia="Sección 3.2", origen="Detectado",
        estado="generado", markdown="...", items=[], validacion={},
    )
    sb_c = SubbloqueResult(
        nombre="Sub C", horas=2.0, evidencia="Sección 3.3", origen="Detectado",
        estado="pendiente", markdown="", items=[], validacion={},
    )

    progreso_bloque = calcular_progreso_bloque([sb_a, sb_b, sb_c])
    check("Bloque: total = 3", progreso_bloque["total"] == 3)
    check("Bloque: aprobados = 1", progreso_bloque["aprobados"] == 1)
    check("Bloque: porcentaje = 33.3%", progreso_bloque["porcentaje"] == 33.3)

    sb_d = SubbloqueResult(
        nombre="Sub D", horas=2.0, evidencia="Sección 4.1", origen="Detectado",
        estado="aprobado", markdown="...", items=[], validacion={},
    )
    progreso_asig = calcular_progreso_asignatura([sb_a, sb_b, sb_c, sb_d])
    check("Asignatura: total = 4", progreso_asig["total"] == 4)
    check("Asignatura: aprobados = 2", progreso_asig["aprobados"] == 2)
    check("Asignatura: porcentaje = 50.0%", progreso_asig["porcentaje"] == 50.0)

    # Escenario: todos aprobados
    progreso_completo = calcular_progreso_bloque([sb_a, sb_d])
    check("Todos aprobados: 100%", progreso_completo["porcentaje"] == 100.0)

    # Escenario: ninguno aprobado
    progreso_cero = calcular_progreso_bloque([sb_b, sb_c])
    check("Ninguno aprobado: 0%", progreso_cero["porcentaje"] == 0.0)


# ── 5. Fallback: bloque sin subbloques (comportamiento clásico) ───────────────

def test_fallback_sin_subbloques() -> None:
    print("\n[5] Ensamblado: bloque con un único subbloque")

    md = assemble_block_with_subbloques(
        [{"nombre": "Polimeros", "horas": 3.0, "evidencia": "Sin senal verificable",
          "origen": "Fallback", "estado": "generado", "markdown": "# Polimeros\n\nContenido.",
          "items": [], "validacion": {}}],
        nombre_del_archivo="tema_pol.pdf",
        nombre_bloque="Polimeros",
        bloque_horas=3.0,
    )
    check("Fallback: total_subbloques: 1 en frontmatter", "total_subbloques: 1" in md)
    inicios = re.findall(r'<!-- SUBBLOQUE_INICIO:.*?-->', md)
    check("Fallback: 1 marcador INICIO", len(inicios) == 1)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Validación de la pipeline de subbloques")
    print("=" * 60)

    test_parseo_org_md()
    test_split_monotono_basico()
    test_ensamblado()
    test_progreso()
    test_fallback_sin_subbloques()

    total = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    failed = total - passed
    print(f"\n{'=' * 60}")
    print(f"Resultado: {passed}/{total} checks pasados" + (f" — {failed} FALLIDOS" if failed else " — TODOS OK"))
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
