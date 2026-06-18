"""Script de validación del esquema v2 de la base de datos.

Simula una asignatura completa (Tecnología de Materiales) con varios bloques
y subbloques — incluyendo el caso fallback del Organizador (bloque sin señal
estructural → único subbloque) — y verifica el cálculo de progreso.

Ejecutar desde TFG/TFG/:
    py -3 database/validar_esquema.py
"""

import os
import sys
import tempfile

# Permitir importar database/db.py desde cualquier directorio de trabajo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db

# ---------------------------------------------------------------------------
# Datos de prueba: Tecnología de Materiales (simplificado)
# ---------------------------------------------------------------------------

ASIGNATURA = "Tecnología de Materiales"

BLOQUES = [
    {
        "numero": 1,
        "nombre": "Estructura de los materiales",
        "horas": 6.0,
        "subtemas": [
            {"nombre": "Enlace atómico y estructura cristalina", "horas": 2.0,
             "orden": 1, "evidencia": "Sección 1.1", "origen": "Detectado", "es_fallback": 0},
            {"nombre": "Defectos cristalinos", "horas": 2.0,
             "orden": 2, "evidencia": "Sección 1.2", "origen": "Detectado", "es_fallback": 0},
            {"nombre": "Difusión en sólidos", "horas": 2.0,
             "orden": 3, "evidencia": "Sección 1.3", "origen": "Detectado", "es_fallback": 0},
        ],
    },
    {
        "numero": 2,
        "nombre": "Propiedades mecánicas",
        "horas": 8.0,
        "subtemas": [
            {"nombre": "Tracción y compresión", "horas": 2.5,
             "orden": 1, "evidencia": "Slide 5", "origen": "Detectado", "es_fallback": 0},
            {"nombre": "Dureza y ensayos", "horas": 2.5,
             "orden": 2, "evidencia": "Slide 12", "origen": "Detectado", "es_fallback": 0},
            {"nombre": "Fatiga y fractura", "horas": 3.0,
             "orden": 3, "evidencia": "Slide 18", "origen": "Detectado", "es_fallback": 0},
        ],
    },
    {
        # Caso fallback: bloque sin señal estructural → único subbloque
        "numero": 3,
        "nombre": "Tratamientos térmicos",
        "horas": 4.0,
        "subtemas": [
            {"nombre": "Tratamientos térmicos",  # mismo nombre que el bloque
             "horas": 4.0, "orden": 1,
             "evidencia": "Sin señal verificable", "origen": "Fallback", "es_fallback": 1},
        ],
    },
    {
        "numero": 4,
        "nombre": "Materiales metálicos",
        "horas": 5.0,
        "subtemas": [
            {"nombre": "Aceros y fundiciones", "horas": 2.5,
             "orden": 1, "evidencia": "Sección 4.1", "origen": "Detectado", "es_fallback": 0},
            {"nombre": "Aleaciones no férricas", "horas": 2.5,
             "orden": 2, "evidencia": "Sección 4.2", "origen": "Detectado", "es_fallback": 0},
        ],
    },
]

# ---------------------------------------------------------------------------
# Helpers de prueba (equivalentes a los de app-unificada/app.py)
# ---------------------------------------------------------------------------


def _seed_asignatura(conn, nombre: str) -> int:
    conn.execute("INSERT OR IGNORE INTO asignaturas (nombre) VALUES (?)", (nombre,))
    conn.commit()
    return conn.execute("SELECT id FROM asignaturas WHERE nombre = ?", (nombre,)).fetchone()[0]


def _seed_bloques(conn, asignatura_id: int, bloques: list[dict]) -> dict[str, int]:
    """Inserta temas y subbloques. Devuelve {nombre_subtema: subbloque_id}."""
    conn.execute("DELETE FROM subbloques WHERE tema_id IN "
                 "(SELECT id FROM temas WHERE asignatura_id = ?)", (asignatura_id,))
    conn.execute("DELETE FROM temas WHERE asignatura_id = ?", (asignatura_id,))
    conn.commit()
    sub_ids: dict[str, int] = {}
    for orden, bloque in enumerate(bloques, 1):
        cur = conn.execute(
            "INSERT INTO temas (asignatura_id, nombre, horas, bloque, orden) VALUES (?,?,?,?,?)",
            (asignatura_id, bloque["nombre"], bloque["horas"],
             f"Bloque {bloque['numero']}", orden),
        )
        tema_id = cur.lastrowid
        for sub in bloque["subtemas"]:
            cur2 = conn.execute(
                "INSERT INTO subbloques (tema_id, nombre, orden, horas, evidencia, origen, es_fallback) "
                "VALUES (?,?,?,?,?,?,?)",
                (tema_id, sub["nombre"], sub["orden"], sub["horas"],
                 sub["evidencia"], sub["origen"], sub["es_fallback"]),
            )
            sub_ids[sub["nombre"]] = cur2.lastrowid
    conn.commit()
    return sub_ids


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------


def main() -> None:
    # Usar un fichero de BD temporal para no contaminar la BD de desarrollo.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        ruta_bd = tf.name

    try:
        print(f"BD temporal: {ruta_bd}")
        version = db.init_db(ruta_bd)
        print(f"Esquema inicializado — versión {version}")
        assert version == db.VERSION_SCHEMA, f"Versión esperada {db.VERSION_SCHEMA}, obtenida {version}"

        conn = db.get_connection(ruta_bd)

        # 1. Crear asignatura y estructura.
        asignatura_id = _seed_asignatura(conn, ASIGNATURA)
        sub_ids = _seed_bloques(conn, asignatura_id, BLOQUES)
        total_subs = sum(len(b["subtemas"]) for b in BLOQUES)
        print(f"\n[1] Asignatura '{ASIGNATURA}' (id={asignatura_id}) — {total_subs} subbloques en total")

        # 2. Progreso inicial: 0 aprobados.
        prog_0 = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[2] Progreso inicial: {prog_0}")
        assert prog_0["total"] == total_subs, f"Total esperado {total_subs}, obtenido {prog_0['total']}"
        assert prog_0["aprobados"] == 0
        assert prog_0["porcentaje"] == 0.0

        # 3. Aprobar subbloques del Bloque 1 (3 de 9 total).
        for nombre in ["Enlace atómico y estructura cristalina", "Defectos cristalinos"]:
            db.upsert_estado_subbloque(sub_ids[nombre], "aprobado", ruta=ruta_bd)
        db.upsert_estado_subbloque(
            sub_ids["Difusión en sólidos"], "generado",
            markdown="# Difusión en sólidos\nContenido generado por IA.",
            ruta=ruta_bd,
        )
        prog_1 = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[3] Después de aprobar 2/{total_subs}: {prog_1}")
        assert prog_1["aprobados"] == 2
        assert prog_1["total"] == total_subs
        assert prog_1["porcentaje"] == round(2 / total_subs * 100, 1)

        # 4. Verificar progreso del Bloque 1 por separado.
        bloque1_id = conn.execute(
            "SELECT id FROM temas WHERE asignatura_id = ? AND orden = 1",
            (asignatura_id,)
        ).fetchone()[0]
        prog_b1 = db.get_progreso_bloque(bloque1_id, ruta_bd)
        print(f"\n[4] Progreso Bloque 1 (3 subbloques, 2 aprobados): {prog_b1}")
        assert prog_b1["total"] == 3
        assert prog_b1["aprobados"] == 2
        assert prog_b1["porcentaje"] == round(2 / 3 * 100, 1)

        # 5. Caso fallback: Bloque 3 tiene 1 único subbloque.
        bloque3_id = conn.execute(
            "SELECT id FROM temas WHERE asignatura_id = ? AND orden = 3",
            (asignatura_id,)
        ).fetchone()[0]
        prog_b3_pre = db.get_progreso_bloque(bloque3_id, ruta_bd)
        print(f"\n[5a] Bloque 3 (fallback, 1 subbloque) antes de aprobar: {prog_b3_pre}")
        assert prog_b3_pre["total"] == 1
        assert prog_b3_pre["aprobados"] == 0
        assert prog_b3_pre["porcentaje"] == 0.0

        db.upsert_estado_subbloque(sub_ids["Tratamientos térmicos"], "aprobado", ruta=ruta_bd)
        prog_b3_post = db.get_progreso_bloque(bloque3_id, ruta_bd)
        print(f"[5b] Bloque 3 después de aprobar el único subbloque: {prog_b3_post}")
        assert prog_b3_post["aprobados"] == 1
        assert prog_b3_post["porcentaje"] == 100.0

        # 6. Marcar subbloque con interactivo — no debe alterar progreso.
        sub_interactivo = sub_ids["Tracción y compresión"]
        db.set_interactivo_subbloque(sub_interactivo, html_path="/data/tecmat/interactivo/traccion.html", ruta=ruta_bd)
        row = conn.execute(
            "SELECT tiene_interactivo, html_path FROM presentacion_subbloque WHERE subbloque_id = ?",
            (sub_interactivo,)
        ).fetchone()
        assert row["tiene_interactivo"] == 1
        assert row["html_path"] is not None
        prog_tras_interactivo = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[6] Después de marcar interactivo (no afecta progreso): {prog_tras_interactivo}")
        assert prog_tras_interactivo["aprobados"] == 3  # sigue igual (2 del bloque 1 + 1 del bloque 3)

        # 7. Aprobar todos — progreso 100%.
        todos_los_nombres = [
            sub["nombre"]
            for bloque in BLOQUES
            for sub in bloque["subtemas"]
        ]
        for nombre in todos_los_nombres:
            db.upsert_estado_subbloque(sub_ids[nombre], "aprobado", ruta=ruta_bd)
        prog_final = db.get_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[7] Progreso final (todos aprobados): {prog_final}")
        assert prog_final["aprobados"] == total_subs
        assert prog_final["porcentaje"] == 100.0

        # 8. Desglose por bloque.
        desglose = db.get_desglose_progreso_asignatura(asignatura_id, ruta_bd)
        print(f"\n[8] Desglose por bloque (todos al 100%):")
        for b in desglose:
            print(f"    {b['nombre']}: {b['aprobados']}/{b['total_sub']} ({b['porcentaje']}%)")
            assert b["porcentaje"] == 100.0

        # 9. Inputs: upsert sin duplicar filas al re-subir el mismo fichero.
        db.registrar_input(
            asignatura_id, "material_teoria", "tema1.pdf", "/tmp/tema1.pdf", ruta=ruta_bd
        )
        db.registrar_input(
            asignatura_id, "material_teoria", "tema1.pdf", "/tmp/tema1_v2.pdf", ruta=ruta_bd
        )
        n_inputs = conn.execute(
            "SELECT COUNT(*) FROM inputs WHERE asignatura_id = ? AND nombre_fichero = ?",
            (asignatura_id, "tema1.pdf"),
        ).fetchone()[0]
        ruta_guardada = conn.execute(
            "SELECT ruta_disco FROM inputs WHERE asignatura_id = ? AND nombre_fichero = ?",
            (asignatura_id, "tema1.pdf"),
        ).fetchone()[0]
        print(f"\n[9] Re-subida de input: {n_inputs} fila(s), ruta={ruta_guardada}")
        assert n_inputs == 1
        assert ruta_guardada == "/tmp/tema1_v2.pdf"

        conn.close()
        print("\nOK — Todas las validaciones pasaron correctamente.")

    finally:
        os.unlink(ruta_bd)


if __name__ == "__main__":
    main()
