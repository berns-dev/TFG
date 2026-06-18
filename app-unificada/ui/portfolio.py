"""Vista portfolio — listado global de asignaturas."""

import html

import streamlit as st

from database import db
from utils import formatear_fecha_relativa


def _badge_estado(progreso: dict) -> tuple[str, str]:
    total = progreso.get("total", 0)
    pct = progreso.get("porcentaje", 0.0)
    if total == 0:
        return "Sin organizar", "badge-sin-organizar"
    if pct >= 100:
        return "Completo", "badge-completo"
    return "En curso", "badge-en-curso"


def render_portfolio(ruta_db: str) -> None:
    filas = db.listar_asignaturas_portfolio(ruta_db)
    n = len(filas)

    st.markdown(
        f'<p class="portfolio-subtitulo">{n} asignatura{"s" if n != 1 else ""} en el pipeline</p>',
        unsafe_allow_html=True,
    )

    if not filas:
        st.info("Aún no hay asignaturas. Usa **➕ Nueva asignatura** en la barra lateral para crear la primera.")
        return

    h1, h2, h3, h4, h5 = st.columns([2.4, 1.4, 1.2, 1.4, 0.7])
    h1.markdown('<div class="inputs-tabla-header">Asignatura</div>', unsafe_allow_html=True)
    h2.markdown('<div class="inputs-tabla-header">Progreso</div>', unsafe_allow_html=True)
    h3.markdown('<div class="inputs-tabla-header">Inputs</div>', unsafe_allow_html=True)
    h4.markdown('<div class="inputs-tabla-header">Última actividad</div>', unsafe_allow_html=True)
    h5.markdown('<div class="inputs-tabla-header"></div>', unsafe_allow_html=True)

    for fila in filas:
        prog = fila["progreso"]
        etiqueta, clase_badge = _badge_estado(prog)
        fecha_corta, fecha_rel = formatear_fecha_relativa(fila.get("ultima_ejecucion"))
        nombre = html.escape(fila["nombre"])
        n_guia = fila.get("n_guia", 0)
        n_mat = fila.get("n_materiales", 0)
        inputs_txt = f"{n_guia} guía · {n_mat} materiales"
        prog_txt = (
            f"{prog['aprobados']}/{prog['total']} ({prog['porcentaje']}%)"
            if prog["total"] > 0
            else "—"
        )

        c1, c2, c3, c4, c5 = st.columns([2.4, 1.4, 1.2, 1.4, 0.7])
        with c1:
            st.markdown(
                f'<div class="portfolio-card" style="margin-bottom:6px;padding:12px 14px;">'
                f'<div class="nombre">{nombre}</div>'
                f'<span class="badge {clase_badge}">{etiqueta}</span></div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.caption(prog_txt)
            if prog["total"] > 0:
                st.progress(prog["porcentaje"] / 100)
        with c3:
            st.caption(inputs_txt)
        with c4:
            st.caption(fecha_corta)
            if fecha_rel:
                st.caption(fecha_rel)
        with c5:
            if st.button("Abrir", key=f"abrir_asignatura_{fila['id']}", use_container_width=True):
                st.session_state["asignatura_actual"] = fila["nombre"]
                st.session_state["vista_actual"] = "Resumen"
                st.rerun()

        st.divider()
