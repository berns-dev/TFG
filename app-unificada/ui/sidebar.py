"""Barra lateral — Suite Docente IA (handoff navy)."""

from __future__ import annotations

import html

import streamlit as st

from database import db
from ui.meta import barra_progreso_html
from ui.shell import PIPELINE_VISTAS

NAV_VISTAS = ["Resumen", "Inputs"]


def _render_brand() -> None:
    st.markdown(
        """
        <div class="sd-brand">
          <div class="logo">SD</div>
          <div>
            <div class="titulo">Suite Docente IA</div>
            <div class="sub">U. de Oviedo · EPI Gijón</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_lista_asignaturas(ruta_db: str, *, key_prefix: str = "sd_asig") -> None:
    """Lista de asignaturas guardadas — usada en «Cargar proyecto existente»."""
    filas = db.listar_asignaturas_portfolio(ruta_db)
    if not filas:
        st.caption("Sin asignaturas todavía. Crea una nueva para empezar.")
        return

    for fila in filas:
        prog = fila["progreso"]
        pct = int(prog["porcentaje"]) if prog["total"] > 0 else 0
        pct_txt = f"{pct}%" if prog["total"] > 0 else "Sin bloques"
        nombre = fila["nombre"]

        with st.container(gap=None, key=f"sd_asig_item_{fila['id']}"):
            if st.button(
                f"{nombre}  ·  {pct_txt}",
                key=f"{key_prefix}_btn_{fila['id']}",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state["asignatura_actual"] = nombre
                st.session_state["vista_actual"] = "Resumen"
                st.session_state.pop("landing_modo", None)
                st.rerun()
            if prog["total"] > 0:
                st.progress(pct / 100.0)


def _render_asignatura_activa(ruta_db: str, asignatura_activa: str) -> None:
    """Bloque compacto con la asignatura abierta + enlace para volver al inicio."""
    filas = db.listar_asignaturas_portfolio(ruta_db)
    fila = next((f for f in filas if f["nombre"] == asignatura_activa), None)
    pct = 0
    if fila:
        prog = fila["progreso"]
        pct = int(prog["porcentaje"]) if prog["total"] > 0 else 0
    completo = pct >= 100
    nombre_esc = html.escape(asignatura_activa)

    st.markdown(
        f"""
        <div class="sd-asig-activa">
          <div class="nombre">{nombre_esc}</div>
          {barra_progreso_html(pct, completo)}
          <div style="font-size:10px;color:#93A6C0;margin-top:6px;">{pct}%</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(gap=None, key="sd_cambiar_proyecto"):
        if st.button(
            "← Cambiar de proyecto",
            key="sd_btn_cambiar_proyecto",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state["asignatura_actual"] = None
            st.session_state.pop("landing_modo", None)
            st.rerun()


def _nav_item(label: str, vista: str, vista_actual: str, key: str) -> None:
    activo = vista_actual == vista
    if st.button(
        label,
        key=key,
        use_container_width=True,
        type="primary" if activo else "secondary",
    ):
        st.session_state["vista_actual"] = vista
        st.rerun()


def _pipe_item(num: int, vista: str, label: str, vista_actual: str, key: str) -> None:
    activo = vista_actual == vista
    if st.button(
        f"{num}. {label}",
        key=key,
        use_container_width=True,
        type="primary" if activo else "secondary",
    ):
        st.session_state["vista_actual"] = vista
        st.rerun()


def render_sidebar(
    ruta_db: str,
    asignatura_activa: str | None,
    vista_actual: str,
    vistas_debug: list[str] | None = None,
) -> None:
    """Sidebar unificada — sin asignatura activa queda solo la marca (la
    elección de proyecto vive en la pantalla de inicio del área principal)."""
    _render_brand()

    if not asignatura_activa:
        return

    _render_asignatura_activa(ruta_db, asignatura_activa)

    st.markdown(
        '<div style="height:1px;background:rgba(255,255,255,.09);margin:14px 8px;"></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sd-seccion-label">Navegación</div>', unsafe_allow_html=True)
    with st.container(gap=None, key="sd_nav_list"):
        for vista in NAV_VISTAS:
            _nav_item(vista, vista, vista_actual, key=f"sd_nav_{vista}")

    st.markdown('<div class="sd-seccion-label">Pipeline docente</div>', unsafe_allow_html=True)
    with st.container(gap=None, key="sd_pipe_list"):
        for i, vista in enumerate(PIPELINE_VISTAS, 1):
            _pipe_item(i, vista, vista, vista_actual, key=f"sd_pipe_{vista}")

    if vistas_debug:
        with st.expander("Depuración", expanded=False):
            for v in vistas_debug:
                if v not in NAV_VISTAS + PIPELINE_VISTAS:
                    if st.button(v, key=f"sd_dbg_{v}", use_container_width=True, type="secondary"):
                        st.session_state["vista_actual"] = v
                        st.rerun()
