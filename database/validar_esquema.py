"""Script de validación del esquema v7 de la base de datos.

Simula una asignatura completa (Tecnología de Materiales) con varios bloques
temáticos y verifica contenido_tema, visualizacion_interactiva y progreso.

Ejecutar desde TFG/TFG/:
    py -3 database/validar_esquema.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db

ASIGNATURA = "Tecnología de Materiales"

BLOQUES = [
    {"numero": 1, "nombre": "Estructura de los materiales", "horas": 6.0},
    {"numero": 2, "nombre": "Propiedades mecánicas", "horas": 8.0},
    {"numero": 3, "nombre": "Tratamientos térmicos", "horas": 4.0},
]


def _seed_asignatura(conn, nombre: str) -> int:
    conn.execute("INSERT OR IGNORE INTO asignaturas (nombre) VALUES (?)", (nombre,))
    conn.commit()
    return conn.execute("SELECT id FROM asignaturas WHERE nombre = ?", (nombre,)).fetchone()[0]


def _seed_temas(conn, asignatura_id: int) -> dict[str, int]:
    conn.execute("DELETE FROM temas WHERE asignatura_id = ?", (asignatura_id,))
    conn.commit()
    ids: dict[str, int] = {}
    for orden, bloque in enumerate(BLOQUES, 1):
        cur = conn.execute(
            "INSERT INTO temas (asignatura_id, nombre, horas, bloque, orden) VALUES (?,?,?,?,?)",
            (asignatura_id, bloque["nombre"], bloque["horas"], f"Bloque {bloque['numero']}", orden),
        )
        ids[bloque["nombre"]] = cur.lastrowid
    conn.commit()
    return ids


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        ruta_bd = tf.name

    try:
        print(f"BD temporal: {ruta_bd}")
        version = db.init_db(ruta_bd)
        print(f"Esquema inicializado — versión {version}")
        assert version == db.VERSION_SCHEMA

        asignatura_id = _seed_asignatura(db.get_connection(ruta_bd), ASIGNATURA)
        tema_ids = _seed_temas(db.get_connection(ruta_bd), asignatura_id)
        total_bloques = len(BLOQUES)

        prog_0 = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[1] Progreso inicial: {prog_0}")
        assert prog_0["total"] == total_bloques
        assert prog_0["aprobados"] == 0

        db.upsert_contenido_tema_borrador(
            tema_ids["Estructura de los materiales"],
            "# Estructura\n\n## Contenido teórico\n\nTexto.",
            ruta_bd,
        )
        prog_gen = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        assert prog_gen["aprobados"] == 0

        db.aprobar_contenido_tema(
            tema_ids["Estructura de los materiales"],
            "# Estructura\n\n## Contenido teórico\n\nTexto.",
            0.0,
            8,
            ruta_bd,
        )
        prog_1 = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[2] Tras aprobar 1 bloque: {prog_1}")
        assert prog_1["aprobados"] == 1
        assert prog_1["porcentaje"] == round(1 / total_bloques * 100, 1)

        vid = db.insertar_visualizacion_borrador(
            tema_ids["Propiedades mecánicas"],
            "Ensayo tracción",
            "Gráfico con dos sliders",
            "[]",
            "<div>html</div>",
            ruta_bd,
        )
        db.aprobar_visualizacion(vid, "Ensayo de tracción", ruta_bd)
        aprobadas = db.listar_visualizaciones_aprobadas(
            tema_ids["Propiedades mecánicas"], ruta_bd
        )
        assert len(aprobadas) == 1
        assert aprobadas[0]["seccion_ancla"] == "Ensayo de tracción"
        print(f"\n[3] Visualización aprobada: {aprobadas[0]['titulo']}")

        for nombre in tema_ids:
            db.aprobar_contenido_tema(
                tema_ids[nombre],
                f"# {nombre}\n\nContenido.",
                0.0,
                7,
                ruta_bd,
            )
        prog_final = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[4] Progreso final: {prog_final}")
        assert prog_final["aprobados"] == total_bloques
        assert prog_final["porcentaje"] == 100.0

        print("\nOK — Todas las validaciones pasaron correctamente.")
    finally:
        try:
            os.unlink(ruta_bd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
