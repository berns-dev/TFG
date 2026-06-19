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
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

_log = logging.getLogger(__name__)

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
from ui.components import (  # noqa: E402
    cobertura_item_html,
    file_meta,
    file_tag_html,
    inline_estado,
    kpi_card,
    mapa_fila_html,
    pill_estado,
)
from ui.prototype_html import cobertura_bar_html  # noqa: E402
from ui.shell import (  # noqa: E402
    pipeline_subtitulos,
    render_bloque_chips,
    render_pipeline_banner,
    render_topbar,
)
from ui.sidebar import render_lista_asignaturas, render_sidebar  # noqa: E402
from ui.theme import inject_theme, inject_button_fix  # noqa: E402
from utils import (  # noqa: E402
    fichero_existe,
    formatear_fecha_relativa,
    preparar_carpetas_asignatura,
    slugify,
)

RUTA_DB = os.path.join(RAIZ_MONOREPO, "data", "tfg.db")

# =============================================================================
# Identidad visual
# =============================================================================

ACENTO = "#185FA5"
ACENTO_OSCURO = "#0C447C"

VISTAS_NAV = ["Resumen", "Inputs", "Organizador", "Contenido", "Presentación", "Base de datos"]
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
        RAIZ_ORGANIZADOR, "organizador", ["org_config", "agente", "parser", "org_prompts"]
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
            "assembler", "validator", "coverage_checklist", "pipeline",
        ],
    )
    _cnt_config = _cnt_mods["cnt_config"]
    _cnt_cleaner = _cnt_mods["cleaner"]
    _cnt_extractor = _cnt_mods["extractor"]
    _cnt_chunker = _cnt_mods["chunker"]
    _cnt_classifier = _cnt_mods["classifier"]
    _cnt_assembler = _cnt_mods["assembler"]
    _cnt_validator = _cnt_mods["validator"]
    _cnt_coverage = _cnt_mods["coverage_checklist"]
    _cnt_pipeline = _cnt_mods["pipeline"]
    _CNT_ERROR: str | None = None
except Exception as _ce:
    _cnt_config = _cnt_cleaner = _cnt_extractor = _cnt_chunker = _cnt_classifier = None
    _cnt_assembler = _cnt_validator = _cnt_coverage = _cnt_pipeline = None
    _CNT_ERROR = str(_ce)


# ── Agente Presentación (detector/generador_html←prs_config, prs_prompts) ─────
# generador_presentacion importa de generador_html → va al final del lote.
try:
    _prs_mods = _cargar_modulos_agente(
        RAIZ_PRESENTACION, "presentacion",
        ["prs_config", "prs_prompts", "generador_html", "workshop", "generador_pdf", "generador_presentacion"],
    )
    _prs_config = _prs_mods["prs_config"]
    _prs_prompts = _prs_mods["prs_prompts"]
    _prs_generador_html = _prs_mods["generador_html"]
    _prs_workshop = _prs_mods["workshop"]
    _prs_generador_pdf = _prs_mods["generador_pdf"]
    _prs_generador_presentacion = _prs_mods["generador_presentacion"]
    _PRS_ERROR: str | None = None
except Exception as _pe:
    _prs_config = _prs_prompts = _prs_generador_html = _prs_workshop = None
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
    """Alias local — delega en utils.slugify."""
    return slugify(nombre)


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
    db.registrar_input(asignatura_id, tipo, nombre_fichero, ruta_disco, RUTA_DB)


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

    Cada subtema puede incluir horas, evidencia, origen, fuente y es_fallback cuando
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
                       (tema_id, nombre, orden, horas, evidencia, origen, es_fallback, fuente)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tema_id,
                        subtema["nombre"],
                        subtema.get("orden", 0),
                        subtema.get("horas", 0.0),
                        subtema.get("evidencia", ""),
                        subtema.get("origen", "Detectado"),
                        subtema.get("es_fallback", 0),
                        subtema.get("fuente", ""),
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
    "org_modo_prompt_libre": False,
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
        except Exception as exc:
            _log.warning("BD: no se pudo registrar %s (%s)", archivo.name, exc)
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

    # Estado estructurado para la edición manual.
    bloques = _org_parser.parsear_bloques_desde_markdown(resultado)
    archivos = st.session_state.get("org_ultimos_archivos_teoria", [])
    candidatos = st.session_state.get("org_subtemas_detectados", [])
    if archivos:
        if not candidatos:
            _, candidatos = _org_cargar_candidatos_material_desde_disco(asignatura_id)
        bloques = _org_parser.enriquecer_bloques_con_evidencia_detectada(
            bloques, candidatos, archivos
        )
    for i, bloque in enumerate(bloques):
        if not bloque.get("archivo_origen"):
            bloque["archivo_origen"] = _org_resolver_archivo_bloque(
                bloque["nombre"], archivos, i
            )
    st.session_state["org_organizacion_bloques"] = bloques
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
    candidatos_precalculados: list[list[dict]] | None = None,
) -> list[list[dict]] | None:
    """Guía docente primero (modo libre); lista cerrada del material solo sin guía."""
    return _org_parser.construir_subtemas_confirmados(
        texto_guia,
        textos_teoria,
        archivos_teoria,
        archivos_bytes,
        candidatos_precalculados=candidatos_precalculados,
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
            cands_raw = _org_parser.extraer_candidatos_con_evidencia(
                texto, nombre, archivo_bytes
            )
            cands = [
                {
                    "nombre": c["nombre"],
                    "evidencia": c["evidencia"],
                    "origen": "Detectado",
                    "fuente": c.get("fuente", ""),
                }
                for c in cands_raw
            ]
        except Exception as exc:
            _log.warning("Extracción candidatos fallida para %s: %s", nombre, exc)
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


def _org_etiqueta_fuente(sub: dict) -> str:
    """Etiqueta legible de la estrategia de detección de un subtema."""
    if sub.get("manual"):
        return _org_parser.etiqueta_fuente("manual")
    if sub.get("es_fallback"):
        return _org_parser.etiqueta_fuente("fallback")
    fuente = (sub.get("fuente") or "").strip()
    if fuente:
        return _org_parser.etiqueta_fuente(fuente)
    origen = (sub.get("origen") or "").strip()
    if origen and origen.lower() not in {"detectado", "detectado (aprox.)"}:
        return origen
    return _org_parser.etiqueta_fuente("modelo")


def _org_render_panel_deteccion() -> None:
    """Muestra las señales deterministas detectadas en cada material."""
    archivos = st.session_state.get("org_ultimos_archivos_teoria", [])
    candidatos = st.session_state.get("org_subtemas_detectados", [])
    modo_libre = st.session_state.get("org_modo_prompt_libre", False)
    with st.expander("🔬 Señales de detección estructural", expanded=False):
        if modo_libre:
            st.caption(
                "Modo libre (guía docente con bloques): el modelo estructura subtemas, "
                "pero la detección determinista se ejecutó para enriquecer evidencia al confirmar."
            )
        if not archivos:
            st.caption("Aún no hay materiales de teoría procesados en esta sesión.")
            return
        for idx, nombre_arch in enumerate(archivos):
            lista = candidatos[idx] if idx < len(candidatos) else []
            st.markdown(f"**{nombre_arch}** — {len(lista)} candidato(s)")
            if not lista:
                st.caption("Sin señales estructurales detectadas en este material.")
                continue
            for cand in lista:
                fuente = _org_parser.etiqueta_fuente(cand.get("fuente", ""))
                ev = cand.get("evidencia", "—")
                st.text(f"• {cand.get('nombre', '')}  [{fuente}]  {ev}")


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
                candidatos_detectados = _org_parser.detectar_candidatos_por_material(
                    textos_teoria, archivos_teoria, archivos_teoria_bytes
                )
                st.session_state["org_subtemas_detectados"] = candidatos_detectados
                st.session_state["org_modo_prompt_libre"] = _org_parser.modo_prompt_libre(
                    texto_guia
                )
                subtemas_confirmados = _org_build_subtemas_confirmados(
                    texto_guia,
                    textos_teoria,
                    archivos_teoria,
                    archivos_teoria_bytes,
                    candidatos_precalculados=candidatos_detectados,
                )
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
                "SELECT id, nombre, horas, bloque, orden, input_id FROM temas "
                "WHERE asignatura_id = ? ORDER BY orden",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_materiales_teoria(asignatura_id: int) -> list[dict]:
    """PDFs/PPTX de teoría registrados para la asignatura (orden alfabético)."""
    return sorted(
        (
            i for i in db.listar_inputs_asignatura(asignatura_id, RUTA_DB)
            if i["tipo"] == "material_teoria"
        ),
        key=lambda i: (i.get("nombre_fichero") or "").lower(),
    )


def _db_cnt_get_subbloques(tema_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre, orden, horas, evidencia, origen, es_fallback, fuente "
                "FROM subbloques WHERE tema_id = ? ORDER BY orden",
                (tema_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_contenido_tema(tema_id: int) -> dict | None:
    return db.get_contenido_tema(tema_id, RUTA_DB)


def _cnt_extraer_headings(markdown: str) -> list[str]:
    """Extrae títulos ##, ### y #### del markdown para anclar visualizaciones."""
    return [
        m.group(1).strip()
        for m in re.finditer(r"^#{2,4}\s+(.+)$", markdown or "", re.MULTILINE)
    ]


def _cnt_extraer_figuras(markdown: str) -> list[str]:
    """Extrae marcadores [FIGURA: ...] del markdown como opciones de ancla."""
    vistos: set[str] = set()
    result: list[str] = []
    for m in re.finditer(r"\[FIGURA:\s*([^\]]+)\]", markdown or ""):
        desc = m.group(1).strip()
        key = desc.lower()
        if key not in vistos:
            vistos.add(key)
            result.append(f"[FIGURA: {desc}]")
    return result


def _cnt_markdown_visible(ct: dict | None) -> str:
    if not ct:
        return ""
    return (ct.get("markdown_final") or ct.get("markdown_borrador") or "").strip()


# =============================================================================
# Lógica de curación por bloque — Agente Contenido
# =============================================================================


@st.cache_data(show_spinner=False)
def _cnt_extract_text_cached(ruta: str, mtime_ns: int) -> str:
    """Extracción cacheada; ``mtime_ns`` invalida la caché si el fichero cambia."""
    if _cnt_extractor is None:
        return ""
    return (_cnt_extractor.extract_text(ruta) or "").strip()


def _cnt_leer_material(ruta: str) -> str:
    """Texto de un PDF/PPTX en disco, con caché entre reruns de Streamlit."""
    if not os.path.exists(ruta):
        return ""
    try:
        mtime_ns = os.stat(ruta).st_mtime_ns
        return _cnt_extract_text_cached(ruta, mtime_ns)
    except Exception as exc:
        _log.warning("Extracción texto fallida para %s: %s", ruta, exc)
        return ""


def _cnt_extraer_texto_bloque(rutas_material: list[str]) -> str:
    """Concatena el texto extraído de todos los materiales del bloque."""
    partes: list[str] = []
    for ruta in rutas_material:
        texto = _cnt_leer_material(ruta)
        if texto:
            partes.append(texto)
    return "\n\n".join(partes)


def _cnt_numero_bloque(bloque_label: str) -> int | None:
    """Extrae el número de «Bloque N» del etiquetado del Organizador."""
    m = re.search(r"bloque\s*(\d+)", (bloque_label or ""), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _cnt_ruta_markdown_disco(slug: str, bloque_label: str) -> str:
    """Ruta de exportación: ``data/{slug}/outputs/contenido/bloque-N.md``."""
    n = _cnt_numero_bloque(bloque_label)
    if n is not None:
        nombre = f"bloque-{n}.md"
    else:
        nombre = f"bloque-{_slugify(bloque_label or 'sin-numero')}.md"
    dir_out = os.path.join(RAIZ_MONOREPO, "data", slug, "outputs", "contenido")
    os.makedirs(dir_out, exist_ok=True)
    return os.path.join(dir_out, nombre)


def _cnt_exportar_markdown_disco(slug: str, bloque_label: str, markdown: str) -> str | None:
    """Copia el markdown curado a disco (además de la BD)."""
    texto = (markdown or "").strip()
    if not texto:
        return None
    ruta = _cnt_ruta_markdown_disco(slug, bloque_label)
    try:
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(texto)
        return ruta
    except OSError:
        return None


def _cnt_sugerir_material_id(tema: dict, materiales: list[dict]) -> int | None:
    """Preselección del material: convención Bloque N → Tema N, luego vínculo guardado."""
    if not materiales:
        return None
    ids = {m["id"] for m in materiales}
    n = _cnt_numero_bloque(tema.get("bloque", ""))
    if n is not None:
        for mat in materiales:
            stem = Path(mat["nombre_fichero"]).stem
            if re.search(rf"(?:tema|bloque|unidad)\s*[_-]?\s*{n}$", stem, re.IGNORECASE):
                return mat["id"]
            if stem.strip() == str(n):
                return mat["id"]
    guardado = tema.get("input_id")
    if guardado in ids:
        return guardado
    return materiales[0]["id"]


def _cnt_etiqueta_material(mat: dict) -> str:
    nombre = mat.get("nombre_fichero") or "?"
    if fichero_existe(mat.get("ruta_disco") or ""):
        return nombre
    return f"{nombre} (no encontrado en disco)"


def _cnt_curar_bloque(
    tema_nombre: str,
    rutas_material: list[str],
    nombre_archivo: str = "",
) -> tuple[str, float | None, list[dict]]:
    """Genera el markdown curado del bloque completo (extracción fiel, sin densidad horaria)."""
    texto = _cnt_extraer_texto_bloque(rutas_material)
    if not texto.strip():
        return "", None, []

    if not nombre_archivo and rutas_material:
        nombre_archivo = Path(rutas_material[0]).name
    if not nombre_archivo:
        nombre_archivo = f"{tema_nombre}.md"

    max_w = getattr(_cnt_config, "MAX_WORKERS", 5)
    _items, markdown, reporte = _cnt_pipeline.procesar_bloque(
        texto=texto,
        nombre_bloque=tema_nombre,
        nombre_archivo=nombre_archivo,
        horas=None,
        max_workers=max_w,
    )
    if not markdown.strip():
        return "", None, []

    scores = [
        r["coverage_score"]
        for r in (reporte.get("fidelity") or [])
        if r.get("coverage_score") is not None
    ]
    fidelidad: float | None = round(sum(scores) / len(scores), 3) if scores else None
    return markdown, fidelidad, reporte.get("fidelity") or []


def _cnt_generar_bloque_desde_material(
    asignatura_id: int,
    tema_id: int,
    tema_nombre: str,
    material_sel: dict,
    slug: str,
    bloque_label: str,
    *,
    regenerar: bool = False,
) -> None:
    """Curación del bloque a partir del material elegido y persistencia en BD."""
    ruta_material = material_sel.get("ruta_disco") or ""
    nombre_archivo = material_sel.get("nombre_fichero") or ""
    if not fichero_existe(ruta_material):
        st.error(
            f"El archivo **{nombre_archivo}** no está en disco. "
            "Vuelve a subirlo en el **Agente Organizador**."
        )
        return

    umbral = float(getattr(_cnt_config, "FIDELITY_THRESHOLD", 0.85))
    ejecucion_id = _db_crear_ejecucion_contenido(asignatura_id)
    accion = "Regenerando" if regenerar else "Curando"
    with st.status(f"{accion} bloque: {tema_nombre}…", expanded=True) as status:
        try:
            md_bloque, fidelidad, _ = _cnt_curar_bloque(
                tema_nombre=tema_nombre,
                rutas_material=[ruta_material],
                nombre_archivo=nombre_archivo,
            )
            if not md_bloque.strip():
                raise ValueError("No se pudo extraer ni curar contenido del material.")
            db.actualizar_tema_input_id(tema_id, material_sel["id"], RUTA_DB)
            if regenerar:
                db.regenerar_contenido_tema_borrador(tema_id, md_bloque, RUTA_DB)
            else:
                db.upsert_contenido_tema_borrador(tema_id, md_bloque, RUTA_DB)
            _cnt_exportar_markdown_disco(slug, bloque_label, md_bloque)
            if fidelidad is not None and fidelidad < umbral:
                _db_registrar_validacion(
                    ejecucion_id=ejecucion_id,
                    tipo="fidelidad_baja",
                    descripcion=f"bloque '{tema_nombre}' con fidelidad media {fidelidad}",
                    valor_afectado=fidelidad,
                    bloqueante=0,
                )
            label = f"✅ Borrador listo: {tema_nombre}"
            if fidelidad is not None and fidelidad < umbral:
                label += f" (fidelidad {fidelidad} < {umbral})"
            status.update(label=label, state="complete")
            _db_actualizar_ejecucion(ejecucion_id, "completado")
        except Exception as err:
            _db_actualizar_ejecucion(ejecucion_id, "error")
            status.update(label="❌ Error", state="error")
            st.error(f"Error al generar el bloque: {err}")
            return

    st.session_state.pop(f"cnt_md_{tema_id}", None)
    st.rerun()


def _cnt_etiqueta_modificacion(ct: dict | None) -> str:
    if ct is None:
        return ""
    pct = ct.get("porcentaje_editado")
    if pct is None or pct == 0:
        return "sin modificaciones"
    return f"modificado ({pct}%)"


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

    slug = _slugify(asignatura)

    if st.session_state.get("cnt_asignatura") != asignatura:
        for k in [k for k in list(st.session_state.keys()) if k.startswith("cnt_")]:
            del st.session_state[k]
        st.session_state["cnt_asignatura"] = asignatura

    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos para esta asignatura. "
            "Ejecuta primero el **Agente Organizador** y pulsa "
            "**Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    if "cnt_tema_idx" not in st.session_state:
        st.session_state["cnt_tema_idx"] = 0
    estados_map = _estados_bloques_asignatura(asignatura_id)
    tema_idx = render_bloque_chips(temas, st.session_state["cnt_tema_idx"], estados_map, "cnt")
    st.session_state["cnt_tema_idx"] = tema_idx
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]

    materiales_teoria = _db_cnt_get_materiales_teoria(asignatura_id)
    material_sel: dict | None = None
    if materiales_teoria:
        sugerido_id = _cnt_sugerir_material_id(tema, materiales_teoria)
        ids = [m["id"] for m in materiales_teoria]
        default_idx = ids.index(sugerido_id) if sugerido_id in ids else 0
        mat_idx = st.selectbox(
            "Material de teoría para este bloque:",
            options=range(len(materiales_teoria)),
            format_func=lambda i: _cnt_etiqueta_material(materiales_teoria[i]),
            index=default_idx,
            key=f"cnt_material_{tema_id}",
            help=(
                "Confirma qué PDF o PPTX corresponde a este bloque antes de generar. "
                "La selección se guarda al generar el borrador."
            ),
        )
        material_sel = materiales_teoria[mat_idx]
    else:
        st.warning(
            "No hay materiales de teoría registrados. "
            "Sube los archivos en el **Agente Organizador** primero."
        )

    subbloques = _db_cnt_get_subbloques(tema_id)
    ct = _db_cnt_get_contenido_tema(tema_id)
    estado = ct["estado"] if ct else "pendiente"
    texto_md = _cnt_markdown_visible(ct)
    borrador_ia = (ct.get("markdown_borrador") or "") if ct else ""
    if ct and texto_md:
        ruta_export = _cnt_ruta_markdown_disco(slug, tema.get("bloque", ""))
        if not fichero_existe(ruta_export):
            _cnt_exportar_markdown_disco(slug, tema.get("bloque", ""), texto_md)

    prog = db.get_progreso_bloque(tema_id, RUTA_DB)

    col_cov, col_ed = st.columns([0.9, 2.1])

    with col_cov:
        with st.container(gap=None, key="sd_card_cov_panel"):
            st.markdown(
                '<div style="font-size:12.5px;font-weight:600;margin-bottom:3px;">Cobertura curricular</div>'
                '<div style="font-size:11px;color:#6B7A8D;margin-bottom:14px;">'
                'Apartados del Organizador presentes en el contenido curado.</div>',
                unsafe_allow_html=True,
            )
            if subbloques and texto_md:
                cobertura = _cnt_coverage.verificar_cobertura(texto_md, subbloques)
                cubiertos = sum(1 for c in cobertura if c["cubierto"])
                pct_cov = round(cubiertos / max(len(cobertura), 1) * 100)
                st.markdown(cobertura_bar_html(pct_cov), unsafe_allow_html=True)
                items_html = "".join(
                    cobertura_item_html(c["nombre"], c["cubierto"], c["detalle"])
                    for c in cobertura
                )
                st.markdown(items_html, unsafe_allow_html=True)
            elif subbloques:
                for sub in subbloques:
                    st.markdown(
                        cobertura_item_html(sub["nombre"], False, ""),
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Sin subtemas del Organizador.")

    with col_ed:
        if ct is None:
            if not material_sel:
                pass
            elif not fichero_existe(material_sel.get("ruta_disco") or ""):
                st.error(
                    f"El archivo **{material_sel['nombre_fichero']}** no está en disco. "
                    "Vuelve a subirlo en el **Agente Organizador**."
                )
            else:
                st.markdown("**Generar markdown del bloque**")
                st.caption(
                    f"Se procesará **{material_sel['nombre_fichero']}** para el bloque "
                    f"«{tema_nombre}». Comprueba que la selección es correcta."
                )
                if st.button(
                    "Generar borrador del bloque",
                    type="primary",
                    use_container_width=True,
                    key="cnt_btn_generar_bloque",
                ):
                    _cnt_generar_bloque_desde_material(
                        asignatura_id,
                        tema_id,
                        tema_nombre,
                        material_sel,
                        slug,
                        tema.get("bloque", ""),
                        regenerar=False,
                    )

        if ct is not None:
            _ETIQUETAS = {
                "pendiente": "⚪ Sin borrador",
                "generado": "🤖 Borrador generado por IA",
                "editado": "✏️ Editado por el profesor",
                "aprobado": "✅ Aprobado",
            }
            etiqueta = _ETIQUETAS.get(estado, estado)
            if estado == "aprobado":
                nota = ct.get("puntuacion_profesor")
                mod = _cnt_etiqueta_modificacion(ct)
                etiqueta = f"✅ Aprobado — {nota}/10 — {mod}" if nota else f"✅ Aprobado — {mod}"

            ta_key = f"cnt_md_{tema_id}"
            if ta_key not in st.session_state:
                st.session_state[ta_key] = texto_md or borrador_ia
            texto_actual = st.session_state.get(ta_key, texto_md or "")

            ratio_prev = difflib.SequenceMatcher(
                None, borrador_ia, (texto_actual or "").strip()
            ).ratio()
            pct_prev = round((1 - ratio_prev) * 100, 1)

            tab_hdr_l, tab_hdr_r = st.columns([3, 1])
            with tab_hdr_r:
                if pct_prev > 0:
                    st.markdown(
                        f'<span class="sd-mod-badge">● Modificado {pct_prev}% vs. borrador IA</span>',
                        unsafe_allow_html=True,
                    )

            with st.container(gap=None, key="sd_card_editor"):
                tab_div, tab_prev, tab_md = st.tabs(["Dividido", "Vista previa", "Markdown"])
                with tab_div:
                    c_src, c_render = st.columns(2)
                    with c_src:
                        if estado == "aprobado":
                            st.text_area(
                                "Fuente",
                                value=texto_actual,
                                height=400,
                                disabled=True,
                                key=f"cnt_view_src_{tema_id}",
                                label_visibility="collapsed",
                            )
                        else:
                            st.text_area(
                                "Fuente",
                                key=ta_key,
                                height=400,
                                label_visibility="collapsed",
                            )
                            texto_actual = st.session_state.get(ta_key, texto_md)
                    with c_render:
                        with st.container(gap=None, key=f"sd_render_box_{tema_id}"):
                            st.markdown(texto_actual or "_Sin contenido_")
                with tab_prev:
                    st.markdown(st.session_state.get(ta_key, texto_actual) or "_Sin contenido_")
                with tab_md:
                    if estado == "aprobado":
                        st.text_area(
                            "Markdown",
                            value=texto_actual,
                            height=450,
                            disabled=True,
                            key=f"cnt_view_{tema_id}",
                            label_visibility="collapsed",
                        )
                    else:
                        st.code(
                            st.session_state.get(ta_key, texto_actual) or "",
                            language="markdown",
                        )
                        texto_actual = st.session_state.get(ta_key, texto_md)

                if estado == "aprobado":
                    nota = ct.get("puntuacion_profesor") or "—"
                    with st.container(gap=None, key=f"sd_btn_aprobar_{tema_id}"):
                        st.button(
                            f"✓ Aprobado {nota}/10",
                            disabled=True,
                            use_container_width=True,
                            type="secondary",
                            key=f"cnt_aprobado_{tema_id}",
                        )
                else:
                    f_val, f_btn = st.columns([1.2, 1])
                    with f_val:
                        puntuacion = st.slider(
                            "Valoración",
                            min_value=1,
                            max_value=10,
                            value=7,
                            key=f"cnt_valoracion_{tema_id}",
                        )
                        st.markdown(
                            f'<span style="font-size:14px;font-weight:700;color:#0C447C;">'
                            f'{puntuacion}/10</span>',
                            unsafe_allow_html=True,
                        )
                    with f_btn:
                        b1, b2, b3 = st.columns([1, 1, 1])
                        with b1:
                            if st.button(
                                "Guardar edición",
                                key=f"cnt_btn_guardar_{tema_id}",
                                type="secondary",
                                use_container_width=True,
                            ):
                                db.guardar_contenido_tema_edicion(
                                    tema_id, texto_actual.strip(), pct_prev, RUTA_DB
                                )
                                _cnt_exportar_markdown_disco(
                                    slug, tema.get("bloque", ""), texto_actual.strip()
                                )
                                st.rerun()
                        with b2:
                            if st.button(
                                "Regenerar con IA",
                                key=f"cnt_btn_regenerar_{tema_id}",
                                type="secondary",
                                use_container_width=True,
                                disabled=not material_sel,
                            ):
                                if material_sel:
                                    _cnt_generar_bloque_desde_material(
                                        asignatura_id,
                                        tema_id,
                                        tema_nombre,
                                        material_sel,
                                        slug,
                                        tema.get("bloque", ""),
                                        regenerar=True,
                                    )
                        with b3:
                            with st.container(gap=None, key=f"sd_btn_aprobar_{tema_id}"):
                                if st.button(
                                    "Aprobar contenido",
                                    key=f"cnt_btn_aprobar_{tema_id}",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    if texto_actual.strip():
                                        db.aprobar_contenido_tema(
                                            tema_id,
                                            texto_actual.strip(),
                                            pct_prev,
                                            puntuacion,
                                            RUTA_DB,
                                        )
                                        _cnt_exportar_markdown_disco(
                                            slug, tema.get("bloque", ""), texto_actual.strip()
                                        )
                                        st.rerun()

            if material_sel:
                with st.expander("Material de teoría"):
                    st.caption(f"**{material_sel['nombre_fichero']}**")


# =============================================================================
# Helpers de base de datos — Presentación (taller interactivo)
# =============================================================================


def _db_cnt_get_rutas_material(tema_id: int) -> list[str]:
    """Ruta del PDF/PPTX vinculado al bloque temático (``temas.input_id``)."""
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


def _prs_extraer_texto_material(rutas: list[str]) -> tuple[str, list[str]]:
    """Texto del material original para contexto del taller (truncado)."""
    partes: list[str] = []
    fallos: list[str] = []
    for ruta in rutas:
        if not os.path.exists(ruta):
            fallos.append(os.path.basename(ruta))
            continue
        texto = _cnt_leer_material(ruta)
        if texto:
            partes.append(texto)
        else:
            fallos.append(os.path.basename(ruta))
    texto = "\n\n".join(partes)
    return texto[:8000], fallos


def _prs_taller_key(tema_id: int) -> str:
    return f"prs_taller_{tema_id}"


def _prs_init_taller(tema_id: int) -> None:
    key = _prs_taller_key(tema_id)
    if key not in st.session_state:
        st.session_state[key] = {
            "viz_id": None,
            "html": "",
            "slug": "",
            "titulo": "",
            "historial": [],
        }


def _prs_get_markdown_bloque(tema_id: int, tema_nombre: str) -> str:
    ct = _db_cnt_get_contenido_tema(tema_id)
    md = _cnt_markdown_visible(ct)
    if md and not md.lstrip().startswith("#"):
        return f"# {tema_nombre}\n\n{md}"
    return md or f"# {tema_nombre}"


# =============================================================================
# Vista Presentación — taller iterativo por bloque
# =============================================================================

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

    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos. Ejecuta primero el **Agente Organizador** "
            "y pulsa **Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    if "prs_tema_idx" not in st.session_state:
        st.session_state["prs_tema_idx"] = 0
    estados_map = _estados_bloques_asignatura(asignatura_id)
    tema_idx = render_bloque_chips(temas, st.session_state["prs_tema_idx"], estados_map, "prs")
    st.session_state["prs_tema_idx"] = tema_idx
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]

    ct = _db_cnt_get_contenido_tema(tema_id)
    md_bloque = _prs_get_markdown_bloque(tema_id, tema_nombre)
    tiene_md = len(md_bloque.splitlines()) > 1

    if not tiene_md:
        st.warning(
            "Genera y aprueba el contenido del bloque en la vista **Contenido** primero."
        )
        return

    rutas = _db_cnt_get_rutas_material(tema_id)
    texto_original = None
    fallos_material: list[str] = []
    if rutas:
        texto_original, fallos_material = _prs_extraer_texto_material(rutas)
        if fallos_material:
            st.warning(
                "No se pudo extraer texto de: "
                + ", ".join(f"**{f}**" for f in fallos_material)
                + ". El taller usará solo el markdown curado."
            )
    headings = _cnt_extraer_headings(md_bloque)
    figuras_ancla = _cnt_extraer_figuras(md_bloque)

    aprobadas = db.listar_visualizaciones_aprobadas(tema_id, RUTA_DB)

    if st.session_state.pop("topbar_nav_export", None):
        st.info(
            "La exportación es **por bloque**. Usa los controles del panel derecho "
            "o la sección inferior para generar PDF o presentación HTML."
        )

    col_main, col_rail = st.columns([2.5, 1])

    with col_main:
        _prs_init_taller(tema_id)
        taller = st.session_state[_prs_taller_key(tema_id)]

        if st.button("Nueva visualización", key=f"prs_nueva_{tema_id}", type="secondary"):
            st.session_state[_prs_taller_key(tema_id)] = {
                "viz_id": None, "html": "", "slug": "", "titulo": "", "historial": [],
            }
            st.rerun()

        viz_id = taller.get("viz_id")
        if viz_id:
            row = db.get_visualizacion(viz_id, RUTA_DB)
            if row and row.get("estado") == "borrador":
                taller["html"] = row.get("html_fragment") or taller.get("html", "")
                taller["titulo"] = row.get("titulo") or taller.get("titulo", "")

        html_preview = taller.get("html") or ""
        if html_preview:
            with st.container(gap=None, key="sd_card_preview"):
                st.markdown(
                    '<div class="sd-preview-bar">'
                    '<span class="sd-preview-dot r"></span>'
                    '<span class="sd-preview-dot a"></span>'
                    '<span class="sd-preview-dot v"></span>'
                    '<span style="font-size:11px;color:#6B7A8D;margin-left:6px;">'
                    'preview · visualización interactiva</span>'
                    '<span style="margin-left:auto;font-size:10px;color:#8693A3;">'
                    'Chart.js + MathJax</span></div>',
                    unsafe_allow_html=True,
                )
                preview_page = _prs_generador_html.envolver_preview_taller(html_preview)
                st.components.v1.html(preview_page, height=420, scrolling=True)

        with st.container(gap=None, key="sd_card_composer"):
            prompt_key = f"prs_prompt_{tema_id}"
            if prompt_key not in st.session_state:
                st.session_state[prompt_key] = ""

            with st.container(gap=None, key=f"sd_composer_row_{tema_id}"):
                c_prompt, c_actions = st.columns([4.2, 1])
                with c_prompt:
                    instruccion = st.text_area(
                        "Describe la visualización:",
                        key=prompt_key,
                        height=64,
                        placeholder="Describe un ajuste a la visualización…",
                        label_visibility="collapsed",
                    )
                with c_actions:
                    refinar = st.button(
                        "Refinar →",
                        use_container_width=True,
                        key=f"prs_ref_preview_{tema_id}",
                        disabled=not taller.get("html"),
                        type="secondary",
                    )
                    if not taller.get("html"):
                        generar = st.button(
                            "Generar preview",
                            type="primary",
                            use_container_width=True,
                            key=f"prs_gen_preview_{tema_id}",
                        )
                    else:
                        generar = False

            if generar and instruccion.strip():
                with st.status("Generando visualización…", expanded=True) as status:
                    try:
                        titulo_viz = instruccion.strip()[:80]
                        slug, html_frag = _prs_workshop.generar_desde_instruccion(
                            instruccion.strip(),
                            md_bloque,
                            titulo=titulo_viz,
                            texto_original=texto_original,
                        )
                        import json
                        historial = [{"rol": "profesor", "texto": instruccion.strip()}]
                        if taller.get("viz_id"):
                            db.actualizar_visualizacion_borrador(
                                taller["viz_id"], html_frag, json.dumps(historial), titulo_viz, RUTA_DB
                            )
                            vid = taller["viz_id"]
                        else:
                            vid = db.insertar_visualizacion_borrador(
                                tema_id, titulo_viz, instruccion.strip(),
                                json.dumps(historial), html_frag, RUTA_DB,
                            )
                        st.session_state[_prs_taller_key(tema_id)] = {
                            "viz_id": vid, "html": html_frag, "slug": slug,
                            "titulo": titulo_viz, "historial": historial,
                        }
                        status.update(label="Preview generado", state="complete")
                    except Exception as err:
                        status.update(label="Error", state="error")
                        st.error(str(err))
                st.rerun()

            if refinar and instruccion.strip() and taller.get("html"):
                with st.status("Refinando visualización…", expanded=True) as status:
                    try:
                        import json
                        slug = taller.get("slug") or "viz"
                        html_frag = _prs_workshop.refinar_html(
                            taller["html"], instruccion.strip(), slug
                        )
                        historial = list(taller.get("historial") or [])
                        historial.append({"rol": "profesor", "texto": instruccion.strip()})
                        vid = taller["viz_id"]
                        if vid:
                            db.actualizar_visualizacion_borrador(
                                vid, html_frag, json.dumps(historial), None, RUTA_DB
                            )
                        st.session_state[_prs_taller_key(tema_id)] = {
                            **taller, "html": html_frag, "historial": historial,
                        }
                        status.update(label="Preview actualizado", state="complete")
                    except Exception as err:
                        status.update(label="Error", state="error")
                        st.error(str(err))
                st.rerun()

            if html_preview:
                opciones_ancla = headings + figuras_ancla if (headings or figuras_ancla) else []
                if "(final del bloque)" not in opciones_ancla:
                    opciones_ancla = opciones_ancla + ["(final del bloque)"]
                sugerida = _prs_workshop.sugerir_seccion_ancla(
                    taller.get("titulo") or instruccion, opciones_ancla
                )
                idx_sug = (
                    opciones_ancla.index(sugerida)
                    if sugerida in opciones_ancla
                    else len(opciones_ancla) - 1
                )
                ancla = st.selectbox(
                    "Ancla:",
                    options=opciones_ancla,
                    index=idx_sug,
                    key=f"prs_ancla_{tema_id}",
                )
                ancla_val = "" if ancla == "(final del bloque)" else ancla
                if st.button(
                    "Aprobar y anclar",
                    type="primary",
                    key=f"prs_aprobar_viz_{tema_id}",
                    use_container_width=True,
                ):
                    vid = taller.get("viz_id")
                    if vid:
                        db.aprobar_visualizacion(vid, ancla_val, RUTA_DB)
                    st.session_state[_prs_taller_key(tema_id)] = {
                        "viz_id": None, "html": "", "slug": "", "titulo": "", "historial": [],
                    }
                    st.session_state[prompt_key] = ""
                    st.success("Visualización aprobada.")
                    st.rerun()

    with col_rail:
        with st.container(gap=None, key="sd_card_rail_viz"):
            st.markdown(
                '<div style="font-size:13px;font-weight:600;margin-bottom:12px;">'
                "Visualizaciones ancladas</div>",
                unsafe_allow_html=True,
            )
            if aprobadas:
                for v in aprobadas:
                    ancla = v.get("seccion_ancla") or "(final del bloque)"
                    st.markdown(
                        f'<div class="sd-rail-item"><div class="tit">{html.escape(v["titulo"])}</div>'
                        f'<div class="ancla">↳ {html.escape(ancla)}</div></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("Ninguna todavía.")

        historial = st.session_state.get(_prs_taller_key(tema_id), {}).get("historial") or []
        if historial:
            with st.container(gap=None, key="sd_card_rail_iter"):
                st.markdown(
                    '<div style="font-size:13px;font-weight:600;margin-bottom:10px;">Iteraciones</div>',
                    unsafe_allow_html=True,
                )
                for i, h in enumerate(historial, 1):
                    activa = i == len(historial)
                    clase = "sd-iter activa" if activa else "sd-iter"
                    texto_h = (h.get("texto") or "")[:60]
                    st.markdown(
                        f'<div class="{clase}">{i}. {html.escape(texto_h)}</div>',
                        unsafe_allow_html=True,
                    )

        with st.container(gap=None, key="sd_card_rail_export"):
            st.markdown("**Exportar presentación del bloque**")
            if st.button(
                "Generar PDF del bloque",
                key=f"prs_pdf_{tema_id}",
                use_container_width=True,
                type="secondary",
            ):
                with st.status("Generando PDF…", expanded=True) as _st_pdf:
                    try:
                        _pdf_bytes = _prs_generador_pdf.generar_pdf(md_bloque, titulo=tema_nombre)
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

            n_aprobadas = len(aprobadas)
            if st.button(
                "Generar presentación completa",
                key=f"prs_presentacion_{tema_id}",
                use_container_width=True,
                type="secondary",
            ):
                with st.status("Generando presentación…", expanded=True) as _st_pres:
                    try:
                        fragmentos = db.listar_visualizaciones_aprobadas(tema_id, RUTA_DB)
                        if fragmentos:
                            st.write(
                                f"Integrando {len(fragmentos)} visualización(es) aprobada(s)…"
                            )
                            _html_pres = (
                                _prs_generador_presentacion.generar_presentacion_con_fragmentos(
                                    md_bloque, fragmentos, tema_nombre
                                )
                            )
                        else:
                            st.write("Sin visualizaciones — solo contenido teórico…")
                            _html_pres = _prs_generador_presentacion.generar_presentacion(
                                md_bloque, [], tema_nombre, verbose=False
                            )
                        st.session_state[f"prs_html_pres_{tema_id}"] = _html_pres.encode("utf-8")
                        _st_pres.update(label="Presentación generada", state="complete")
                    except Exception as _e:
                        _st_pres.update(label="Error al generar la presentación", state="error")
                        st.error(str(_e))
                st.rerun()

            if n_aprobadas == 0:
                st.caption("Puedes exportar solo teoría o aprobar visualizaciones antes.")
            if st.session_state.get(f"prs_html_pres_{tema_id}"):
                st.download_button(
                    "Descargar presentación completa",
                    data=st.session_state[f"prs_html_pres_{tema_id}"],
                    file_name=f"{_slugify(tema_nombre)}_bloque_presentacion.html",
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
                    sub["fuente"] = "manual"
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
                        type="secondary",
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

            h1, h2, h3, h4, h5 = st.columns([3, 2.2, 1.1, 0.55, 0.55])
            h1.markdown("**Subtema**")
            h2.markdown("**Evidencia**")
            h3.markdown("**Estrategia**")
            if editable:
                h4.markdown("**✓**")
                h5.markdown("")

            for idx_s, sub in enumerate(bloque.get("subtemas", [])):
                r1, r2, r3, r4, r5 = st.columns([3, 2.2, 1.1, 0.55, 0.55])
                evidencia = _org_format_evidencia(sub, archivo_bloque)
                estrategia = _org_etiqueta_fuente(sub)
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
                        extra = ""
                        if sub.get("es_fallback"):
                            extra = " _(fallback)_"
                        elif sub.get("origen") == "Detectado (aprox.)":
                            extra = " _(aprox.)_"
                        st.markdown(f"{sub['nombre']}{marca}{extra}")
                with r2:
                    st.caption(evidencia)
                with r3:
                    fuente_raw = (sub.get("fuente") or "").strip()
                    if fuente_raw == "titulo_visual":
                        st.caption(f"🟠 {estrategia}")
                    elif fuente_raw in {"numeracion", "titulo_slide"}:
                        st.caption(f"🟢 {estrategia}")
                    elif fuente_raw in {"fallback", ""} and sub.get("es_fallback"):
                        st.caption(f"🔴 {estrategia}")
                    else:
                        st.caption(estrategia)
                if editable:
                    with r4:
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
                    with r5:
                        if st.button(
                            "✕",
                            key=f"org_del_sub_{idx_b}_{idx_s}_{iter_key}_{sub_rev}",
                            help="Eliminar subtema",
                            type="secondary",
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
                    if st.button("+ Añadir", key=f"org_btn_ns_{idx_b}_{ctr_s}", type="secondary"):
                        _org_sync_widgets_a_bloques(iter_key)
                        nombre_ns = st.session_state.get(f"org_ns_nombre_{idx_b}_{ctr_s}", "").strip()
                        if nombre_ns:
                            st.session_state["org_organizacion_bloques"][idx_b]["subtemas"].append({
                                "nombre": nombre_ns,
                                "evidencia": "Manual (profesor)",
                                "origen": "Manual",
                                "fuente": "manual",
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
            if st.button("+ Añadir bloque", key=f"org_btn_nb_{ctr_b}", type="secondary"):
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

    st.markdown(
        '<p class="sd-vista-titulo">Distribución temática extraída</p>'
        '<p class="sd-vista-desc">Revisa, edita y aprueba cada subtema. '
        'Confirma para poblar la base de datos curricular.</p>',
        unsafe_allow_html=True,
    )

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
        _org_render_panel_deteccion()

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


def _db_resumen_kpis(asignatura_id: int) -> dict:
    """KPIs del dashboard Resumen según handoff."""
    conn = db.get_connection(RUTA_DB)
    try:
        n_bloques = conn.execute(
            "SELECT COUNT(*) FROM temas WHERE asignatura_id = ?", (asignatura_id,)
        ).fetchone()[0]
        horas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM temas WHERE asignatura_id = ?",
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
    finally:
        conn.close()
    prog = db.get_progreso_asignatura(asignatura_id, RUTA_DB)
    return {
        "bloques": n_bloques,
        "aprobados": prog["aprobados"],
        "total": prog["total"],
        "horas": horas,
        "visualizaciones": n_viz,
    }


def _db_mapa_curricular(asignatura_id: int) -> list[dict]:
    """Filas del mapa curricular para la vista Resumen."""
    conn = db.get_connection(RUTA_DB)
    try:
        temas = conn.execute(
            "SELECT id, nombre, horas, bloque, orden FROM temas "
            "WHERE asignatura_id = ? ORDER BY orden",
            (asignatura_id,),
        ).fetchall()
        resultado: list[dict] = []
        for i, t in enumerate(temas):
            n_sub = conn.execute(
                "SELECT COUNT(*) FROM subbloques WHERE tema_id = ?", (t["id"],)
            ).fetchone()[0]
            ct = conn.execute(
                "SELECT estado FROM contenido_tema WHERE tema_id = ?", (t["id"],)
            ).fetchone()
            estado = ct["estado"] if ct else "pendiente"
            n_viz = conn.execute(
                "SELECT COUNT(*) FROM visualizacion_interactiva "
                "WHERE tema_id = ? AND estado = 'aprobado'",
                (t["id"],),
            ).fetchone()[0]
            bloque_lbl = t["bloque"] or f"B{i + 1}"
            resultado.append({
                "tema_id": t["id"],
                "idx": i,
                "bloque": bloque_lbl,
                "nombre": t["nombre"],
                "horas": t["horas"],
                "n_subtemas": n_sub,
                "estado_contenido": estado,
                "n_viz": n_viz,
                "org_confirmado": True,
            })
        return resultado
    finally:
        conn.close()


def _estados_bloques_asignatura(asignatura_id: int) -> dict[int, str]:
    conn = db.get_connection(RUTA_DB)
    try:
        filas = conn.execute(
            """
            SELECT t.id, COALESCE(ct.estado, 'pendiente') AS estado
            FROM temas t
            LEFT JOIN contenido_tema ct ON ct.tema_id = t.id
            WHERE t.asignatura_id = ?
            ORDER BY t.orden
            """,
            (asignatura_id,),
        ).fetchall()
        return {r["id"]: r["estado"] for r in filas}
    finally:
        conn.close()


def _vista_resumen() -> None:
    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    kpis = _db_resumen_kpis(asignatura_id)
    mapa = _db_mapa_curricular(asignatura_id)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            kpi_card("Bloques temáticos", str(kpis["bloques"]), unidad="totales"),
            unsafe_allow_html=True,
        )
    with c2:
        if kpis["total"]:
            apr_val = str(kpis["aprobados"])
            apr_unit = f"de {kpis['total']}"
        else:
            apr_val, apr_unit = "0", "de 0"
        st.markdown(
            kpi_card("Aprobados", apr_val, color="#2E815A", unidad=apr_unit),
            unsafe_allow_html=True,
        )
    with c3:
        h = kpis["horas"]
        h_fmt = str(int(h)) if h == int(h) else f"{h:.1f}"
        st.markdown(kpi_card("Horas lectivas", h_fmt, unidad="h"), unsafe_allow_html=True)
    with c4:
        st.markdown(
            kpi_card(
                "Visualizaciones",
                str(kpis["visualizaciones"]),
                color="#185FA5",
                unidad="ancladas",
            ),
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div style="display:flex;align-items:baseline;justify-content:space-between;margin:22px 0 12px;">
          <h2 style="margin:0;font-size:15px;font-weight:600;">Mapa curricular</h2>
          <span style="font-size:12px;color:#6B7A8D;">{len(mapa)} bloques · estado por agente</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not mapa:
        st.info(
            "Aún no hay bloques temáticos. Ejecuta el **Organizador** y confirma la estructura."
        )
        return

    with st.container(gap=None, key="sd_tabla_mapa"):
        st.markdown(
            '<div class="sd-tabla-header">'
            "<span>Bloque temático</span><span>Horas</span>"
            "<span>Organizador</span><span>Contenido</span>"
            "<span>Presentación</span>"
            '<span style="text-align:right;">Estado</span></div>',
            unsafe_allow_html=True,
        )
        for fila in mapa:
            col_fila, col_ir = st.columns([24, 1])
            with col_fila:
                st.markdown(mapa_fila_html(fila), unsafe_allow_html=True)
            with col_ir:
                if st.button(
                    "→",
                    key=f"mapa_btn_{fila['tema_id']}",
                    help="Abrir en Contenido",
                    type="secondary",
                ):
                    st.session_state["vista_actual"] = "Contenido"
                    st.session_state["cnt_tema_idx"] = fila["idx"]
                    st.rerun()

    avisos = _db_resumen_avisos(asignatura_id)
    if avisos:
        with st.expander(f"Avisos de validación ({len(avisos)})", expanded=False):
            _ICONO_TIPO = {"cobertura_incompleta": "🧩", "fidelidad_baja": "📉"}
            for a in avisos:
                icono = _ICONO_TIPO.get(a["tipo"], "⚠️")
                st.caption(f"{icono} `{a['tipo']}` — {a['agente']}: {a['descripcion']}")


# =============================================================================
# Vista Inputs — archivos registrados de la asignatura activa
# =============================================================================

def _vista_inputs() -> None:
    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    st.markdown(
        '<p class="sd-vista-titulo">Materiales de la asignatura</p>'
        '<p class="sd-vista-desc">Documentos de origen que alimentan a los tres agentes.</p>',
        unsafe_allow_html=True,
    )

    inputs = db.listar_inputs_asignatura(asignatura_id, RUTA_DB)
    guias = [i for i in inputs if i["tipo"] == "guia_docente"]
    materiales = [i for i in inputs if i["tipo"] == "material_teoria"]
    grupos = [
        ("Guía docente", guias),
        ("Materiales de teoría", materiales),
    ]

    col_a, col_b = st.columns(2)
    for idx, (col, (titulo, filas)) in enumerate(zip((col_a, col_b), grupos)):
        with col:
            with st.container(gap=None, key=f"sd_card_inputs_{idx}"):
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;'
                    f'margin-bottom:14px;"><span style="font-size:13px;font-weight:600;">'
                    f'{html.escape(titulo)}</span>'
                    f'<span style="font-size:11px;color:#8693A3;">{len(filas)} archivo'
                    f'{"s" if len(filas) != 1 else ""}</span></div>',
                    unsafe_allow_html=True,
                )
                if not filas:
                    st.caption("Sin archivos registrados.")
                for fila in filas:
                    meta = file_meta(fila.get("ruta_disco"), fila["nombre_fichero"])
                    fecha = fila.get("fecha_subida") or ""
                    if fecha:
                        meta = f"{meta} · {fecha}" if meta != "—" else fecha
                    disp = "✓ en disco" if fichero_existe(fila.get("ruta_disco") or "") else "⚠ no encontrado"
                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:11px;padding:9px 0;'
                        f'border-top:1px solid #F0F3F7;">'
                        f'{file_tag_html(fila["nombre_fichero"])}'
                        f'<span style="flex:1;min-width:0;">'
                        f'<span style="display:block;font-size:12.5px;font-weight:500;color:#16202E;">'
                        f'{html.escape(fila["nombre_fichero"])}</span>'
                        f'<span style="font-size:11px;color:#6B7A8D;">{html.escape(meta)} · {disp}</span>'
                        f'</span></div>',
                        unsafe_allow_html=True,
                    )
            with st.container(gap=None, key=f"sd_input_dashed_{idx}"):
                if st.button(
                    "+ Añadir documento",
                    key=f"inputs_add_{titulo}",
                    use_container_width=True,
                    type="secondary",
                    help="La subida de archivos se realiza en el Agente Organizador.",
                ):
                    st.session_state["vista_actual"] = "Organizador"
                    st.rerun()


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
# Vista de inicio (sin asignatura activa) — elegir proyecto
# =============================================================================

def _vista_landing() -> None:
    st.markdown(
        """
        <div class="sd-landing-wrap">
          <span class="sd-landing-badge">🎓 Universidad de Oviedo</span>
          <div class="sd-landing-title">Suite Docente IA</div>
          <p class="sd-landing-sub">Orquestación docente inteligente</p>
          <p class="sd-landing-escuela">Escuela Politécnica de Ingeniería de Gijón</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    modo = st.session_state.get("landing_modo")
    _, col_c, _ = st.columns([1, 3, 1])
    with col_c:
        c1, c2 = st.columns(2, gap="medium")
        with c1:
            if st.button(
                "🌱\n\nComenzar nuevo proyecto\n\nCarga la guía docente y materiales "
                "didácticos para estructurar un nuevo mapa curricular.",
                key="landing_btn_nuevo",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state["landing_modo"] = "nuevo"
                st.rerun()
        with c2:
            if st.button(
                "📁\n\nCargar proyecto existente\n\nSelecciona una asignatura de la "
                "base de datos local para continuar editándola.",
                key="landing_btn_cargar",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state["landing_modo"] = "cargar"
                st.rerun()

        if modo == "nuevo":
            st.divider()
            st.markdown("**Nueva asignatura**")
            nombre = st.text_input(
                "Nombre",
                key="landing_nueva_asignatura_nombre",
                placeholder="Ej. Mecánica de Fluidos",
                label_visibility="collapsed",
            )
            if st.button("Crear asignatura", type="primary", key="landing_btn_crear_asignatura"):
                nombre_limpio = (nombre or "").strip()
                if not nombre_limpio:
                    st.error("Introduce un nombre.")
                else:
                    try:
                        db.crear_asignatura(nombre_limpio, RUTA_DB)
                        slug = slugify(nombre_limpio)
                        preparar_carpetas_asignatura(RAIZ_MONOREPO, slug)
                        st.session_state["asignatura_actual"] = nombre_limpio
                        st.session_state["vista_actual"] = "Organizador"
                        st.session_state.pop("landing_modo", None)
                        st.session_state.pop("landing_nueva_asignatura_nombre", None)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        elif modo == "cargar":
            st.divider()
            st.markdown("**Selecciona una asignatura**")
            render_lista_asignaturas(RUTA_DB)

    st.markdown(
        '<p class="sd-landing-footer">Suite Docente IA · Universidad de Oviedo · '
        "EPI Gijón</p>",
        unsafe_allow_html=True,
    )


# =============================================================================
# Configuración de página + inicialización
# =============================================================================

st.set_page_config(layout="wide", page_title="Suite Docente IA", page_icon="📘")


@st.cache_resource
def _preparar_bd():
    db.init_db(RUTA_DB)
    db.seed_asignaturas(RUTA_DB)
    return True


_preparar_bd()


# =============================================================================
# CSS — identidad visual compartida
# =============================================================================

_asignatura_activa = st.session_state.get("asignatura_actual")
_vista_actual = st.session_state.get("vista_actual", VISTAS_NAV[0])

# CSS base al inicio; fix de botones al final (después de widgets).
inject_theme(ACENTO, ACENTO_OSCURO, mostrar_sidebar=bool(_asignatura_activa))


# =============================================================================
# Barra lateral + área principal
# =============================================================================

with st.sidebar:
    render_sidebar(
        RUTA_DB,
        _asignatura_activa,
        _vista_actual,
        vistas_debug=[VISTA_BASE_DATOS],
    )

if not _asignatura_activa:
    _vista_landing()
else:
    asignatura_id = _get_asignatura_id(_asignatura_activa)
    if asignatura_id is not None:
        render_topbar(_asignatura_activa, asignatura_id, RUTA_DB)
        subs = pipeline_subtitulos(asignatura_id, RUTA_DB)
        render_pipeline_banner(_vista_actual, subs)

    vista = st.session_state.get("vista_actual", VISTAS_NAV[0])
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
    elif vista == "Base de datos":
        _vista_base_datos()
    else:
        st.info("Vista no reconocida.")

inject_button_fix(ACENTO, ACENTO_OSCURO)
