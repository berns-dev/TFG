"""UI Streamlit para el pipeline de Agente_contenido."""

from __future__ import annotations

import re
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

_SUITE_ROOT = Path(__file__).resolve().parent.parent
if str(_SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUITE_ROOT))

from shared.ui_hero import render_hero

from assembler import (
    assemble_block_with_subbloques,
    assemble_markdown,
    assemble_multiple,
    assemble_subbloque_body,
    unified_download_filename,
)
from chunker import split_into_chunks
from classifier import classify_and_format
from config import FIDELITY_THRESHOLD, MAX_WORKERS
from extractor import extract_text
from segmentor import segment_text_by_subbloques
from subblock_state import SubbloqueResult, calcular_progreso_bloque
from validator import validate_items


# ── Parseo del .md del Agente Organizador ────────────────────────────────────

_BLOCK_HEADER_RE = re.compile(
    r"^##\s+Bloque\s+\d+\s+—\s+(.+?)\s*·\s*([\d,.]+)h",
    re.MULTILINE,
)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s|:-]+\|$")


def _parse_subbloques_table(section: str) -> list[dict]:
    """Parsea la tabla de subbloques de la sección de un bloque.

    Soporta tablas con 4 columnas (flujo normal):
        | Subtema | Horas | Evidencia | Origen |
    y con 3 columnas (tras edición manual sin evidencia):
        | Subtema | Horas | Origen |
    """
    lines = section.strip().split("\n")

    # Buscar fila de cabecera de la tabla
    header_idx = None
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith("|") and "subtema" in stripped.lower():
            header_idx = i
            break

    if header_idx is None:
        return []

    # Determinar columnas por nombre
    raw_header = lines[header_idx].strip().strip("|")
    header_cells = [c.strip().lower() for c in raw_header.split("|")]

    col_nombre = next((i for i, h in enumerate(header_cells) if "subtema" in h), None)
    col_horas = next((i for i, h in enumerate(header_cells) if "hora" in h), None)
    col_evidencia = next((i for i, h in enumerate(header_cells) if "evidencia" in h), None)
    col_origen = next((i for i, h in enumerate(header_cells) if "origen" in h), None)

    if col_nombre is None:
        return []

    subbloques: list[dict] = []
    for ln in lines[header_idx + 1 :]:
        stripped = ln.strip()
        if not stripped.startswith("|"):
            break  # fin de la tabla
        if _TABLE_SEPARATOR_RE.match(stripped):
            continue  # fila separadora

        cells = [c.strip() for c in stripped.strip("|").split("|")]

        nombre = cells[col_nombre] if col_nombre < len(cells) else ""
        if not nombre or nombre == "---":
            continue

        horas_raw = cells[col_horas] if col_horas is not None and col_horas < len(cells) else "0"
        try:
            horas = float(horas_raw.replace(",", "."))
        except ValueError:
            horas = 0.0

        evidencia = (
            cells[col_evidencia]
            if col_evidencia is not None and col_evidencia < len(cells)
            else ""
        )
        origen = (
            cells[col_origen]
            if col_origen is not None and col_origen < len(cells)
            else ""
        )

        subbloques.append(
            {"nombre": nombre, "horas": horas, "evidencia": evidencia, "origen": origen}
        )

    return subbloques


def parse_organization_md(content: str) -> list[dict]:
    """Extrae bloques (con sus subbloques) de un .md del Agente Organizador.

    Formato bloque canónico (prompts.py del Organizador):
        ## Bloque N — Nombre del bloque · Xh

    Devuelve lista de dicts con 'nombre' (sin prefijo «Bloque N —»), 'horas'
    y 'subbloques' (lista de dicts con nombre, horas, evidencia, origen).
    """
    bloques: list[dict] = []
    matches = list(_BLOCK_HEADER_RE.finditer(content))

    for i, m in enumerate(matches):
        nombre = m.group(1).strip()
        horas_str = m.group(2).replace(",", ".")
        try:
            horas = float(horas_str)
        except ValueError:
            horas = 0.0

        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block_section = content[block_start:block_end]

        subbloques = _parse_subbloques_table(block_section)
        bloques.append({"nombre": nombre, "horas": horas, "subbloques": subbloques})

    return bloques


# ── Pipeline por subbloque ────────────────────────────────────────────────────

def _process_subbloque(
    seg_text: str,
    sb_meta: dict,
    effective_horas: float | None,
    sb_label: str,
    nombre_del_archivo: str,
    status: object,
) -> SubbloqueResult:
    """Ejecuta el pipeline completo sobre un segmento de texto para un subbloque.

    Si el segmento está vacío, devuelve un resultado con estado 'pendiente'
    sin realizar llamadas a la API.
    """
    nombre = sb_meta.get("nombre", "Subbloque")
    horas = float(sb_meta.get("horas", 0.0) or 0.0)
    evidencia = sb_meta.get("evidencia", "")
    origen = sb_meta.get("origen", "")

    if not seg_text or not seg_text.strip():
        return SubbloqueResult(
            nombre=nombre,
            horas=horas,
            evidencia=evidencia,
            origen=origen,
            estado="pendiente",
            markdown="",
            items=[],
            validacion={"ok": True, "errores": [], "fidelity": []},
        )

    chunks = split_into_chunks(seg_text)
    if not chunks:
        return SubbloqueResult(
            nombre=nombre,
            horas=horas,
            evidencia=evidencia,
            origen=origen,
            estado="pendiente",
            markdown="",
            items=[],
            validacion={"ok": True, "errores": [], "fidelity": []},
        )

    n_chunks = len(chunks)
    ordered: list = [None] * n_chunks
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_to_i = {
            pool.submit(classify_and_format, chunk, effective_horas): i
            for i, chunk in enumerate(chunks)
        }
        for fut in as_completed(future_to_i):
            i = future_to_i[fut]
            try:
                ordered[i] = fut.result()
            except Exception as chunk_exc:
                error_msg = str(chunk_exc)
                st.warning(
                    f"⚠️ Error en chunk {i + 1}/{n_chunks} ({sb_label}): {error_msg}"
                )
                ordered[i] = {
                    "tipo": "mixto",
                    "titulo_detectado": None,
                    "idioma": "es",
                    "contenido_markdown": f"[ERROR EN CHUNK {i + 1}: {error_msg}]",
                }
            done += 1
            status.write(f"{sb_label} — chunk {done}/{n_chunks}…")  # type: ignore[attr-defined]

    items = ordered
    sb_markdown = assemble_subbloque_body(
        items, nombre_subbloque=nombre, nombre_del_archivo=nombre_del_archivo
    )
    sb_validacion = validate_items(items, original_chunks=chunks)

    if not sb_validacion.get("ok"):
        failed = [
            r for r in (sb_validacion.get("fidelity") or []) if not r.get("passed", True)
        ]
        if failed:
            min_score = min(r["coverage_score"] for r in failed)
            st.warning(
                f"⚠️ Subbloque '{nombre}': fidelidad léxica por debajo del umbral "
                f"(score: {min_score:.2f} < {FIDELITY_THRESHOLD}). Revisa antes de usar."
            )

    return SubbloqueResult(
        nombre=nombre,
        horas=horas,
        evidencia=evidencia,
        origen=origen,
        estado="generado",
        markdown=sb_markdown,
        items=items,
        validacion=sb_validacion,
    )


# ── UI principal ──────────────────────────────────────────────────────────────

def main() -> None:
    if "resultados" not in st.session_state:
        st.session_state["resultados"] = []
    if "archivos_hash" not in st.session_state:
        st.session_state["archivos_hash"] = tuple()
    if "org_bloques" not in st.session_state:
        st.session_state["org_bloques"] = []

    st.set_page_config(page_title="Agente contenido", layout="wide")

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("""
<div style="padding-bottom:20px; border-bottom:1px solid rgba(128,128,128,0.2); margin-bottom:8px;">
  <div style="font-family:'DM Sans',sans-serif; font-size:11px; font-weight:500;
       color:var(--text-color); opacity:0.55; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:8px;">
    Suite de Agentes
  </div>
  <div style="font-family:'DM Sans',sans-serif; font-size:16px; font-weight:500;
       color:var(--text-color); letter-spacing:-0.2px; line-height:1.2;">
    Agente Contenido
  </div>
</div>
""", unsafe_allow_html=True)
        st.markdown("""
<div style="display:flex; flex-direction:column; gap:12px; margin-bottom:4px; padding-top:6px;">
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="display:inline-flex; align-items:center; justify-content:center;
          width:20px; height:20px; border-radius:50%;
          background:#E6F1FB; color:#185FA5;
          font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">1</span>
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Organizaci&#243;n del tema</span>
  </div>
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="display:inline-flex; align-items:center; justify-content:center;
          width:20px; height:20px; border-radius:50%;
          background:#E6F1FB; color:#185FA5;
          font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">2</span>
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Material del tema</span>
  </div>
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="display:inline-flex; align-items:center; justify-content:center;
          width:20px; height:20px; border-radius:50%;
          background:#E6F1FB; color:#185FA5;
          font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">3</span>
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Procesa el contenido</span>
  </div>
</div>
""", unsafe_allow_html=True)
        st.divider()

        # Sección 1: Organización del tema
        st.markdown("""<div style="display:flex; align-items:center; gap:10px; margin:0 0 8px 0;">
  <span style="display:inline-flex; align-items:center; justify-content:center;
        width:20px; height:20px; border-radius:50%;
        background:#E6F1FB; color:#185FA5;
        font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">1</span>
  <div>
    <div style="font-family:'DM Sans',sans-serif; font-size:11px; font-weight:500;
         color:var(--text-color); letter-spacing:0.06em; text-transform:uppercase; line-height:1;">
      Organizaci&#243;n del tema</div>
    <div style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.55; margin-top:3px;">
      Archivo .md del Agente Organizador &mdash; opcional</div>
  </div>
</div>""", unsafe_allow_html=True)
        uploaded_org = st.file_uploader(
            "Organización del tema (.md)",
            type=["md"],
            accept_multiple_files=False,
            key="org_uploader",
        )

        tema_horas: float | None = None
        bloque_seleccionado: str | None = None
        bloque_subbloques: list[dict] = []

        if uploaded_org is not None:
            org_content = uploaded_org.getvalue().decode("utf-8", errors="replace")
            bloques = parse_organization_md(org_content)
            st.session_state["org_bloques"] = bloques
            if bloques:
                opciones = [f"{b['nombre']} ({b['horas']}h)" for b in bloques]
                seleccion = st.selectbox(
                    "¿Qué bloque estás procesando?",
                    options=opciones,
                    index=0,
                    key="bloque_selectbox",
                )
                idx = opciones.index(seleccion)
                tema_horas = bloques[idx]["horas"]
                bloque_seleccionado = bloques[idx]["nombre"]
                bloque_subbloques = bloques[idx].get("subbloques") or []

                n_sb = len(bloque_subbloques)
                if n_sb > 0:
                    st.caption(f"{n_sb} subbloque{'s' if n_sb != 1 else ''} detectado{'s' if n_sb != 1 else ''}")
                else:
                    st.caption("Sin subbloques detectados — se procesará como bloque único")
            else:
                st.warning(
                    "No se detectaron bloques con formato "
                    "'## Bloque N — Nombre · Xh' en el archivo. "
                    "Comprueba que es un output del Agente Organizador."
                )
        else:
            st.session_state["org_bloques"] = []

        st.markdown(
            '<div style="height:1px; background:rgba(128,128,128,0.2); margin:20px 0;"></div>',
            unsafe_allow_html=True,
        )

        # Sección 2: Material del tema
        st.markdown("""<div style="display:flex; align-items:center; gap:10px; margin:0 0 8px 0;">
  <span style="display:inline-flex; align-items:center; justify-content:center;
        width:20px; height:20px; border-radius:50%;
        background:#E6F1FB; color:#185FA5;
        font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">2</span>
  <div>
    <div style="font-family:'DM Sans',sans-serif; font-size:11px; font-weight:500;
         color:var(--text-color); letter-spacing:0.06em; text-transform:uppercase; line-height:1;">
      Material del tema</div>
    <div style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.55; margin-top:3px;">
      Uno o varios PDF o PPTX con el contenido te&#243;rico del tema a convertir</div>
  </div>
</div>""", unsafe_allow_html=True)
        uploaded_files = st.file_uploader(
            "Material del tema (PDF o PPTX)",
            type=["pdf", "pptx"],
            accept_multiple_files=True,
            key="material_uploader",
        )
        files: list = list(uploaded_files) if uploaded_files else []
        current_files_hash = tuple(sorted(f.name for f in files))

        st.divider()
        st.button("Procesar", key="procesar_btn", disabled=not bool(files), use_container_width=True)

    # ── Área principal ────────────────────────────────────────────────────────
    render_hero(
        agent_number="02",
        title_keyword="contenido",
        steps=["Organizaci&#243;n", "Material", "Procesar"],
        title_before="Generaci&#243;n de ",
        description=(
            "Convierte tus PDFs y PPTXs en Markdown estructurado, fiel al original "
            "y listo para reutilizar."
        ),
        upload_zone_background=True,
    )

    if files and any(Path(f.name).suffix.lower() == ".pdf" for f in files):
        st.warning(
            "Si este archivo es una presentación exportada desde PowerPoint, los "
            "resultados serán limitados. Para mejor fidelidad, sube el archivo "
            ".pptx original."
        )

    if files:
        if st.session_state.get("procesar_btn"):
            st.session_state["resultados"] = []
            st.session_state["archivos_hash"] = current_files_hash

            if bloque_seleccionado:
                n_sb = len(bloque_subbloques)
                sb_info = f", {n_sb} subbloques" if n_sb > 0 else ""
                st.info(
                    f"Procesando con contexto de densidad: **{bloque_seleccionado}** "
                    f"({tema_horas}h{sb_info})"
                )

            for uploaded in files:
                name = uploaded.name
                stem = Path(name).stem
                tmp_path: str | None = None

                with st.status(name, expanded=True) as status:
                    try:
                        suffix = Path(name).suffix
                        with tempfile.NamedTemporaryFile(
                            delete=False, suffix=suffix
                        ) as tmp:
                            tmp.write(uploaded.getbuffer())
                            tmp_path = tmp.name

                        status.write("Extracción…")
                        text = extract_text(tmp_path)

                        if bloque_subbloques:
                            # ── Pipeline con subbloques ───────────────────────
                            status.write("Segmentación por subbloques…")
                            segments = segment_text_by_subbloques(text, bloque_subbloques)

                            sb_results: list[SubbloqueResult] = []
                            all_items: list[dict] = []

                            for sb_idx, (sb_meta, seg_text) in enumerate(segments):
                                sb_nombre = sb_meta.get("nombre", f"Subbloque {sb_idx + 1}")
                                sb_horas = float(sb_meta.get("horas", 0.0) or 0.0)
                                effective_horas = sb_horas if sb_horas > 0 else tema_horas
                                sb_label = f"Subbloque {sb_idx + 1}/{len(segments)}: {sb_nombre}"

                                status.write(f"{sb_label}…")

                                sb_result = _process_subbloque(
                                    seg_text=seg_text,
                                    sb_meta=sb_meta,
                                    effective_horas=effective_horas,
                                    sb_label=sb_label,
                                    nombre_del_archivo=name,
                                    status=status,
                                )
                                sb_results.append(sb_result)
                                all_items.extend(sb_result.items)

                            status.write("Ensamblado…")
                            output_md = assemble_block_with_subbloques(
                                [sb.to_dict() for sb in sb_results],
                                nombre_del_archivo=name,
                                nombre_bloque=bloque_seleccionado or stem,
                                bloque_horas=tema_horas or 0.0,
                            )

                            report = {
                                "ok": all(
                                    sb.validacion.get("ok", True) for sb in sb_results
                                ),
                                "errores": [
                                    e
                                    for sb in sb_results
                                    for e in sb.validacion.get("errores", [])
                                ],
                                "fidelity": [
                                    f
                                    for sb in sb_results
                                    for f in sb.validacion.get("fidelity", [])
                                ],
                            }
                            progreso = calcular_progreso_bloque(sb_results)

                            st.session_state["resultados"].append(
                                {
                                    "nombre": name,
                                    "stem": stem,
                                    "markdown": output_md,
                                    "subbloques": [sb.to_dict() for sb in sb_results],
                                    "progreso": progreso,
                                    "items": all_items,
                                    "validacion": report,
                                    "error": None,
                                }
                            )

                        else:
                            # ── Pipeline clásico (sin subbloques) ────────────
                            status.write("Chunks…")
                            chunks = split_into_chunks(text)
                            n_chunks = len(chunks)

                            if n_chunks == 0:
                                items: list = []
                            else:
                                status.write(f"Clasificación… (0/{n_chunks})")
                                ordered: list = [None] * n_chunks
                                done = 0
                                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                                    future_to_i = {
                                        pool.submit(classify_and_format, chunk, tema_horas): i
                                        for i, chunk in enumerate(chunks)
                                    }
                                    for fut in as_completed(future_to_i):
                                        i = future_to_i[fut]
                                        try:
                                            ordered[i] = fut.result()
                                        except Exception as chunk_exc:
                                            error_msg = str(chunk_exc)
                                            st.warning(
                                                f"⚠️ Error en chunk {i + 1}/{n_chunks}: "
                                                f"{error_msg}"
                                            )
                                            ordered[i] = {
                                                "tipo": "mixto",
                                                "titulo_detectado": None,
                                                "idioma": "es",
                                                "contenido_markdown": (
                                                    f"[ERROR EN CHUNK {i + 1}: {error_msg}]"
                                                ),
                                            }
                                        done += 1
                                        status.write(
                                            f"Clasificación… ({done}/{n_chunks})"
                                        )
                                items = ordered

                            status.write("Ensamblado…")
                            output_md = assemble_markdown(items, nombre_del_archivo=name)

                            status.write("Validación…")
                            report = validate_items(items, original_chunks=chunks)

                            if not report.get("ok"):
                                failed_fidelity = [
                                    r
                                    for r in (report.get("fidelity") or [])
                                    if not r.get("passed", True)
                                ]
                                if failed_fidelity:
                                    min_score = min(
                                        r["coverage_score"] for r in failed_fidelity
                                    )
                                    st.warning(
                                        f"⚠️ Fidelidad léxica por debajo del umbral "
                                        f"(score: {min_score:.2f} < {FIDELITY_THRESHOLD}). "
                                        f"Revisa el output antes de usar."
                                    )

                            # Envuelve en estructura de subbloque único para
                            # mantener el formato de session_state consistente.
                            sb_nombre = bloque_seleccionado or stem
                            sb_dict = {
                                "nombre": sb_nombre,
                                "horas": tema_horas or 0.0,
                                "evidencia": "Sin señal verificable",
                                "origen": "Fallback",
                                "estado": "generado",
                                "markdown": output_md,
                                "items": items,
                                "validacion": report,
                            }
                            st.session_state["resultados"].append(
                                {
                                    "nombre": name,
                                    "stem": stem,
                                    "markdown": output_md,
                                    "subbloques": [sb_dict],
                                    "progreso": {
                                        "total": 1,
                                        "aprobados": 0,
                                        "porcentaje": 0.0,
                                    },
                                    "items": items,
                                    "validacion": report,
                                    "error": None,
                                }
                            )

                        status.update(label=f"Completado: {name}", state="complete")

                    except Exception as exc:  # noqa: BLE001
                        status.update(label=f"Error: {name}", state="error")
                        status.write(str(exc))
                        st.session_state["resultados"].append(
                            {
                                "nombre": name,
                                "stem": stem,
                                "markdown": "",
                                "subbloques": [],
                                "progreso": {"total": 0, "aprobados": 0, "porcentaje": 0.0},
                                "items": [],
                                "validacion": {},
                                "error": str(exc),
                            }
                        )
                    finally:
                        if tmp_path:
                            try:
                                Path(tmp_path).unlink(missing_ok=True)
                            except OSError:
                                pass

    if not st.session_state["resultados"] and not files:
        st.info(
            "Sube la organización del tema (.md) y uno o varios archivos PDF o PPTX, "
            "luego pulsa **Procesar** para comenzar. "
            "El archivo de organización es opcional."
        )

    if st.session_state["resultados"]:
        if current_files_hash != st.session_state.get("archivos_hash", tuple()):
            st.warning(
                "⚠️ Los archivos han cambiado. Pulsa 'Procesar' para actualizar los resultados."
            )

        ok = [r for r in st.session_state["resultados"] if not r.get("error")]
        if len(ok) > 1:
            unified_md = assemble_multiple(ok)
            n_ok = len(ok)
            unified_fn = unified_download_filename([r["stem"] for r in ok])
            st.download_button(
                label=f"Descargar todo unificado ({n_ok} archivos)",
                data=unified_md,
                file_name=unified_fn,
                mime="text/markdown",
                key="dl_unificado",
            )
            st.divider()

        for i, res in enumerate(st.session_state["resultados"]):
            with st.expander(res["nombre"], expanded=False):
                if res["error"]:
                    st.error(f"Error: {res['error']}")
                else:
                    # Metadata pills (del frontmatter del primer resultado)
                    lineas_frontmatter = [
                        ln
                        for ln in res["markdown"].split("\n")
                        if ln.startswith(
                            (
                                "archivo_origen",
                                "bloque",
                                "tipo_documento",
                                "idioma",
                                "tema_detectado",
                                "fecha_procesado",
                                "total_subbloques",
                            )
                        )
                    ]
                    if lineas_frontmatter:
                        pills_html = "".join(
                            f'<span style="display:inline-block; font-size:11px; '
                            f'background:rgba(128,128,128,0.07); border-radius:4px; '
                            f'padding:3px 8px; margin:0 4px 4px 0; '
                            f'color:var(--text-color); opacity:0.75;">{ln}</span>'
                            for ln in lineas_frontmatter
                        )
                        st.markdown(
                            f'<div style="display:flex; flex-wrap:wrap; margin-bottom:10px;">'
                            f"{pills_html}</div>",
                            unsafe_allow_html=True,
                        )

                    # Métricas de subbloques o chunks
                    subbloques_list = res.get("subbloques") or []
                    progreso = res.get("progreso") or {}
                    has_real_subbloques = len(subbloques_list) > 1

                    if has_real_subbloques:
                        n_sb = len(subbloques_list)
                        aprobados = progreso.get("aprobados", 0)
                        pct = progreso.get("porcentaje", 0.0)
                        col_sb, col_aprob, col_rest = st.columns([1, 1, 2])
                        with col_sb:
                            st.metric("Subbloques", n_sb)
                        with col_aprob:
                            st.metric("Aprobados", f"{aprobados}/{n_sb}", f"{pct:.1f}%")
                        with col_rest:
                            estados_counter = Counter(
                                sb.get("estado", "?") for sb in subbloques_list
                            )
                            st.caption(
                                " · ".join(f"{v} {k}" for k, v in estados_counter.items())
                            )
                    else:
                        n_bloques = len(res.get("items") or [])
                        tipos = [it.get("tipo", "?") for it in (res.get("items") or [])]
                        conteo = Counter(tipos)
                        resumen = " · ".join(f"{v} {k}" for k, v in conteo.items())
                        col_total, col_rest = st.columns([1, 3])
                        with col_total:
                            st.metric("Bloques totales", n_bloques)
                        with col_rest:
                            st.caption(resumen)

                    st.download_button(
                        label=f"Descargar {res['stem']}_curado.md",
                        data=res["markdown"],
                        file_name=f"{res['stem']}_curado.md",
                        mime="text/markdown",
                        key=f"dl_{i}",
                    )

                    with st.expander("Ver reporte de fidelidad", expanded=False):
                        st.json(res["validacion"])


if __name__ == "__main__":
    main()
