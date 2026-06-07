import re
import sys
import unicodedata
from pathlib import Path

import streamlit as st

_SUITE_ROOT = Path(__file__).resolve().parent.parent
if str(_SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUITE_ROOT))

from shared.ui_hero import render_hero

from agente import ejecutar_agente
from parser import clasificar_archivo, extraer_texto
from prompts import construir_prompt, construir_prompt_refinamiento


def extraer_horas_docencia(texto_guia: str) -> dict[str, int]:
    """
    Extrae horas TE/PA/PL de guías docentes heterogéneas (tablas o texto libre).
    Si no encuentra una categoría, devuelve 0 para esa categoría.
    """
    def norm(texto: str) -> str:
        base = unicodedata.normalize("NFKD", texto or "")
        base = base.encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"\s+", " ", base).strip()

    def parsear_numero(token: str) -> int | None:
        try:
            valor = float(token.replace(",", "."))
            if valor < 0:
                return None
            return int(round(valor))
        except ValueError:
            return None

    def categoria_fila_modalidad(linea_norm: str) -> str | None:
        # Reglas mutuamente excluyentes para evitar solapes TE/PA/PL.
        # Incluye raíz "pract" para abreviaturas tipo "Práct. de aula" (sin "practic").
        tiene_practica = ("practic" in linea_norm) or bool(re.search(r"\bpract\b", linea_norm))
        tiene_aula = "aula" in linea_norm
        tiene_seminario = "seminar" in linea_norm
        tiene_taller = "taller" in linea_norm
        tiene_laboratorio = "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None
        tiene_campo = "campo" in linea_norm
        tiene_informatica = "informatica" in linea_norm
        tiene_idiomas = "idioma" in linea_norm
        tiene_teoria = ("expositiv" in linea_norm) or ("teoric" in linea_norm) or ("magistral" in linea_norm)

        # PL primero: categoría más específica y fácil de confundir si no se prioriza.
        if tiene_laboratorio or (tiene_practica and (tiene_campo or tiene_informatica or tiene_idiomas)):
            return "laboratorio"
        # PA: solo con "práctica(s)" (no basta con "seminario"/"taller" sueltos: otras tablas
        # y el texto narrativo también los usan y pueden llevar a 14h en lugar de 7h).
        if tiene_practica and (tiene_aula or tiene_seminario or tiene_taller):
            return "aula"
        # TE: expositiva/teórica/magistral y sin prácticas.
        if tiene_teoria and not tiene_practica:
            return "teoria"
        return None

    def fuerza_fila_pa(linea_norm: str) -> int:
        """Mayor = más seguro que es la fila de modalidad PA (no otra tabla)."""
        if linea_norm is None:
            return 0
        tiene_practica = ("practic" in linea_norm) or bool(re.search(r"\bpract\b", linea_norm))
        if not tiene_practica:
            return 0
        if "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None:
            return 0
        tiene_aula = "aula" in linea_norm
        tiene_seminario = "seminar" in linea_norm
        tiene_taller = "taller" in linea_norm
        tiene_informatica = "informatica" in linea_norm
        tiene_idiomas = "idioma" in linea_norm
        tiene_campo = "campo" in linea_norm
        tiene_laboratorio = "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None
        if tiene_laboratorio or (tiene_practica and (tiene_campo or tiene_informatica or tiene_idiomas)):
            return 0
        if tiene_aula and not (tiene_informatica or tiene_idiomas):
            return 3
        if tiene_seminario or tiene_taller:
            return 2
        return 0

    def es_fila_desglose_temas(linea_norm: str) -> bool:
        """Evita filas de tablas por tema/unidad (suelen repetir columnas TE/PA/PL con otros totales)."""
        if re.match(r"^\d+\s*[\.\)]\s", linea_norm):
            return True
        if re.match(r"^tema\s*\d", linea_norm):
            return True
        if re.match(r"^unidad\s*\d", linea_norm):
            return True
        if re.match(r"^bloque\s*\d", linea_norm):
            return True
        return False

    def es_contexto_horario(linea_norm: str) -> bool:
        # Señales de que el número se refiere a carga horaria y no a conteos (sesiones, grupos...).
        return any(
            patron in linea_norm
            for patron in ("hora", "horas", "h ", " h", "lectiv", "dedicacion", "carga docente", "credit")
        )

    def linea_parece_header_tabla(linea_norm: str) -> bool:
        return (
            ("modalidad" in linea_norm or "modalidades" in linea_norm)
            and ("hora" in linea_norm or "horas" in linea_norm)
        )

    def extraer_hora_fila(linea_original: str) -> int | None:
        nums = [parsear_numero(m.group(0)) for m in re.finditer(r"\d+(?:[.,]\d+)?", linea_original)]
        nums = [n for n in nums if n is not None and 0 <= n <= 500]
        if not nums:
            return None
        candidatos = [n for n in nums if 0 <= n <= 120]
        return candidatos[0] if candidatos else nums[0]

    def es_linea_numerica_de_tabla(linea_original: str, linea_norm: str) -> bool:
        # Acepta líneas "continuación de fila" típicas del OCR de tablas, evita texto narrativo.
        if "sesion" in linea_norm or "sesiones" in linea_norm:
            return False
        numeros = re.findall(r"\d+(?:[.,]\d+)?", linea_original)
        if not numeros:
            return False
        letras = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", linea_original)
        # Heurística: línea casi numérica (poca letra) y al menos 1 número.
        return len(letras) <= 3

    lineas_originales = [l.strip() for l in (texto_guia or "").splitlines() if l.strip()]
    lineas_norm = [norm(l) for l in lineas_originales]

    def extraer_primera_hora_fila_tabla(linea_original: str) -> int | None:
        """
        En tablas MODALIDADES el orden suele ser Horas | % | Totales.
        No usar la posición del texto 'Horas' en la cabecera: cada fila tiene
        prefijo de longitud distinta y el número más cercano puede ser el %.
        """
        coincidencias = list(re.finditer(r"\d+(?:[.,]\d+)?", linea_original))
        for m in coincidencias:
            v = parsear_numero(m.group(0))
            if v is None:
                continue
            if 1900 <= v <= 2100:
                continue
            if 0 <= v <= 120:
                return v
        return None

    horas = {"teoria": 0, "aula": 0, "laboratorio": 0}

    # Estrategia 1 (preferente): detectar tabla(s) MODALIDADES y leer columna Horas.
    # Puede haber varias tablas (p. ej. desglose por temas + resumen); se elige la ventana
    # con más datos y mayor confianza en la fila PA.
    indices_headers = [i for i, ln in enumerate(lineas_norm) if linea_parece_header_tabla(ln)]
    mejor_ventana = None  # (puntuacion, indice_cabecera, dict horas)

    for idx_header in indices_headers:
        local = {"teoria": 0, "aula": 0, "laboratorio": 0}
        fuerza_pa_mejor = -1
        ventana_fin = min(len(lineas_originales), idx_header + 45)

        for i in range(idx_header + 1, ventana_fin):
            ln = lineas_norm[i]
            if es_fila_desglose_temas(ln):
                continue
            if "total" in ln and "modalidad" not in ln:
                continue

            categoria = categoria_fila_modalidad(ln)
            if categoria is None:
                continue

            if categoria == "aula":
                fuerza = fuerza_fila_pa(ln)
                if fuerza < fuerza_pa_mejor:
                    continue

            if categoria != "aula" and local[categoria] != 0:
                continue

            valor = extraer_primera_hora_fila_tabla(lineas_originales[i])

            if valor is None:
                for salto in (1, 2):
                    if i + salto >= ventana_fin:
                        break
                    ln_sig = lineas_norm[i + salto]
                    if es_fila_desglose_temas(ln_sig):
                        continue
                    if categoria_fila_modalidad(ln_sig) is not None or linea_parece_header_tabla(ln_sig):
                        break
                    if not es_linea_numerica_de_tabla(lineas_originales[i + salto], ln_sig):
                        continue
                    valor = extraer_primera_hora_fila_tabla(lineas_originales[i + salto])
                    if valor is not None:
                        break

            if valor is None:
                continue

            if categoria == "aula":
                fuerza = fuerza_fila_pa(ln)
                if fuerza < fuerza_pa_mejor:
                    continue
                local["aula"] = int(valor)
                fuerza_pa_mejor = fuerza
            else:
                local[categoria] = int(valor)

        completitud = sum(1 for v in local.values() if v > 0)
        puntuacion = completitud * 100 + fuerza_pa_mejor
        if mejor_ventana is None:
            mejor_ventana = (puntuacion, idx_header, local)
        elif puntuacion > mejor_ventana[0] or (
            puntuacion == mejor_ventana[0] and idx_header > mejor_ventana[1]
        ):
            # Empate: preferir tabla más abajo en el documento (suele ser el resumen MODALIDADES).
            mejor_ventana = (puntuacion, idx_header, local)

    if mejor_ventana is not None:
        horas = mejor_ventana[2]

    # Estrategia 2 (fallback): búsqueda en texto libre, siempre en la MISMA línea.
    # Se aplica tras tabla y exige señales horarias para evitar capturar "sesiones".
    if 0 in horas.values():
        for linea_original, linea_norm in zip(lineas_originales, lineas_norm):
            categoria = categoria_fila_modalidad(linea_norm)
            if categoria is None or horas[categoria] != 0:
                continue
            if not es_contexto_horario(linea_norm):
                # Evita confundir número de sesiones con horas.
                continue
            valor = extraer_hora_fila(linea_original)
            if valor is not None:
                horas[categoria] = int(valor)

    return {
        "horas_teoria": horas["teoria"],
        "horas_aula": horas["aula"],
        "horas_laboratorio": horas["laboratorio"],
    }


def contar_bloques_output(markdown_text: str) -> int:
    """Cuenta encabezados ## Bloque N en el markdown generado.

    La regex es estricta: solo cuenta líneas que coinciden exactamente con
    el patrón de bloque temático (## Bloque <número>). Otros encabezados ##
    (subtítulos, secciones internas) no producen falsos positivos.
    """
    return len(re.findall(r"^## Bloque\s+\d+", markdown_text, re.MULTILINE))


def construir_nombre_descarga(texto_guia: str) -> str:
    # Se busca el patrón habitual "NOMBRE ... CÓDIGO" para extraer la asignatura.
    coincidencia = re.search(r"NOMBRE\s+(.+?)\s+C[ÓO]DIGO", texto_guia or "", flags=re.IGNORECASE | re.DOTALL)
    if not coincidencia:
        return "Propuesta_asignatura.md"

    nombre_asignatura = coincidencia.group(1).strip()
    # Se eliminan caracteres no válidos para nombres de archivo.
    nombre_limpio = re.sub(r'[\\/:\*\?"<>\|]', "", nombre_asignatura)
    # Se normalizan espacios a guiones bajos.
    nombre_limpio = re.sub(r"\s+", "_", nombre_limpio).strip("_")
    if not nombre_limpio:
        return "Propuesta_asignatura.md"

    return f"Propuesta_{nombre_limpio}.md"


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


def generar_organizacion(
    guia_docente,
    materiales_teoria,
    feedback_previo: list[str] | None = None,
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
            )

            st.write("🤖 Consultando al agente (esto puede tardar ~15s)...")
            resultado = ejecutar_agente(prompt)

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
        st.session_state["session_id_archivos"] = session_id_actual

    puede_generar = guia_docente is not None and len(materiales_teoria or []) > 0

    if st.button("Generar organización", disabled=not puede_generar, use_container_width=True):
        # Se reinicia el ciclo de refinamiento cuando se genera una nueva versión base.
        st.session_state["historial_feedback"] = []
        st.session_state["iteracion"] = 1
        if generar_organizacion(guia_docente, materiales_teoria):
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

if st.session_state["ultimo_output"] is None:
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

if st.session_state["ultimo_output"]:
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

    st.markdown("### Propuesta generada")
    st.markdown(st.session_state["ultimo_output"])
    st.download_button(
        label="Descargar resultado (.md)",
        data=st.session_state["ultimo_output"],
        file_name=st.session_state.get("ultimo_nombre_descarga", "Propuesta_asignatura.md"),
        mime="text/markdown",
    )

    st.divider()
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

    col1, col2 = st.columns([1, 4])
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

    if st.session_state["iteracion"] >= 5:
        st.info("Has alcanzado el máximo de 5 iteraciones. Descarga el resultado actual o reinicia la app.")

    if regenerar:
        entrada_feedback = feedback.strip() if feedback and feedback.strip() else "[Sin feedback — regeneración directa]"
        st.session_state["historial_feedback"].append(entrada_feedback)
        st.session_state["iteracion"] += 1
        if generar_organizacion(guia_docente, materiales_teoria, feedback_previo=st.session_state["historial_feedback"]):
            st.rerun()
