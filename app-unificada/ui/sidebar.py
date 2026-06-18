"""Barra lateral — modo portfolio y modo workspace."""

import streamlit as st

from database import db
from utils import preparar_carpetas_asignatura, slugify


def render_marca() -> None:
    st.markdown(
        """
        <div class="marca">
            <div class="icono"></div>
            <div><div class="nombre">Pipeline</div><div class="sub">TFG</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_portfolio(ruta_db: str, raiz_monorepo: str) -> None:
    """Sidebar en modo portfolio: alta de asignatura."""
    with st.expander("➕ Nueva asignatura", expanded=False):
        nombre = st.text_input(
            "Nombre de la asignatura",
            key="nueva_asignatura_nombre",
            placeholder="Ej. Mecánica de Fluidos",
            label_visibility="collapsed",
        )
        if st.button("Crear asignatura", type="primary", use_container_width=True, key="btn_crear_asignatura"):
            nombre_limpio = (nombre or "").strip()
            if not nombre_limpio:
                st.error("Introduce un nombre para la asignatura.")
            else:
                try:
                    db.crear_asignatura(nombre_limpio, ruta_db)
                    slug = slugify(nombre_limpio)
                    preparar_carpetas_asignatura(raiz_monorepo, slug)
                    st.session_state["asignatura_actual"] = nombre_limpio
                    st.session_state["vista_actual"] = "Organizador"
                    st.session_state.pop("nueva_asignatura_nombre", None)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))


def render_sidebar_workspace(
    vistas_nav: list[str],
    iconos_vista: dict[str, str],
    asignatura: str,
) -> None:
    """Sidebar en modo workspace: volver al portfolio + navegación por agente."""
    if st.button("← Todas las asignaturas", key="nav_volver_portfolio", use_container_width=True):
        st.session_state["asignatura_actual"] = None
        st.session_state["vista_actual"] = vistas_nav[0]
        st.rerun()

    nombre_esc = (
        asignatura.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    st.markdown(
        f'<div class="asignatura-sidebar-nombre">{nombre_esc}</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    if "vista_actual" not in st.session_state:
        st.session_state["vista_actual"] = vistas_nav[0]

    st.radio(
        "Navegación",
        vistas_nav,
        key="vista_actual",
        label_visibility="collapsed",
        format_func=lambda v: f"{iconos_vista.get(v, '·')} {v}",
    )
