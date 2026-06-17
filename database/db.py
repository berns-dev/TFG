"""Capa de base de datos local SQLite para la suite de agentes docentes del TFG.

Almacén compartido de inputs, outputs, estados y progreso de los tres agentes
(Organizador, Contenido, Presentación) cuando se unifican en una sola app Streamlit.

Esquema actual: versión 2 (user_version = 2).
Migración automática desde v1: añade columnas para evidencia/estado/interactivo.

Uso directo:
    python database/db.py
"""

import os
import sqlite3

RUTA_DB_POR_DEFECTO = "data/tfg.db"

VERSION_SCHEMA = 2

# Asignaturas con las que se ha validado la suite (ver CLAUDE.md).
ASIGNATURAS_CONOCIDAS = [
    "Oleohidráulica y Neumática",
    "Elementos de Máquinas",
    "Tecnología de Materiales",
]

# ---------------------------------------------------------------------------
# Esquema canónico v2.
# Cada sentencia incluye ya las columnas añadidas en la migración a v2, de
# forma que las nuevas instalaciones (sin datos previos) obtienen el esquema
# correcto directamente, sin necesidad de ejecutar las sentencias ALTER TABLE.
# ---------------------------------------------------------------------------

ESQUEMA = [
    """
    CREATE TABLE IF NOT EXISTS asignaturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        tipo TEXT NOT NULL CHECK(tipo IN ('guia_docente','material_teoria')),
        nombre_fichero TEXT NOT NULL,
        ruta_disco TEXT NOT NULL,
        fecha_subida TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ejecuciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        agente TEXT NOT NULL CHECK(agente IN ('organizador','contenido','presentacion')),
        version INTEGER NOT NULL DEFAULT 1,
        fecha_inicio TEXT DEFAULT CURRENT_TIMESTAMP,
        estado TEXT DEFAULT 'en_progreso'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organizador_outputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        ejecucion_id INTEGER REFERENCES ejecuciones(id),
        markdown_path TEXT NOT NULL,
        feedback_texto TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        fecha_generacion TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS temas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        organizador_output_id INTEGER REFERENCES organizador_outputs(id),
        nombre TEXT NOT NULL,
        horas REAL,
        bloque TEXT,
        orden INTEGER
    )
    """,
    # v2: añadidas horas, evidencia, origen, es_fallback
    """
    CREATE TABLE IF NOT EXISTS subbloques (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tema_id INTEGER NOT NULL REFERENCES temas(id),
        nombre TEXT NOT NULL,
        orden INTEGER,
        horas REAL DEFAULT 0,
        evidencia TEXT DEFAULT '',
        origen TEXT DEFAULT 'Detectado',
        es_fallback INTEGER DEFAULT 0
    )
    """,
    # v2: añadido estado
    """
    CREATE TABLE IF NOT EXISTS contenido_subbloque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subbloque_id INTEGER NOT NULL REFERENCES subbloques(id),
        markdown_borrador TEXT,
        markdown_final TEXT,
        porcentaje_editado REAL,
        estado TEXT NOT NULL DEFAULT 'pendiente'
            CHECK(estado IN ('pendiente','generado','editado','aprobado')),
        fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # v2: añadido tiene_interactivo
    """
    CREATE TABLE IF NOT EXISTS presentacion_subbloque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subbloque_id INTEGER NOT NULL REFERENCES subbloques(id),
        patron_visualizacion TEXT CHECK(patron_visualizacion IN
            ('curva_simple','familia_curvas','region_criterio','mapa_2d',
             'trayectoria','respuesta_frecuencial','ninguna')),
        elegido_por_profesor INTEGER DEFAULT 0,
        html_path TEXT,
        tiene_interactivo INTEGER DEFAULT 0,
        fecha_generacion TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS parametros_subbloque (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        presentacion_subbloque_id INTEGER NOT NULL REFERENCES presentacion_subbloque(id),
        nombre_parametro TEXT NOT NULL,
        simbolo TEXT,
        es_slider INTEGER DEFAULT 1,
        valor_min REAL,
        valor_max REAL,
        valor_predeterminado REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS presentacion_outputs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        pdf_path TEXT,
        html_path TEXT,
        version INTEGER NOT NULL DEFAULT 1,
        fecha_generacion TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS validaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ejecucion_id INTEGER NOT NULL REFERENCES ejecuciones(id),
        tipo TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        valor_afectado REAL,
        bloqueante INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# ---------------------------------------------------------------------------
# Migraciones incrementales (v_anterior → VERSION_SCHEMA).
# Cada clave es la versión DESTINO. Las sentencias ALTER TABLE son idempotentes
# en SQLite si se envuelven en un try/except (ADD COLUMN falla si ya existe).
# ---------------------------------------------------------------------------

MIGRACIONES: dict[int, list[str]] = {
    2: [
        "ALTER TABLE subbloques ADD COLUMN horas REAL DEFAULT 0",
        "ALTER TABLE subbloques ADD COLUMN evidencia TEXT DEFAULT ''",
        "ALTER TABLE subbloques ADD COLUMN origen TEXT DEFAULT 'Detectado'",
        "ALTER TABLE subbloques ADD COLUMN es_fallback INTEGER DEFAULT 0",
        "ALTER TABLE contenido_subbloque ADD COLUMN estado TEXT NOT NULL DEFAULT 'pendiente'",
        "ALTER TABLE presentacion_subbloque ADD COLUMN tiene_interactivo INTEGER DEFAULT 0",
    ],
}

# Estados válidos para el ciclo de vida de un subbloque de contenido.
ESTADOS_SUBBLOQUE = frozenset({"pendiente", "generado", "editado", "aprobado"})


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------


def get_connection(ruta=RUTA_DB_POR_DEFECTO):
    """Devuelve una conexión sqlite3 con filas accesibles por nombre y FK activadas."""
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Inicialización y migración
# ---------------------------------------------------------------------------


def init_db(ruta=RUTA_DB_POR_DEFECTO) -> int:
    """Crea el archivo SQLite (y su carpeta) si no existe, aplica el esquema
    canónico y ejecuta las migraciones pendientes hasta VERSION_SCHEMA.

    Devuelve la versión de esquema resultante (== VERSION_SCHEMA si todo fue bien).
    """
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    conn = get_connection(ruta)
    try:
        # Crear tablas para instalaciones nuevas (IF NOT EXISTS es idempotente).
        for sentencia in ESQUEMA:
            conn.execute(sentencia)
        conn.commit()

        # Detectar versión actual del esquema.
        version_actual = conn.execute("PRAGMA user_version").fetchone()[0]

        # Aplicar migraciones pendientes en orden ascendente.
        for version_destino in sorted(MIGRACIONES.keys()):
            if version_actual >= version_destino:
                continue
            for sentencia in MIGRACIONES[version_destino]:
                try:
                    conn.execute(sentencia)
                except sqlite3.OperationalError:
                    # La columna ya existe — la migración fue aplicada parcialmente
                    # en una sesión anterior. Se continúa sin error.
                    pass
            conn.commit()
            version_actual = version_destino

        # Fijar la versión final.
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
        conn.commit()
        return VERSION_SCHEMA
    finally:
        conn.close()


def seed_asignaturas(ruta=RUTA_DB_POR_DEFECTO) -> int:
    """Inserta las tres asignaturas conocidas sin duplicar las ya existentes.

    Devuelve el número de filas insertadas en esta llamada.
    """
    conn = get_connection(ruta)
    try:
        insertadas = 0
        for nombre in ASIGNATURAS_CONOCIDAS:
            cur = conn.execute(
                "INSERT OR IGNORE INTO asignaturas (nombre) VALUES (?)", (nombre,)
            )
            insertadas += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return insertadas


# ---------------------------------------------------------------------------
# CRUD de estado de subbloque de contenido
# ---------------------------------------------------------------------------


def upsert_estado_subbloque(
    subbloque_id: int,
    estado: str,
    markdown: str | None = None,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Crea o actualiza la fila de contenido_subbloque para un subbloque.

    Args:
        subbloque_id: PK del subbloque en la tabla subbloques.
        estado: uno de 'pendiente' | 'generado' | 'editado' | 'aprobado'.
        markdown: si se proporciona, actualiza también markdown_borrador.
    """
    if estado not in ESTADOS_SUBBLOQUE:
        raise ValueError(
            f"Estado inválido: {estado!r}. Válidos: {sorted(ESTADOS_SUBBLOQUE)}"
        )
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        if existe:
            if markdown is not None:
                conn.execute(
                    "UPDATE contenido_subbloque "
                    "SET estado = ?, markdown_borrador = ?, "
                    "fecha_actualizacion = CURRENT_TIMESTAMP "
                    "WHERE subbloque_id = ?",
                    (estado, markdown, subbloque_id),
                )
            else:
                conn.execute(
                    "UPDATE contenido_subbloque "
                    "SET estado = ?, fecha_actualizacion = CURRENT_TIMESTAMP "
                    "WHERE subbloque_id = ?",
                    (estado, subbloque_id),
                )
        else:
            conn.execute(
                "INSERT INTO contenido_subbloque "
                "(subbloque_id, estado, markdown_borrador) VALUES (?, ?, ?)",
                (subbloque_id, estado, markdown or ""),
            )
        conn.commit()
    finally:
        conn.close()


def get_estado_subbloque(
    subbloque_id: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> str:
    """Devuelve el estado actual del subbloque ('pendiente' si no tiene fila)."""
    conn = get_connection(ruta)
    try:
        r = conn.execute(
            "SELECT estado FROM contenido_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        return r["estado"] if r else "pendiente"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD de contenido interactivo (Presentación)
# ---------------------------------------------------------------------------


def set_interactivo_subbloque(
    subbloque_id: int,
    html_path: str | None = None,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Crea o actualiza la fila de presentacion_subbloque marcando tiene_interactivo.

    tiene_interactivo = 1 si html_path no es None ni vacío, 0 en caso contrario.
    No afecta al progreso (el campo se usa como referencia informativa, no entra
    en el cálculo de aprobados/total).
    """
    tiene = 1 if html_path else 0
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM presentacion_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE presentacion_subbloque "
                "SET tiene_interactivo = ?, html_path = ?, "
                "fecha_generacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (tiene, html_path, subbloque_id),
            )
        else:
            conn.execute(
                "INSERT INTO presentacion_subbloque "
                "(subbloque_id, tiene_interactivo, html_path) VALUES (?, ?, ?)",
                (subbloque_id, tiene, html_path),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Progreso — calculado en tiempo real, nunca almacenado como campo
# ---------------------------------------------------------------------------


def get_progreso_bloque(tema_id: int, ruta=RUTA_DB_POR_DEFECTO) -> dict:
    """Calcula el progreso de un bloque temático en tiempo real.

    Progreso = subbloques con estado 'aprobado' / total subbloques del bloque.
    El contenido interactivo (tiene_interactivo) NO entra en este cálculo.

    Returns:
        {"total": int, "aprobados": int, "porcentaje": float}
    """
    conn = get_connection(ruta)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM subbloques WHERE tema_id = ?",
            (tema_id,),
        ).fetchone()[0]
        aprobados = conn.execute(
            """
            SELECT COUNT(*)
            FROM subbloques s
            JOIN contenido_subbloque cs ON cs.subbloque_id = s.id
            WHERE s.tema_id = ? AND cs.estado = 'aprobado'
            """,
            (tema_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "total": total,
        "aprobados": aprobados,
        "porcentaje": round(aprobados / max(total, 1) * 100, 1),
    }


def get_progreso_asignatura(asignatura_id: int, ruta=RUTA_DB_POR_DEFECTO) -> dict:
    """Calcula el progreso global de una asignatura en tiempo real.

    Progreso = subbloques con estado 'aprobado' / total subbloques de la asignatura.
    Los bloques con un único subbloque (caso fallback del Organizador) se tratan
    exactamente igual que los bloques con varios subbloques — el denominador es
    siempre la suma de todos los subbloques sin distinción.

    Returns:
        {"total": int, "aprobados": int, "porcentaje": float}
    """
    conn = get_connection(ruta)
    try:
        total = conn.execute(
            """
            SELECT COUNT(*)
            FROM subbloques s
            JOIN temas t ON t.id = s.tema_id
            WHERE t.asignatura_id = ?
            """,
            (asignatura_id,),
        ).fetchone()[0]
        aprobados = conn.execute(
            """
            SELECT COUNT(*)
            FROM subbloques s
            JOIN temas t ON t.id = s.tema_id
            JOIN contenido_subbloque cs ON cs.subbloque_id = s.id
            WHERE t.asignatura_id = ? AND cs.estado = 'aprobado'
            """,
            (asignatura_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "total": total,
        "aprobados": aprobados,
        "porcentaje": round(aprobados / max(total, 1) * 100, 1),
    }


def get_desglose_progreso_asignatura(
    asignatura_id: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> list[dict]:
    """Devuelve el progreso desglosado por bloque para la vista de mapa curricular.

    Returns:
        list[dict] ordenado por temas.orden, con:
        {"tema_id", "nombre", "horas", "total_sub", "aprobados", "porcentaje"}
    """
    conn = get_connection(ruta)
    try:
        temas = conn.execute(
            "SELECT id, nombre, horas, orden FROM temas "
            "WHERE asignatura_id = ? ORDER BY orden",
            (asignatura_id,),
        ).fetchall()
        resultado = []
        for t in temas:
            total_sub = conn.execute(
                "SELECT COUNT(*) FROM subbloques WHERE tema_id = ?",
                (t["id"],),
            ).fetchone()[0]
            aprobados = conn.execute(
                """
                SELECT COUNT(*)
                FROM subbloques s
                JOIN contenido_subbloque cs ON cs.subbloque_id = s.id
                WHERE s.tema_id = ? AND cs.estado = 'aprobado'
                """,
                (t["id"],),
            ).fetchone()[0]
            resultado.append({
                "tema_id": t["id"],
                "nombre": t["nombre"],
                "horas": t["horas"],
                "total_sub": total_sub,
                "aprobados": aprobados,
                "porcentaje": round(aprobados / max(total_sub, 1) * 100, 1),
            })
        return resultado
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Entry point — inicialización y diagnóstico
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    version = init_db()
    n_insertadas = seed_asignaturas()
    print(f"Base de datos inicializada — esquema versión {version}.")
    print(f"Asignaturas sembradas en esta ejecución: {n_insertadas} de {len(ASIGNATURAS_CONOCIDAS)}.")

    # Verificación rápida del esquema.
    conn = get_connection()
    try:
        tablas = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        print(f"Tablas presentes: {tablas}")
        cols_sub = [
            r[1] for r in conn.execute("PRAGMA table_info(subbloques)").fetchall()
        ]
        cols_cs = [
            r[1] for r in conn.execute("PRAGMA table_info(contenido_subbloque)").fetchall()
        ]
        cols_ps = [
            r[1] for r in conn.execute("PRAGMA table_info(presentacion_subbloque)").fetchall()
        ]
        print(f"subbloques cols: {cols_sub}")
        print(f"contenido_subbloque cols: {cols_cs}")
        print(f"presentacion_subbloque cols: {cols_ps}")
    finally:
        conn.close()
