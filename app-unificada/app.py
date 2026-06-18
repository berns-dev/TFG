"""App Streamlit unificada de la suite de agentes docentes del TFG.

Punto de entrada único que reúne los tres agentes (Organizador, Contenido,
Presentación) sobre la base de datos compartida `database/db.py`.

Arranque:
    streamlit run app-unificada/app.py
"""

import difflib
from datetime import datetime
import html
import importlib.util as _importlib_util
import os
import re
import sys
import unicodedata
from pathlib import Path

import streamlit as st

# =============================================================================
# Rutas del monorepo
# =============================================================================

RAIZ_MONOREPO = str(Path(__file__).resolve().parent.parent)
RAIZ_APP = str(Path(__file__).resolve().parent)
RAIZ_ORGANIZADOR = os.path.join(RAIZ_MONOREPO, "agente-organizador")

if RAIZ_MONOREPO not in sys.path:
    sys.path.insert(0, RAIZ_MONOREPO)
if RAIZ_APP not in sys.path:
    sys.path.insert(0, RAIZ_APP)

from database import db  # noqa: E402
from ui.portfolio import render_portfolio  # noqa: E402
from ui.sidebar import (  # noqa: E402
    render_marca,
    render_sidebar_portfolio,
    render_sidebar_workspace,
)
from ui.theme import inject_theme  # noqa: E402
from utils import fichero_existe  # noqa: E402

RUTA_DB = os.path.join(RAIZ_MONOREPO, "data", "tfg.db")

# =============================================================================
# Identidad visual
# =============================================================================

ACENTO = "#185FA5"
ACENTO_OSCURO = "#0C447C"

VISTAS_NAV = ["Resumen", "Inputs", "Organizador", "Contenido", "Presentación"]
# Vista de depuración (no aparece en la navegación lateral).
VISTA_BASE_DATOS = "Base de datos"
VISTAS = VISTAS_NAV

TITULOS_SECCION = {
    "Resumen": "Resumen del pipeline",
    "Inputs": "Inputs almacenados",
    "Organizador": "Agente organizador",
    "Contenido": "Agente de contenido",
    "Presentación": "Agente de presentación",
    "Base de datos": "Base de datos",
}

ICONOS_VISTA = {
    "Resumen": "📊",
    "Inputs": "📁",
    "Organizador": "🗂️",
    "Contenido": "📝",
    "Presentación": "🎨",
    "Base de datos": "🗄️",
}

# =============================================================================
# Carga aislada de los módulos de los tres agentes vía importlib
#
# Problema: los tres agentes tienen archivos con el mismo nombre genérico
# (config.py y prompts.py en Contenido y Presentación, además de "parser" que
# colisiona con un nombre de stdlib). Si se registran en sys.modules bajo su
# nombre genérico, cargar un agente después de otro sobreescribe esa clave y
# puede romper silenciosamente al agente anterior si vuelve a resolver ese módulo.
#
# Solución: cada módulo se registra de forma PERMANENTE bajo una clave única con
# prefijo de agente ("organizador_config", "contenido_config", "presentacion_config"…).
# El nombre genérico ("config", "cleaner", …) se registra solo TEMPORALMENTE durante
# la carga del propio agente, porque los imports cruzados internos de sus archivos
# —que no podemos modificar— usan ese nombre genérico (p.ej. extractor hace
# `from cleaner import …`). Al terminar el lote se restaura el estado previo de
# sys.modules para esos nombres genéricos, de modo que cargar un agente nunca
# afecte a los módulos ya cargados de otro, sin importar el orden de carga.
# =============================================================================

RAIZ_CONTENIDO = os.path.join(RAIZ_MONOREPO, "agente-contenido")
RAIZ_PRESENTACION = os.path.join(RAIZ_MONOREPO, "agente-presentacion")


def _cargar_modulos_agente(raiz: str, prefijo: str, nombres: list[str]) -> dict:
    """Carga los módulos de un agente con aislamiento en sys.modules.

    `nombres` debe listarse en orden de dependencia (las dependencias primero,
    para que el nombre genérico de cada una esté disponible cuando un módulo
    dependiente la importe). Devuelve {nombre_genérico: módulo}.

    Claves permanentes: f"{prefijo}_{nombre}" (aisladas por agente).
    Claves genéricas: temporales durante el lote; se restauran al final.
    """
    previos: dict[str, object] = {}
    genericos_tocados: list[str] = []
    cargados: dict[str, object] = {}
    try:
        for name in nombres:
            ruta = os.path.join(raiz, f"{name}.py")
            spec = _importlib_util.spec_from_file_location(f"{prefijo}_{name}", ruta)
            mod = _importlib_util.module_from_spec(spec)
            # Clave permanente prefijada — nunca colisiona con otro agente.
            sys.modules[f"{prefijo}_{name}"] = mod
            # Clave genérica TEMPORAL — solo para resolver imports cruzados internos.
            if name not in previos:
                previos[name] = sys.modules.get(name)
                genericos_tocados.append(name)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            cargados[name] = mod
        return cargados
    finally:
        # Restaurar el estado previo de las claves genéricas: elimina toda
        # posibilidad de colisión entre agentes una vez cargado este lote.
        for name in genericos_tocados:
            anterior = previos.get(name)
            if anterior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = anterior


# ── Agente Organizador (sin imports cruzados entre los módulos cargados) ──────
try:
    _org_mods = _cargar_modulos_agente(
        RAIZ_ORGANIZADOR, "organizador", ["agente", "parser", "org_prompts"]
    )
    _org_agente = _org_mods["agente"]
    _org_parser = _org_mods["parser"]
    _org_prompts = _org_mods["org_prompts"]
    _ORG_ERROR: str | None = None
except Exception as _e:
    _org_agente = _org_parser = _org_prompts = None
    _ORG_ERROR = str(_e)


# ── Agente Contenido (extractor←cleaner; chunker/classifier/validator←cnt_config) ─
# pipeline importa de chunker, classifier, assembler, validator → va al final.
try:
    _cnt_mods = _cargar_modulos_agente(
        RAIZ_CONTENIDO, "contenido",
        [
            "cnt_config", "cleaner", "extractor", "chunker", "classifier",
            "assembler", "validator", "segmentor", "pipeline",
        ],
    )
    _cnt_config = _cnt_mods["cnt_config"]
    _cnt_cleaner = _cnt_mods["cleaner"]
    _cnt_extractor = _cnt_mods["extractor"]
    _cnt_chunker = _cnt_mods["chunker"]
    _cnt_classifier = _cnt_mods["classifier"]
    _cnt_assembler = _cnt_mods["assembler"]
    _cnt_validator = _cnt_mods["validator"]
    _cnt_segmentor = _cnt_mods["segmentor"]
    _cnt_pipeline = _cnt_mods["pipeline"]
    _CNT_ERROR: str | None = None
except Exception as _ce:
    _cnt_config = _cnt_cleaner = _cnt_extractor = _cnt_chunker = _cnt_classifier = None
    _cnt_assembler = _cnt_validator = _cnt_segmentor = _cnt_pipeline = None
    _CNT_ERROR = str(_ce)


# ── Agente Presentación (detector/generador_html←prs_config, prs_prompts) ─────
# generador_presentacion importa de generador_html → va al final del lote.
try:
    _prs_mods = _cargar_modulos_agente(
        RAIZ_PRESENTACION, "presentacion",
        ["prs_config", "prs_prompts", "generador_html", "detector", "generador_pdf", "generador_presentacion"],
    )
    _prs_config = _prs_mods["prs_config"]
    _prs_prompts = _prs_mods["prs_prompts"]
    _prs_generador_html = _prs_mods["generador_html"]
    _prs_detector = _prs_mods["detector"]
    _prs_generador_pdf = _prs_mods["generador_pdf"]
    _prs_generador_presentacion = _prs_mods["generador_presentacion"]
    _PRS_ERROR: str | None = None
except Exception as _pe:
    _prs_config = _prs_prompts = _prs_generador_html = _prs_detector = None
    _prs_generador_pdf = _prs_generador_presentacion = None
    _PRS_ERROR = str(_pe)


# =============================================================================
# Lógica pura del Organizador — importada desde agente-organizador/parser.py
#
# Estas funciones (extraer_horas_docencia, normalizar_horas_output,
# contar_bloques_output, construir_nombre_descarga y parsear_bloques_organizador)
# vivían aquí como copias literales de agente-organizador/app.py. Ahora son la
# fuente de verdad única en el módulo `parser` del Organizador, ya importable
# porque no arrastra Streamlit. Se acceden vía `_org_parser.<funcion>` en la
# lógica de generación y al confirmar la organización; ya no se duplican.
# =============================================================================


# =============================================================================
# Helpers de base de datos
# =============================================================================

def _slugify(nombre: str) -> str:
    """Convierte un nombre de asignatura a slug para nombres de carpeta."""
    s = unicodedata.normalize("NFD", nombre)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _get_asignatura_id(nombre: str) -> int | None:
    conn = db.get_connection(RUTA_DB)
    try:
        fila = conn.execute(
            "SELECT id FROM asignaturas WHERE nombre = ?", (nombre,)
        ).fetchone()
    finally:
        conn.close()
    return fila["id"] if fila else None


def _db_registrar_input(asignatura_id: int, tipo: str, nombre_fichero: str, ruta_disco: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO inputs (asignatura_id, tipo, nombre_fichero, ruta_disco)
               VALUES (?, ?, ?, ?)""",
            (asignatura_id, tipo, nombre_fichero, ruta_disco),
        )
        conn.commit()
    finally:
        conn.close()


def _db_crear_ejecucion(asignatura_id: int) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO ejecuciones (asignatura_id, agente, estado)
               VALUES (?, 'organizador', 'en_progreso')""",
            (asignatura_id,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_actualizar_ejecucion(ejecucion_id: int, estado: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE ejecuciones SET estado = ? WHERE id = ?", (estado, ejecucion_id)
        )
        conn.commit()
    finally:
        conn.close()


def _db_crear_ejecucion_contenido(asignatura_id: int) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO ejecuciones (asignatura_id, agente, estado)
               VALUES (?, 'contenido', 'en_progreso')""",
            (asignatura_id,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_registrar_validacion(
    ejecucion_id: int | None,
    tipo: str,
    descripcion: str,
    valor_afectado: float | None,
    bloqueante: int = 0,
) -> None:
    """Persiste un aviso de validación automática ligado a una ejecución.

    Solo añade la fila; la lógica que calcula la cobertura (Organizador) o la
    fidelidad léxica (Contenido) no se altera — esto es únicamente persistencia.
    """
    if ejecucion_id is None:
        return
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            """INSERT INTO validaciones
               (ejecucion_id, tipo, descripcion, valor_afectado, bloqueante)
               VALUES (?, ?, ?, ?, ?)""",
            (ejecucion_id, tipo, descripcion, valor_afectado, bloqueante),
        )
        conn.commit()
    finally:
        conn.close()


def _db_guardar_organizador_output(
    asignatura_id: int,
    ejecucion_id: int,
    markdown_path: str,
    version: int,
    feedback_texto: str | None = None,
) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO organizador_outputs
               (asignatura_id, ejecucion_id, markdown_path, feedback_texto, version)
               VALUES (?, ?, ?, ?, ?)""",
            (asignatura_id, ejecucion_id, markdown_path, feedback_texto, version),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_confirmar_organizacion(asignatura_id: int, output_id: int, bloques: list[dict]) -> None:
    """Borra temas/subbloques anteriores e inserta los de la versión confirmada.

    Cada subtema puede incluir horas, evidencia, origen y es_fallback cuando
    procede del nuevo formato del Agente Organizador (v2+).
    Cada bloque puede incluir ``archivo_origen`` para vincular su PDF (``input_id``).
    """
    conn = db.get_connection(RUTA_DB)
    try:
        temas_existentes = conn.execute(
            "SELECT id FROM temas WHERE asignatura_id = ?", (asignatura_id,)
        ).fetchall()
        for tema in temas_existentes:
            conn.execute("DELETE FROM subbloques WHERE tema_id = ?", (tema["id"],))
        conn.execute("DELETE FROM temas WHERE asignatura_id = ?", (asignatura_id,))

        for orden, bloque in enumerate(bloques, start=1):
            input_id: int | None = None
            archivo = (bloque.get("archivo_origen") or "").strip()
            if archivo:
                fila = conn.execute(
                    "SELECT id FROM inputs "
                    "WHERE asignatura_id = ? AND tipo = 'material_teoria' "
                    "AND nombre_fichero = ?",
                    (asignatura_id, archivo),
                ).fetchone()
                if fila:
                    input_id = fila["id"]

            cur = conn.execute(
                """INSERT INTO temas
                   (asignatura_id, organizador_output_id, nombre, horas, bloque, orden, input_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    asignatura_id, output_id,
                    bloque["nombre"], bloque["horas"],
                    f"Bloque {bloque['numero']}", orden,
                    input_id,
                ),
            )
            tema_id = cur.lastrowid
            for subtema in bloque["subtemas"]:
                conn.execute(
                    """INSERT INTO subbloques
                       (tema_id, nombre, orden, horas, evidencia, origen, es_fallback)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tema_id,
                        subtema["nombre"],
                        subtema.get("orden", 0),
                        subtema.get("horas", 0.0),
                        subtema.get("evidencia", ""),
                        subtema.get("origen", "Detectado"),
                        subtema.get("es_fallback", 0),
                    ),
                )

        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Organizador — gestión de session_state
# =============================================================================

_ORG_KEYS: dict[str, object] = {
    "org_ultimo_output": None,
    "org_historial_feedback": [],
    "org_iteracion": 1,
    "org_ultimos_archivos_teoria": [],
    "org_ultimos_archivos_contexto": [],
    "org_ultimas_horas_teoria": None,
    "org_ultimas_horas_totales": None,
    "org_session_id_archivos": "",
    "org_ultimo_nombre_descarga": "Propuesta_asignatura.md",
    "org_warning_cardinalidad": None,
    "org_warning_normalizacion": None,
    "org_warning_truncamiento": None,
    "org_ejecucion_id": None,
    "org_version_actual": 0,
    "org_output_id": None,
    "org_confirmada": False,
    "org_inputs_registrados": set(),  # {"{slug}:{filename}"}
    # Estado estructurado para la edición manual de bloques/subbloques.
    # Solo operativo antes de confirmar la organización (fase de revisión).
    "org_organizacion_bloques": lambda: [],
    "org_contador_add_subtema": lambda: {},
    "org_contador_add_bloque": 0,
    "org_subtemas_detectados": lambda: [],
    "org_sub_widget_rev": lambda: {},
}


def _org_init_state() -> None:
    for k, v_default in _ORG_KEYS.items():
        if k not in st.session_state:
            st.session_state[k] = v_default() if callable(v_default) else v_default


def _org_reset_state() -> None:
    for k, v_default in _ORG_KEYS.items():
        st.session_state[k] = v_default() if callable(v_default) else v_default


# =============================================================================
# Organizador — persistencia de archivos
# =============================================================================

def _org_registrar_archivos(
    guia_docente,
    materiales_teoria,
    asignatura_id: int,
    slug: str,
    asignatura_nombre: str,
) -> None:
    """Guarda en disco y registra en BD los archivos que sean nuevos en esta sesión."""
    dir_inputs = os.path.join(RAIZ_MONOREPO, "data", slug, "inputs")
    os.makedirs(dir_inputs, exist_ok=True)

    def _registrar(archivo, tipo: str) -> None:
        clave = f"{slug}:{archivo.name}"
        if clave in st.session_state["org_inputs_registrados"]:
            return
        ruta = os.path.join(dir_inputs, archivo.name)
        with open(ruta, "wb") as f:
            f.write(archivo.getvalue())
        try:
            _db_registrar_input(asignatura_id, tipo, archivo.name, ruta)
        except Exception:
            pass
        st.session_state["org_inputs_registrados"].add(clave)

    if guia_docente is not None:
        _registrar(guia_docente, "guia_docente")
    for mat in (materiales_teoria or []):
        _registrar(mat, "material_teoria")


def _org_detectar_cambio(guia_docente, materiales_teoria) -> None:
    """Resetea el output y la fase si el conjunto de archivos cambió."""
    nombres: list[str] = []
    if guia_docente is not None:
        nombres.append(f"guia:{guia_docente.name}")
    for f in (materiales_teoria or []):
        nombres.append(f"mat:{f.name}")
    session_id = "|".join(sorted(nombres))

    if session_id and session_id != st.session_state["org_session_id_archivos"]:
        st.session_state["org_ultimo_output"] = None
        st.session_state["org_historial_feedback"] = []
        st.session_state["org_iteracion"] = 1
        st.session_state["org_warning_cardinalidad"] = None
        st.session_state["org_warning_normalizacion"] = None
        st.session_state["org_ejecucion_id"] = None
        st.session_state["org_version_actual"] = 0
        st.session_state["org_output_id"] = None
        st.session_state["org_confirmada"] = False
        st.session_state["org_organizacion_bloques"] = []
        st.session_state["org_contador_add_subtema"] = {}
        st.session_state["org_contador_add_bloque"] = 0
        st.session_state["org_session_id_archivos"] = session_id


# =============================================================================
# Organizador — lógica de generación (adaptada de agente-organizador/app.py)
# =============================================================================

def _texto_warning_cobertura(esperados: int, generados: int) -> str:
    """Texto exacto del aviso de cobertura incompleta guía-vs-materiales.

    Único origen del texto: lo usa tanto la vista (st.warning) como la
    persistencia en `validaciones`, para que `descripcion` sea idéntica a lo
    que ve el profesor.
    """
    return (
        f"⚠️ **Discrepancia de bloques detectada:** el output contiene "
        f"**{generados} bloques** pero se esperaban **{esperados}** "
        f"(uno por archivo de teoría subido). "
        f"El modelo probablemente elevó una subsección a bloque independiente. "
        f"Usa el campo de feedback para indicar qué bloque debe reintegrarse como subtema "
        f"y pulsa Regenerar."
    )


def _org_validar_y_persistir(
    resultado: str,
    n_esperados: int,
    asignatura_id: int,
    slug: str,
    version: int,
    ejecucion_id: int,
    feedback_texto: str | None = None,
    nombre_descarga: str | None = None,
) -> None:
    n_generados = _org_parser.contar_bloques_output(resultado)
    st.session_state["org_warning_cardinalidad"] = (
        {"esperados": n_esperados, "generados": n_generados}
        if n_generados != n_esperados
        else None
    )

    # Registrar el aviso de cobertura incompleta en `validaciones`. El cálculo de
    # cobertura (bloques esperados = un material de teoría por bloque) no se toca;
    # aquí solo se persiste. valor_afectado = bloques sin cubrir (esperados − generados):
    # la métrica determinista de cobertura de este agente es por bloque, no por hora.
    if st.session_state["org_warning_cardinalidad"]:
        bloques_sin_cubrir = max(0, n_esperados - n_generados)
        _db_registrar_validacion(
            ejecucion_id=ejecucion_id,
            tipo="cobertura_incompleta",
            descripcion=_texto_warning_cobertura(n_esperados, n_generados),
            valor_afectado=float(bloques_sin_cubrir),
            bloqueante=0,
        )

    st.session_state["org_ultimo_output"] = resultado
    if nombre_descarga:
        st.session_state["org_ultimo_nombre_descarga"] = nombre_descarga

    # Guardar markdown en disco
    dir_out = os.path.join(RAIZ_MONOREPO, "data", slug, "outputs", "organizador")
    os.makedirs(dir_out, exist_ok=True)
    ruta_md = os.path.join(dir_out, f"v{version}.md")
    with open(ruta_md, "w", encoding="utf-8") as fh:
        fh.write(resultado)

    output_id = _db_guardar_organizador_output(
        asignatura_id=asignatura_id,
        ejecucion_id=ejecucion_id,
        markdown_path=ruta_md,
        version=version,
        feedback_texto=feedback_texto,
    )
    st.session_state["org_output_id"] = output_id
    st.session_state["org_version_actual"] = version

    # Estado estructurado para la edición manual (mismo helper que el standalone).
    # Reutiliza parsear_bloques_desde_markdown del Organizador: deriva la lista
    # de bloques/subtemas editables del Markdown recién generado.
    st.session_state["org_organizacion_bloques"] = _org_parser.parsear_bloques_desde_markdown(resultado)
    archivos = st.session_state.get("org_ultimos_archivos_teoria", [])
    for i, bloque in enumerate(st.session_state["org_organizacion_bloques"]):
        bloque["archivo_origen"] = _org_resolver_archivo_bloque(bloque["nombre"], archivos, i)
    st.session_state["org_contador_add_subtema"] = {}
    st.session_state["org_contador_add_bloque"] = 0


def _org_actualizar_desde_bloques(slug: str) -> None:
    """Regenera el Markdown y la persistencia tras una edición manual de bloques.

    Reutiliza regenerar_markdown_desde_bloques del Organizador para reconstruir
    el output desde el estado estructurado, actualiza la versión en disco
    (data/{slug}/outputs/organizador/vN.md) para que el fichero persistido siga
    el estado editado, y refresca el aviso de cardinalidad. No crea una versión
    nueva: la edición manual ajusta la versión actual en fase de revisión.
    """
    bloques = st.session_state.get("org_organizacion_bloques", [])
    output_actual = st.session_state.get("org_ultimo_output", "")
    if not (bloques and output_actual):
        return

    nuevo_md = _org_parser.regenerar_markdown_desde_bloques(bloques, output_actual)
    st.session_state["org_ultimo_output"] = nuevo_md

    version = st.session_state.get("org_version_actual", 0)
    if version:
        dir_out = os.path.join(RAIZ_MONOREPO, "data", slug, "outputs", "organizador")
        os.makedirs(dir_out, exist_ok=True)
        ruta_md = os.path.join(dir_out, f"v{version}.md")
        try:
            with open(ruta_md, "w", encoding="utf-8") as fh:
                fh.write(nuevo_md)
        except OSError:
            pass

    # Recalcular el aviso de cobertura con la nueva estructura.
    n_esperados = len(st.session_state.get("org_ultimos_archivos_teoria", []))
    n_generados = _org_parser.contar_bloques_output(nuevo_md)
    st.session_state["org_warning_cardinalidad"] = (
        {"esperados": n_esperados, "generados": n_generados}
        if n_esperados and n_generados != n_esperados
        else None
    )


def _org_build_subtemas_confirmados(
    texto_guia: str,
    textos_teoria: list[str],
    archivos_teoria: list[str],
    archivos_bytes: list[bytes],
) -> list[list[dict]] | None:
    """Guía docente primero (modo libre); lista cerrada del material solo sin guía."""
    return _org_parser.construir_subtemas_confirmados(
        texto_guia, textos_teoria, archivos_teoria, archivos_bytes
    )


def _org_bump_sub_widget_rev(idx_b: int) -> None:
    """Invalida widgets de subtemas tras borrar o reordenar filas (evita desfase Streamlit)."""
    revs = st.session_state.setdefault("org_sub_widget_rev", {})
    revs[idx_b] = revs.get(idx_b, 0) + 1
    st.session_state["org_sub_widget_rev"] = revs


def _org_resolver_archivo_bloque(nombre_bloque: str, archivos: list[str], idx: int) -> str:
    """Asocia un bloque generado al PDF/PPTX de teoría más probable."""
    return _org_parser.resolver_archivo_bloque(nombre_bloque, archivos, idx)


def _org_cargar_candidatos_material_desde_disco(
    asignatura_id: int,
) -> tuple[list[str], list[list[dict]]]:
    """Re-detecta candidatos con evidencia desde los inputs persistidos en BD."""
    conn = db.get_connection(RUTA_DB)
    try:
        filas = conn.execute(
            "SELECT nombre_fichero, ruta_disco FROM inputs "
            "WHERE asignatura_id = ? AND tipo = 'material_teoria' "
            "ORDER BY id",
            (asignatura_id,),
        ).fetchall()
    finally:
        conn.close()

    archivos: list[str] = []
    candidatos: list[list[dict]] = []
    for fila in filas:
        ruta = fila["ruta_disco"]
        if not os.path.exists(ruta):
            continue
        nombre = fila["nombre_fichero"]
        try:
            with open(ruta, "rb") as fh:
                archivo_bytes = fh.read()
            texto = _org_parser.extraer_texto(archivo_bytes, nombre)
            cands = _org_parser.extraer_candidatos_con_evidencia(
                texto, nombre, archivo_bytes
            )
        except Exception:
            cands = []
        archivos.append(nombre)
        candidatos.append(cands)
    return archivos, candidatos


def _org_preparar_bloques_para_confirmar(
    markdown: str,
    asignatura_id: int,
) -> list[dict]:
    """Parsea el Markdown de organización y completa evidencia desde detección determinista."""
    bloques = _org_parser.parsear_bloques_organizador(markdown)
    if not bloques:
        return []

    archivos = st.session_state.get("org_ultimos_archivos_teoria", [])
    candidatos = st.session_state.get("org_subtemas_detectados", [])
    if not archivos:
        archivos, candidatos = _org_cargar_candidatos_material_desde_disco(asignatura_id)
    elif not candidatos:
        _, candidatos = _org_cargar_candidatos_material_desde_disco(asignatura_id)

    return _org_parser.enriquecer_bloques_con_evidencia_detectada(
        bloques, candidatos, archivos
    )


def _org_format_evidencia(sub: dict, archivo_bloque: str) -> str:
    """Texto interpretable para la columna Evidencia en la vista unificada."""
    ev = (sub.get("evidencia") or "").strip()
    if sub.get("manual"):
        return ev or "Manual (profesor)"
    vacios = {"", "—", "-", "Sin señal verificable", "Sin senal verificable"}
    if ev and ev not in vacios:
        return ev
    if archivo_bloque:
        return f"Sin señal estructural — extraído de {archivo_bloque}"
    return "Sin señal estructural"


def _org_generar_organizacion(
    guia_docente,
    materiales_teoria,
    asignatura_id: int,
    slug: str,
    feedback_previo: list[str] | None = None,
    subtemas_confirmados: list[list[dict]] | None = None,
) -> bool:
    output_previo = st.session_state.get("org_ultimo_output")

    # ── Camino rápido: refinamiento ────────────────────────────────────────────
    if feedback_previo and output_previo:
        with st.status("Aplicando ajuste...", expanded=True) as status:
            try:
                horas_totales = st.session_state.get("org_ultimas_horas_totales")
                n_esperados = len(st.session_state.get("org_ultimos_archivos_teoria", []))
                prompt = _org_prompts.construir_prompt_refinamiento(
                    output_previo=output_previo,
                    feedback_previo=feedback_previo,
                    horas_totales=horas_totales,
                )
                st.write("🤖 Aplicando ajuste sobre la organización actual...")
                resultado, stop_reason = _org_agente.ejecutar_agente(prompt)
                st.session_state["org_warning_truncamiento"] = _org_parser.detectar_output_truncado(
                    resultado, stop_reason
                )
                resultado, info_norm = _org_parser.normalizar_horas_output(resultado, horas_totales or 0)
                st.session_state["org_warning_normalizacion"] = info_norm

                version = st.session_state.get("org_version_actual", 1) + 1
                ejecucion_id = st.session_state.get("org_ejecucion_id")
                feedback_texto = feedback_previo[-1] if feedback_previo else None

                _org_validar_y_persistir(
                    resultado, n_esperados, asignatura_id, slug,
                    version, ejecucion_id, feedback_texto=feedback_texto,
                )
                status.update(label="✅ Ajuste aplicado", state="complete")
                return True
            except Exception as err:
                status.update(label="❌ Error al aplicar el ajuste", state="error")
                st.error(f"Error durante el refinamiento: {err}")
                return False

    # ── Camino completo: primera generación ───────────────────────────────────
    if guia_docente is None:
        st.error("Debes subir una guía docente para generar la organización.")
        return False
    if not materiales_teoria:
        st.error("Debes subir al menos un material de teoría.")
        return False

    ejecucion_id = _db_crear_ejecucion(asignatura_id)
    st.session_state["org_ejecucion_id"] = ejecucion_id

    with st.status("Procesando documentos...", expanded=True) as status:
        try:
            st.write("📄 Extrayendo texto de la guía docente...")
            texto_guia = _org_parser.extraer_texto(guia_docente.getvalue(), guia_docente.name)

            st.write("📚 Extrayendo y clasificando materiales de teoría...")
            textos_teoria: list[str] = []
            textos_contexto: list[str] = []
            archivos_teoria: list[str] = []
            archivos_teoria_bytes: list[bytes] = []
            archivos_contexto: list[str] = []

            for archivo in materiales_teoria:
                try:
                    archivo_bytes = archivo.getvalue()
                    texto_material = _org_parser.extraer_texto(archivo_bytes, archivo.name)
                    categoria = _org_parser.clasificar_archivo(archivo.name, texto_material)
                    if categoria == "contexto":
                        textos_contexto.append(texto_material)
                        archivos_contexto.append(archivo.name)
                        st.write(f"  → {archivo.name} → contexto")
                    else:
                        textos_teoria.append(texto_material)
                        archivos_teoria.append(archivo.name)
                        archivos_teoria_bytes.append(archivo_bytes)
                        st.write(f"  → {archivo.name} → teoría")
                except Exception as err:
                    st.warning(f"No se pudo procesar '{archivo.name}': {err}")

            if not textos_teoria:
                _db_actualizar_ejecucion(ejecucion_id, "error")
                status.update(label="❌ Error en el proceso", state="error")
                st.error("No se pudo extraer texto válido de ningún material de teoría.")
                return False

            longitud_total = sum(len(t) for t in textos_teoria) + sum(len(t) for t in textos_contexto)
            if longitud_total > 120000:
                textos_teoria = [t[:20000] for t in textos_teoria]
                textos_contexto = [t[:20000] for t in textos_contexto]
                st.info("Materiales truncados a 20.000 caracteres por archivo para no superar el límite del modelo.")

            st.session_state["org_ultimos_archivos_teoria"] = archivos_teoria
            st.session_state["org_ultimos_archivos_contexto"] = archivos_contexto

            st.write("🕐 Detectando horas lectivas (TE + PA) y laboratorio...")
            horas_docencia = _org_parser.extraer_horas_docencia(texto_guia)
            horas_teoria = horas_docencia["horas_teoria"]
            horas_aula = horas_docencia["horas_aula"]
            horas_laboratorio = horas_docencia["horas_laboratorio"]
            horas_totales = horas_teoria + horas_aula

            if horas_totales == 0:
                st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")
            st.session_state["org_ultimas_horas_teoria"] = horas_docencia
            st.session_state["org_ultimas_horas_totales"] = horas_totales if horas_totales > 0 else None

            if subtemas_confirmados is None:
                st.write("🔍 Detectando subtemas (guía docente + señales del material)…")
                subtemas_confirmados = _org_build_subtemas_confirmados(
                    texto_guia,
                    textos_teoria, archivos_teoria, archivos_teoria_bytes
                )
            st.session_state["org_subtemas_detectados"] = subtemas_confirmados or []
            st.session_state["org_candidatos_guia"] = _org_parser.extraer_subtemas_guia(
                texto_guia
            )
            if subtemas_confirmados is None:
                n_guia = len(st.session_state["org_candidatos_guia"])
                st.caption(
                    f"Guía docente: {n_guia} bloques temáticos detectados — "
                    "el modelo estructurará los subtemas libremente (sin lista cerrada del PDF)."
                )

            st.write("🌐 Detectando idioma de los materiales...")
            prompt, _idioma = _org_prompts.construir_prompt(
                texto_guia=texto_guia,
                textos_teoria=textos_teoria,
                textos_contexto=textos_contexto,
                horas_totales=horas_totales if horas_totales > 0 else None,
                horas_laboratorio=horas_laboratorio,
                subtemas_por_material=subtemas_confirmados,
            )

            st.write("🤖 Consultando al agente (esto puede tardar ~15s)...")
            resultado, stop_reason = _org_agente.ejecutar_agente(prompt)
            st.session_state["org_warning_truncamiento"] = _org_parser.detectar_output_truncado(
                resultado, stop_reason
            )

            resultado, info_norm = _org_parser.normalizar_horas_output(resultado, horas_totales if horas_totales else 0)
            st.session_state["org_warning_normalizacion"] = info_norm

            _org_validar_y_persistir(
                resultado,
                n_esperados=len(textos_teoria),
                asignatura_id=asignatura_id,
                slug=slug,
                version=1,
                ejecucion_id=ejecucion_id,
                feedback_texto=None,
                nombre_descarga=_org_parser.construir_nombre_descarga(texto_guia),
            )
            _db_actualizar_ejecucion(ejecucion_id, "completado")
            status.update(label="✅ Organización generada", state="complete")
            return True
        except Exception as err:
            _db_actualizar_ejecucion(ejecucion_id, "error")
            status.update(label="❌ Error en el proceso", state="error")
            st.error(f"Error durante la generación: {err}")
            return False


# =============================================================================
# Helpers de base de datos — Contenido
# =============================================================================

def _db_cnt_get_temas(asignatura_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre, horas, bloque, orden FROM temas "
                "WHERE asignatura_id = ? ORDER BY orden",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_subbloques(tema_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre, orden, horas, evidencia, origen, es_fallback "
                "FROM subbloques WHERE tema_id = ? ORDER BY orden",
                (tema_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_contenido_subbloque(subbloque_id: int) -> dict | None:
    conn = db.get_connection(RUTA_DB)
    try:
        r = conn.execute(
            "SELECT id, markdown_borrador, markdown_final, porcentaje_editado, "
            "puntuacion_profesor, estado, fecha_actualizacion "
            "FROM contenido_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _db_cnt_get_rutas_material(tema_id: int) -> list[str]:
    """Ruta del PDF/PPTX vinculado al bloque temático (``temas.input_id``).

    Si el bloque no tiene ``input_id`` (datos legados), devuelve lista vacía.
    """
    conn = db.get_connection(RUTA_DB)
    try:
        fila = conn.execute(
            "SELECT i.ruta_disco FROM temas t "
            "JOIN inputs i ON i.id = t.input_id "
            "WHERE t.id = ? AND i.tipo = 'material_teoria'",
            (tema_id,),
        ).fetchone()
    finally:
        conn.close()
    if not fila:
        return []
    ruta = fila["ruta_disco"]
    return [ruta] if os.path.exists(ruta) else []


def _db_cnt_upsert_borrador(subbloque_id: int, markdown_borrador: str) -> None:
    """Guarda el borrador generado por IA y actualiza el estado a 'generado'."""
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET markdown_borrador = ?, estado = 'generado', "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE subbloque_id = ?",
                (markdown_borrador, subbloque_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_subbloque (subbloque_id, markdown_borrador, estado) "
                "VALUES (?, ?, 'generado')",
                (subbloque_id, markdown_borrador),
            )
        conn.commit()
    finally:
        conn.close()


def _db_cnt_guardar_final(
    subbloque_id: int, markdown_final: str, porcentaje_editado: float
) -> None:
    """Guarda el contenido final editado por el profesor.

    Estado resultante:
    - porcentaje_editado == 0 → 'aprobado' (sin cambios sobre el borrador).
    - porcentaje_editado > 0  → 'editado' (el profesor modificó el borrador).
    """
    estado = "aprobado" if porcentaje_editado == 0 else "editado"
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET markdown_final = ?, "
                "porcentaje_editado = ?, estado = ?, "
                "fecha_actualizacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (markdown_final, porcentaje_editado, estado, subbloque_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_subbloque "
                "(subbloque_id, markdown_borrador, markdown_final, porcentaje_editado, estado) "
                "VALUES (?, '', ?, ?, ?)",
                (subbloque_id, markdown_final, porcentaje_editado, estado),
            )
        conn.commit()
    finally:
        conn.close()


def _db_cnt_aprobar_subbloque(subbloque_id: int, puntuacion: int) -> None:
    """Marca un subbloque como 'aprobado' y guarda la valoración del profesor (1-10)."""
    if not 1 <= puntuacion <= 10:
        raise ValueError(f"Puntuación inválida: {puntuacion}")
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET estado = 'aprobado', "
                "puntuacion_profesor = ?, fecha_actualizacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (puntuacion, subbloque_id),
            )
            conn.commit()
    finally:
        conn.close()


# =============================================================================
# Lógica de curación por sub-bloque — Agente Contenido
# =============================================================================

_CNT_EVIDENCIAS_FALLBACK = frozenset({
    "sin señal verificable", "sin senal verificable",
    "fallback", "sin señal", "sin senal", "",
})


def _cnt_metas_para_segmentacion(subbloques: list[dict]) -> list[dict]:
    """Adapta filas de BD al formato que espera segment_text_by_subbloques."""
    return [
        {
            "nombre": sb["nombre"],
            "horas": float(sb.get("horas") or 0.0),
            "evidencia": sb.get("evidencia") or "",
            "origen": sb.get("origen") or "",
        }
        for sb in subbloques
    ]


def _cnt_extraer_segmento_subbloque(
    subbloque_meta: dict,
    todos_subbloques: list[dict],
    rutas_material: list[str],
) -> str:
    """Acota el texto de entrada al tramo del sub-bloque usando evidencia estructural."""
    target_idx = next(
        (i for i, sb in enumerate(todos_subbloques) if sb["id"] == subbloque_meta["id"]),
        None,
    )
    if target_idx is None:
        return ""

    sb_metas = _cnt_metas_para_segmentacion(todos_subbloques)
    partes: list[str] = []

    for ruta in rutas_material:
        if not os.path.exists(ruta):
            continue
        try:
            texto = _cnt_extractor.extract_text(ruta)
        except Exception:
            continue
        if not (texto or "").strip():
            continue

        segments = _cnt_segmentor.segment_text_by_subbloques(texto, sb_metas)
        if target_idx < len(segments):
            _, seg_text = segments[target_idx]
            if seg_text and seg_text.strip():
                partes.append(seg_text.strip())

    return "\n\n".join(partes)


def _cnt_curar_subbloque(
    subbloque_meta: dict,
    todos_subbloques: list[dict],
    tema_nombre: str,
    tema_horas: float | None,
    rutas_material: list[str],
) -> tuple[str, float | None]:
    """Genera markdown curado para un sub-bloque usando el pipeline del Agente Contenido.

    Segmenta el material por evidencia estructural, luego delega en
    `pipeline.procesar_segmento()` (fuente única del pipeline chunk→classify→assemble→validate).
    Devuelve (markdown_body, fidelidad). La fidelidad es la media de los coverage_score
    del validador, o None si no hubo nada que validar.
    """
    subbloque_nombre = subbloque_meta["nombre"]
    sb_horas = float(subbloque_meta.get("horas") or 0.0)
    effective_horas = sb_horas if sb_horas > 0 else tema_horas

    seg_text = _cnt_extraer_segmento_subbloque(subbloque_meta, todos_subbloques, rutas_material)
    if not seg_text.strip():
        return (
            f"# {subbloque_nombre}\n\n*No se pudo extraer contenido del material de entrada.*",
            None,
        )

    sub_ctx = (
        f"[CONTEXTO SUBTEMA: Este fragmento pertenece al subtema «{subbloque_nombre}» "
        f"del bloque «{tema_nombre}». "
        f"Extrae y estructura únicamente el contenido relevante para este subtema.]\n\n"
    )
    max_w = getattr(_cnt_config, "MAX_WORKERS", 5)

    items, markdown, reporte = _cnt_pipeline.procesar_segmento(
        seg_text=seg_text,
        nombre_subbloque=subbloque_nombre,
        nombre_archivo=f"{subbloque_nombre}.md",
        horas=effective_horas,
        contexto_prefix=sub_ctx,
        max_workers=max_w,
    )

    if not items:
        return (
            f"# {subbloque_nombre}\n\n*No se pudo extraer contenido del material de entrada.*",
            None,
        )

    fidelidad: float | None = None
    scores = [
        r["coverage_score"]
        for r in (reporte.get("fidelity") or [])
        if r.get("coverage_score") is not None
    ]
    if scores:
        fidelidad = round(sum(scores) / len(scores), 3)

    return markdown, fidelidad


def _cnt_init_edicion_state() -> None:
    if "cnt_en_edicion" not in st.session_state:
        st.session_state["cnt_en_edicion"] = set()


def _cnt_subbloque_en_edicion(subbloque_id: int, estado: str) -> bool:
    """True si el sub-bloque debe mostrarse en textarea editable."""
    _cnt_init_edicion_state()
    if estado in ("editado", "generado"):
        return True
    return subbloque_id in st.session_state["cnt_en_edicion"]


def _cnt_etiqueta_modificacion(cs: dict | None) -> str:
    """Texto breve sobre si el Markdown final difiere del borrador de la IA."""
    if cs is None:
        return ""
    pct = cs.get("porcentaje_editado")
    if pct is None or pct == 0:
        return "sin modificaciones"
    return f"modificado ({pct}%)"


def _cnt_persistir_y_aprobar(
    subbloque_id: int, texto: str, borrador: str, puntuacion: int
) -> None:
    """Guarda el Markdown visible, marca el sub-bloque como aprobado y registra la nota."""
    texto_limpio = texto.strip()
    if not texto_limpio:
        return
    ratio = difflib.SequenceMatcher(None, borrador, texto_limpio).ratio()
    pct = round((1 - ratio) * 100, 1)
    _db_cnt_guardar_final(subbloque_id, texto_limpio, pct)
    _db_cnt_aprobar_subbloque(subbloque_id, puntuacion)
    _cnt_init_edicion_state()
    st.session_state["cnt_en_edicion"].discard(subbloque_id)


def _cnt_persistir_edicion(subbloque_id: int, texto: str, borrador: str) -> None:
    """Guarda una edición manual sin aprobar todavía."""
    texto_limpio = texto.strip()
    if not texto_limpio:
        return
    ratio = difflib.SequenceMatcher(None, borrador, texto_limpio).ratio()
    pct = round((1 - ratio) * 100, 1)
    _db_cnt_guardar_final(subbloque_id, texto_limpio, pct)
    _cnt_init_edicion_state()
    st.session_state["cnt_en_edicion"].discard(subbloque_id)


def _cnt_generar_borrador_subbloque(
    sub: dict,
    subbloques: list[dict],
    tema_nombre: str,
    tema_horas: float | None,
    rutas_material: list[str],
    asignatura_id: int,
) -> None:
    """Genera el borrador de un único sub-bloque (una llamada a la API por sub-bloque)."""
    umbral = float(getattr(_cnt_config, "FIDELITY_THRESHOLD", 0.85))
    ejecucion_id = _db_crear_ejecucion_contenido(asignatura_id)
    hubo_error = False
    with st.status(f"Generando: {sub['nombre']}…", expanded=True) as status:
        try:
            st.write("📚 Segmentando y clasificando material…")
            ev_norm = (sub.get("evidencia") or "").strip().lower()
            if (
                not sub.get("es_fallback")
                and ev_norm not in _CNT_EVIDENCIAS_FALLBACK
            ):
                seg_previo = _cnt_extraer_segmento_subbloque(
                    sub, subbloques, rutas_material
                )
                if not seg_previo.strip():
                    st.warning(
                        f"⚠️ La referencia «{sub.get('evidencia', '')}» "
                        "no se encontró en el material. "
                        "El borrador puede quedar vacío — "
                        "puedes editarlo manualmente tras generarlo."
                    )
            md, fidelidad = _cnt_curar_subbloque(
                subbloque_meta=sub,
                todos_subbloques=subbloques,
                tema_nombre=tema_nombre,
                tema_horas=tema_horas,
                rutas_material=rutas_material,
            )
            _db_cnt_upsert_borrador(sub["id"], md)
            if fidelidad is not None and fidelidad < umbral:
                _db_registrar_validacion(
                    ejecucion_id=ejecucion_id,
                    tipo="fidelidad_baja",
                    descripcion=(
                        f"sub-bloque '{sub['nombre']}' con fidelidad {fidelidad}"
                    ),
                    valor_afectado=fidelidad,
                    bloqueante=0,
                )
                status.update(
                    label=(
                        f"⚠️ Borrador listo (fidelidad {fidelidad} < {umbral}): "
                        f"{sub['nombre']}"
                    ),
                    state="complete",
                )
            else:
                status.update(
                    label=f"✅ Borrador listo: {sub['nombre']}",
                    state="complete",
                )
        except Exception as err:
            hubo_error = True
            status.update(label="❌ Error", state="error")
            st.error(f"Error en «{sub['nombre']}»: {err}")
    _db_actualizar_ejecucion(ejecucion_id, "error" if hubo_error else "completado")


# =============================================================================
# Vista Contenido
# =============================================================================

def _vista_contenido() -> None:
    if _CNT_ERROR:
        st.error(f"No se pudo cargar el Agente Contenido: {_CNT_ERROR}")
        st.caption("Comprueba que `agente-contenido/.env` tiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en el portfolio para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    # Reset de claves cnt_ si cambió la asignatura
    if st.session_state.get("cnt_asignatura") != asignatura:
        for k in [k for k in list(st.session_state.keys()) if k.startswith("cnt_")]:
            del st.session_state[k]
        st.session_state["cnt_asignatura"] = asignatura

    _cnt_init_edicion_state()

    # ── Selector de tema ──────────────────────────────────────────────────────
    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos para esta asignatura. "
            "Ejecuta primero el **Agente Organizador** y pulsa "
            "**Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    tema_idx = st.selectbox(
        "Bloque temático:",
        options=range(len(temas)),
        format_func=lambda i: tema_labels[i],
        key="cnt_tema_idx",
    )
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]
    tema_horas: float | None = tema["horas"] or None

    # ── Sub-bloques y materiales disponibles ──────────────────────────────────
    subbloques = _db_cnt_get_subbloques(tema_id)
    if not subbloques:
        st.warning("Este bloque no tiene sub-bloques registrados.")
        return

    rutas_material = _db_cnt_get_rutas_material(tema_id)

    # Estado de cada sub-bloque (orden de la organización)
    estados_sb: list[dict] = []
    for sub in subbloques:
        cs = _db_cnt_get_contenido_subbloque(sub["id"])
        estados_sb.append({
            "sub": sub,
            "cs": cs,
            "estado": cs["estado"] if cs else "pendiente",
        })

    pendientes = [e for e in estados_sb if e["cs"] is None]
    en_revision_count = sum(
        1 for e in estados_sb if e["estado"] in ("generado", "editado")
    )
    todos_aprobados = all(e["estado"] == "aprobado" for e in estados_sb)

    st.divider()

    # Progreso del bloque en tiempo real.
    prog = db.get_progreso_bloque(tema_id, RUTA_DB)
    _pct = prog["porcentaje"]
    _col_prog, _col_info = st.columns([3, 1])
    with _col_prog:
        st.progress(
            _pct / 100,
            text=(
                f"Progreso del bloque: {prog['aprobados']}/{prog['total']} "
                f"sub-bloques aprobados ({_pct}%)"
            ),
        )
    with _col_info:
        st.caption(f"**{len(subbloques)} sub-bloques** del bloque *{tema_nombre}*")

    # ── Índice de sub-bloques ─────────────────────────────────────────────────
    st.markdown("**Sub-bloques de este tema**")
    for i, e in enumerate(estados_sb, 1):
        sub = e["sub"]
        cs = e["cs"]
        estado = e["estado"]
        if estado == "aprobado":
            nota = cs.get("puntuacion_profesor") if cs else None
            mod = _cnt_etiqueta_modificacion(cs)
            sufijo = f"✅ {nota}/10 — {mod}" if nota else f"✅ Aprobado — {mod}"
        elif estado in ("generado", "editado"):
            sufijo = "🔵 En revisión"
        else:
            sufijo = "⚪ Pendiente"
        st.caption(f"{i}. **{sub['nombre']}** — {sufijo}")

    st.divider()

    # ── Generación por selección (cada sub-bloque = una llamada a la API) ───
    if pendientes:
        if not rutas_material:
            st.warning(
                "No hay materiales de teoría en disco. "
                "Sube los archivos en el **Agente Organizador** primero."
            )
        else:
            st.markdown("**Generar borradores**")
            st.caption(
                "Marca los sub-bloques pendientes que quieras procesar. "
                "Cada uno se genera por separado (segmentación independiente)."
            )
            seleccionados: list[dict] = []
            for i, e in enumerate(estados_sb, 1):
                if e["cs"] is not None:
                    continue
                sub = e["sub"]
                col_chk, col_lbl = st.columns([0.06, 0.94])
                with col_chk:
                    if st.checkbox(
                        "Seleccionar",
                        key=f"cnt_sel_{sub['id']}",
                        label_visibility="collapsed",
                    ):
                        seleccionados.append(sub)
                with col_lbl:
                    st.markdown(f"{i}. **{sub['nombre']}** — ⚪ Pendiente")

            n_sel = len(seleccionados)
            if st.button(
                f"Generar seleccionados ({n_sel})",
                type="primary",
                use_container_width=True,
                key="cnt_btn_generar",
                disabled=n_sel == 0,
            ):
                for sub in seleccionados:
                    _cnt_generar_borrador_subbloque(
                        sub=sub,
                        subbloques=subbloques,
                        tema_nombre=tema_nombre,
                        tema_horas=tema_horas,
                        rutas_material=rutas_material,
                        asignatura_id=asignatura_id,
                    )
                st.rerun()
    elif todos_aprobados:
        st.success("Todos los sub-bloques de este tema están aprobados y valorados.")
    elif en_revision_count > 0:
        st.caption(
            f"{en_revision_count} sub-bloque(s) en revisión — confírmalos cuando estés listo."
        )

    # ── Sub-bloques — áreas de edición ────────────────────────────────────────
    st.divider()

    _ETIQUETAS_ESTADO = {
        "pendiente": "⚪ Sin borrador",
        "generado": "🤖 Borrador generado por IA",
        "editado": "✏️ Editado por el profesor",
        "aprobado": "✅ Aprobado",
    }

    for sub in subbloques:
        cs = _db_cnt_get_contenido_subbloque(sub["id"])
        estado_actual = cs["estado"] if cs else "pendiente"

        if cs is None:
            etiqueta = _ETIQUETAS_ESTADO["pendiente"]
            texto_inicial = ""
        elif estado_actual == "aprobado":
            nota = cs.get("puntuacion_profesor")
            mod = _cnt_etiqueta_modificacion(cs)
            etiqueta = (
                f"✅ Aprobado — {nota}/10 — {mod}" if nota
                else f"✅ Aprobado — {mod}"
            )
            texto_inicial = cs.get("markdown_final") or cs.get("markdown_borrador") or ""
        elif estado_actual == "editado":
            pct_ed = cs.get("porcentaje_editado") or 0
            etiqueta = f"✏️ Editado ({pct_ed}% modificado)"
            texto_inicial = cs.get("markdown_final") or cs.get("markdown_borrador") or ""
        elif estado_actual == "generado":
            etiqueta = _ETIQUETAS_ESTADO["generado"]
            texto_inicial = cs.get("markdown_borrador") or ""
        else:
            etiqueta = _ETIQUETAS_ESTADO["pendiente"]
            texto_inicial = ""

        es_activo = estado_actual in ("generado", "editado")
        with st.expander(
            f"**{sub['nombre']}** — {etiqueta}",
            expanded=es_activo,
        ):
            en_edicion = _cnt_subbloque_en_edicion(sub["id"], estado_actual)
            tiene_contenido = bool(texto_inicial.strip())

            if estado_actual == "aprobado" and tiene_contenido:
                st.text_area(
                    "Contenido Markdown (solo lectura):",
                    value=texto_inicial,
                    height=300,
                    disabled=True,
                    key=f"cnt_view_{sub['id']}",
                    label_visibility="collapsed",
                )
            elif en_edicion and tiene_contenido:
                ta_key = f"contenido_{sub['id']}"
                if ta_key not in st.session_state:
                    st.session_state[ta_key] = texto_inicial
                st.text_area(
                    "Contenido Markdown:",
                    key=ta_key,
                    height=350,
                    label_visibility="collapsed",
                )
                borrador = (cs.get("markdown_borrador") or "") if cs else ""
                texto_actual = st.session_state.get(ta_key, texto_inicial)
                ratio_prev = difflib.SequenceMatcher(
                    None, borrador, texto_actual.strip()
                ).ratio()
                pct_prev = round((1 - ratio_prev) * 100, 1)
                if pct_prev > 0:
                    st.caption(f"📝 Borrador modificado un {pct_prev}% respecto al original de la IA.")
                else:
                    st.caption("📝 Sin modificaciones respecto al borrador de la IA.")

                puntuacion = st.select_slider(
                    "Valoración del sub-bloque (1-10):",
                    options=list(range(1, 11)),
                    value=7,
                    key=f"cnt_valoracion_{sub['id']}",
                )
                col_guardar, col_confirmar = st.columns(2)
                with col_guardar:
                    if st.button(
                        "💾 Guardar edición",
                        key=f"cnt_btn_guardar_sub_{sub['id']}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        _cnt_persistir_edicion(sub["id"], texto_actual, borrador)
                        st.rerun()
                with col_confirmar:
                    if st.button(
                        "✅ Confirmar y valorar",
                        key=f"cnt_btn_confirmar_{sub['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        _cnt_persistir_y_aprobar(
                            sub["id"], texto_actual, borrador, puntuacion
                        )
                        st.rerun()
            elif not tiene_contenido:
                st.caption(
                    "Sin contenido todavía — selecciónalo arriba y pulsa "
                    "**Generar seleccionados**."
                )


# =============================================================================
# Helpers de base de datos — Presentación
# =============================================================================

def _db_prs_get_presentacion_subbloque(subbloque_id: int) -> dict | None:
    conn = db.get_connection(RUTA_DB)
    try:
        r = conn.execute(
            "SELECT id, patron_visualizacion, elegido_por_profesor, html_path "
            "FROM presentacion_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _db_prs_upsert_presentacion_subbloque(
    subbloque_id: int,
    patron: str,
    elegido_por_profesor: int,
) -> int:
    """Inserta o actualiza presentacion_subbloque. Devuelve el id de la fila."""
    conn = db.get_connection(RUTA_DB)
    try:
        existing = conn.execute(
            "SELECT id FROM presentacion_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE presentacion_subbloque SET patron_visualizacion = ?, "
                "elegido_por_profesor = ?, fecha_generacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (patron, elegido_por_profesor, subbloque_id),
            )
            row_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO presentacion_subbloque "
                "(subbloque_id, patron_visualizacion, elegido_por_profesor) "
                "VALUES (?, ?, ?)",
                (subbloque_id, patron, elegido_por_profesor),
            )
            row_id = cur.lastrowid
        conn.commit()
        return row_id
    finally:
        conn.close()


def _db_prs_update_html_path(subbloque_id: int, html_path: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE presentacion_subbloque SET html_path = ?, "
            "fecha_generacion = CURRENT_TIMESTAMP WHERE subbloque_id = ?",
            (html_path, subbloque_id),
        )
        conn.commit()
    finally:
        conn.close()


def _db_prs_get_parametros(presentacion_subbloque_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre_parametro, simbolo, es_slider, "
                "valor_min, valor_max, valor_predeterminado "
                "FROM parametros_subbloque WHERE presentacion_subbloque_id = ? "
                "ORDER BY id",
                (presentacion_subbloque_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_prs_insert_parametros(
    presentacion_subbloque_id: int,
    parametros: list[dict],
) -> None:
    """Inserta parámetros solo si la tabla está vacía para ese presentacion_subbloque_id."""
    conn = db.get_connection(RUTA_DB)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM parametros_subbloque WHERE presentacion_subbloque_id = ?",
            (presentacion_subbloque_id,),
        ).fetchone()[0]
        if count:
            return
        for p in parametros:
            conn.execute(
                "INSERT INTO parametros_subbloque "
                "(presentacion_subbloque_id, nombre_parametro, simbolo, "
                "es_slider, valor_min, valor_max, valor_predeterminado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    presentacion_subbloque_id,
                    p.get("nombre_parametro") or p.get("simbolo", "x"),
                    p.get("simbolo", "x"),
                    1,
                    p.get("valor_min"),
                    p.get("valor_max"),
                    p.get("valor_predeterminado"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _db_prs_update_parametro(
    param_id: int,
    es_slider: int,
    valor_min: float | None,
    valor_max: float | None,
    valor_pred: float | None,
) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE parametros_subbloque SET es_slider = ?, valor_min = ?, "
            "valor_max = ?, valor_predeterminado = ? WHERE id = ?",
            (es_slider, valor_min, valor_max, valor_pred, param_id),
        )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Lógica del Agente Presentación — razonador y generador por sub-bloque
# =============================================================================

_CHIP_LABELS = [
    "curva simple", "familia de curvas", "región / criterio",
    "mapa 2d", "trayectoria", "respuesta en frecuencia", "ninguna",
]
# Chip → valor DB (minúscula snake_case, igual que el CHECK del esquema)
_CHIP_TO_PATRON = {
    "curva simple": "curva_simple",
    "familia de curvas": "familia_curvas",
    "región / criterio": "region_criterio",
    "mapa 2d": "mapa_2d",
    "trayectoria": "trayectoria",
    "respuesta en frecuencia": "respuesta_frecuencial",
    "ninguna": "ninguna",
}
_PATRON_TO_CHIP = {v: k for k, v in _CHIP_TO_PATRON.items()}

# Conversión entre valor DB (lowercase) y valor API del razonador (UPPERCASE)
_PATRON_DB_TO_API = {
    "curva_simple": "CURVA_SIMPLE",
    "familia_curvas": "FAMILIA_CURVAS",
    "region_criterio": "REGION_CRITERIO",
    "mapa_2d": "MAPA_2D",
    "trayectoria": "TRAYECTORIA",
    "respuesta_frecuencial": "RESPUESTA_FRECUENCIAL",
    "ninguna": "ninguna",
}
_PATRON_API_TO_DB = {v: k for k, v in _PATRON_DB_TO_API.items()}


def _prs_elemento_desde_markdown(nombre: str, markdown: str) -> dict:
    """Construye un dict 'elemento' compatible con el razonador desde texto Markdown."""
    block_m = re.search(r"\$\$([\s\S]+?)\$\$", markdown)
    inline_m = re.search(r"(?<!\$)\$([^$\n]{3,}?)\$(?!\$)", markdown)
    expresion = ""
    if block_m:
        expresion = block_m.group(1).strip()
    elif inline_m:
        expresion = inline_m.group(1).strip()
    return {
        "nombre": nombre,
        "expresion": expresion,
        "contexto": markdown[:3000],
        "seccion": nombre,
        "tipo": "relacion" if expresion else "texto",
        "es_bloque": bool(block_m),
        "advertencia": None,
    }


def _prs_razonar_subbloque(subbloque_nombre: str, markdown: str) -> dict:
    """Llama al razonador Sonnet (del Agente Presentación) sobre el markdown del sub-bloque.

    Devuelve el dict de visualización con PATRON, PARAMETROS_SLIDER y RANGO_VARIABLES.
    Si el razonador devuelve VISUALIZABLE=NO o falla, devuelve patron='ninguna'.
    """
    import anthropic as _ant
    client = _ant.Anthropic(
        api_key=_prs_config.ANTHROPIC_API_KEY,
        timeout=float(_prs_config.REQUEST_TIMEOUT_SECONDS),
    )
    elemento = _prs_elemento_desde_markdown(subbloque_nombre, markdown)
    try:
        viz = _prs_generador_html._razonar_visualizacion(elemento, client, verbose=False)
        if viz.get("VISUALIZABLE") == "NO":
            return {"PATRON": "ninguna", "PARAMETROS_SLIDER": "", "RANGO_VARIABLES": ""}
        # Convertir PATRON a formato DB (lowercase snake_case) antes de devolver
        patron_api = viz.get("PATRON", "ninguna")
        viz["PATRON"] = _PATRON_API_TO_DB.get(patron_api, "ninguna")
        return viz
    except Exception:
        return {"PATRON": "ninguna", "PARAMETROS_SLIDER": "", "RANGO_VARIABLES": ""}


def _prs_extraer_parametros_desde_viz(viz: dict) -> list[dict]:
    """Extrae los parámetros candidatos del dict de visualización del razonador."""
    params_raw = viz.get("PARAMETROS_SLIDER") or ""
    rangos_raw = viz.get("RANGO_VARIABLES") or ""
    rangos = _prs_generador_html._parse_rango_variables(rangos_raw)
    slider_names = [p.strip() for p in re.split(r"[,;]", params_raw) if p.strip()]
    parametros = []
    for nombre in slider_names:
        rango = rangos.get(nombre, {})
        parametros.append({
            "nombre_parametro": nombre,
            "simbolo": nombre,
            "valor_min": rango.get("min"),
            "valor_max": rango.get("max"),
            "valor_predeterminado": rango.get("default"),
        })
    if not parametros:
        for nombre, rango in rangos.items():
            parametros.append({
                "nombre_parametro": nombre,
                "simbolo": nombre,
                "valor_min": rango.get("min"),
                "valor_max": rango.get("max"),
                "valor_predeterminado": rango.get("default"),
            })
    return parametros


def _prs_generar_html_subbloque(
    subbloque_nombre: str,
    markdown: str,
    patron: str,
    parametros_db: list[dict],
) -> str:
    """Genera el HTML del sub-bloque usando el patrón y parámetros guardados en BD.

    Construye el dict `visualizacion` desde los datos de BD (sin llamar al razonador,
    porque el patrón ya fue elegido por el profesor) y delega en
    `generador_html.generar_bloque_con_visualizacion()` (fuente única del bucle
    de reintentos, aplicar_rangos y validar_bloque_html).
    """
    elemento = _prs_elemento_desde_markdown(subbloque_nombre, markdown)
    patron_api = _PATRON_DB_TO_API.get(patron, "CURVA_SIMPLE")

    sliders_activos = [p for p in parametros_db if p["es_slider"]]
    parametros_slider_str = ", ".join(p["simbolo"] for p in sliders_activos)

    rango_lines = []
    for p in sliders_activos:
        mn = p["valor_min"] if p["valor_min"] is not None else 0.0
        mx = p["valor_max"] if p["valor_max"] is not None else 100.0
        df = p["valor_predeterminado"] if p["valor_predeterminado"] is not None else (mn + mx) / 2
        rango_lines.append(f"{p['simbolo']}: min={mn}, max={mx}, default={df}")

    visualizacion = {
        "VISUALIZABLE": "SI",
        "PATRON": patron_api,
        "EJE_X": "x",
        "EJE_Y": "y",
        "PARAMETROS_SLIDER": parametros_slider_str,
        "ESCALA_LOG_X": "NO",
        "ESCALA_LOG_Y": "NO",
        "JUSTIFICACION": f"Patrón seleccionado: {patron_api}",
        "RANGO_VARIABLES": "\n".join(rango_lines),
        "ZONA_VALIDEZ": "ninguna",
    }

    return _prs_generador_html.generar_bloque_con_visualizacion(
        elemento, visualizacion, requiere_autoarranque=True
    )


# =============================================================================
# Vista Presentación
# =============================================================================

def _prs_ensamblar_markdown_bloque(tema_nombre: str, subbloques: list[dict]) -> str:
    """Concatena el markdown de todos los sub-bloques del tema (final > borrador)."""
    partes: list[str] = [f"# {tema_nombre}"]
    for sub in subbloques:
        cs = _db_cnt_get_contenido_subbloque(sub["id"])
        if cs:
            md_sub = cs.get("markdown_final") or cs.get("markdown_borrador") or ""
            if md_sub.strip():
                partes.append(md_sub.strip())
    return "\n\n".join(partes)


def _vista_presentacion() -> None:
    if _PRS_ERROR:
        st.error(f"No se pudo cargar el Agente Presentación: {_PRS_ERROR}")
        st.caption("Comprueba que `agente-presentacion/.env` tiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en el portfolio para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    if st.session_state.get("prs_asignatura") != asignatura:
        for k in [k for k in list(st.session_state.keys()) if k.startswith("prs_")]:
            del st.session_state[k]
        st.session_state["prs_asignatura"] = asignatura

    # CSS para chips (radio horizontal con estilo pill), acotado al área principal
    st.markdown(f"""
    <style>
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] > div[role="radiogroup"] {{
        flex-wrap: wrap; gap: 6px;
    }}
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] label {{
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 20px !important;
        padding: 4px 14px !important;
        font-size: 13px !important;
        cursor: pointer;
    }}
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] label:has(input:checked) {{
        background: {ACENTO} !important;
        color: #ffffff !important;
        border-color: {ACENTO} !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    # ── Selector de tema (igual que en Contenido) ─────────────────────────────
    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos. Ejecuta primero el **Agente Organizador** "
            "y pulsa **Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    tema_idx = st.selectbox(
        "Bloque temático:",
        options=range(len(temas)),
        format_func=lambda i: tema_labels[i],
        key="prs_tema_idx",
    )
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]

    subbloques = _db_cnt_get_subbloques(tema_id)
    if not subbloques:
        st.warning("Este bloque no tiene sub-bloques registrados.")
        return

    _paso_prs = 1
    for _s in subbloques:
        _prs_r = _db_prs_get_presentacion_subbloque(_s["id"])
        if _prs_r and _prs_r.get("html_path"):
            _paso_prs = 2
            break
    _render_stepper(["Bloque", "Configuración", "Generación"], _paso_prs)

    st.divider()

    for sub in subbloques:
        sub_id: int = sub["id"]
        sub_nombre: str = sub["nombre"]

        # Contenido del sub-bloque (markdown_final prioritario sobre borrador)
        cs = _db_cnt_get_contenido_subbloque(sub_id)
        markdown_sub = ""
        if cs:
            markdown_sub = cs.get("markdown_final") or cs.get("markdown_borrador") or ""

        # Obtener o crear fila en presentacion_subbloque
        prs_row = _db_prs_get_presentacion_subbloque(sub_id)

        if prs_row is None and not markdown_sub:
            with st.expander(f"**{sub_nombre}** — sin contenido"):
                st.caption("Genera el contenido en la vista **Contenido** primero.")
            continue

        if prs_row is None:
            # Primera visita: ejecutar razonador para sugerir patrón
            with st.spinner(f"Analizando «{sub_nombre}» con el razonador…"):
                viz = _prs_razonar_subbloque(sub_nombre, markdown_sub)
            patron_sugerido = viz.get("PATRON", "ninguna")
            # viz["PATRON"] ya viene en formato DB (lowercase) desde _prs_razonar_subbloque
            if patron_sugerido not in _CHIP_TO_PATRON.values():
                patron_sugerido = "ninguna"
            prs_id = _db_prs_upsert_presentacion_subbloque(sub_id, patron_sugerido, 0)
            if patron_sugerido != "ninguna":
                params = _prs_extraer_parametros_desde_viz(viz)
                if params:
                    _db_prs_insert_parametros(prs_id, params)
            prs_row = {
                "id": prs_id,
                "patron_visualizacion": patron_sugerido,
                "elegido_por_profesor": 0,
                "html_path": None,
            }

        patron_actual: str = prs_row["patron_visualizacion"] or "ninguna"
        elegido: int = prs_row["elegido_por_profesor"]
        prs_id: int = prs_row["id"]

        # Badge de estado junto al título
        if elegido:
            badge = (
                f'<span style="font-size:11px;background:#E6F1FB;color:{ACENTO};'
                f'border-radius:20px;padding:2px 10px;font-weight:500;margin-left:8px;">'
                f'elegido por el profesor</span>'
            )
        else:
            badge = (
                '<span style="font-size:11px;background:rgba(128,128,128,0.12);'
                'color:var(--text-color);border-radius:20px;padding:2px 10px;margin-left:8px;">'
                'automático</span>'
            )

        with st.expander(f"**{sub_nombre}**", expanded=True):
            st.markdown(
                f'<div style="margin-bottom:10px;font-size:14px;font-weight:600;">'
                f'{sub_nombre}{badge}</div>',
                unsafe_allow_html=True,
            )

            # ── Chips de patrón ────────────────────────────────────────────────
            chip_actual = _PATRON_TO_CHIP.get(patron_actual, "ninguna")
            chip_key = f"prs_chip_{sub_id}"
            if chip_key not in st.session_state:
                st.session_state[chip_key] = chip_actual

            nuevo_chip = st.radio(
                "Patrón:",
                options=_CHIP_LABELS,
                index=_CHIP_LABELS.index(st.session_state.get(chip_key, chip_actual))
                      if st.session_state.get(chip_key, chip_actual) in _CHIP_LABELS else 6,
                horizontal=True,
                key=chip_key,
                label_visibility="collapsed",
            )
            nuevo_patron = _CHIP_TO_PATRON.get(nuevo_chip, "ninguna")
            if nuevo_patron != patron_actual:
                _db_prs_upsert_presentacion_subbloque(sub_id, nuevo_patron, 1)
                patron_actual = nuevo_patron
                elegido = 1
                prs_row["patron_visualizacion"] = nuevo_patron
                st.rerun()

            # ── Tabla de parámetros (solo si patrón != ninguna) ────────────────
            if patron_actual != "ninguna":
                parametros = _db_prs_get_parametros(prs_id)

                if not parametros and markdown_sub:
                    with st.spinner("Detectando parámetros del sub-bloque…"):
                        viz2 = _prs_razonar_subbloque(sub_nombre, markdown_sub)
                    params2 = _prs_extraer_parametros_desde_viz(viz2)
                    if not params2:
                        params2 = [{
                            "nombre_parametro": "x", "simbolo": "x",
                            "valor_min": 0.0, "valor_max": 100.0, "valor_predeterminado": 50.0,
                        }]
                    _db_prs_insert_parametros(prs_id, params2)
                    parametros = _db_prs_get_parametros(prs_id)

                if parametros:
                    st.markdown(
                        "<p style='font-size:11px;font-weight:500;color:var(--text-color);"
                        "opacity:0.55;text-transform:uppercase;letter-spacing:0.08em;"
                        "margin:10px 0 4px;'>Parámetros de la visualización</p>",
                        unsafe_allow_html=True,
                    )
                    col_h1, col_h2, col_h3, col_h4 = st.columns([2, 1.3, 1.3, 1.3])
                    col_h1.caption("Parámetro")
                    col_h2.caption("mín")
                    col_h3.caption("máx")
                    col_h4.caption("defecto")

                    for p in parametros:
                        pid = p["id"]
                        c1, c2, c3, c4 = st.columns([2, 1.3, 1.3, 1.3])
                        with c1:
                            es_slider = st.checkbox(
                                f"{p['nombre_parametro']} `{p['simbolo']}`",
                                value=bool(p["es_slider"]),
                                key=f"prs_slider_{pid}",
                            )
                        if es_slider:
                            v_min = c2.number_input(
                                "mín",
                                value=float(p["valor_min"]) if p["valor_min"] is not None else 0.0,
                                key=f"prs_min_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            v_max = c3.number_input(
                                "máx",
                                value=float(p["valor_max"]) if p["valor_max"] is not None else 100.0,
                                key=f"prs_max_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            dfl = p["valor_predeterminado"]
                            if dfl is None:
                                mn = p["valor_min"] or 0.0
                                mx = p["valor_max"] or 100.0
                                dfl = (mn + mx) / 2
                            v_def = c4.number_input(
                                "defecto",
                                value=float(dfl),
                                key=f"prs_def_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            _db_prs_update_parametro(pid, 1, v_min, v_max, v_def)
                        else:
                            _db_prs_update_parametro(
                                pid, 0, p["valor_min"], p["valor_max"], p["valor_predeterminado"]
                            )

                # ── Botón de generación HTML ───────────────────────────────────
                html_path = prs_row.get("html_path")
                if html_path and os.path.exists(str(html_path)):
                    st.success(f"HTML listo: `{os.path.basename(html_path)}`")
                    try:
                        with open(html_path, encoding="utf-8") as _f:
                            st.download_button(
                                "Descargar HTML",
                                data=_f.read(),
                                file_name=os.path.basename(html_path),
                                mime="text/html",
                                key=f"prs_dl_{sub_id}",
                            )
                    except OSError:
                        pass

                if st.button(
                    f"Generar HTML de este sub-bloque",
                    type="primary",
                    key=f"prs_gen_{sub_id}",
                    use_container_width=True,
                ):
                    if not markdown_sub:
                        st.error("Sin contenido generado. Ve a la vista **Contenido** primero.")
                    else:
                        params_para_generar = _db_prs_get_parametros(prs_id)
                        with st.status(
                            f"Generando HTML de «{sub_nombre}»…", expanded=True
                        ) as status:
                            try:
                                st.write("Llamando al generador Sonnet…")
                                html_bloque = _prs_generar_html_subbloque(
                                    subbloque_nombre=sub_nombre,
                                    markdown=markdown_sub,
                                    patron=patron_actual,
                                    parametros_db=params_para_generar,
                                )
                                html_pagina = _prs_generador_html._construir_pagina(
                                    [(sub_nombre, html_bloque)],
                                    titulo_tema=f"{tema_nombre} — {sub_nombre}",
                                )
                                html_dir = os.path.join(
                                    RAIZ_MONOREPO, "data", "html", _slugify(asignatura)
                                )
                                os.makedirs(html_dir, exist_ok=True)
                                html_path_nuevo = os.path.join(
                                    html_dir, f"subbloque_{sub_id}.html"
                                )
                                with open(html_path_nuevo, "w", encoding="utf-8") as _f:
                                    _f.write(html_pagina)
                                _db_prs_update_html_path(sub_id, html_path_nuevo)
                                status.update(label="HTML generado correctamente", state="complete")
                            except Exception as _err:
                                status.update(label="Error en la generación", state="error")
                                st.error(str(_err))
                        st.rerun()

    # ── Exportar bloque completo ──────────────────────────────────────────────
    st.divider()
    st.markdown("### Exportar bloque completo")

    _md_bloque = _prs_ensamblar_markdown_bloque(tema_nombre, subbloques)
    _tiene_contenido_bloque = len(_md_bloque.splitlines()) > 1  # más que solo el título H1

    if not _tiene_contenido_bloque:
        st.info(
            "Genera el contenido de al menos un sub-bloque en la vista **Contenido** "
            "para poder exportar el bloque completo."
        )
        return

    _col_pdf, _col_pres = st.columns(2)

    with _col_pdf:
        if st.button(
            "Generar PDF del bloque",
            key=f"prs_pdf_{tema_id}",
            use_container_width=True,
        ):
            with st.status("Generando PDF…", expanded=True) as _st_pdf:
                try:
                    st.write("Renderizando ecuaciones y tablas…")
                    _pdf_bytes = _prs_generador_pdf.generar_pdf(_md_bloque, titulo=tema_nombre)
                    st.session_state[f"prs_pdf_bytes_{tema_id}"] = _pdf_bytes
                    _st_pdf.update(label="PDF generado", state="complete")
                except Exception as _e:
                    _st_pdf.update(label="Error al generar el PDF", state="error")
                    st.error(str(_e))
            st.rerun()

        if st.session_state.get(f"prs_pdf_bytes_{tema_id}"):
            st.download_button(
                "Descargar PDF",
                data=st.session_state[f"prs_pdf_bytes_{tema_id}"],
                file_name=f"{_slugify(tema_nombre)}_bloque.pdf",
                mime="application/pdf",
                key=f"prs_dl_pdf_{tema_id}",
                use_container_width=True,
            )

    with _col_pres:
        if st.button(
            "Generar presentación completa",
            key=f"prs_presentacion_{tema_id}",
            use_container_width=True,
        ):
            with st.status("Generando presentación…", expanded=True) as _st_pres:
                try:
                    st.write("Detectando elementos interactivos…")
                    _elementos_pres = _prs_detector.detectar_elementos(
                        _md_bloque, analizar_advertencias=False
                    )
                    st.write(
                        f"{len(_elementos_pres)} elementos detectados — "
                        "generando presentación completa…"
                    )
                    _html_pres = _prs_generador_presentacion.generar_presentacion(
                        _md_bloque, _elementos_pres, tema_nombre, verbose=False
                    )
                    st.session_state[f"prs_html_pres_{tema_id}"] = _html_pres.encode("utf-8")
                    _st_pres.update(label="Presentación generada", state="complete")
                except Exception as _e:
                    _st_pres.update(label="Error al generar la presentación", state="error")
                    st.error(str(_e))
            st.rerun()

        if st.session_state.get(f"prs_html_pres_{tema_id}"):
            st.download_button(
                "Descargar presentación completa",
                data=st.session_state[f"prs_html_pres_{tema_id}"],
                file_name=f"{_slugify(tema_nombre)}_presentacion_completa.html",
                mime="text/html",
                key=f"prs_dl_pres_{tema_id}",
                use_container_width=True,
            )


# =============================================================================
# Stepper contextual — flujos multi-paso
# =============================================================================

def _render_stepper(pasos: list[str], paso_actual: int) -> None:
    """Fila de tarjetas conectadas por flechas: activo en color de acento, resto en gris."""
    partes: list[str] = []
    for i, paso in enumerate(pasos):
        if i < paso_actual:
            estilo = (
                f"background:rgba(24,95,165,0.08);color:{ACENTO};"
                "border-radius:8px;padding:5px 15px;font-size:12px;font-weight:500;"
                "font-family:'DM Sans',sans-serif;opacity:0.7;"
            )
        elif i == paso_actual:
            estilo = (
                f"background:{ACENTO};color:#ffffff;"
                "border-radius:8px;padding:5px 15px;font-size:12px;font-weight:600;"
                "font-family:'DM Sans',sans-serif;"
            )
        else:
            estilo = (
                "background:rgba(128,128,128,0.08);color:var(--text-color);"
                "border-radius:8px;padding:5px 15px;font-size:12px;"
                "font-family:'DM Sans',sans-serif;opacity:0.4;"
            )
        partes.append(f'<span style="{estilo}">{paso}</span>')
        if i < len(pasos) - 1:
            partes.append(
                '<span style="color:rgba(128,128,128,0.3);font-size:16px;'
                'padding:0 2px;line-height:1;">›</span>'
            )
    st.markdown(
        '<div style="display:flex;align-items:center;gap:4px;margin:0 0 18px 0;flex-wrap:wrap;">'
        + "".join(partes)
        + "</div>",
        unsafe_allow_html=True,
    )


# =============================================================================
# Vista Organizador
# =============================================================================

def _org_sync_widgets_a_bloques(iter_key: int) -> bool:
    """Lee los widgets de edición y actualiza org_organizacion_bloques. Devuelve True si hubo cambios."""
    bloques = st.session_state.get("org_organizacion_bloques", [])
    sub_revs: dict = st.session_state.get("org_sub_widget_rev", {})
    changed = False
    for idx_b, bloque in enumerate(bloques):
        k_n = f"org_bn_{idx_b}_{iter_key}"
        k_h = f"org_bh_{idx_b}_{iter_key}"
        if k_n in st.session_state:
            v = st.session_state[k_n].strip()
            if v and v != bloque["nombre"]:
                bloque["nombre"] = v
                changed = True
        if k_h in st.session_state:
            v = float(st.session_state[k_h])
            if abs(v - float(bloque.get("horas", 0))) > 0.001:
                bloque["horas"] = v
                changed = True
        for idx_s, sub in enumerate(bloque.get("subtemas", [])):
            sub_rev = sub_revs.get(idx_b, 0)
            k_s = f"org_sn_{idx_b}_{idx_s}_{iter_key}_{sub_rev}"
            if k_s in st.session_state:
                v = st.session_state[k_s].strip()
                if v and v != sub["nombre"]:
                    sub["nombre"] = v
                    sub["manual"] = True
                    changed = True
    if changed:
        st.session_state["org_organizacion_bloques"] = bloques
    return changed


def _org_render_vista_organizacion(slug: str, *, editable: bool) -> None:
    """Vista unificada de bloques y subbloques — editable o solo lectura."""
    bloques = st.session_state.get("org_organizacion_bloques", [])
    if not bloques:
        st.info(
            "No se pudo mostrar la organización en formato estructurado. "
            "Revisa que el Markdown siga el patrón «## Bloque N — Nombre · Xh»."
        )
        if st.session_state.get("org_ultimo_output"):
            with st.expander("Ver Markdown generado"):
                st.markdown(st.session_state["org_ultimo_output"])
        return

    iter_key = st.session_state["org_iteracion"]
    sub_revs: dict = st.session_state.get("org_sub_widget_rev", {})

    if editable:
        st.markdown(
            """
            <style>
            button[title="Aprobar subbloque"][kind="primary"] {
                background-color: #16a34a !important;
                color: #fff !important;
                border-color: #15803d !important;
            }
            button[title="Aprobar subbloque"][kind="primary"]:hover {
                background-color: #15803d !important;
                border-color: #166534 !important;
            }
            button[title="Aprobar subbloque"][kind="secondary"] {
                background-color: #ecfdf5 !important;
                color: #166534 !important;
                border: 1px solid #86efac !important;
            }
            button[title="Aprobar subbloque"][kind="secondary"]:hover {
                background-color: #d1fae5 !important;
                border-color: #4ade80 !important;
            }
            button[title="Eliminar subtema"],
            button[title="Eliminar bloque"] {
                background-color: #dc2626 !important;
                color: #fff !important;
                border-color: #dc2626 !important;
            }
            button[title="Eliminar subtema"]:hover,
            button[title="Eliminar bloque"]:hover {
                background-color: #b91c1c !important;
                border-color: #b91c1c !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("### Revisa y edita la organización")
        st.caption(
            "Marca cada subbloque como correcto (✓), edita nombres, elimina filas o añade "
            "bloques/subbloques. Las horas se gestionan solo a nivel de bloque. "
            "Para cambios grandes usa el cuadro de redistribución por prompt más abajo."
        )
    else:
        st.markdown("### Organización confirmada")

    for idx_b, bloque in enumerate(bloques):
        archivo_bloque = bloque.get("archivo_origen", "")
        with st.container(border=True):
            if editable:
                c_tit, c_horas, c_del_b = st.columns([5, 1.5, 0.5])
                with c_tit:
                    st.text_input(
                        f"Nombre — Bloque {bloque['numero']}",
                        value=bloque["nombre"],
                        key=f"org_bn_{idx_b}_{iter_key}",
                        label_visibility="collapsed",
                    )
                with c_horas:
                    ch_val, ch_unit = st.columns([4, 1])
                    with ch_val:
                        st.number_input(
                            "Horas del bloque",
                            min_value=0.0,
                            step=0.5,
                            value=float(bloque.get("horas", 0)),
                            key=f"org_bh_{idx_b}_{iter_key}",
                            label_visibility="collapsed",
                        )
                    with ch_unit:
                        st.markdown(
                            "<p style='margin-top:28px;margin-bottom:0;color:var(--text-color);'>h</p>",
                            unsafe_allow_html=True,
                        )
                with c_del_b:
                    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
                    if st.button(
                        "✕",
                        key=f"org_del_bloque_{idx_b}_{iter_key}",
                        help="Eliminar bloque",
                    ):
                        _org_sync_widgets_a_bloques(iter_key)
                        st.session_state["org_organizacion_bloques"].pop(idx_b)
                        _org_actualizar_desde_bloques(slug)
                        st.rerun()
            else:
                h = bloque.get("horas", 0)
                h_fmt = str(int(h)) if h == int(h) else f"{h:.1f}"
                st.markdown(f"**Bloque {bloque['numero']} — {bloque['nombre']} · {h_fmt}h**")

            if bloque.get("manual"):
                st.caption("Origen: Añadido manualmente")
            elif archivo_bloque:
                st.caption(f"Origen: {archivo_bloque}")

            h1, h2, h3, h4 = st.columns([3.5, 2.8, 0.55, 0.55])
            h1.markdown("**Subtema**")
            h2.markdown("**Evidencia**")
            if editable:
                h3.markdown("**✓**")
                h4.markdown("")

            for idx_s, sub in enumerate(bloque.get("subtemas", [])):
                r1, r2, r3, r4 = st.columns([3.5, 2.8, 0.55, 0.55])
                evidencia = _org_format_evidencia(sub, archivo_bloque)
                sub_rev = sub_revs.get(idx_b, 0)
                with r1:
                    if editable:
                        st.text_input(
                            "Subtema",
                            value=sub["nombre"],
                            key=f"org_sn_{idx_b}_{idx_s}_{iter_key}_{sub_rev}",
                            label_visibility="collapsed",
                        )
                    else:
                        marca = " ✓" if sub.get("aprobado") else ""
                        st.markdown(f"{sub['nombre']}{marca}")
                with r2:
                    st.caption(evidencia)
                if editable:
                    with r3:
                        aprobado = sub.get("aprobado", False)
                        if st.button(
                            "✓",
                            key=f"org_ok_{idx_b}_{idx_s}_{iter_key}_{sub_rev}",
                            help="Aprobar subbloque",
                            type="primary" if aprobado else "secondary",
                        ):
                            _org_sync_widgets_a_bloques(iter_key)
                            st.session_state["org_organizacion_bloques"][idx_b]["subtemas"][idx_s][
                                "aprobado"
                            ] = not aprobado
                            st.rerun()
                    with r4:
                        if st.button(
                            "✕",
                            key=f"org_del_sub_{idx_b}_{idx_s}_{iter_key}_{sub_rev}",
                            help="Eliminar subtema",
                        ):
                            _org_sync_widgets_a_bloques(iter_key)
                            st.session_state["org_organizacion_bloques"][idx_b]["subtemas"].pop(idx_s)
                            _org_bump_sub_widget_rev(idx_b)
                            _org_actualizar_desde_bloques(slug)
                            st.rerun()

            if editable:
                ctr_s = st.session_state["org_contador_add_subtema"].get(idx_b, 0)
                a1, a2 = st.columns([5, 1])
                with a1:
                    st.text_input(
                        "Nuevo subbloque",
                        key=f"org_ns_nombre_{idx_b}_{ctr_s}",
                        label_visibility="collapsed",
                        placeholder="+ Añadir subbloque…",
                    )
                with a2:
                    if st.button("+ Añadir", key=f"org_btn_ns_{idx_b}_{ctr_s}"):
                        _org_sync_widgets_a_bloques(iter_key)
                        nombre_ns = st.session_state.get(f"org_ns_nombre_{idx_b}_{ctr_s}", "").strip()
                        if nombre_ns:
                            st.session_state["org_organizacion_bloques"][idx_b]["subtemas"].append({
                                "nombre": nombre_ns,
                                "evidencia": "Manual (profesor)",
                                "origen": "Manual",
                                "manual": True,
                                "aprobado": False,
                            })
                            ctrs = st.session_state["org_contador_add_subtema"]
                            ctrs[idx_b] = ctr_s + 1
                            st.session_state["org_contador_add_subtema"] = ctrs
                            _org_actualizar_desde_bloques(slug)
                            st.rerun()

    if editable:
        ctr_b = st.session_state["org_contador_add_bloque"]
        st.markdown("**Añadir bloque**")
        nb1, nb2, nb3 = st.columns([4, 1.5, 1])
        with nb1:
            st.text_input(
                "Nombre del nuevo bloque",
                key=f"org_nb_nombre_{ctr_b}",
                label_visibility="collapsed",
                placeholder="Nombre del nuevo bloque…",
            )
        with nb2:
            nbh_val, nbh_unit = st.columns([4, 1])
            with nbh_val:
                st.number_input(
                    "Horas",
                    min_value=0.0,
                    step=0.5,
                    value=0.0,
                    key=f"org_nb_horas_{ctr_b}",
                    label_visibility="collapsed",
                )
            with nbh_unit:
                st.markdown(
                    "<p style='margin-top:28px;margin-bottom:0;color:var(--text-color);'>h</p>",
                    unsafe_allow_html=True,
                )
        with nb3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("+ Añadir bloque", key=f"org_btn_nb_{ctr_b}"):
                _org_sync_widgets_a_bloques(iter_key)
                nombre_nb = st.session_state.get(f"org_nb_nombre_{ctr_b}", "").strip()
                if nombre_nb:
                    nums = [b["numero"] for b in st.session_state["org_organizacion_bloques"]]
                    nuevo_num = max(nums) + 1 if nums else 1
                    horas_nb = float(st.session_state.get(f"org_nb_horas_{ctr_b}", 0.0))
                    st.session_state["org_organizacion_bloques"].append({
                        "numero": nuevo_num,
                        "nombre": nombre_nb,
                        "horas": horas_nb,
                        "subtemas": [],
                        "manual": True,
                        "archivo_origen": "",
                    })
                    st.session_state["org_contador_add_bloque"] = ctr_b + 1
                    _org_actualizar_desde_bloques(slug)
                    st.rerun()

        if st.button("💾 Aplicar cambios de edición", type="secondary", use_container_width=True):
            if _org_sync_widgets_a_bloques(iter_key):
                _org_actualizar_desde_bloques(slug)
            st.success("Cambios aplicados al Markdown de la organización.")
            st.rerun()


def _render_valoracion_profesor(
    asignatura_id: int,
    agente: str,
    *,
    etiqueta: str,
    key_prefix: str,
) -> None:
    """Control reutilizable de valoración 1-10 (persistente por asignatura y agente)."""
    valor_guardada = db.get_valoracion_profesor(asignatura_id, agente, RUTA_DB)
    st.subheader("Valoración del resultado")
    if valor_guardada is not None:
        st.caption(f"Valoración guardada: **{valor_guardada}/10**")
    puntuacion = st.select_slider(
        etiqueta,
        options=list(range(1, 11)),
        value=valor_guardada if valor_guardada is not None else 7,
        key=f"{key_prefix}_slider_{asignatura_id}",
    )
    if st.button(
        "Guardar valoración",
        key=f"{key_prefix}_btn_{asignatura_id}",
        type="secondary",
    ):
        try:
            db.upsert_valoracion_profesor(asignatura_id, agente, puntuacion, RUTA_DB)
            st.success(f"Valoración guardada: {puntuacion}/10")
        except (ValueError, Exception) as e:
            st.error(f"No se pudo guardar la valoración: {e}")


def _vista_organizador() -> None:
    if _ORG_ERROR:
        st.error(f"No se pudo cargar el Agente Organizador: {_ORG_ERROR}")
        st.caption(f"Comprueba que `agente-organizador/.env` existe y contiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en el portfolio para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    slug = _slugify(asignatura)

    # Reset si la asignatura cambió entre reruns
    if st.session_state.get("org_asignatura") != asignatura:
        _org_reset_state()
        st.session_state["org_asignatura"] = asignatura

    _org_init_state()

    if st.session_state.get("org_ultimo_output"):
        _paso_org = 1
    else:
        _paso_org = 0
    _render_stepper(["Guía docente", "Organización"], _paso_org)

    # ── Uploaders ──────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-family:\"DM Sans\",sans-serif; font-size:11px; font-weight:500; "
        "color:var(--text-color); opacity:0.55; letter-spacing:0.1em; text-transform:uppercase; "
        "margin-bottom:10px;'>Archivos de entrada</div>",
        unsafe_allow_html=True,
    )
    col_guia, col_mat = st.columns([1, 2])
    with col_guia:
        guia_docente = st.file_uploader(
            "Guía docente (PDF)", type=["pdf"], accept_multiple_files=False,
            key="org_uploader_guia",
        )
    with col_mat:
        materiales_teoria = st.file_uploader(
            "Materiales de teoría (PDF / PPTX)", type=["pdf", "pptx"],
            accept_multiple_files=True, key="org_uploader_materiales",
        )

    _org_registrar_archivos(guia_docente, materiales_teoria, asignatura_id, slug, asignatura)
    _org_detectar_cambio(guia_docente, materiales_teoria)

    puede_generar = guia_docente is not None and bool(materiales_teoria)

    # ── Expanders de validación ────────────────────────────────────────────────
    with st.expander("⏱️ Validación de horas detectadas", expanded=False):
        horas_info = st.session_state.get("org_ultimas_horas_teoria") or {}
        h_te = int(horas_info.get("horas_teoria", 0))
        h_pa = int(horas_info.get("horas_aula", 0))
        h_pl = int(horas_info.get("horas_laboratorio", 0))
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Horas TE detectadas", f"{h_te}h")
        col2.metric("Horas PA detectadas", f"{h_pa}h")
        col3.metric("Horas PL (informativo)", f"{h_pl}h")
        col4.metric("Total TE + PA", f"{h_te + h_pa}h")
        if h_te + h_pa <= 0 and st.session_state.get("org_ultimas_horas_teoria"):
            st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")

    if st.session_state["org_ultimos_archivos_teoria"] or st.session_state["org_ultimos_archivos_contexto"]:
        with st.expander("📋 Clasificación de archivos detectada", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Teoría")
                for n in st.session_state["org_ultimos_archivos_teoria"]:
                    st.write(f"- {n}")
                if not st.session_state["org_ultimos_archivos_teoria"]:
                    st.write("Sin archivos clasificados como teoría.")
            with c2:
                st.subheader("Contexto/Outline")
                for n in st.session_state["org_ultimos_archivos_contexto"]:
                    st.write(f"- {n}")
                if not st.session_state["org_ultimos_archivos_contexto"]:
                    st.write("Sin archivos clasificados como contexto.")

    st.divider()

    # ── Botón de generación ───────────────────────────────────────────────────
    if st.button(
        "Generar organización", disabled=not puede_generar,
        use_container_width=True, type="primary", key="org_btn_generar",
    ):
        st.session_state["org_historial_feedback"] = []
        st.session_state["org_iteracion"] = 1
        st.session_state["org_ultimo_output"] = None
        st.session_state["org_confirmada"] = False
        if _org_generar_organizacion(
            guia_docente, materiales_teoria,
            asignatura_id=asignatura_id, slug=slug,
        ):
            st.rerun()

    if not puede_generar and not st.session_state.get("org_ultimo_output"):
        st.info("Sube los archivos arriba y pulsa **Generar organización** para comenzar.")

    # ── Output generado ────────────────────────────────────────────────────────
    if st.session_state.get("org_ultimo_output"):
        w = st.session_state.get("org_warning_cardinalidad")
        if w:
            st.warning(_texto_warning_cobertura(w["esperados"], w["generados"]))

        wn = st.session_state.get("org_warning_normalizacion")
        if wn:
            diferencia = wn["diferencia"]
            suma_antes = wn["suma_antes"]
            total_obj = suma_antes - diferencia
            bloques_ajustados = ", ".join(
                f"**{nombre}** ({v['antes']}h → {v['despues']}h)"
                for nombre, v in list(wn["ajustes"].items())[:6]
            )
            st.warning(
                f"⚠️ **Normalización de horas aplicada:** el modelo asignó **{suma_antes:.1f}h** "
                f"en total de bloques en lugar de **{total_obj:.0f}h** (diferencia: {diferencia:+.1f}h). "
                f"Las horas se redistribuyeron entre bloques. "
                + (f"Bloques ajustados: {bloques_ajustados}." if bloques_ajustados else "")
            )

        wt = st.session_state.get("org_warning_truncamiento")
        if wt:
            st.error(
                f"⚠️ **Posible truncamiento en la generación:** {wt.get('motivo', '')} "
                f"{wt.get('detalle', '')} Revisa el último bloque y usa Regenerar si la tabla quedó incompleta."
            )

        st.caption(
            f"Versión {st.session_state['org_version_actual']} · "
            f"guardada en `data/{slug}/outputs/organizador/v{st.session_state['org_version_actual']}.md`"
        )

        org_confirmada = st.session_state.get("org_confirmada")
        _org_render_vista_organizacion(slug, editable=not org_confirmada)

        st.download_button(
            label="Descargar resultado (.md)",
            data=st.session_state["org_ultimo_output"],
            file_name=st.session_state.get("org_ultimo_nombre_descarga", "Propuesta_asignatura.md"),
            mime="text/markdown",
            key="org_download",
        )

        if not org_confirmada:
            with st.expander("Ver Markdown generado"):
                st.markdown(st.session_state["org_ultimo_output"])

        st.divider()

        # ── Confirmar organización ─────────────────────────────────────────────
        st.subheader("¿La organización es correcta?")

        if org_confirmada:
            st.success(
                f"✅ Organización confirmada y guardada en la base de datos "
                f"(versión {st.session_state['org_version_actual']})."
            )
            st.info(
                "🔒 **Estructura congelada.** La organización se ha pasado al Agente "
                "Contenido. La edición de bloques/subbloques y el refinamiento "
                "por prompt quedan deshabilitados. Descarga el resultado o sube nuevos "
                "archivos para empezar otra organización."
            )
            st.divider()
            _render_valoracion_profesor(
                asignatura_id,
                "organizador",
                etiqueta="¿Cómo valoras la organización generada? (1 = muy deficiente, 10 = excelente)",
                key_prefix="org_valoracion",
            )
        else:
            if st.button(
                "✅ Confirmar organización como definitiva",
                type="primary", use_container_width=True, key="org_btn_confirmar_org",
            ):
                _org_sync_widgets_a_bloques(st.session_state["org_iteracion"])
                _org_actualizar_desde_bloques(slug)
                output_id = st.session_state.get("org_output_id")
                if not output_id:
                    st.error("No hay output registrado en la base de datos — genera la organización primero.")
                else:
                    try:
                        bloques = _org_preparar_bloques_para_confirmar(
                            st.session_state["org_ultimo_output"],
                            asignatura_id,
                        )
                        if not bloques:
                            st.warning(
                                "No se pudieron extraer bloques del output. "
                                "Revisa que el formato sigue el patrón '## Bloque N — Nombre · Xh'."
                            )
                        else:
                            _db_confirmar_organizacion(asignatura_id, output_id, bloques)
                            st.session_state["org_confirmada"] = True
                            n_sub = sum(len(b["subtemas"]) for b in bloques)
                            st.success(
                                f"✅ {len(bloques)} bloques y {n_sub} subtemas guardados en la base de datos."
                            )
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar en la base de datos: {e}")

            st.divider()

            # ── Loop de feedback (refinamiento por IA) ─────────────────────────
            feedback = st.text_area(
                "Si quieres mejorar algo, descríbelo aquí (opcional):",
                placeholder=(
                    "Ejemplos:\n"
                    "- 'Divide el bloque 3 en dos partes más granulares'\n"
                    "- 'Renombra el subtema X a Y'\n"
                    "- 'El bloque 2 necesita más subtemas según el material'"
                ),
                key=f"org_feedback_{st.session_state['org_iteracion']}",
            )

            col_regen, col_info = st.columns([1, 4])
            with col_regen:
                regenerar = (
                    st.button("🔄 Regenerar", type="secondary", key="org_btn_regen")
                    if st.session_state["org_iteracion"] < 5
                    else False
                )
            with col_info:
                if st.session_state["org_iteracion"] > 1:
                    st.caption(
                        f"Iteración {st.session_state['org_iteracion']} — "
                        f"{len(st.session_state['org_historial_feedback'])} refinamiento(s) aplicado(s)"
                    )

            if st.session_state["org_iteracion"] >= 5:
                st.info("Has alcanzado el máximo de 5 iteraciones. Descarga el resultado o reinicia subiendo nuevos archivos.")

            if regenerar:
                entrada = feedback.strip() if feedback and feedback.strip() else "[Sin feedback — regeneración directa]"
                st.session_state["org_historial_feedback"].append(entrada)
                st.session_state["org_iteracion"] += 1
                st.session_state["org_confirmada"] = False
                if _org_generar_organizacion(
                    guia_docente, materiales_teoria,
                    asignatura_id=asignatura_id, slug=slug,
                    feedback_previo=st.session_state["org_historial_feedback"],
                ):
                    st.rerun()


# =============================================================================
# Vista Resumen — métricas agregadas de la asignatura activa
# =============================================================================

def _db_resumen_metricas(asignatura_id: int) -> dict:
    """Consulta las métricas agregadas de la asignatura para la vista Resumen.

    - progreso: {total, aprobados, porcentaje} — calculado en tiempo real.
    - fidelidad_media: AVG de los scores de fidelidad guardados (validaciones
      tipo 'fidelidad_baja'); son los únicos scores que se persisten.
    - n_outputs: organizador_outputs + presentacion_outputs.
    - n_avisos: todas las validaciones ligadas a ejecuciones de la asignatura.
    - ultima_ejecucion: fecha de inicio de la ejecución más reciente.
    """
    conn = db.get_connection(RUTA_DB)
    try:
        fid = conn.execute(
            "SELECT AVG(v.valor_afectado) AS media, COUNT(*) AS n "
            "FROM validaciones v JOIN ejecuciones e ON v.ejecucion_id = e.id "
            "WHERE e.asignatura_id = ? AND v.tipo = 'fidelidad_baja' "
            "AND v.valor_afectado IS NOT NULL",
            (asignatura_id,),
        ).fetchone()
        n_org = conn.execute(
            "SELECT COUNT(*) FROM organizador_outputs WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        n_prs = conn.execute(
            "SELECT COUNT(*) FROM presentacion_outputs WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        n_avisos = conn.execute(
            "SELECT COUNT(*) FROM validaciones v JOIN ejecuciones e "
            "ON v.ejecucion_id = e.id WHERE e.asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        ultima = conn.execute(
            "SELECT MAX(fecha_inicio) FROM ejecuciones WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        return {
            "fidelidad_media": fid["media"] if fid else None,
            "n_fidelidad": fid["n"] if fid else 0,
            "n_outputs": n_org + n_prs,
            "n_org": n_org,
            "n_prs": n_prs,
            "n_avisos": n_avisos,
            "ultima_ejecucion": ultima,
        }
    finally:
        conn.close()


def _db_resumen_avisos(asignatura_id: int) -> list[dict]:
    """Avisos de validación de la asignatura (los más recientes primero)."""
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT v.tipo, v.descripcion, v.valor_afectado, v.bloqueante, "
                "v.created_at, e.agente "
                "FROM validaciones v JOIN ejecuciones e ON v.ejecucion_id = e.id "
                "WHERE e.asignatura_id = ? ORDER BY v.id DESC",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _vista_resumen() -> None:
    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en el portfolio para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    m = _db_resumen_metricas(asignatura_id)

    fidelidad_txt = (
        f"{m['fidelidad_media']:.3f}" if m["fidelidad_media"] is not None else "—"
    )
    if m["ultima_ejecucion"]:
        try:
            _dt = datetime.strptime(m["ultima_ejecucion"], "%Y-%m-%d %H:%M:%S")
            ultima_txt = f"{_dt.day} {_dt.strftime('%b, %H:%M')}"
            _delta_s = int((datetime.now() - _dt).total_seconds())
            if _delta_s < 60:
                _relativo = "ahora mismo"
            elif _delta_s < 3600:
                _relativo = f"hace {_delta_s // 60} min"
            elif _delta_s < 86400:
                _relativo = f"hace {_delta_s // 3600}h"
            else:
                _d = _delta_s // 86400
                _relativo = f"hace {_d} día{'s' if _d != 1 else ''}"
        except ValueError:
            ultima_txt = m["ultima_ejecucion"]
            _relativo = None
    else:
        ultima_txt = "—"
        _relativo = None

    # ── Progreso global de la asignatura ──────────────────────────────────────
    prog = db.get_progreso_asignatura(asignatura_id, RUTA_DB)
    _pct = prog["porcentaje"]
    if prog["total"] > 0:
        st.progress(
            _pct / 100,
            text=(
                f"Progreso de contenido: **{prog['aprobados']}/{prog['total']}** "
                f"sub-bloques aprobados ({_pct}%)"
            ),
        )
    else:
        st.info("Confirma la organización en el Agente Organizador para ver el progreso.")

    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Fidelidad media",
        fidelidad_txt,
        help=(
            "Media de los scores de fidelidad léxica guardados "
            f"({m['n_fidelidad']} sub-bloque(s) por debajo de 0.85). "
            "Si no hay ninguno marcado, no hay scores que promediar."
        ),
    )
    c2.metric(
        "Outputs generados",
        m["n_outputs"],
        help=f"organizador_outputs ({m['n_org']}) + presentacion_outputs ({m['n_prs']}).",
    )
    c3.metric(
        "Avisos de validación",
        m["n_avisos"],
        help="Filas en `validaciones` ligadas a ejecuciones de esta asignatura.",
    )
    c4.metric("Última ejecución", ultima_txt)
    if _relativo:
        c4.caption(_relativo)

    # ── Progreso desglosado por bloque ────────────────────────────────────────
    desglose = db.get_desglose_progreso_asignatura(asignatura_id, RUTA_DB)
    if desglose:
        st.divider()
        st.markdown("**Progreso por bloque temático**")
        for bloque in desglose:
            _bp = bloque["porcentaje"]
            _label = (
                f"{bloque['nombre']} — {bloque['aprobados']}/{bloque['total_sub']} "
                f"sub-bloques ({_bp}%)"
            )
            st.progress(_bp / 100, text=_label)

    st.divider()

    avisos = _db_resumen_avisos(asignatura_id)
    st.markdown(f"**Avisos de validación registrados** ({len(avisos)})")
    if not avisos:
        st.caption("Sin avisos de validación para esta asignatura todavía.")
        return

    _ICONO_TIPO = {"cobertura_incompleta": "🧩", "fidelidad_baja": "📉"}
    for a in avisos:
        icono = _ICONO_TIPO.get(a["tipo"], "⚠️")
        valor = a["valor_afectado"]
        valor_txt = f" · valor: {valor}" if valor is not None else ""
        bloq_txt = " · 🔴 bloqueante" if a["bloqueante"] else ""
        with st.expander(
            f"{icono} `{a['tipo']}` — {a['agente']}{valor_txt}{bloq_txt}",
            expanded=False,
        ):
            st.markdown(a["descripcion"])
            st.caption(f"Registrado: {a['created_at']}")


# =============================================================================
# Vista Inputs — archivos registrados de la asignatura activa
# =============================================================================

def _render_tabla_inputs(filas: list[dict], vacio: str) -> None:
    if not filas:
        st.caption(vacio)
        return
    h1, h2, h3 = st.columns([2.2, 1.2, 1])
    h1.markdown('<div class="inputs-tabla-header">Archivo</div>', unsafe_allow_html=True)
    h2.markdown('<div class="inputs-tabla-header">Subido</div>', unsafe_allow_html=True)
    h3.markdown('<div class="inputs-tabla-header">En disco</div>', unsafe_allow_html=True)
    for fila in filas:
        c1, c2, c3 = st.columns([2.2, 1.2, 1])
        c1.markdown(f'<span class="file-chip">{html.escape(fila["nombre_fichero"])}</span>', unsafe_allow_html=True)
        c2.caption(fila.get("fecha_subida") or "—")
        if fichero_existe(fila.get("ruta_disco") or ""):
            c3.caption("✅ Disponible")
        else:
            c3.caption("⚠️ No encontrado")


def _vista_inputs() -> None:
    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en el portfolio para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    inputs = db.listar_inputs_asignatura(asignatura_id, RUTA_DB)
    guias = [i for i in inputs if i["tipo"] == "guia_docente"]
    materiales = [i for i in inputs if i["tipo"] == "material_teoria"]

    st.markdown('<div class="inputs-seccion-titulo">Guía docente</div>', unsafe_allow_html=True)
    _render_tabla_inputs(guias, "No hay guía docente registrada todavía.")

    st.markdown('<div class="inputs-seccion-titulo">Materiales de teoría</div>', unsafe_allow_html=True)
    _render_tabla_inputs(materiales, "No hay materiales de teoría registrados todavía.")

    st.divider()
    st.caption("Para subir o actualizar archivos, ve al **Agente Organizador**.")


# =============================================================================
# Vista Base de datos — navegador de solo lectura del esquema SQLite
# =============================================================================

# Nombres de columna que se interpretan como marca temporal del registro.
_COLS_FECHA = {"fecha_subida", "fecha_inicio", "fecha_generacion",
               "fecha_actualizacion", "created_at"}


def _db_info_tablas() -> list[dict]:
    """Para cada tabla del esquema: filas, columna de fecha y fecha más reciente.

    Los nombres de tabla/columna provienen de `sqlite_master`/`PRAGMA`, no de
    entrada del usuario, por lo que su interpolación en el SQL es segura.
    """
    conn = db.get_connection(RUTA_DB)
    try:
        tablas = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        info: list[dict] = []
        for t in tablas:
            columnas = [
                {"nombre": c["name"], "tipo": c["type"] or "—"}
                for c in conn.execute(f"PRAGMA table_info({t})").fetchall()
            ]
            fecha_col = next(
                (c["nombre"] for c in columnas if c["nombre"].lower() in _COLS_FECHA),
                None,
            )
            n_filas = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            ultima = None
            if fecha_col:
                ultima = conn.execute(f"SELECT MAX({fecha_col}) FROM {t}").fetchone()[0]
            info.append({
                "tabla": t,
                "n_filas": n_filas,
                "fecha_col": fecha_col,
                "ultima_fecha": ultima,
                "columnas": columnas,
            })
        return info
    finally:
        conn.close()


def _vista_base_datos() -> None:
    info = _db_info_tablas()
    st.caption(f"`{RUTA_DB}` — {len(info)} tablas (navegador de solo lectura).")

    h1, h2, h3 = st.columns([2.2, 1, 2])
    h1.markdown("**Tabla**")
    h2.markdown("**Filas**")
    h3.markdown("**Registro más reciente**")
    st.divider()

    for t in info:
        c1, c2, c3 = st.columns([2.2, 1, 2])
        c1.markdown(f"`{t['tabla']}`")
        c2.markdown(str(t["n_filas"]))
        if t["fecha_col"]:
            c3.markdown(t["ultima_fecha"] or "—")
        else:
            c3.caption("sin columna de fecha")

    st.divider()
    with st.expander("Ver esquema completo", expanded=False):
        for t in info:
            st.markdown(f"**`{t['tabla']}`** — {t['n_filas']} fila(s)")
            filas_esquema = [
                {"columna": c["nombre"], "tipo": c["tipo"]} for c in t["columnas"]
            ]
            st.table(filas_esquema)


# =============================================================================
# Configuración de página + inicialización
# =============================================================================

st.set_page_config(layout="wide", page_title="Pipeline TFG")


@st.cache_resource
def _preparar_bd():
    db.init_db(RUTA_DB)
    db.seed_asignaturas(RUTA_DB)
    return True


_preparar_bd()


# =============================================================================
# CSS — identidad visual compartida
# =============================================================================

inject_theme(ACENTO, ACENTO_OSCURO)


# =============================================================================
# Barra lateral + área principal
# =============================================================================

_asignatura_activa = st.session_state.get("asignatura_actual")

with st.sidebar:
    render_marca()
    st.divider()
    if _asignatura_activa:
        if st.session_state.get("vista_actual") == VISTA_BASE_DATOS:
            st.session_state["vista_actual"] = VISTAS_NAV[0]
        render_sidebar_workspace(VISTAS_NAV, ICONOS_VISTA, _asignatura_activa)
    else:
        render_sidebar_portfolio(RUTA_DB, RAIZ_MONOREPO)

if not _asignatura_activa:
    st.markdown(
        '<div class="seccion"><div class="barra"></div>'
        '<div class="titulo">Asignaturas</div></div>',
        unsafe_allow_html=True,
    )
    render_portfolio(RUTA_DB)
else:
    vista = st.session_state["vista_actual"]
    st.markdown(
        f'<div class="seccion"><div class="barra"></div>'
        f'<div class="titulo">{TITULOS_SECCION[vista]}</div></div>',
        unsafe_allow_html=True,
    )
    if vista == "Resumen":
        _vista_resumen()
    elif vista == "Inputs":
        _vista_inputs()
    elif vista == "Organizador":
        _vista_organizador()
    elif vista == "Contenido":
        _vista_contenido()
    elif vista == "Presentación":
        _vista_presentacion()
    else:
        st.info("Vista en construcción — se integra en el siguiente paso.")
