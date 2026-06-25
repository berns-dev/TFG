"""Capa de base de datos local SQLite para la suite de agentes docentes del TFG.

Almacén compartido de inputs, outputs, estados y progreso de los tres agentes
(Organizador, Contenido, Presentación) cuando se unifican en una sola app Streamlit.

Esquema actual: versión 8 (user_version = 8).
Migración automática desde v1: añade columnas para evidencia/estado/interactivo.
Migración v3: tabla valoraciones_profesor (puntuación 1-10 por asignatura y agente).
Migración v4: puntuacion_profesor por sub-bloque en contenido_subbloque.
Migración v5: input_id en temas (vínculo bloque → PDF de teoría).
Migración v6: índice UNIQUE en inputs (asignatura, tipo, nombre) y deduplicación.
Migración v7: contenido_tema (markdown por bloque) y visualizacion_interactiva.
Migración v8: columna fuente en subbloques (estrategia de detección).

Uso directo:
    python database/db.py
"""

import os
import sqlite3

RUTA_DB_POR_DEFECTO = "data/tfg.db"

VERSION_SCHEMA = 8

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
        orden INTEGER,
        input_id INTEGER REFERENCES inputs(id)
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
        es_fallback INTEGER DEFAULT 0,
        fuente TEXT DEFAULT ''
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
        puntuacion_profesor INTEGER CHECK(puntuacion_profesor BETWEEN 1 AND 10),
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
    """
    CREATE TABLE IF NOT EXISTS valoraciones_profesor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
        agente TEXT NOT NULL CHECK(agente IN ('organizador','contenido','presentacion')),
        puntuacion INTEGER NOT NULL CHECK(puntuacion BETWEEN 1 AND 10),
        fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(asignatura_id, agente)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contenido_tema (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tema_id INTEGER NOT NULL UNIQUE REFERENCES temas(id),
        markdown_borrador TEXT,
        markdown_final TEXT,
        porcentaje_editado REAL,
        puntuacion_profesor INTEGER CHECK(puntuacion_profesor BETWEEN 1 AND 10),
        estado TEXT NOT NULL DEFAULT 'pendiente'
            CHECK(estado IN ('pendiente','generado','editado','aprobado')),
        fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS visualizacion_interactiva (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tema_id INTEGER NOT NULL REFERENCES temas(id),
        titulo TEXT NOT NULL,
        prompt_inicial TEXT,
        historial_json TEXT DEFAULT '[]',
        html_fragment TEXT,
        seccion_ancla TEXT DEFAULT '',
        estado TEXT NOT NULL DEFAULT 'borrador'
            CHECK(estado IN ('borrador','aprobado')),
        orden INTEGER DEFAULT 0,
        fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
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
    3: [
        """
        CREATE TABLE IF NOT EXISTS valoraciones_profesor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
            agente TEXT NOT NULL CHECK(agente IN ('organizador','contenido','presentacion')),
            puntuacion INTEGER NOT NULL CHECK(puntuacion BETWEEN 1 AND 10),
            fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asignatura_id, agente)
        )
        """,
    ],
    4: [
        "ALTER TABLE contenido_subbloque ADD COLUMN puntuacion_profesor INTEGER "
        "CHECK(puntuacion_profesor BETWEEN 1 AND 10)",
    ],
    5: [
        "ALTER TABLE temas ADD COLUMN input_id INTEGER REFERENCES inputs(id)",
    ],
    6: [
        """
        UPDATE temas
        SET input_id = (
            SELECT MAX(i.id)
            FROM inputs i
            INNER JOIN inputs i_orig ON i_orig.id = temas.input_id
            WHERE i.asignatura_id = i_orig.asignatura_id
              AND i.tipo = i_orig.tipo
              AND i.nombre_fichero = i_orig.nombre_fichero
        )
        WHERE input_id IS NOT NULL
        """,
        """
        DELETE FROM inputs
        WHERE id IN (
            SELECT id FROM inputs
            WHERE id NOT IN (
                SELECT MAX(id) FROM inputs
                GROUP BY asignatura_id, tipo, nombre_fichero
            )
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_inputs_asignatura_tipo_nombre
            ON inputs(asignatura_id, tipo, nombre_fichero)
        """,
    ],
    7: [
        """
        CREATE TABLE IF NOT EXISTS contenido_tema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema_id INTEGER NOT NULL UNIQUE REFERENCES temas(id),
            markdown_borrador TEXT,
            markdown_final TEXT,
            porcentaje_editado REAL,
            puntuacion_profesor INTEGER CHECK(puntuacion_profesor BETWEEN 1 AND 10),
            estado TEXT NOT NULL DEFAULT 'pendiente'
                CHECK(estado IN ('pendiente','generado','editado','aprobado')),
            fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS visualizacion_interactiva (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tema_id INTEGER NOT NULL REFERENCES temas(id),
            titulo TEXT NOT NULL,
            prompt_inicial TEXT,
            historial_json TEXT DEFAULT '[]',
            html_fragment TEXT,
            seccion_ancla TEXT DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'borrador'
                CHECK(estado IN ('borrador','aprobado')),
            orden INTEGER DEFAULT 0,
            fecha_actualizacion TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ],
    8: [
        "ALTER TABLE subbloques ADD COLUMN fuente TEXT DEFAULT ''",
    ],
}

# Estados válidos para el ciclo de vida de un subbloque de contenido (legado).
ESTADOS_SUBBLOQUE = frozenset({"pendiente", "generado", "editado", "aprobado"})

# Estados válidos para contenido curado a nivel de bloque temático.
ESTADOS_TEMA = frozenset({"pendiente", "generado", "editado", "aprobado"})

# Agentes que admiten valoración global del profesor (1-10).
AGENTES_VALORACION = frozenset({"organizador", "contenido", "presentacion"})


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------


def get_connection(ruta=RUTA_DB_POR_DEFECTO):
    """Devuelve una conexión sqlite3 con filas accesibles por nombre y FK activadas."""
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
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
                except sqlite3.OperationalError as exc:
                    msg = str(exc).lower()
                    if "duplicate column" in msg or "already exists" in msg:
                        continue
                    raise
            conn.commit()
            version_actual = version_destino

        # Fijar la versión final.
        conn.execute(f"PRAGMA user_version = {VERSION_SCHEMA}")
        conn.commit()
        return VERSION_SCHEMA
    finally:
        conn.close()


def crear_asignatura(nombre: str, ruta=RUTA_DB_POR_DEFECTO) -> int:
    """Inserta una asignatura nueva y devuelve su id.

    Raises:
        ValueError: si el nombre está vacío o ya existe en la BD.
    """
    nombre_limpio = nombre.strip()
    if not nombre_limpio:
        raise ValueError("El nombre de la asignatura no puede estar vacío.")
    conn = get_connection(ruta)
    try:
        cur = conn.execute(
            "INSERT INTO asignaturas (nombre) VALUES (?)",
            (nombre_limpio,),
        )
        conn.commit()
        return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe una asignatura con el nombre «{nombre_limpio}».")
    finally:
        conn.close()


def listar_asignaturas_portfolio(ruta=RUTA_DB_POR_DEFECTO) -> list[dict]:
    """Datos agregados de cada asignatura para la vista portfolio."""
    conn = get_connection(ruta)
    try:
        filas = conn.execute(
            "SELECT id, nombre FROM asignaturas ORDER BY id"
        ).fetchall()
        resultado: list[dict] = []
        for fila in filas:
            aid = fila["id"]
            n_guia = conn.execute(
                "SELECT COUNT(*) FROM inputs "
                "WHERE asignatura_id = ? AND tipo = 'guia_docente'",
                (aid,),
            ).fetchone()[0]
            n_materiales = conn.execute(
                "SELECT COUNT(*) FROM inputs "
                "WHERE asignatura_id = ? AND tipo = 'material_teoria'",
                (aid,),
            ).fetchone()[0]
            ultima = conn.execute(
                "SELECT MAX(fecha_inicio) FROM ejecuciones WHERE asignatura_id = ?",
                (aid,),
            ).fetchone()[0]
            resultado.append({
                "id": aid,
                "nombre": fila["nombre"],
                "n_guia": n_guia,
                "n_materiales": n_materiales,
                "n_inputs": n_guia + n_materiales,
                "ultima_ejecucion": ultima,
                "progreso": get_progreso_asignatura(aid, ruta),
            })
        return resultado
    finally:
        conn.close()


def listar_inputs_asignatura(
    asignatura_id: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> list[dict]:
    """Devuelve los inputs registrados de una asignatura, más recientes primero."""
    conn = get_connection(ruta)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, tipo, nombre_fichero, ruta_disco, fecha_subida "
                "FROM inputs WHERE asignatura_id = ? "
                "ORDER BY fecha_subida DESC, id DESC",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def registrar_input(
    asignatura_id: int,
    tipo: str,
    nombre_fichero: str,
    ruta_disco: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Registra un input o actualiza ruta y fecha si ya existe (misma asignatura, tipo y nombre)."""
    conn = get_connection(ruta)
    try:
        conn.execute(
            """
            INSERT INTO inputs (asignatura_id, tipo, nombre_fichero, ruta_disco)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asignatura_id, tipo, nombre_fichero) DO UPDATE SET
                ruta_disco = excluded.ruta_disco,
                fecha_subida = CURRENT_TIMESTAMP
            """,
            (asignatura_id, tipo, nombre_fichero, ruta_disco),
        )
        conn.commit()
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
# Vínculo bloque temático → material de teoría
# ---------------------------------------------------------------------------


def actualizar_tema_input_id(
    tema_id: int,
    input_id: int | None,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Actualiza el PDF/PPTX de teoría asociado a un bloque temático."""
    conn = get_connection(ruta)
    try:
        conn.execute(
            "UPDATE temas SET input_id = ? WHERE id = ?",
            (input_id, tema_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD de contenido curado por bloque temático (v7)
# ---------------------------------------------------------------------------


def get_contenido_tema(tema_id: int, ruta=RUTA_DB_POR_DEFECTO) -> dict | None:
    """Devuelve la fila de contenido_tema o None si el bloque no tiene contenido."""
    conn = get_connection(ruta)
    try:
        row = conn.execute(
            "SELECT id, tema_id, markdown_borrador, markdown_final, porcentaje_editado, "
            "puntuacion_profesor, estado, fecha_actualizacion "
            "FROM contenido_tema WHERE tema_id = ?",
            (tema_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def contar_trabajo_curado_asignatura(
    asignatura_id: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> tuple[int, int]:
    """Cuenta bloques con markdown curado y visualizaciones aprobadas de la asignatura."""
    conn = get_connection(ruta)
    try:
        n_contenido = conn.execute(
            """
            SELECT COUNT(*) FROM contenido_tema ct
            JOIN temas t ON t.id = ct.tema_id
            WHERE t.asignatura_id = ?
              AND (
                TRIM(COALESCE(ct.markdown_final, '')) != ''
                OR TRIM(COALESCE(ct.markdown_borrador, '')) != ''
              )
            """,
            (asignatura_id,),
        ).fetchone()[0]
        n_viz = conn.execute(
            """
            SELECT COUNT(*) FROM visualizacion_interactiva vi
            JOIN temas t ON t.id = vi.tema_id
            WHERE t.asignatura_id = ? AND vi.estado = 'aprobado'
            """,
            (asignatura_id,),
        ).fetchone()[0]
        return int(n_contenido), int(n_viz)
    finally:
        conn.close()


def upsert_contenido_tema_borrador(
    tema_id: int,
    markdown_borrador: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Guarda el borrador generado por IA y marca el bloque como 'generado'."""
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_tema WHERE tema_id = ?", (tema_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_tema SET markdown_borrador = ?, estado = 'generado', "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE tema_id = ?",
                (markdown_borrador, tema_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_tema (tema_id, markdown_borrador, estado) "
                "VALUES (?, ?, 'generado')",
                (tema_id, markdown_borrador),
            )
        conn.commit()
    finally:
        conn.close()


def regenerar_contenido_tema_borrador(
    tema_id: int,
    markdown_borrador: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Sustituye el borrador y revierte ediciones/aprobación previas del bloque."""
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_tema WHERE tema_id = ?", (tema_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_tema SET markdown_borrador = ?, markdown_final = NULL, "
                "porcentaje_editado = NULL, puntuacion_profesor = NULL, estado = 'generado', "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE tema_id = ?",
                (markdown_borrador, tema_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_tema (tema_id, markdown_borrador, estado) "
                "VALUES (?, ?, 'generado')",
                (tema_id, markdown_borrador),
            )
        conn.commit()
    finally:
        conn.close()


def guardar_contenido_tema_edicion(
    tema_id: int,
    markdown: str,
    porcentaje_editado: float,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Persiste una edición manual del profesor (sin aprobar todavía)."""
    estado = "editado"
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_tema WHERE tema_id = ?", (tema_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_tema SET markdown_final = ?, porcentaje_editado = ?, "
                "estado = ?, fecha_actualizacion = CURRENT_TIMESTAMP WHERE tema_id = ?",
                (markdown, porcentaje_editado, estado, tema_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_tema "
                "(tema_id, markdown_borrador, markdown_final, porcentaje_editado, estado) "
                "VALUES (?, '', ?, ?, ?)",
                (tema_id, markdown, porcentaje_editado, estado),
            )
        conn.commit()
    finally:
        conn.close()


def aprobar_contenido_tema(
    tema_id: int,
    markdown: str,
    porcentaje_editado: float,
    puntuacion: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Marca el bloque temático como aprobado con valoración del profesor."""
    if not 1 <= puntuacion <= 10:
        raise ValueError(f"Puntuación fuera de rango: {puntuacion}")
    conn = get_connection(ruta)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_tema WHERE tema_id = ?", (tema_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_tema SET markdown_final = ?, porcentaje_editado = ?, "
                "estado = 'aprobado', puntuacion_profesor = ?, "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE tema_id = ?",
                (markdown, porcentaje_editado, puntuacion, tema_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_tema "
                "(tema_id, markdown_borrador, markdown_final, porcentaje_editado, "
                "estado, puntuacion_profesor) VALUES (?, ?, ?, ?, 'aprobado', ?)",
                (tema_id, markdown, markdown, porcentaje_editado, puntuacion),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD de visualizaciones interactivas (Presentación v7)
# ---------------------------------------------------------------------------


def listar_visualizaciones_tema(tema_id: int, ruta=RUTA_DB_POR_DEFECTO) -> list[dict]:
    conn = get_connection(ruta)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, tema_id, titulo, prompt_inicial, historial_json, "
                "html_fragment, seccion_ancla, estado, orden, fecha_actualizacion "
                "FROM visualizacion_interactiva WHERE tema_id = ? "
                "ORDER BY orden, id",
                (tema_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def get_visualizacion(viz_id: int, ruta=RUTA_DB_POR_DEFECTO) -> dict | None:
    conn = get_connection(ruta)
    try:
        row = conn.execute(
            "SELECT id, tema_id, titulo, prompt_inicial, historial_json, "
            "html_fragment, seccion_ancla, estado, orden, fecha_actualizacion "
            "FROM visualizacion_interactiva WHERE id = ?",
            (viz_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def insertar_visualizacion_borrador(
    tema_id: int,
    titulo: str,
    prompt_inicial: str,
    historial_json: str,
    html_fragment: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> int:
    conn = get_connection(ruta)
    try:
        max_orden = conn.execute(
            "SELECT COALESCE(MAX(orden), -1) FROM visualizacion_interactiva WHERE tema_id = ?",
            (tema_id,),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO visualizacion_interactiva "
            "(tema_id, titulo, prompt_inicial, historial_json, html_fragment, orden) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tema_id, titulo, prompt_inicial, historial_json, html_fragment, max_orden + 1),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def actualizar_visualizacion_borrador(
    viz_id: int,
    html_fragment: str,
    historial_json: str,
    titulo: str | None = None,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    conn = get_connection(ruta)
    try:
        if titulo is not None:
            conn.execute(
                "UPDATE visualizacion_interactiva SET html_fragment = ?, historial_json = ?, "
                "titulo = ?, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
                (html_fragment, historial_json, titulo, viz_id),
            )
        else:
            conn.execute(
                "UPDATE visualizacion_interactiva SET html_fragment = ?, historial_json = ?, "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
                (html_fragment, historial_json, viz_id),
            )
        conn.commit()
    finally:
        conn.close()


def aprobar_visualizacion(
    viz_id: int,
    seccion_ancla: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    conn = get_connection(ruta)
    try:
        conn.execute(
            "UPDATE visualizacion_interactiva SET estado = 'aprobado', seccion_ancla = ?, "
            "fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = ?",
            (seccion_ancla, viz_id),
        )
        conn.commit()
    finally:
        conn.close()


def eliminar_visualizacion(viz_id: int, ruta=RUTA_DB_POR_DEFECTO) -> None:
    conn = get_connection(ruta)
    try:
        conn.execute("DELETE FROM visualizacion_interactiva WHERE id = ?", (viz_id,))
        conn.commit()
    finally:
        conn.close()


def listar_visualizaciones_aprobadas(tema_id: int, ruta=RUTA_DB_POR_DEFECTO) -> list[dict]:
    conn = get_connection(ruta)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, titulo, html_fragment, seccion_ancla, orden "
                "FROM visualizacion_interactiva "
                "WHERE tema_id = ? AND estado = 'aprobado' "
                "ORDER BY orden, id",
                (tema_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD de estado de subbloque de contenido (legado)
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

    Progreso = 1 si contenido_tema.estado == 'aprobado', 0 en caso contrario.

    Returns:
        {"total": int, "aprobados": int, "porcentaje": float}
    """
    conn = get_connection(ruta)
    try:
        row = conn.execute(
            "SELECT estado FROM contenido_tema WHERE tema_id = ?",
            (tema_id,),
        ).fetchone()
        aprobado = 1 if row and row["estado"] == "aprobado" else 0
    finally:
        conn.close()
    return {
        "total": 1,
        "aprobados": aprobado,
        "porcentaje": 100.0 if aprobado else 0.0,
    }


def get_progreso_asignatura(asignatura_id: int, ruta=RUTA_DB_POR_DEFECTO) -> dict:
    """Calcula el progreso global de una asignatura en tiempo real.

    Progreso = bloques temáticos con contenido_tema aprobado / total bloques.

    Returns:
        {"total": int, "aprobados": int, "porcentaje": float}
    """
    conn = get_connection(ruta)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM temas WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        aprobados = conn.execute(
            """
            SELECT COUNT(*)
            FROM temas t
            JOIN contenido_tema ct ON ct.tema_id = t.id
            WHERE t.asignatura_id = ? AND ct.estado = 'aprobado'
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
        (total_sub y aprobados son 0/1 por bloque — compatibilidad con la UI)
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
            row = conn.execute(
                "SELECT estado FROM contenido_tema WHERE tema_id = ?",
                (t["id"],),
            ).fetchone()
            aprobado = 1 if row and row["estado"] == "aprobado" else 0
            resultado.append({
                "tema_id": t["id"],
                "nombre": t["nombre"],
                "horas": t["horas"],
                "total_sub": 1,
                "aprobados": aprobado,
                "porcentaje": 100.0 if aprobado else 0.0,
            })
        return resultado
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Valoración global del profesor (1-10) por asignatura y agente
# ---------------------------------------------------------------------------


def upsert_valoracion_profesor(
    asignatura_id: int,
    agente: str,
    puntuacion: int,
    ruta=RUTA_DB_POR_DEFECTO,
) -> None:
    """Guarda o actualiza la puntuación 1-10 del profesor para un agente y asignatura."""
    if agente not in AGENTES_VALORACION:
        raise ValueError(
            f"Agente inválido: {agente!r}. Válidos: {sorted(AGENTES_VALORACION)}"
        )
    if not 1 <= puntuacion <= 10:
        raise ValueError(f"Puntuación fuera de rango: {puntuacion}. Debe estar entre 1 y 10.")
    conn = get_connection(ruta)
    try:
        conn.execute(
            """
            INSERT INTO valoraciones_profesor (asignatura_id, agente, puntuacion)
            VALUES (?, ?, ?)
            ON CONFLICT(asignatura_id, agente) DO UPDATE SET
                puntuacion = excluded.puntuacion,
                fecha_actualizacion = CURRENT_TIMESTAMP
            """,
            (asignatura_id, agente, puntuacion),
        )
        conn.commit()
    finally:
        conn.close()


def get_valoracion_profesor(
    asignatura_id: int,
    agente: str,
    ruta=RUTA_DB_POR_DEFECTO,
) -> int | None:
    """Devuelve la puntuación guardada o None si el profesor aún no ha valorado."""
    if agente not in AGENTES_VALORACION:
        raise ValueError(
            f"Agente inválido: {agente!r}. Válidos: {sorted(AGENTES_VALORACION)}"
        )
    conn = get_connection(ruta)
    try:
        row = conn.execute(
            "SELECT puntuacion FROM valoraciones_profesor "
            "WHERE asignatura_id = ? AND agente = ?",
            (asignatura_id, agente),
        ).fetchone()
        return int(row["puntuacion"]) if row else None
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
