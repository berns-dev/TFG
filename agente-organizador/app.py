import sys
from pathlib import Path

import streamlit as st

_SUITE_ROOT = Path(__file__).resolve().parent.parent
if str(_SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUITE_ROOT))

from shared.ui_hero import render_hero

from agente import ejecutar_agente
from parser import (
    clasificar_archivo,
    construir_nombre_descarga,
    contar_bloques_output,
    extraer_candidatos_con_evidencia,
    extraer_horas_docencia,
    extraer_subtemas_guia,
    extraer_texto,
    hay_discrepancia,
    normalizar_horas_output,
    normalizar_subtema,
    parsear_bloques_desde_markdown,
    regenerar_markdown_desde_bloques,
)
from prompts import construir_prompt, construir_prompt_refinamiento


st.set_page_config(page_title="Agente Organizador de Contenidos", layout="wide")
if "ultimo_output" not in st.session_state:
    st.session_state["ultimo_output"] = None
if "historial_feedback" not in st.session_state:
    st.session_state["historial_feedback"] = []
if "iteracion" not in st.session_state:
    st.session_state["iteracion"] = 1
if "ultimos_archivos_teoria" not in st.session_state:
    st.session_state["ultimos_archivos_teoria"] = []
if "ultimos_archivos_contexto" not in st.session_state:
    st.session_state["ultimos_archivos_contexto"] = []
if "ultimas_horas_teoria" not in st.session_state:
    st.session_state["ultimas_horas_teoria"] = None
if "ultimas_horas_totales" not in st.session_state:
    st.session_state["ultimas_horas_totales"] = None
if "session_id_archivos" not in st.session_state:
    st.session_state["session_id_archivos"] = ""
if "ultimo_nombre_descarga" not in st.session_state:
    st.session_state["ultimo_nombre_descarga"] = "Propuesta_asignatura.md"
if "warning_cardinalidad" not in st.session_state:
    st.session_state["warning_cardinalidad"] = None
if "warning_normalizacion" not in st.session_state:
    st.session_state["warning_normalizacion"] = None
if "subtemas_editor" not in st.session_state:
    st.session_state["subtemas_editor"] = []
if "fase" not in st.session_state:
    st.session_state["fase"] = None
if "organizacion_bloques" not in st.session_state:
    st.session_state["organizacion_bloques"] = []
if "contador_add_subtema" not in st.session_state:
    st.session_state["contador_add_subtema"] = {}
if "contador_add_bloque" not in st.session_state:
    st.session_state["contador_add_bloque"] = 0


def _validar_y_persistir(resultado: str, n_esperados: int, nombre_descarga: str | None = None) -> None:
    """Valida cardinalidad y persiste el output en session_state."""
    n_generados = contar_bloques_output(resultado)
    if n_generados != n_esperados:
        st.session_state["warning_cardinalidad"] = {
            "esperados": n_esperados,
            "generados": n_generados,
        }
    else:
        st.session_state["warning_cardinalidad"] = None

    st.session_state["ultimo_output"] = resultado
    if nombre_descarga is not None:
        st.session_state["ultimo_nombre_descarga"] = nombre_descarga

    # Parsear en estado estructurado para edición manual y establecer fase "resultado".
    st.session_state["organizacion_bloques"] = parsear_bloques_desde_markdown(resultado)
    st.session_state["contador_add_subtema"] = {}
    st.session_state["contador_add_bloque"] = 0
    st.session_state["fase"] = "resultado"


def extraer_y_detectar(guia_docente, materiales_teoria) -> bool:
    """Fase 1: extrae texto y detecta candidatos de subtemas determinísticamente.
    No llama al LLM. Almacena los datos del editor en session_state y pone
    fase='editar' para que el área principal muestre el revisor de subtemas.
    """
    if guia_docente is None or not materiales_teoria:
        st.error("Debes subir guía docente y materiales de teoría.")
        return False

    with st.status("Extrayendo y detectando subtemas...", expanded=True) as status:
        try:
            st.write("📄 Extrayendo texto de la guía docente...")
            texto_guia = extraer_texto(guia_docente.getvalue(), guia_docente.name)
            candidatos_guia = extraer_subtemas_guia(texto_guia)

            st.write("📚 Extrayendo y clasificando materiales de teoría...")
            textos_teoria_raw: list[str] = []
            archivos_teoria: list[str] = []
            archivos_teoria_bytes: list[bytes] = []
            archivos_contexto: list[str] = []

            for archivo in materiales_teoria:
                try:
                    archivo_bytes = archivo.getvalue()
                    texto_material = extraer_texto(archivo_bytes, archivo.name)
                    categoria = clasificar_archivo(archivo.name, texto_material)
                    if categoria == "contexto":
                        archivos_contexto.append(archivo.name)
                        st.write(f"  → {archivo.name} → contexto")
                    else:
                        textos_teoria_raw.append(texto_material)
                        archivos_teoria.append(archivo.name)
                        archivos_teoria_bytes.append(archivo_bytes)
                        st.write(f"  → {archivo.name} → teoría")
                except Exception as error_archivo:
                    st.warning(f"No se pudo procesar '{archivo.name}': {error_archivo}")

            if not textos_teoria_raw:
                status.update(label="❌ Error", state="error")
                st.error("No se pudo extraer texto válido de ningún material de teoría.")
                return False

            st.write("🔍 Detectando señales estructurales (secciones numeradas, títulos de diapositiva)...")
            editor_data: list[dict] = []
            for texto_mat, nombre_arch, bytes_arch in zip(
                textos_teoria_raw, archivos_teoria, archivos_teoria_bytes
            ):
                cands_con_ev = extraer_candidatos_con_evidencia(texto_mat, nombre_arch, bytes_arch)

                if cands_con_ev:
                    candidatos = [c["nombre"] for c in cands_con_ev]
                    cands_mat_orig = candidatos[:]  # para origen "Detectado"
                    origen_base = "material"
                    discrepancia = hay_discrepancia(candidatos, candidatos_guia)
                elif candidatos_guia:
                    cands_con_ev = [
                        {"nombre": c, "evidencia": "Guía docente", "fuente": "guia"}
                        for c in candidatos_guia
                    ]
                    candidatos = candidatos_guia
                    cands_mat_orig = []
                    origen_base = "guia"
                    discrepancia = False
                else:
                    cands_con_ev = []
                    candidatos = []
                    cands_mat_orig = []
                    origen_base = "ninguno"
                    discrepancia = False

                editor_data.append({
                    "archivo": nombre_arch,
                    "candidatos": candidatos,
                    "candidatos_con_evidencia": cands_con_ev,
                    "candidatos_mat_orig": cands_mat_orig,
                    "origen": origen_base,
                    "discrepancia": discrepancia,
                    "tiene_senales_material": origen_base == "material",
                })

            # Detectar horas ya en fase 1 para que el expander esté disponible.
            horas_docencia = extraer_horas_docencia(texto_guia)
            st.session_state["ultimas_horas_teoria"] = horas_docencia
            st.session_state["ultimos_archivos_teoria"] = archivos_teoria
            st.session_state["ultimos_archivos_contexto"] = archivos_contexto
            st.session_state["subtemas_editor"] = editor_data
            st.session_state["fase"] = "editar"

            status.update(
                label="✅ Subtemas detectados — revisa y confirma en el área principal",
                state="complete",
            )
            return True
        except Exception as error:
            status.update(label="❌ Error en la extracción", state="error")
            st.error(f"Error durante la extracción: {error}")
            return False


def generar_organizacion(
    guia_docente,
    materiales_teoria,
    feedback_previo: list[str] | None = None,
    subtemas_confirmados: list[list[dict]] | None = None,
) -> bool:
    # ── Camino rápido: refinamiento sobre output existente ────────────────────
    # Se activa cuando hay feedback Y ya existe un output previo válido.
    # No re-extrae documentos ni re-detecta horas: solo aplica el ajuste.
    output_previo = st.session_state.get("ultimo_output")
    if feedback_previo and output_previo:
        with st.status("Aplicando ajuste...", expanded=True) as status:
            try:
                horas_totales = st.session_state.get("ultimas_horas_totales")
                n_esperados = len(st.session_state.get("ultimos_archivos_teoria", []))

                prompt = construir_prompt_refinamiento(
                    output_previo=output_previo,
                    feedback_previo=feedback_previo,
                    horas_totales=horas_totales,
                )

                st.write("🤖 Aplicando ajuste sobre la organización actual...")
                resultado = ejecutar_agente(prompt)

                resultado, info_norm = normalizar_horas_output(
                    resultado, horas_totales or 0
                )
                st.session_state["warning_normalizacion"] = info_norm

                _validar_y_persistir(resultado, n_esperados)
                status.update(label="✅ Ajuste aplicado", state="complete")
                return True
            except Exception as error:
                status.update(label="❌ Error al aplicar el ajuste", state="error")
                st.error(f"Error durante el refinamiento: {error}")
                return False

    # ── Camino completo: primera generación ───────────────────────────────────
    if guia_docente is None:
        st.error("Debes subir una guía docente para generar la organización.")
        return False
    if not materiales_teoria:
        st.error("Debes subir al menos un material de teoría.")
        return False

    with st.status("Procesando documentos...", expanded=True) as status:
        try:
            st.write("📄 Extrayendo texto de la guía docente...")
            texto_guia = extraer_texto(guia_docente.getvalue(), guia_docente.name)

            st.write("📚 Extrayendo y clasificando materiales de teoría...")
            textos_teoria = []
            textos_contexto = []
            archivos_teoria = []
            archivos_contexto = []

            for archivo in materiales_teoria:
                try:
                    texto_material = extraer_texto(archivo.getvalue(), archivo.name)
                    categoria = clasificar_archivo(archivo.name, texto_material)
                    if categoria == "contexto":
                        textos_contexto.append(texto_material)
                        archivos_contexto.append(archivo.name)
                        st.write(f"  → {archivo.name} → contexto")
                    else:
                        textos_teoria.append(texto_material)
                        archivos_teoria.append(archivo.name)
                        st.write(f"  → {archivo.name} → teoría")
                except Exception as error_archivo:
                    st.warning(f"No se pudo procesar '{archivo.name}': {error_archivo}")

            if not textos_teoria:
                status.update(label="❌ Error en el proceso", state="error")
                st.error("No se pudo extraer texto válido de ningún material de teoría.")
                return False

            # Si el volumen total es muy alto, se trunca por archivo para evitar saturar el modelo.
            longitud_total_materiales = sum(len(t) for t in textos_teoria) + sum(len(t) for t in textos_contexto)
            if longitud_total_materiales > 120000:
                textos_teoria = [t[:20000] for t in textos_teoria]
                textos_contexto = [t[:20000] for t in textos_contexto]
                st.info(
                    "Materiales truncados a 20.000 caracteres por archivo "
                    "para evitar superar el límite del modelo."
                )

            st.session_state["ultimos_archivos_teoria"] = archivos_teoria
            st.session_state["ultimos_archivos_contexto"] = archivos_contexto

            st.write("🕐 Detectando horas lectivas (TE + PA) y laboratorio...")
            horas_docencia = extraer_horas_docencia(texto_guia)
            horas_teoria = horas_docencia["horas_teoria"]
            horas_aula = horas_docencia["horas_aula"]
            horas_laboratorio = horas_docencia["horas_laboratorio"]
            horas_totales = horas_teoria + horas_aula

            if horas_totales == 0:
                st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")
            st.session_state["ultimas_horas_teoria"] = horas_docencia
            st.session_state["ultimas_horas_totales"] = horas_totales if horas_totales > 0 else None

            st.write("🌐 Detectando idioma de los materiales...")
            prompt, _idioma = construir_prompt(
                texto_guia=texto_guia,
                textos_teoria=textos_teoria,
                textos_contexto=textos_contexto,
                horas_totales=horas_totales if horas_totales > 0 else None,
                horas_laboratorio=horas_laboratorio,
                subtemas_por_material=subtemas_confirmados,
            )

            st.write("🤖 Consultando al agente (esto puede tardar ~15s)...")
            resultado = ejecutar_agente(prompt)

            resultado, info_norm = normalizar_horas_output(
                resultado, horas_totales if horas_totales else 0
            )
            st.session_state["warning_normalizacion"] = info_norm

            _validar_y_persistir(
                resultado,
                n_esperados=len(textos_teoria),
                nombre_descarga=construir_nombre_descarga(texto_guia),
            )
            status.update(label="✅ Organización generada", state="complete")
            return True
        except Exception as error:
            status.update(label="❌ Error en el proceso", state="error")
            st.error(f"Error durante la generación: {error}")
            return False


with st.sidebar:
    st.markdown("""
<div style="padding-bottom:20px; border-bottom:1px solid rgba(128,128,128,0.2); margin-bottom:8px;">
  <div style="font-family:'DM Sans',sans-serif; font-size:11px; font-weight:500;
       color:var(--text-color); opacity:0.55; letter-spacing:0.1em; text-transform:uppercase; margin-bottom:8px;">
    Suite de Agentes
  </div>
  <div style="font-family:'DM Sans',sans-serif; font-size:16px; font-weight:500;
       color:var(--text-color); letter-spacing:-0.2px; line-height:1.2;">
    Agente Organizador
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
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Sube la gu&#237;a docente</span>
  </div>
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="display:inline-flex; align-items:center; justify-content:center;
          width:20px; height:20px; border-radius:50%;
          background:#E6F1FB; color:#185FA5;
          font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">2</span>
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Sube los materiales</span>
  </div>
  <div style="display:flex; align-items:center; gap:10px;">
    <span style="display:inline-flex; align-items:center; justify-content:center;
          width:20px; height:20px; border-radius:50%;
          background:#E6F1FB; color:#185FA5;
          font-family:'DM Sans',sans-serif; font-size:10px; font-weight:500; flex-shrink:0;">3</span>
    <span style="font-family:'DM Sans',sans-serif; font-size:12px; color:var(--text-color); opacity:0.7;">Genera la propuesta</span>
  </div>
</div>
""", unsafe_allow_html=True)
    st.divider()
    guia_docente = st.file_uploader(
        "Sube la guía docente",
        type=["pdf"],
        accept_multiple_files=False,
    )
    materiales_teoria = st.file_uploader(
        "Sube los materiales de teoría",
        type=["pdf", "pptx"],
        accept_multiple_files=True,
    )
    st.divider()
    # Se detecta cambio de archivos para resetear estado entre asignaturas distintas.
    nombres_actuales = []
    if guia_docente is not None:
        nombres_actuales.append(f"guia:{guia_docente.name}")
    if materiales_teoria:
        nombres_actuales.extend(f"mat:{archivo.name}" for archivo in materiales_teoria)
    session_id_actual = "|".join(sorted(nombres_actuales))
    if session_id_actual and session_id_actual != st.session_state["session_id_archivos"]:
        st.session_state["ultimo_output"] = None
        st.session_state["historial_feedback"] = []
        st.session_state["iteracion"] = 1
        st.session_state["warning_cardinalidad"] = None
        st.session_state["warning_normalizacion"] = None
        st.session_state["subtemas_editor"] = []
        st.session_state["fase"] = None
        st.session_state["organizacion_bloques"] = []
        st.session_state["contador_add_subtema"] = {}
        st.session_state["contador_add_bloque"] = 0
        st.session_state["session_id_archivos"] = session_id_actual

    puede_generar = guia_docente is not None and len(materiales_teoria or []) > 0

    if st.button("Generar organización", disabled=not puede_generar, use_container_width=True):
        st.session_state["historial_feedback"] = []
        st.session_state["iteracion"] = 1
        st.session_state["ultimo_output"] = None
        st.session_state["fase"] = None
        if extraer_y_detectar(guia_docente, materiales_teoria):
            st.rerun()


render_hero(
    agent_number="01",
    title_keyword="curricular",
    steps=["Gu&#237;a docente", "Materiales", "Propuesta"],
    title_before="Organizaci&#243;n ",
    description=(
        "Extrae la distribuci&#243;n tem&#225;tica y las horas lectivas directamente "
        "de tu gu&#237;a docente y materiales de teor&#237;a."
    ),
    button_full_width=True,
)

if st.session_state["ultimo_output"] is None and st.session_state.get("fase") != "editar":
    st.info("Sube los archivos en el panel izquierdo y pulsa **Generar organización** para comenzar.")

with st.expander("⏱️ Validación de horas detectadas", expanded=False):
    horas_info = st.session_state.get("ultimas_horas_teoria") or {}
    horas_teoria = int(horas_info.get("horas_teoria", 0))
    horas_aula = int(horas_info.get("horas_aula", 0))
    horas_laboratorio = int(horas_info.get("horas_laboratorio", 0))
    horas_lectivas = horas_teoria + horas_aula

    col_te_metric, col_pa_metric, col_pl_metric, col_total_metric = st.columns(4)
    with col_te_metric:
        st.metric("Horas TE detectadas", f"{horas_teoria}h")
    with col_pa_metric:
        st.metric("Horas PA detectadas", f"{horas_aula}h")
    with col_pl_metric:
        st.metric("Horas PL (informativo)", f"{horas_laboratorio}h")
    with col_total_metric:
        st.metric("Total TE + PA", f"{horas_lectivas}h")

    if horas_lectivas <= 0:
        st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")

if st.session_state["ultimos_archivos_teoria"] or st.session_state["ultimos_archivos_contexto"]:
    with st.expander("📋 Clasificación de archivos detectada", expanded=False):
        col_teoria, col_contexto = st.columns(2)
        with col_teoria:
            st.subheader("Teoría")
            if st.session_state["ultimos_archivos_teoria"]:
                for nombre in st.session_state["ultimos_archivos_teoria"]:
                    st.write(f"- {nombre}")
            else:
                st.write("Sin archivos clasificados como teoría.")
        with col_contexto:
            st.subheader("Contexto/Outline")
            if st.session_state["ultimos_archivos_contexto"]:
                for nombre in st.session_state["ultimos_archivos_contexto"]:
                    st.write(f"- {nombre}")
            else:
                st.write("Sin archivos clasificados como contexto.")

st.divider()

# ── Editor de subtemas (fase 1 → fase 2) ─────────────────────────────────────
if st.session_state.get("fase") == "editar" and st.session_state["ultimo_output"] is None:
    editor_data = st.session_state.get("subtemas_editor", [])
    if editor_data:
        st.markdown("### Subbloques detectados — revisa y confirma")
        st.caption(
            "Los subbloques se han detectado por señales estructurales verificables en los "
            "materiales (numeración jerárquica o títulos de diapositiva). Edita la lista "
            "antes de generar la propuesta. Si no aparece ninguno, indica los subbloques "
            "manualmente o deja el campo vacío para tratar el bloque como unidad completa."
        )

        for i, bloque_info in enumerate(editor_data):
            nombre_archivo = bloque_info["archivo"]
            candidatos = bloque_info["candidatos"]
            cands_con_ev = bloque_info.get("candidatos_con_evidencia", [])
            discrepancia = bloque_info.get("discrepancia", False)
            tiene_senales = bloque_info.get("tiene_senales_material", False)

            st.markdown(
                f'<div style="font-family:\'DM Sans\',sans-serif; font-size:13px; '
                f'font-weight:500; margin:16px 0 4px 0; color:var(--text-color);">'
                f'Material {i + 1}: <code>{nombre_archivo}</code></div>',
                unsafe_allow_html=True,
            )

            if discrepancia:
                st.warning(
                    "⚠️ La guía docente y el material discrepan en los subtemas de este "
                    "archivo. Se ha usado la lista del material como base — revísala."
                )

            if not tiene_senales:
                st.warning(
                    "⚠️ **Sin señales estructurales verificables.** No se encontraron "
                    "secciones numeradas ni títulos de diapositiva reconocibles en este "
                    "material. Si dejas el campo vacío, el bloque se tratará como un único "
                    "subbloque sin subdivisión (recomendado para no inventar estructura). "
                    "Puedes añadir subbloques manualmente si los conoces."
                )
            elif cands_con_ev:
                # Mostrar tabla de señales detectadas como referencia (read-only)
                fuente_label = {
                    "numeracion": "📑 Sección numerada",
                    "titulo_slide": "📎 Título de diapositiva",
                    "guia": "📋 Guía docente",
                }.get
                st.markdown(
                    '<span style="font-size:12px; opacity:0.7;">Señales estructurales detectadas '
                    '(referencia — edita la lista de abajo si es necesario):</span>',
                    unsafe_allow_html=True,
                )
                for cand in cands_con_ev:
                    tipo = fuente_label(cand.get("fuente", ""), "📌 Señal")
                    ev = cand.get("evidencia", "—")
                    st.markdown(
                        f'<div style="font-size:12px; margin-left:8px; opacity:0.85;">'
                        f'{tipo} &nbsp;·&nbsp; <b>{cand["nombre"]}</b> '
                        f'<span style="color:gray;">({ev})</span></div>',
                        unsafe_allow_html=True,
                    )

            if not candidatos:
                st.info(
                    "No se detectaron subbloques automáticamente. "
                    "Indica los subbloques del bloque manualmente (uno por línea) "
                    "o deja el campo vacío."
                )

            st.text_area(
                "Subbloques (uno por línea — edita, añade o elimina):",
                value="\n".join(candidatos),
                key=f"subtemas_ta_{i}",
                height=max(100, min(300, 30 * len(candidatos) + 60)),
            )

        st.divider()
        if st.button(
            "Confirmar subbloques y generar propuesta",
            type="primary",
            use_container_width=True,
        ):
            subtemas_confirmados: list[list[dict]] = []
            for i, bloque_info in enumerate(editor_data):
                ta_valor = st.session_state.get(f"subtemas_ta_{i}", "")
                lineas = [l.strip() for l in ta_valor.splitlines() if l.strip()]
                cands_orig_norm = {
                    normalizar_subtema(c)
                    for c in bloque_info.get("candidatos_mat_orig", [])
                }
                # Mapa nombre_normalizado → evidencia para asignar la referencia correcta
                ev_map = {
                    normalizar_subtema(c["nombre"]): c.get("evidencia", "")
                    for c in bloque_info.get("candidatos_con_evidencia", [])
                }
                lista: list[dict] = []
                for linea in lineas:
                    clave = normalizar_subtema(linea)
                    origen = "Detectado" if clave in cands_orig_norm else "Manual"
                    evidencia = ev_map.get(clave, "Manual (profesor)" if origen == "Manual" else "")
                    lista.append({"nombre": linea, "origen": origen, "evidencia": evidencia})
                subtemas_confirmados.append(lista)

            if generar_organizacion(
                guia_docente,
                materiales_teoria,
                subtemas_confirmados=subtemas_confirmados,
            ):
                st.rerun()

def _actualizar_desde_bloques() -> None:
    """Regenera ultimo_output desde organizacion_bloques tras una edición manual."""
    bloques = st.session_state.get("organizacion_bloques", [])
    output_actual = st.session_state.get("ultimo_output", "")
    if bloques and output_actual:
        st.session_state["ultimo_output"] = regenerar_markdown_desde_bloques(
            bloques, output_actual
        )


fase_actual = st.session_state.get("fase")

if st.session_state["ultimo_output"] and fase_actual in ("resultado", "cerrado"):

    # ── Aviso de organización cerrada ──────────────────────────────────────
    if fase_actual == "cerrado":
        st.info(
            "✅ **Organización cerrada.** La estructura de bloques y subbloques ha quedado "
            "congelada. Ya no puedes añadir, eliminar ni pedir cambios por prompt. "
            "Descarga el archivo y úsalo como input del Agente Contenido."
        )

    # ── Warnings de cardinalidad y normalización (solo en fase resultado) ──
    if fase_actual == "resultado":
        w = st.session_state.get("warning_cardinalidad")
        if w:
            st.warning(
                f"⚠️ **Discrepancia de bloques detectada:** el output contiene "
                f"**{w['generados']} bloques** pero se esperaban **{w['esperados']}** "
                f"(uno por archivo de teoría subido). "
                f"El modelo probablemente elevó una subsección a bloque independiente. "
                f"Usa el campo de feedback para indicar qué bloque debe reintegrarse como subtema "
                f"y pulsa Regenerar."
            )

        wn = st.session_state.get("warning_normalizacion")
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
                f"en lugar de **{total_obj:.0f}h** (diferencia: {diferencia:+.1f}h). "
                f"Las horas se redistribuyeron proporcionalmente. "
                + (f"Subtemas ajustados: {bloques_ajustados}." if bloques_ajustados else "")
            )

    # ── Output + descarga (siempre visibles) ───────────────────────────────
    st.markdown("### Propuesta generada")
    st.markdown(st.session_state["ultimo_output"])
    st.download_button(
        label="Descargar resultado (.md)",
        data=st.session_state["ultimo_output"],
        file_name=st.session_state.get("ultimo_nombre_descarga", "Propuesta_asignatura.md"),
        mime="text/markdown",
    )

    # ── Edición manual + refinamiento por IA (solo en fase resultado) ──────
    if fase_actual == "resultado":
        st.divider()

        # --- Editor manual de bloques y subbloques ---
        bloques_estado = st.session_state.get("organizacion_bloques", [])
        if bloques_estado:
            with st.expander("✏️ Editar estructura manualmente (añadir / eliminar bloques y subbloques)", expanded=False):
                st.caption(
                    "Los cambios manuales no requieren verificación de señal estructural — "
                    "reflejan el criterio pedagógico del profesor. Coexisten con el refinamiento "
                    "por prompt: ambos mecanismos operan sobre el mismo estado."
                )

                for idx_b, bloque in enumerate(bloques_estado):
                    horas_b = sum(s["horas"] for s in bloque["subtemas"]) if bloque["subtemas"] else bloque["horas"]
                    manual_tag = " *(añadido manualmente)*" if bloque.get("manual") else ""
                    st.markdown(
                        f'<div style="font-family:\'DM Sans\',sans-serif; font-weight:600; '
                        f'font-size:13px; margin-top:14px; color:var(--text-color);">'
                        f'Bloque {bloque["numero"]} — {bloque["nombre"]} · {horas_b:.1f}h'
                        f'{manual_tag}</div>',
                        unsafe_allow_html=True,
                    )

                    # Listar subbloques con botón de eliminar
                    iter_key = st.session_state["iteracion"]
                    for idx_s, sub in enumerate(bloque["subtemas"]):
                        col_sub, col_del = st.columns([6, 1])
                        with col_sub:
                            manual_s = " *(manual)*" if sub.get("manual") else ""
                            st.markdown(
                                f'<div style="font-size:12px; margin-left:12px; '
                                f'padding:2px 0; color:var(--text-color);">'
                                f'• {sub["nombre"]} ({sub["horas"]:.1f}h){manual_s}</div>',
                                unsafe_allow_html=True,
                            )
                        with col_del:
                            if st.button(
                                "🗑",
                                key=f"del_sub_{idx_b}_{idx_s}_{iter_key}",
                                help=f"Eliminar subbloque '{sub['nombre']}'",
                            ):
                                st.session_state["organizacion_bloques"][idx_b]["subtemas"].pop(idx_s)
                                _actualizar_desde_bloques()
                                st.rerun()

                    # Añadir nuevo subbloque
                    ctr_s = st.session_state["contador_add_subtema"].get(idx_b, 0)
                    col_ns1, col_ns2, col_ns3 = st.columns([3, 1, 1])
                    with col_ns1:
                        nuevo_sub_nombre = st.text_input(
                            "Nuevo subbloque",
                            key=f"ns_nombre_{idx_b}_{ctr_s}",
                            label_visibility="collapsed",
                            placeholder="Nombre del subbloque...",
                        )
                    with col_ns2:
                        nuevo_sub_horas = st.number_input(
                            "Horas",
                            min_value=0.0,
                            step=0.5,
                            key=f"ns_horas_{idx_b}_{ctr_s}",
                            label_visibility="collapsed",
                        )
                    with col_ns3:
                        if st.button("+ Añadir", key=f"btn_ns_{idx_b}_{ctr_s}"):
                            nombre_ns = st.session_state.get(f"ns_nombre_{idx_b}_{ctr_s}", "").strip()
                            if nombre_ns:
                                horas_ns = float(st.session_state.get(f"ns_horas_{idx_b}_{ctr_s}", 0.0))
                                st.session_state["organizacion_bloques"][idx_b]["subtemas"].append({
                                    "nombre": nombre_ns,
                                    "horas": horas_ns,
                                    "manual": True,
                                })
                                ctrs = st.session_state["contador_add_subtema"]
                                ctrs[idx_b] = ctr_s + 1
                                st.session_state["contador_add_subtema"] = ctrs
                                _actualizar_desde_bloques()
                                st.rerun()

                    # Eliminar bloque completo
                    if st.button(
                        f"🗑 Eliminar bloque completo",
                        key=f"del_bloque_{idx_b}_{iter_key}",
                        help=f"Eliminar el bloque '{bloque['nombre']}' y todos sus subbloques",
                    ):
                        st.session_state["organizacion_bloques"].pop(idx_b)
                        _actualizar_desde_bloques()
                        st.rerun()

                    st.markdown(
                        '<hr style="border:none; border-top:1px solid rgba(128,128,128,0.15); margin:8px 0;">',
                        unsafe_allow_html=True,
                    )

                # Añadir nuevo bloque
                ctr_b = st.session_state["contador_add_bloque"]
                st.markdown("**Añadir bloque:**")
                col_nb1, col_nb2 = st.columns([4, 1])
                with col_nb1:
                    nuevo_bloque_nombre = st.text_input(
                        "Nombre del nuevo bloque",
                        key=f"nb_nombre_{ctr_b}",
                        label_visibility="collapsed",
                        placeholder="Nombre del nuevo bloque...",
                    )
                with col_nb2:
                    if st.button("+ Añadir bloque", key=f"btn_nb_{ctr_b}"):
                        nombre_nb = st.session_state.get(f"nb_nombre_{ctr_b}", "").strip()
                        if nombre_nb:
                            nums_existentes = [b["numero"] for b in st.session_state["organizacion_bloques"]]
                            nuevo_num = max(nums_existentes) + 1 if nums_existentes else 1
                            st.session_state["organizacion_bloques"].append({
                                "numero": nuevo_num,
                                "nombre": nombre_nb,
                                "horas": 0.0,
                                "subtemas": [],
                                "manual": True,
                            })
                            st.session_state["contador_add_bloque"] = ctr_b + 1
                            _actualizar_desde_bloques()
                            st.rerun()
        else:
            st.info("La edición manual no está disponible porque el Markdown generado no pudo parsearse en bloques estructurados.")

        st.divider()

        # --- Refinamiento por IA ---
        st.subheader("¿La organización es correcta?")
        feedback = st.text_area(
            "Si quieres mejorar algo, descríbelo aquí (opcional):",
            placeholder="""Ejemplos de ajustes que puedes pedir:
- 'Aumenta las horas de [subtema] porque a los alumnos les cuesta más, redistribuye el resto'
- 'Divide [subtema] en dos partes separadas'
- 'El bloque [N] necesita más granularidad'
- 'Reduce [subtema] y añade más horas a [otro subtema]'""",
            key=f"feedback_{st.session_state['iteracion']}",
        )

        col1, col2, col3 = st.columns([1, 3, 2])
        with col1:
            if st.session_state["iteracion"] < 5:
                regenerar = st.button("🔄 Regenerar", type="secondary")
            else:
                regenerar = False
        with col2:
            if st.session_state["iteracion"] > 1:
                st.caption(
                    f"Iteración {st.session_state['iteracion']} — "
                    f"{len(st.session_state['historial_feedback'])} refinamiento(s) aplicado(s)"
                )
        with col3:
            cerrar_org = st.button(
                "✅ Dar organización por cerrada",
                type="primary",
                use_container_width=True,
                help="Congela la estructura. No se podrán hacer más cambios en esta sesión.",
            )

        if st.session_state["iteracion"] >= 5:
            st.info("Has alcanzado el máximo de 5 iteraciones. Descarga el resultado actual o cierra la organización.")

        if cerrar_org:
            st.session_state["fase"] = "cerrado"
            st.rerun()

        if regenerar:
            entrada_feedback = feedback.strip() if feedback and feedback.strip() else "[Sin feedback — regeneración directa]"
            st.session_state["historial_feedback"].append(entrada_feedback)
            st.session_state["iteracion"] += 1
            if generar_organizacion(guia_docente, materiales_teoria, feedback_previo=st.session_state["historial_feedback"]):
                st.rerun()
