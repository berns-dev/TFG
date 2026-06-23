"""Shell de la app — topbar, banner de pipeline y estado vacío."""

from __future__ import annotations

import html

import streamlit as st

from database import db
from ui.components import estado_contenido

PIPELINE_VISTAS = ["Organizador", "Contenido", "Presentación"]


def pipeline_subtitulos(asignatura_id: int, ruta_db: str) -> dict[str, str]:
    """Subtítulos del pipeline en sidebar/banner."""
    conn = db.get_connection(ruta_db)
    try:
        n_temas = conn.execute(
            "SELECT COUNT(*) FROM temas WHERE asignatura_id = ?", (asignatura_id,)
        ).fetchone()[0]
        prog = db.get_progreso_asignatura(asignatura_id, ruta_db)
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

    org = "Confirmado" if n_temas > 0 else "Pendiente"
    if prog["total"] == 0:
        cnt = "Sin bloques"
    else:
        cnt = f"{prog['aprobados']}/{prog['total']} aprobados"
    if n_viz == 0:
        prs = "Sin visualizaciones"
    elif n_viz == 1:
        prs = "1 visualización"
    else:
        prs = f"{n_viz} visualizaciones"
    return {"Organizador": org, "Contenido": cnt, "Presentación": prs}


def render_topbar(asignatura: str, asignatura_id: int, ruta_db: str) -> None:
    prog = db.get_progreso_asignatura(asignatura_id, ruta_db)
    pct = int(prog["porcentaje"]) if prog["total"] > 0 else 0
    bar_w = f"{pct}%"
    nombre_esc = html.escape(asignatura)

    total = prog["total"]
    apr = prog["aprobados"]
    hint = f"{apr}/{total} aprobados" if total > 0 else "Sin bloques"
    hint_color = "#9AA7B6"

    with st.container(gap=None, key="sd_topbar_wrap"):
        t1, t2 = st.columns([2.4, 1.0])
        with t1:
            st.markdown(
                f'<div class="asig-titulo">{nombre_esc}</div>',
                unsafe_allow_html=True,
            )
        with t2:
            st.markdown(
                f"""
                <div class="sd-topbar-prog">
                  <div class="bar"><div style="height:100%;width:{bar_w};background:linear-gradient(90deg,#185FA5,#2E815A);border-radius:4px;"></div></div>
                  <span class="pct">{pct}%</span>
                </div>
                <div class="sd-export-hint" style="justify-content:flex-end;margin-top:6px;color:{hint_color};font-size:11px;font-weight:500;display:flex;align-items:center;gap:6px;">
                  <span style="width:7px;height:7px;border-radius:50%;background:{hint_color};"></span>
                  {html.escape(hint)}
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_pipeline_banner(vista_actual: str, subs: dict[str, str]) -> None:
    from ui.meta import pipeline_subfijo

    paso_activo = vista_actual if vista_actual in PIPELINE_VISTAS else None

    def _sub_line(nombre: str) -> str:
        estado = subs.get(nombre, "")
        sub = pipeline_subfijo(nombre)
        if estado and estado not in (sub, ""):
            return f"{sub} · {estado}"
        return sub

    def _step(col, i: int, nombre: str) -> None:
        with col:
            if st.button(
                f"{i + 1}. {nombre}\n{_sub_line(nombre)}",
                key=f"banner_nav_{nombre}",
                use_container_width=True,
                type="primary" if paso_activo == nombre else "secondary",
            ):
                st.session_state["vista_actual"] = nombre
                st.rerun()

    with st.container(gap=None, key="sd_banner_flow"):
        c1, ca1, c2, ca2, c3 = st.columns([5, 0.35, 5, 0.35, 5], gap="small")
        _step(c1, 0, PIPELINE_VISTAS[0])
        with ca1:
            st.markdown('<div class="sd-flow-arrow">→</div>', unsafe_allow_html=True)
        _step(c2, 1, PIPELINE_VISTAS[1])
        with ca2:
            st.markdown('<div class="sd-flow-arrow">→</div>', unsafe_allow_html=True)
        _step(c3, 2, PIPELINE_VISTAS[2])




def _chip_dot_color(estado: str) -> str:
    return estado_contenido(estado)["punto"]


def _bloque_label_corto(bloque_raw: str, idx: int) -> str:
    """Etiqueta compacta "Bloque N" — sin título, para que quepan varias filas."""
    texto = str(bloque_raw or "").strip().lower()
    if "bloque" in texto:
        numero = "".join(c for c in texto.split("bloque")[-1] if c.isdigit())
        if numero:
            return f"Bloque {numero}"
    return f"Bloque {idx + 1}"


def render_bloque_chips(
    temas: list[dict],
    tema_idx: int,
    estados: dict[int, str],
    key_prefix: str,
    chips_per_row: int = 8,
) -> int:
    """Chips de bloque en filas ordenadas (envuelven si no caben en una sola)."""
    n = len(temas)
    if n == 0:
        return 0

    selected = tema_idx
    with st.container(gap=None, key="sd_chip_scroll"):
        for inicio in range(0, n, chips_per_row):
            fila = list(enumerate(temas))[inicio:inicio + chips_per_row]
            cols = st.columns(chips_per_row)
            for col, (i, tema) in zip(cols, fila):
                label = _bloque_label_corto(tema.get("bloque", ""), i)
                activo = i == tema_idx
                with col:
                    if st.button(
                        f"● {label}" if activo else f"○ {label}",
                        key=f"{key_prefix}_chip_{tema['id']}",
                        use_container_width=True,
                        type="primary" if activo else "secondary",
                    ):
                        selected = i

    if selected != tema_idx:
        st.session_state[f"{key_prefix}_tema_idx"] = selected
        st.rerun()
    return selected
