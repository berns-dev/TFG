#!/usr/bin/env python3
"""Validación de la pipeline de subbloques sin llamadas a la API.

Ejecutar desde agente-contenido/:
    python tools/validate_subbloques.py

Comprueba:
1. Parseo de subbloques desde .md del Organizador (tablas de 3 y 4 columnas)
2. Segmentación de texto extraído por subbloques (Slide N, Sección X.X, fallback)
3. Ensamblado del Markdown por bloque con marcadores SUBBLOQUE_INICIO/FIN
4. Cálculo de progreso (aprobados/total) con estados simulados
5. Tratamiento del bloque fallback (único subbloque, "Sin señal verificable")
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Asegurar imports desde agente-contenido/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assembler import assemble_block_with_subbloques
from segmentor import segment_text_by_subbloques
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


# ── 2. Segmentación de texto ──────────────────────────────────────────────────

TEXTO_PDF = """\
[PAGINA 1]
Introducción general al tema.

3.1. Defectos y dislocaciones
Los defectos cristalinos incluyen vacancias, dislocaciones y juntas de grano.
Las dislocaciones son los portadores de la deformación plástica.

3.2. Mecanismos de endurecimiento
Los cuatro mecanismos principales son: solución sólida, deformación plástica,
afino de grano y precipitación. Cada uno actúa obstaculizando las dislocaciones.

3.3. Fractura y fatiga
La fractura puede ser dúctil o frágil. La fatiga ocurre bajo cargas cíclicas.
"""

TEXTO_PPTX = """\
[SLIDE 1]
# Introducción

[SLIDE 12]
# Templado y revenido
El templado consiste en calentar el acero y enfriarlo bruscamente en agua o aceite.
El revenido reduce las tensiones internas mediante calentamiento controlado.

[SLIDE 18]
# Recocido y normalizado
El recocido ablanda el material eliminando tensiones residuales.
El normalizado refina el grano mediante enfriamiento al aire.
"""

TEXTO_SIN_SENALES = """\
Contenido general sobre polímeros sin estructura clara de secciones numeradas.
Termoplásticos, termoestables y elastómeros son los tipos principales.
"""


def test_segmentacion() -> None:
    print("\n[2] Segmentación de texto por subbloques")

    # 2a. Texto PDF con secciones numeradas
    subbloques_pdf = [
        {"nombre": "Defectos y dislocaciones", "horas": 3.0, "evidencia": "Sección 3.1", "origen": "Detectado"},
        {"nombre": "Mecanismos de endurecimiento", "horas": 3.0, "evidencia": "Sección 3.2", "origen": "Detectado"},
        {"nombre": "Fractura y fatiga", "horas": 2.0, "evidencia": "Sección 3.3", "origen": "Detectado"},
    ]
    segments_pdf = segment_text_by_subbloques(TEXTO_PDF, subbloques_pdf)

    check("PDF: devuelve 3 segmentos", len(segments_pdf) == 3)
    _, seg1 = segments_pdf[0]
    _, seg2 = segments_pdf[1]
    _, seg3 = segments_pdf[2]
    check("PDF: seg1 contiene '3.1'", "3.1" in seg1, f"primeros 60: {seg1[:60]!r}")
    check("PDF: seg2 contiene '3.2'", "3.2" in seg2, f"primeros 60: {seg2[:60]!r}")
    check("PDF: seg3 contiene '3.3'", "3.3" in seg3, f"primeros 60: {seg3[:60]!r}")
    check("PDF: seg1 NO contiene '3.2'", "3.2" not in seg1)
    check("PDF: texto intro va a seg1 (antes del primer boundary)", "Introducción" in seg1)

    # 2b. Texto PPTX con marcadores [SLIDE N]
    subbloques_pptx = [
        {"nombre": "Templado y revenido", "horas": 3.0, "evidencia": "Slide 12", "origen": "Detectado"},
        {"nombre": "Recocido y normalizado", "horas": 3.0, "evidencia": "Slide 18", "origen": "Detectado"},
    ]
    segments_pptx = segment_text_by_subbloques(TEXTO_PPTX, subbloques_pptx)

    check("PPTX: devuelve 2 segmentos", len(segments_pptx) == 2)
    _, sp1 = segments_pptx[0]
    _, sp2 = segments_pptx[1]
    check("PPTX: seg1 contiene 'Templado'", "Templado" in sp1)
    check("PPTX: seg2 contiene 'Recocido'", "Recocido" in sp2)
    check("PPTX: intro (SLIDE 1) va a seg1", "Introducción" in sp1)

    # 2c. Fallback: único subbloque sin señal verificable
    sb_fallback = [
        {"nombre": "Polímeros", "horas": 3.0, "evidencia": "Sin señal verificable", "origen": "Fallback"},
    ]
    segments_fb = segment_text_by_subbloques(TEXTO_SIN_SENALES, sb_fallback)
    check("Fallback: 1 segmento", len(segments_fb) == 1)
    _, seg_fb = segments_fb[0]
    check("Fallback: recibe todo el texto", "Termoplásticos" in seg_fb)

    # 2d. Subbloques sin boundary encontrado: primero recibe todo, resto vacíos
    sb_sin_boundary = [
        {"nombre": "Sub A", "horas": 1.0, "evidencia": "Sección 99.99", "origen": "Detectado"},
        {"nombre": "Sub B", "horas": 1.0, "evidencia": "Sección 99.98", "origen": "Detectado"},
    ]
    segs_no_boundary = segment_text_by_subbloques(TEXTO_SIN_SENALES, sb_sin_boundary)
    check("Sin boundary: 2 resultados devueltos", len(segs_no_boundary) == 2)
    _, seg_a = segs_no_boundary[0]
    _, seg_b = segs_no_boundary[1]
    check("Sin boundary: primer subbloque recibe texto", len(seg_a) > 0)
    check("Sin boundary: segundo subbloque vacío", seg_b == "")


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
    print("\n[5] Fallback: sin subbloques (bloque único, comportamiento clásico)")

    # Sin subbloques → lista vacía → segment devuelve lista vacía
    segs = segment_text_by_subbloques("Texto cualquiera.", [])
    check("Lista vacia de subbloques: resultado vacio", segs == [])

    # Subbloque unico fallback: todo el texto al unico subbloque
    sb_unico = [{"nombre": "Polimeros", "horas": 3.0, "evidencia": "Sin senal verificable", "origen": "Fallback"}]
    segs_unico = segment_text_by_subbloques("Texto de polimeros.", sb_unico)
    check("Unico subbloque: 1 resultado", len(segs_unico) == 1)
    meta, txt = segs_unico[0]
    check("Unico subbloque: recibe todo el texto", txt == "Texto de polimeros.")
    check("Unico subbloque: meta correcta", meta["nombre"] == "Polimeros")

    # Ensamblado con subbloque unico
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


# ── 6. Detección de boundary no encontrado (condición de aviso UI) ───────────
#
# Esta sección valida la lógica de detección que app.py usa para emitir st.warning()
# cuando una evidencia estructural no se localiza en el texto. No es posible testear
# el st.warning() directamente (requiere Streamlit), pero sí la condición que lo activa.

_EVIDENCIAS_FALLBACK_TEST = frozenset({
    "sin señal verificable", "sin senal verificable",
    "fallback", "sin señal", "sin senal", "",
})


def _detectar_avisos(segs: list) -> list[str]:
    """Reproduce la lógica de detección de app.py: retorna nombres de subbloques
    cuya evidencia no se encontró (seg vacío + evidencia no-fallback)."""
    avisos: list[str] = []
    for sb_meta, seg_text in segs:
        ev = (sb_meta.get("evidencia") or "").strip().lower()
        if not seg_text.strip() and ev not in _EVIDENCIAS_FALLBACK_TEST:
            avisos.append(sb_meta.get("nombre", "?"))
    return avisos


def test_deteccion_boundary_no_encontrado() -> None:
    print("\n[6] Detección de boundary no encontrado (condición de aviso)")

    # Texto sin secciones numeradas ni marcadores de slide
    texto_sin_estructura = (
        "Contenido general sin secciones numeradas ni marcadores de diapositiva. "
        "Este texto no contiene ni '5.1.' ni '[SLIDE 7]'."
    )

    # 6a. Ningún boundary encontrado: primer sub recibe todo; resto vacíos
    sb_ninguno = [
        {"nombre": "Sub A", "horas": 1.0, "evidencia": "Sección 5.1", "origen": "Detectado"},
        {"nombre": "Sub B", "horas": 1.0, "evidencia": "Slide 7", "origen": "Detectado"},
        {"nombre": "Sub C", "horas": 1.0, "evidencia": "Sin señal verificable", "origen": "Fallback"},
    ]
    segs_ninguno = segment_text_by_subbloques(texto_sin_estructura, sb_ninguno)
    avisos = _detectar_avisos(segs_ninguno)

    check("Sub A (recibe texto, no avisa aunque boundary no encontrado)", "Sub A" not in avisos)
    check("Sub B (Slide 7 no encontrado, avisa)", "Sub B" in avisos)
    check("Sub C (fallback, no avisa)", "Sub C" not in avisos)
    check("Solo 1 aviso generado", len(avisos) == 1)

    # 6b. Caso mixto: una evidencia encontrada, otra no
    texto_con_seccion = (
        "[PAGINA 1]\n3.1. Sección primera\nContenido de la sección primera.\n"
    )
    sb_mixto = [
        {"nombre": "Sub D", "horas": 1.0, "evidencia": "Sección 3.1", "origen": "Detectado"},
        {"nombre": "Sub E", "horas": 1.0, "evidencia": "Sección 99.99", "origen": "Detectado"},
    ]
    segs_mixto = segment_text_by_subbloques(texto_con_seccion, sb_mixto)
    avisos_mixto = _detectar_avisos(segs_mixto)

    check("Sub D (Sección 3.1 encontrada, no avisa)", "Sub D" not in avisos_mixto)
    check("Sub E (Sección 99.99 no encontrada, avisa)", "Sub E" in avisos_mixto)
    check("Solo 1 aviso en caso mixto", len(avisos_mixto) == 1)


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Validación de la pipeline de subbloques")
    print("=" * 60)

    test_parseo_org_md()
    test_segmentacion()
    test_ensamblado()
    test_progreso()
    test_fallback_sin_subbloques()
    test_deteccion_boundary_no_encontrado()

    total = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    failed = total - passed
    print(f"\n{'=' * 60}")
    print(f"Resultado: {passed}/{total} checks pasados" + (f" — {failed} FALLIDOS" if failed else " — TODOS OK"))
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
