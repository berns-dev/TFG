"""UI Streamlit para el pipeline de Agente_contenido."""

from __future__ import annotations

import re
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from assembler import assemble_markdown, assemble_multiple, unified_download_filename
from chunker import split_into_chunks
from classifier import classify_and_format
from config import MAX_WORKERS
from extractor import extract_text
from validator import validate_items


def parse_organization_md(content: str) -> list[dict]:
    """Extrae bloques y horas de un .md generado por el Agente Organizador.

    Detecta líneas con el patrón:  ## Nombre del bloque · Xh
    Devuelve lista de dicts con 'nombre' y 'horas'.
    """
    pattern = re.compile(r"^#{1,3}\s+(.+?)\s*·\s*([\d,.]+)h", re.MULTILINE)
    bloques = []
    for m in pattern.finditer(content):
        nombre = m.group(1).strip()
        horas_str = m.group(2).replace(",", ".")
        try:
            horas = float(horas_str)
        except ValueError:
            continue
        bloques.append({"nombre": nombre, "horas": horas})
    return bloques


_HERO_CONT_HTML = """<!DOCTYPE html><html><head>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
:root{
  --text1:#2C2C2A;--text2:#5F5E5A;--text3:#888780;
  --card:rgba(0,0,0,0.03);--border:rgba(0,0,0,0.1);--arrow:rgba(0,0,0,0.2);
}
:root.dark{
  --text1:#FAFAFA;--text2:rgba(255,255,255,0.65);--text3:rgba(255,255,255,0.4);
  --card:rgba(255,255,255,0.06);--border:rgba(255,255,255,0.1);--arrow:rgba(255,255,255,0.22);
}
@media(prefers-color-scheme:dark){:root:not(.light){
  --text1:#FAFAFA;--text2:rgba(255,255,255,0.65);--text3:rgba(255,255,255,0.4);
  --card:rgba(255,255,255,0.06);--border:rgba(255,255,255,0.1);--arrow:rgba(255,255,255,0.22);
}}
body{background:transparent;font-family:'DM Sans',sans-serif;overflow:hidden;padding:0 2px;}
.hero{padding:32px 0 16px 0;}
.eyebrow{font-size:11px;font-weight:500;color:#185FA5;letter-spacing:.14em;
  text-transform:uppercase;margin-bottom:12px;}
.title{font-family:'Playfair Display',serif;font-size:38px;font-weight:500;
  color:var(--text1);line-height:1.15;margin-bottom:14px;}
.title .accent{color:#185FA5;}
.desc{font-size:15px;font-weight:400;color:var(--text2);line-height:1.6;max-width:560px;}
.workflow{display:flex;align-items:center;margin-top:28px;padding:18px 24px;
  background:var(--card);border:.5px solid var(--border);border-radius:10px;}
.step{display:flex;align-items:center;gap:12px;flex:1;}
.num{width:30px;height:30px;border-radius:50%;background:#185FA5;color:#FFF;
  font-size:13px;font-weight:500;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;box-shadow:0 2px 8px rgba(24,95,165,.25);}
.lbl{font-size:10px;font-weight:500;color:var(--text3);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:3px;}
.sdesc{font-size:13px;font-weight:500;color:var(--text1);}
.arrow{flex-shrink:0;margin:0 8px;color:var(--arrow);}
</style>
<script>
(function(){
  function sync(){
    try{
      var p=window.parent,doc=p.document;
      var els=[doc.body,doc.documentElement];
      for(var i=0;i<els.length;i++){
        var cs=p.getComputedStyle(els[i]);
        var bg=cs.backgroundColor;
        var m=bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
        if(!m) continue;
        var alpha=m[4]===undefined?1:parseFloat(m[4]);
        if(alpha<0.1) continue;
        var lum=(0.299*+m[1]+0.587*+m[2]+0.114*+m[3])/255;
        document.documentElement.classList.toggle('dark',lum<0.5);
        document.documentElement.classList.toggle('light',lum>=0.5);
        document.body.style.backgroundColor=bg;
        return;
      }
    }catch(e){}
  }
  sync();setInterval(sync,800);
})();
</script>
</head><body>
<div class="hero">
  <div class="eyebrow">Agente 02</div>
  <div class="title">Generaci&#243;n de <span class="accent">contenido</span></div>
  <div class="desc">Convierte tus PDFs y PPTXs en Markdown estructurado, fiel al original y listo para reutilizar.</div>
  <div class="workflow">
    <div class="step">
      <div class="num">1</div>
      <div><div class="lbl">Paso 1</div><div class="sdesc">Organizaci&#243;n</div></div>
    </div>
    <svg class="arrow" width="20" height="12" viewBox="0 0 20 12" fill="none">
      <path d="M0 6h16M12 2l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div class="step">
      <div class="num">2</div>
      <div><div class="lbl">Paso 2</div><div class="sdesc">Material</div></div>
    </div>
    <svg class="arrow" width="20" height="12" viewBox="0 0 20 12" fill="none">
      <path d="M0 6h16M12 2l4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <div class="step">
      <div class="num">3</div>
      <div><div class="lbl">Paso 3</div><div class="sdesc">Procesar</div></div>
    </div>
  </div>
</div>
</body></html>"""


def main() -> None:
    if "resultados" not in st.session_state:
        st.session_state["resultados"] = []
    if "archivos_hash" not in st.session_state:
        st.session_state["archivos_hash"] = tuple()
    if "org_bloques" not in st.session_state:
        st.session_state["org_bloques"] = []

    st.set_page_config(page_title="Agente contenido", layout="wide")

    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap');

[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] {
    background-color: var(--background-color) !important;
}
section[data-testid="stMain"] > div {
    background-color: var(--background-color) !important;
}
[data-testid="stSidebar"] {
    background-color: var(--secondary-background-color) !important;
    border-right: 1px solid rgba(128,128,128,0.2) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background-color: var(--secondary-background-color) !important;
    border-radius: 10px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
}
[data-testid="stFileUploaderDropzone"] {
    border-radius: 10px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
    background-color: var(--secondary-background-color) !important;
}
.stButton > button {
    background-color: #185FA5 !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em;
}
.stButton > button:hover {
    background-color: #0C447C !important;
}
.stDownloadButton > button {
    border-radius: 12px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
    color: #185FA5 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
}
.stDownloadButton > button:hover {
    background-color: rgba(24,95,165,0.05) !important;
}
[data-testid="stExpander"] {
    background-color: var(--secondary-background-color) !important;
    border: 0.5px solid rgba(128,128,128,0.2) !important;
    border-radius: 10px !important;
}
</style>
""",
        unsafe_allow_html=True,
    )

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
            else:
                st.warning(
                    "No se detectaron bloques con formato '· Xh' en el archivo. "
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
    components.html(_HERO_CONT_HTML, height=340, scrolling=False)

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
                st.info(
                    f"Procesando con contexto de densidad: **{bloque_seleccionado}** "
                    f"({tema_horas}h)"
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

                        status.write("Chunks…")
                        chunks = split_into_chunks(text)

                        n_chunks = len(chunks)
                        if n_chunks == 0:
                            items = []
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
                        output_md = assemble_markdown(
                            items, nombre_del_archivo=name
                        )

                        status.write("Validación…")
                        report = validate_items(items, original_chunks=chunks)

                        st.session_state["resultados"].append(
                            {
                                "nombre": name,
                                "stem": stem,
                                "markdown": output_md,
                                "items": items,
                                "validacion": report,
                                "error": None,
                            }
                        )

                        status.update(
                            label=f"Completado: {name}",
                            state="complete",
                        )
                    except Exception as exc:  # noqa: BLE001
                        status.update(
                            label=f"Error: {name}",
                            state="error",
                        )
                        status.write(str(exc))
                        st.session_state["resultados"].append(
                            {
                                "nombre": name,
                                "stem": stem,
                                "markdown": "",
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
                    lineas_frontmatter = [
                        ln
                        for ln in res["markdown"].split("\n")
                        if ln.startswith(
                            (
                                "archivo_origen",
                                "tipo_documento",
                                "idioma",
                                "tema_detectado",
                                "fecha_procesado",
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

                    n_bloques = len(res["items"])
                    tipos = [it.get("tipo", "?") for it in res["items"]]
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
