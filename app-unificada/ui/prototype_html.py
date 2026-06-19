"""Fragmentos HTML alineados con `Suite Docente.dc.html` (referencia hi-fi)."""

from __future__ import annotations

import html

from ui.meta import pipeline_subfijo


def sidebar_nav_html(label: str, activo: bool) -> str:
    dot = "#5AA0E0" if activo else "#5C708A"
    bg = "#15406E" if activo else "transparent"
    color = "#E7EEF6" if activo else "#A9BACE"
    weight = "600" if activo else "500"
    return (
        f'<div style="display:flex;align-items:center;gap:10px;padding:9px 11px;'
        f'border-radius:8px;margin-bottom:2px;background:{bg};color:{color};'
        f'font-size:12.5px;font-weight:{weight};">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};flex:none;"></span>'
        f'<span>{html.escape(label)}</span></div>'
    )


def sidebar_pipe_html(num: int, label: str, sub: str, activo: bool) -> str:
    num_bg = "#185FA5" if activo else "rgba(255,255,255,.09)"
    num_color = "#fff" if activo else "#9CB0C8"
    bg = "#15406E" if activo else "transparent"
    sub_color = "#9CC4EC" if activo else "#7E93AE"
    return (
        f'<div style="display:flex;align-items:center;gap:11px;padding:9px 11px;'
        f'border-radius:9px;margin-bottom:3px;background:{bg};color:#E7EEF6;">'
        f'<span style="width:24px;height:24px;flex:none;border-radius:7px;display:flex;'
        f'align-items:center;justify-content:center;font-size:12px;font-weight:700;'
        f'background:{num_bg};color:{num_color};">{num}</span>'
        f'<span style="flex:1;text-align:left;">'
        f'<span style="display:block;font-size:12.5px;font-weight:600;letter-spacing:-.01em;">'
        f'{html.escape(label)}</span>'
        f'<span style="display:block;font-size:10.5px;color:{sub_color};margin-top:1px;">'
        f'{html.escape(sub)}</span></span></div>'
    )


def banner_step_html(num: int, label: str, activo: bool, estado: str = "") -> str:
    sub = pipeline_subfijo(label)
    if estado and estado not in (sub, ""):
        sub_line = f"{sub} · {estado}"
    else:
        sub_line = sub
    bg = "#F2F7FC" if activo else "#fff"
    border_left = "3px solid #185FA5" if activo else "3px solid transparent"
    title_color = "#0C447C" if activo else "#37475A"
    num_bg = "#185FA5" if activo else "#EDF2F8"
    num_color = "#fff" if activo else "#7C8A9C"
    return (
        f'<div style="display:flex;align-items:center;gap:12px;flex:1;padding:14px 18px;'
        f'background:{bg};border-left:{border_left};border-right:1px solid #EAEEF3;">'
        f'<span style="width:28px;height:28px;flex:none;border-radius:8px;display:flex;'
        f'align-items:center;justify-content:center;font-size:13px;font-weight:700;'
        f'background:{num_bg};color:{num_color};">{num}</span>'
        f'<span style="text-align:left;">'
        f'<span style="display:block;font-size:12.5px;font-weight:600;letter-spacing:-.01em;'
        f'color:{title_color};">{html.escape(label)}</span>'
        f'<span style="display:block;font-size:11px;color:#7C8A9C;margin-top:1px;">'
        f'{html.escape(sub_line)}</span></span></div>'
    )


def banner_frame_html(steps_html: list[str]) -> str:
    return (
        '<div style="display:flex;align-items:stretch;background:#fff;'
        'border:1px solid #E4E9F0;border-radius:11px;overflow:hidden;margin-bottom:20px;">'
        + "".join(steps_html)
        + "</div>"
    )


def cobertura_bar_html(pct: int) -> str:
    return (
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">'
        f'<div style="flex:1;height:6px;border-radius:4px;background:#EBEFF4;overflow:hidden;">'
        f'<div style="height:100%;width:{pct}%;background:#2E815A;border-radius:4px;"></div></div>'
        f'<span style="font-size:11.5px;font-weight:600;color:#2E815A;'
        f'font-variant-numeric:tabular-nums;">{pct}%</span></div>'
    )


def mapa_tabla_html(filas_html: list[str]) -> str:
    return (
        '<div class="sd-tabla">'
        '<div class="sd-tabla-header">'
        "<span>Bloque temático</span><span>Horas</span>"
        "<span>Organizador</span><span>Contenido</span>"
        "<span>Presentación</span>"
        '<span style="text-align:right;">Estado</span>'
        "</div>"
        + "".join(filas_html)
        + "</div>"
    )
