#!/usr/bin/env python3
"""Validación del reparto monótono sin llamadas a la API.

Ejecutar desde agente-contenido/:
    python tools/validate_split_monotono.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from split_monotono import split_monotono

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


def test_match_perfecto() -> None:
    print("\n[1] Match perfecto — 3 subtemas, 3 headings")
    md = """---
tema_detectado: Tema prueba
---

# Tema prueba

## Contenido teórico

### Defectos y dislocaciones

Texto sobre dislocaciones.

### Mecanismos de endurecimiento

Texto sobre endurecimiento.

### Fractura y fatiga

Texto sobre fractura.
"""
    subs = [
        {"id": 1, "nombre": "Defectos y dislocaciones", "orden": 1, "evidencia": "Sección 3.1"},
        {"id": 2, "nombre": "Mecanismos de endurecimiento", "orden": 2, "evidencia": "Sección 3.2"},
        {"id": 3, "nombre": "Fractura y fatiga", "orden": 3, "evidencia": "Sección 3.3"},
    ]
    r = split_monotono(md, subs)
    check("3 fragmentos", len(r.fragmentos) == 3)
    check("todos con ancla alta", all(f.confianza == "alta" for f in r.fragmentos))
    check("frag 1 contiene dislocaciones", "dislocaciones" in r.fragmentos[0].markdown.lower())
    check("frag 2 contiene endurecimiento", "endurecimiento" in r.fragmentos[1].markdown.lower())
    check("frag 3 contiene fractura", "fractura" in r.fragmentos[2].markdown.lower())
    check("no requiere revision", not r.requiere_revision)


def test_referencia_cruzada_no_mueve() -> None:
    print("\n[2] Referencia cruzada — el párrafo citando apartado 1 queda en apartado 5")
    md = """---
tema_detectado: Bloque
---

## Contenido teórico

### Apartado uno

Contenido del uno.

### Apartado dos

Solo dos.

### Apartado tres

Solo tres.

### Apartado cuatro

Solo cuatro.

### Apartado cinco

Como vimos en dislocaciones del apartado uno, aquí seguimos en cinco.
"""
    subs = [
        {"id": i, "nombre": f"Apartado {['uno','dos','tres','cuatro','cinco'][i-1]}", "orden": i, "evidencia": ""}
        for i in range(1, 6)
    ]
    r = split_monotono(md, subs)
    frag5 = r.fragmentos[4].markdown
    check("cinco contiene la referencia", "apartado uno" in frag5.lower())
    check("uno no contiene la referencia a cinco", "seguimos en cinco" not in r.fragmentos[0].markdown.lower())


def test_sin_ancla_intermedia() -> None:
    print("\n[3] Sin ancla intermedia — aviso y requiere revisión")
    md = """---
tema_detectado: Bloque
---

### Primero

A.

### Tercero

C.
"""
    subs = [
        {"id": 1, "nombre": "Primero", "orden": 1, "evidencia": ""},
        {"id": 2, "nombre": "Segundo sin titulo", "orden": 2, "evidencia": ""},
        {"id": 3, "nombre": "Tercero", "orden": 3, "evidencia": ""},
    ]
    r = split_monotono(md, subs)
    check("requiere revision", r.requiere_revision)
    check("segundo sin ancla", r.fragmentos[1].confianza == "sin_ancla")
    check("segundo tiene aviso", len(r.fragmentos[1].avisos) > 0)


def test_h2_canonicos_ignorados() -> None:
    print("\n[4] H2 canónicos no cortan subtemas")
    md = """---
tema_detectado: Bloque
---

## Contenido teórico

### Subtema real

Teoría aquí.

---

## Ejemplos resueltos

### Subtema real

Ejemplo aquí.
"""
    subs = [{"id": 1, "nombre": "Subtema real", "orden": 1, "evidencia": ""}]
    r = split_monotono(md, subs)
    check("un fragmento", len(r.fragmentos) == 1)
    check("incluye teoría y ejemplo", "Teoría" in r.fragmentos[0].markdown and "Ejemplo" in r.fragmentos[0].markdown)


def test_intro_antes_primera_ancla() -> None:
    print("\n[5] Intro antes de primera ancla va al primer subtema")
    md = """---
tema_detectado: Bloque
---

Introducción del bloque sin heading de subtema.

### Primer subtema

Cuerpo uno.
"""
    subs = [{"id": 1, "nombre": "Primer subtema", "orden": 1, "evidencia": ""}]
    r = split_monotono(md, subs)
    check("intro incluida", "Introducción del bloque" in r.fragmentos[0].markdown)
    check("cuerpo incluido", "Cuerpo uno" in r.fragmentos[0].markdown)


def main() -> int:
    print("=== Validación split_monotono ===")
    test_match_perfecto()
    test_referencia_cruzada_no_mueve()
    test_sin_ancla_intermedia()
    test_h2_canonicos_ignorados()
    test_intro_antes_primera_ancla()
    ok = sum(1 for _, passed in _results if passed)
    total = len(_results)
    print(f"\n=== {ok}/{total} comprobaciones OK ===")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
