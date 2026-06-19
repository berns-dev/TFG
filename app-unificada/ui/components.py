"""Componentes HTML reutilizables y tokens de estado."""

from __future__ import annotations

import html
import os
from pathlib import Path

# Lenguaje de estado (handoff)
ESTADOS = {
    "pendiente": {
        "label": "Pendiente",
        "texto": "#64748B",
        "fondo": "#EDF1F6",
        "punto": "#94A3B8",
    },
    "generado": {
        "label": "Borrador IA",
        "texto": "#185FA5",
        "fondo": "#E7F0FA",
        "punto": "#185FA5",
    },
    "editado": {
        "label": "Editado",
        "texto": "#9A6608",
        "fondo": "#FBF1DD",
        "punto": "#D6960F",
    },
    "aprobado": {
        "label": "Aprobado",
        "texto": "#2E815A",
        "fondo": "#E3F1EA",
        "punto": "#2E815A",
    },
    "confirmado": {
        "label": "Confirmado",
        "texto": "#2E815A",
        "fondo": "#E3F1EA",
        "punto": "#2E815A",
    },
    "sin_generar": {
        "label": "Sin generar",
        "texto": "#64748B",
        "fondo": "#EDF1F6",
        "punto": "#94A3B8",
    },
}


def estado_contenido(estado: str | None) -> dict:
    return ESTADOS.get(estado or "pendiente", ESTADOS["pendiente"])


def pill_estado(estado: str | None) -> str:
    e = estado_contenido(estado)
    label = e["label"]
    if estado == "aprobado":
        label = "Aprobado"
    return (
        f'<span class="sd-estado-pill" style="background:{e["fondo"]};color:{e["texto"]};">'
        f'{html.escape(label)}</span>'
    )


def inline_estado(estado_key: str, label: str | None = None) -> str:
    e = ESTADOS.get(estado_key, ESTADOS["pendiente"])
    txt = html.escape(label or e["label"])
    return (
        f'<span class="sd-estado-inline" style="color:{e["texto"]};">'
        f'<span class="dot" style="background:{e["punto"]};"></span>{txt}</span>'
    )


def kpi_card(label: str, valor: str, color: str = "#16202E", unidad: str = "") -> str:
    unidad_html = (
        f'<span class="unidad">{html.escape(unidad)}</span>' if unidad else ""
    )
    return (
        f'<div class="sd-kpi">'
        f'<div class="label">{html.escape(label)}</div>'
        f'<div><span class="valor" style="color:{color};">{html.escape(valor)}</span>'
        f'{unidad_html}</div></div>'
    )


def file_meta(ruta_disco: str | None, nombre: str) -> str:
    """Meta de archivo: tamaño y extensión (páginas no disponibles sin leer PDF)."""
    partes: list[str] = []
    ext = Path(nombre).suffix.lower().lstrip(".")
    if ext:
        partes.append(ext.upper())
    if ruta_disco and os.path.isfile(ruta_disco):
        kb = os.path.getsize(ruta_disco) / 1024
        if kb >= 1024:
            partes.append(f"{kb / 1024:.1f} MB")
        else:
            partes.append(f"{kb:.0f} KB")
    return " · ".join(partes) if partes else "—"


def file_tag_html(nombre: str) -> str:
    ext = Path(nombre).suffix.lower()
    if ext in {".pptx", ".ppt"}:
        clase, tipo = "pptx", "PPTX"
    else:
        clase, tipo = "pdf", "PDF"
    return f'<span class="sd-file-tag {clase}">{tipo}</span>'


def cobertura_icono(cubierto: bool, detalle: str) -> tuple[str, str]:
    """Devuelve (clase_css, símbolo). Parcial si hay tokens pero no cubierto."""
    if cubierto:
        return "ok", "✓"
    if "Solo" in (detalle or "") and "/" in (detalle or ""):
        return "parcial", "~"
    return "pend", "·"


def cobertura_item_html(nombre: str, cubierto: bool, detalle: str) -> str:
    clase, sim = cobertura_icono(cubierto, detalle)
    return (
        f'<div class="sd-cob-item">'
        f'<span class="sd-cob-icon {clase}">{sim}</span>'
        f'<span>{html.escape(nombre)}</span></div>'
    )


def mapa_fila_html(fila: dict) -> str:
    """Una fila del mapa curricular (HTML estático)."""
    h = fila["horas"]
    h_fmt = str(int(h)) if h == int(h) else f"{h:.1f}"
    org = inline_estado("confirmado", "Confirmado")
    cnt = inline_estado(fila["estado_contenido"])
    if fila["n_viz"] > 0:
        prs = inline_estado("generado", f"{fila['n_viz']} viz.")
    else:
        prs = inline_estado("sin_generar")
    pill = pill_estado(fila["estado_contenido"])
    bloque_lbl = fila.get("bloque") or "?"
    if "bloque-" in str(bloque_lbl).lower():
        bloque_lbl = "B" + str(bloque_lbl).split("-")[-1]
    elif str(bloque_lbl).lower().startswith("bloque "):
        bloque_lbl = "B" + str(bloque_lbl).split()[-1]
    subtemas = fila["n_subtemas"]
    sub_txt = f"{subtemas} subtema{'s' if subtemas != 1 else ''}"

    return f"""
    <div class="sd-tabla-row">
      <div class="col-bloque">
        <div class="bloque-tit">
          <span class="sd-bloque-num">{html.escape(str(bloque_lbl))}</span>
          <span class="bloque-nombre">{html.escape(fila["nombre"])}</span>
        </div>
        <div class="bloque-sub">{html.escape(sub_txt)}</div>
      </div>
      <div class="col-horas">{h_fmt} h</div>
      <div class="col-est">{org}</div>
      <div class="col-est">{cnt}</div>
      <div class="col-est">{prs}</div>
      <div class="col-pill">{pill}</div>
    </div>
    """
