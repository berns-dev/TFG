"""Inyección de CSS — identidad visual Suite Docente IA (handoff hi-fi)."""

import streamlit as st

# Design tokens
FONDO_APP = "#F1F4F8"
SUPERFICIE = "#FFFFFF"
BORDE = "#E4E9F0"
TEXTO = "#16202E"
TEXTO_SEC = "#475667"
TEXTO_ATENUADO = "#6B7A8D"
ACENTO = "#185FA5"
ACENTO_OSCURO = "#0C447C"
SIDEBAR_BG = "#0C2E54"
SIDEBAR_ACTIVO = "#15406E"


def inject_theme(
    acento: str = ACENTO,
    acento_oscuro: str = ACENTO_OSCURO,
    mostrar_sidebar: bool = True,
) -> None:
    sidebar_css = (
        ""
        if mostrar_sidebar
        else """
        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        """
    )
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap');

        {sidebar_css}

        html, body, [class*="css"] {{
            font-family: 'DM Sans', system-ui, sans-serif !important;
        }}

        /* Forzar esquema claro: el navegador/SO en modo oscuro hace que
           widgets nativos (text_area, code, selectbox, expander) usen
           variantes oscuras que no cubren nuestros overrides puntuales. */
        html {{ color-scheme: light !important; }}
        .stApp, [data-testid="stAppViewContainer"], .main {{
            color-scheme: light !important;
        }}
        /* Variables de tema Streamlit — evita botones oscuros por defecto */
        .stApp, [data-testid="stAppViewContainer"], section.main {{
            --primary-color: {acento} !important;
            --background-color: {FONDO_APP} !important;
            --secondary-background-color: #FFFFFF !important;
            --text-color: {TEXTO} !important;
        }}
        textarea, input, select,
        [data-testid="stTextArea"] textarea,
        [data-testid="stTextArea"] textarea:disabled,
        [data-testid="stCodeBlock"], [data-testid="stCodeBlock"] pre,
        [data-baseweb="select"] > div,
        [data-baseweb="popover"], [data-baseweb="menu"],
        [data-testid="stExpander"], [data-testid="stExpander"] summary {{
            background-color: #fff !important;
            color: {TEXTO} !important;
            border-color: {BORDE} !important;
        }}
        [data-testid="stCodeBlock"] code {{ color: {TEXTO} !important; }}
        [data-testid="stTextArea"] textarea:disabled {{
            color: {TEXTO_SEC} !important;
            -webkit-text-fill-color: {TEXTO_SEC} !important;
            background: #F7F9FC !important;
            opacity: 1 !important;
        }}
        [data-baseweb="menu"] li {{ color: {TEXTO} !important; }}

        /* ── Captions — vence el leak de "dark mode" del navegador/SO en
           texto secundario (evidencia, estrategia, metadatos) ── */
        .stCaption, [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p,
        [data-testid="stCaptionContainer"] span,
        [data-testid="stCaptionContainer"] small {{
            color: {TEXTO_ATENUADO} !important;
            opacity: 1 !important;
        }}

        /* ── st.status — mismo leak en el label/icono de la cabecera ── */
        [data-testid="stStatusWidget"] {{
            background-color: #fff !important;
            border-color: {BORDE} !important;
        }}
        [data-testid="stStatusWidget"] summary,
        [data-testid="stStatusWidget"] p,
        [data-testid="stStatusWidget"] span,
        [data-testid="stStatusWidget"] label {{
            color: {TEXTO} !important;
        }}

        /* ── File uploader — dropzone, nombre de fichero, botón "Browse files" ── */
        [data-testid="stFileUploaderDropzone"] {{
            background-color: #F8FAFC !important;
            border-color: {BORDE} !important;
        }}
        [data-testid="stFileUploaderDropzoneInstructions"],
        [data-testid="stFileUploaderDropzoneInstructions"] span,
        [data-testid="stFileUploaderDropzoneInstructions"] small {{
            color: {TEXTO_SEC} !important;
        }}
        [data-testid="stFileUploaderDropzoneInstructions"] svg {{
            fill: {TEXTO_SEC} !important;
        }}
        [data-testid="stFileUploaderDropzone"] button {{
            background-color: #fff !important;
            color: {TEXTO} !important;
            border: 1px solid #D7DEE7 !important;
            box-shadow: none !important;
        }}
        [data-testid="stFileUploaderFile"] {{
            background-color: transparent !important;
        }}
        [data-testid="stFileUploaderFileName"],
        [data-testid="stFileUploaderFileData"],
        [data-testid="stFileUploaderFileData"] span {{
            color: {TEXTO} !important;
        }}
        [data-testid="stFileUploaderFileData"] small {{
            color: {TEXTO_ATENUADO} !important;
        }}
        [data-testid="stFileUploaderDeleteBtn"] button {{
            background-color: transparent !important;
            color: {TEXTO_SEC} !important;
        }}
        [data-testid="stFileUploaderDeleteBtn"] button svg {{
            fill: {TEXTO_SEC} !important;
        }}

        /* ── Logo institucional en chip blanco (sidebar navy) ── */
        .sd-brand .logo.logo-img {{
            width: auto; height: 96px; background: #fff;
            border-radius: 12px; padding: 12px 20px;
        }}
        .sd-brand .logo.logo-img img {{
            height: 100%; width: auto; display: block;
        }}

        /* Default global de botones "primary" — solo área principal */
        [data-testid="stAppViewContainer"] .main .stButton > button[kind="primary"] {{
            background: {acento} !important; border-color: {acento_oscuro} !important;
            color: #fff !important;
        }}
        [data-testid="stAppViewContainer"] .main .stButton > button[kind="primary"]:hover {{
            background: {acento_oscuro} !important; border-color: {acento_oscuro} !important;
        }}
        .stButton > button:disabled {{
            opacity: 1 !important;
            cursor: not-allowed !important;
        }}
        .stButton > button[kind="secondary"]:disabled {{
            background: #EAEEF3 !important;
            border: 1px solid #D7DEE7 !important;
            color: #7B8794 !important;
        }}
        .stButton > button[kind="primary"]:disabled {{
            background: #EAEEF3 !important;
            border: 1px solid #D7DEE7 !important;
            color: #7B8794 !important;
        }}

        /* Botones secondary solo en área principal (no sidebar) */
        [data-testid="stAppViewContainer"] .main .stButton > button[kind="secondary"] {{
            background: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: #475667 !important;
        }}
        [data-testid="stAppViewContainer"] .main .stButton > button[kind="secondary"]:hover {{
            background: #F8FAFC !important;
            border-color: {acento} !important;
            color: {acento_oscuro} !important;
        }}
        /* Botones sin type explícito en main (evita cuadros oscuros por defecto) */
        [data-testid="stAppViewContainer"] .main .stButton > button:not([kind="primary"]) {{
            background: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: #475667 !important;
        }}
        [data-testid="stAppViewContainer"] .main .stButton > button:not([kind="primary"]) p,
        [data-testid="stAppViewContainer"] .main .stButton > button:not([kind="primary"]) span,
        [data-testid="stAppViewContainer"] .main .stButton > button:not([kind="primary"]) div {{
            color: inherit !important;
        }}

        /* ── Landing: el botón ES la tarjeta ── */
        div[class*="st-key-landing_btn_nuevo"] .stButton > button {{
            min-height: 168px !important;
            height: auto !important;
            padding: 26px 22px !important;
            border-radius: 14px !important;
            white-space: pre-line !important;
            line-height: 1.45 !important;
            text-align: center !important;
            justify-content: center !important;
            align-items: center !important;
            font-size: 13.5px !important;
            font-weight: 600 !important;
            background: #F3FAF6 !important;
            border: 1px solid #CFE9DA !important;
            color: #1F7A4D !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-landing_btn_nuevo"] .stButton > button:hover {{
            background: #EAF6EF !important;
            border-color: #A8D9BE !important;
        }}
        div[class*="st-key-landing_btn_cargar"] .stButton > button {{
            min-height: 168px !important;
            height: auto !important;
            padding: 26px 22px !important;
            border-radius: 14px !important;
            white-space: pre-line !important;
            line-height: 1.45 !important;
            text-align: center !important;
            justify-content: center !important;
            align-items: center !important;
            font-size: 13.5px !important;
            font-weight: 600 !important;
            background: #F2F7FC !important;
            border: 1px solid #D6E4F2 !important;
            color: {acento_oscuro} !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-landing_btn_cargar"] .stButton > button:hover {{
            background: #E8F1FA !important;
            border-color: {acento} !important;
        }}

        /* ── Lista asignaturas landing: tarjeta + progress nativo ── */
        div[class*="st-key-sd_asig_item_"] {{
            background: #fff !important;
            border: 1px solid {BORDE} !important;
            border-radius: 10px !important;
            padding: 12px 14px 10px !important;
            margin-bottom: 10px !important;
        }}
        div[class*="st-key-sd_asig_item_"] div[class*="st-key-sd_asig_btn_"] .stButton > button {{
            min-height: 0 !important;
            height: auto !important;
            padding: 0 0 8px 0 !important;
            border-radius: 0 !important;
            white-space: nowrap !important;
            text-align: left !important;
            justify-content: flex-start !important;
            line-height: 1.4 !important;
            font-size: 13.5px !important;
            font-weight: 600 !important;
            background: #fff !important;
            border: none !important;
            color: {TEXTO} !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-sd_asig_item_"] div[class*="st-key-sd_asig_btn_"] .stButton > button:hover {{
            color: {acento_oscuro} !important;
            background: #fff !important;
        }}
        div[class*="st-key-sd_asig_item_"] div[class*="st-key-sd_asig_btn_"] .stButton > button p,
        div[class*="st-key-sd_asig_item_"] div[class*="st-key-sd_asig_btn_"] .stButton > button span {{
            color: inherit !important;
            background: transparent !important;
        }}
        div[class*="st-key-sd_asig_item_"] [data-testid="stProgress"] {{
            margin-top: 0 !important;
        }}
        /* ── st.progress nativo: estructura real es
           stProgress > [data-baseweb="progress-bar"] > div(BarContainer) > div(Bar=track) > div(BarProgress=fill)
           El track por defecto puede salir oscuro si el navegador fuerza su
           propio tema sobre Streamlit; lo forzamos siempre claro. ── */
        [data-testid="stProgress"] [data-baseweb="progress-bar"] > div > div {{
            background-color: #E0E6EE !important;
        }}
        [data-testid="stProgress"] [data-baseweb="progress-bar"] > div > div > div {{
            background-color: {acento} !important;
        }}

        /* ── Flujo pipeline: 3 tarjetas separadas + flechas ── */
        .st-key-sd_banner_flow {{
            margin-bottom: 20px !important;
        }}
        .st-key-sd_banner_flow [data-testid="stHorizontalBlock"] {{
            align-items: stretch !important;
            gap: 0 !important;
        }}
        .st-key-sd_banner_flow .sd-flow-arrow {{
            display: flex; align-items: center; justify-content: center;
            height: 100%; min-height: 72px;
            color: #9AA7B6; font-size: 22px; font-weight: 600;
            padding: 0 4px; user-select: none;
        }}
        div[class*="st-key-banner_nav_"] .stButton > button {{
            min-height: 72px !important;
            height: 100% !important;
            border-radius: 11px !important;
            border: 1px solid {BORDE} !important;
            white-space: pre-line !important;
            text-align: left !important;
            justify-content: flex-start !important;
            align-items: flex-start !important;
            padding: 14px 18px !important;
            line-height: 1.35 !important;
            font-size: 12.5px !important;
            font-weight: 600 !important;
            box-shadow: 0 1px 2px rgba(16,32,46,.04) !important;
        }}
        div[class*="st-key-banner_nav_"] .stButton > button[kind="secondary"] {{
            background: #fff !important;
            color: {TEXTO} !important;
        }}
        div[class*="st-key-banner_nav_"] .stButton > button[kind="secondary"]:hover {{
            border-color: {acento} !important;
            background: #FAFCFE !important;
        }}
        div[class*="st-key-banner_nav_"] .stButton > button[kind="primary"] {{
            background: #F2F7FC !important;
            color: {acento_oscuro} !important;
            border-color: #B8D4EF !important;
            box-shadow: inset 3px 0 0 {acento}, 0 1px 2px rgba(16,32,46,.04) !important;
        }}

        /* ── Mapa curricular: filas HTML + flecha ── */
        .st-key-sd_tabla_mapa [data-testid="stHorizontalBlock"] {{
            align-items: center !important;
            gap: 6px !important;
        }}
        .st-key-sd_tabla_mapa [data-testid="stHorizontalBlock"] [data-testid="stColumn"]:last-child {{
            padding-right: 18px !important;
        }}
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button {{
            min-height: 36px !important;
            height: 36px !important;
            width: 36px !important;
            min-width: 36px !important;
            padding: 0 !important;
            border-radius: 8px !important;
            font-size: 16px !important;
            font-weight: 600 !important;
            line-height: 1 !important;
            background: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: {acento} !important;
            box-shadow: none !important;
        }}
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button:hover {{
            background: #EAF2FA !important;
            border-color: {acento} !important;
            color: {acento_oscuro} !important;
        }}
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button p,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button span {{
            color: inherit !important;
            background: transparent !important;
        }}

        /* Markdown legible en área principal */
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] li,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] span,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] td,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] th {{
            color: {TEXTO};
        }}
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h1,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h2,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h3,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] h4,
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] strong {{
            color: {TEXTO};
        }}

        /* Ocultar chrome Streamlit */
        #MainMenu, footer, header[data-testid="stHeader"] {{
            visibility: hidden !important;
            height: 0 !important;
            min-height: 0 !important;
        }}
        .stApp {{
            background: {FONDO_APP} !important;
        }}
        .block-container {{
            padding-top: 0 !important;
            padding-bottom: 2rem !important;
            max-width: 100% !important;
            padding-left: 2.25rem !important;
            padding-right: 2.25rem !important;
        }}
        [data-testid="stAppViewContainer"] > .main {{
            background: {FONDO_APP} !important;
        }}

        /* ── Sidebar navy ── */
        section[data-testid="stSidebar"] {{
            background: {SIDEBAR_BG} !important;
            border-right: none !important;
            width: 272px !important;
            min-width: 272px !important;
        }}
        section[data-testid="stSidebar"] > div {{
            background: {SIDEBAR_BG} !important;
            padding-top: 0 !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stMarkdown"] p,
        section[data-testid="stSidebar"] [data-testid="stMarkdown"] span,
        section[data-testid="stSidebar"] label {{
            color: #E7EEF6;
        }}
        section[data-testid="stSidebar"] .stButton > button {{
            border-radius: 8px !important;
            font-family: 'DM Sans', sans-serif !important;
            font-size: 12px !important;
            border: 1px solid rgba(255,255,255,.10) !important;
            box-shadow: none !important;
            text-align: left !important;
            justify-content: flex-start !important;
            padding: 7px 11px !important;
            min-height: 0 !important;
            height: auto !important;
            white-space: nowrap !important;
            line-height: 1.3 !important;
            transition: background .12s ease, color .12s ease, border-color .12s ease !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-sd_nav_"] {{
            margin-bottom: 4px !important;
        }}
        section[data-testid="stSidebar"] div[class*="st-key-sd_pipe_"] {{
            margin-bottom: 4px !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {{
            background: rgba(255,255,255,.08) !important;
            color: #C5D4E8 !important;
            border: 1px solid rgba(255,255,255,.12) !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {{
            background: rgba(255,255,255,.14) !important;
            color: #F0F5FA !important;
            border-color: rgba(255,255,255,.20) !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: {SIDEBAR_ACTIVO} !important;
            color: #F0F5FA !important;
            font-weight: 600 !important;
            box-shadow: inset 2px 0 0 #3D8BD4 !important;
            border: 1px solid rgba(61,139,212,.30) !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
            background: #1A4A7E !important;
        }}
        section[data-testid="stSidebar"] .stButton > button p,
        section[data-testid="stSidebar"] .stButton > button span,
        section[data-testid="stSidebar"] .stButton > button div {{
            color: inherit !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] p,
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] div {{
            color: #F0F5FA !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] p,
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] span,
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] div {{
            color: #C5D4E8 !important;
        }}

        section[data-testid="stSidebar"] .stCaption {{
            color: #7E93AE !important;
            font-size: 10px !important;
            margin-top: -6px !important;
            padding-left: 12px !important;
        }}
        section[data-testid="stSidebar"] .stTextInput input {{
            background: rgba(255,255,255,.08) !important;
            border: 1px solid rgba(255,255,255,.12) !important;
            color: #E7EEF6 !important;
            border-radius: 8px !important;
        }}
        section[data-testid="stSidebar"] .stExpander {{
            background: transparent !important;
            border: 1px solid rgba(255,255,255,.1) !important;
            border-radius: 8px !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary span,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary p {{
            color: #A9BACE !important;
            background: transparent !important;
        }}
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {{
            color: #E7EEF6 !important;
        }}
        section[data-testid="stSidebar"] hr {{
            border-color: rgba(255,255,255,.09) !important;
            margin: 14px 0 !important;
        }}

        .sd-brand {{
            display: flex; flex-direction: column; align-items: center; gap: 10px;
            padding: 22px 12px 18px; margin-bottom: 4px; text-align: center;
            border-bottom: 1px solid rgba(255,255,255,.09);
        }}
        .sd-brand .logo {{
            width: 36px; height: 36px; border-radius: 9px; background: {acento};
            display: flex; align-items: center; justify-content: center;
            font-weight: 700; font-size: 14px; color: #fff; flex-shrink: 0;
        }}
        .sd-brand .titulo {{ font-size: 14px; font-weight: 600; color: #E7EEF6; letter-spacing: -.01em; }}
        .sd-brand .sub {{ font-size: 11px; color: #93A6C0; margin-top: 1px; }}

        .sd-seccion-label {{
            font-size: 10px; font-weight: 600; letter-spacing: .09em;
            color: #7E93AE; text-transform: uppercase;
            padding: 0 8px 9px; margin-top: 4px;
        }}

        .sd-asig-card {{
            display: block; width: 100%; text-align: left;
            padding: 11px 12px; margin-bottom: 6px;
            border-radius: 9px; border: none; cursor: pointer;
            background: transparent; color: #E7EEF6;
            font-family: 'DM Sans', sans-serif;
        }}
        .sd-asig-card:hover {{ background: rgba(255,255,255,.06); }}
        .sd-asig-card.activa {{
            background: {SIDEBAR_ACTIVO};
            box-shadow: inset 3px 0 0 #3D8BD4;
        }}
        .sd-asig-card .fila-top {{
            display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
        }}
        .sd-asig-card .nombre {{ font-size: 12.5px; font-weight: 600; letter-spacing: -.01em; }}
        .sd-asig-card .pct {{ font-size: 10.5px; color: #93A6C0; font-variant-numeric: tabular-nums; }}
        .sd-asig-bar {{
            height: 4px; border-radius: 3px; background: rgba(255,255,255,.13);
            margin-top: 8px; overflow: hidden;
        }}
        .sd-asig-bar .fill {{ height: 100%; border-radius: 3px; background: #3D8BD4; }}
        .sd-asig-bar .fill.completo {{ background: #3FAE6B; }}
        .sd-asig-bar.claro {{ background: #E0E6EE; }}

        /* ── Asignatura activa (sidebar) ── */
        .sd-asig-activa {{
            padding: 13px 16px; margin: 4px 8px 10px; border-radius: 10px;
            background: rgba(255,255,255,.05);
        }}
        .sd-asig-activa .nombre {{
            font-size: 13.5px; font-weight: 600; color: #E7EEF6; letter-spacing: -.01em;
        }}
        div[class*="st-key-sd_cambiar_proyecto"] .stButton > button {{
            background: rgba(255,255,255,.06) !important;
            border: 1px solid rgba(255,255,255,.10) !important;
            box-shadow: none !important;
            color: #B8C9DC !important;
            font-size: 11.5px !important;
            font-weight: 500 !important;
            justify-content: flex-start !important;
            padding: 8px 12px !important;
            min-height: 32px !important;
            height: auto !important;
            border-radius: 8px !important;
        }}
        div[class*="st-key-sd_cambiar_proyecto"] .stButton > button:hover {{
            color: #F0F5FA !important;
            background: rgba(255,255,255,.12) !important;
            border-color: rgba(255,255,255,.18) !important;
        }}
        div[class*="st-key-sd_cambiar_proyecto"] .stButton > button p,
        div[class*="st-key-sd_cambiar_proyecto"] .stButton > button span {{
            color: inherit !important;
        }}

        /* ── Tarjeta de asignatura en "Cargar proyecto existente" (área clara) ── */
        .sd-asig-card-claro {{
            background: #fff; border: 1px solid {BORDE}; border-radius: 10px;
            padding: 14px 16px; margin-bottom: 0;
        }}
        .sd-asig-card-claro .fila-top {{ display: flex; justify-content: space-between; align-items: baseline; }}
        .sd-asig-card-claro .nombre {{ font-size: 13.5px; font-weight: 600; color: {TEXTO}; }}
        .sd-asig-card-claro .pct {{ font-size: 11px; color: #8693A3; font-variant-numeric: tabular-nums; }}
        .sd-asig-card-claro .sd-asig-bar {{
            margin-top: 10px; height: 6px; border-radius: 4px;
        }}

        .sd-nav-item {{
            display: flex; align-items: center; gap: 9px;
            width: 100%; padding: 9px 12px; margin-bottom: 3px;
            border-radius: 8px; border: none; cursor: pointer;
            background: transparent; color: #A9BACE;
            font-family: 'DM Sans', sans-serif; font-size: 12.5px;
            text-align: left;
        }}
        .sd-nav-item:hover {{ background: rgba(255,255,255,.05); color: #E7EEF6; }}
        .sd-nav-item.activo {{ background: {SIDEBAR_ACTIVO}; color: #E7EEF6; font-weight: 600; }}
        .sd-nav-item .dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}

        .sd-pipe-item {{
            display: flex; align-items: flex-start; gap: 10px;
            width: 100%; padding: 9px 10px; margin-bottom: 3px;
            border-radius: 8px; border: none; cursor: pointer;
            background: transparent; color: #E7EEF6;
            font-family: 'DM Sans', sans-serif; text-align: left;
        }}
        .sd-pipe-item:hover {{ background: rgba(255,255,255,.05); }}
        .sd-pipe-item.activo {{ background: {SIDEBAR_ACTIVO}; }}
        .sd-pipe-num {{
            width: 24px; height: 24px; border-radius: 7px; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            font-size: 11px; font-weight: 700;
            background: rgba(255,255,255,.1); color: #A9BACE;
        }}
        .sd-pipe-item.activo .sd-pipe-num {{ background: {acento}; color: #fff; }}
        .sd-pipe-tit {{ font-size: 12.5px; font-weight: 600; letter-spacing: -.01em; }}
        .sd-pipe-sub {{ font-size: 10.5px; color: #7E93AE; margin-top: 1px; }}

        /* ── Topbar ── */
        .st-key-sd_topbar_wrap {{
            position: sticky; top: 0; z-index: 100;
            background: rgba(241,244,248,.94); backdrop-filter: blur(10px);
            border-bottom: 1px solid #E1E7EF;
            margin: 0 -2.25rem 18px; padding: 14px 2.25rem;
        }}
        .st-key-sd_topbar_wrap .curso {{ font-size: 11px; color: {TEXTO_ATENUADO}; font-weight: 500; }}
        .st-key-sd_topbar_wrap .asig-titulo {{
            font-size: 20px; font-weight: 600; letter-spacing: -.02em;
            color: {TEXTO}; margin-top: 1px;
        }}
        .sd-topbar-prog {{
            display: flex; align-items: center; gap: 10px; justify-content: flex-end;
        }}
        .sd-topbar-prog .bar {{
            width: 120px; height: 9px; border-radius: 5px; background: #E0E6EE; overflow: hidden;
        }}
        .sd-topbar-prog .pct {{
            font-size: 13px; font-weight: 700; color: {acento_oscuro};
            font-variant-numeric: tabular-nums; min-width: 36px; text-align: right;
        }}

        /* Botones export en topbar */
        .st-key-sd_topbar_actions [data-testid="column"] {{
            min-width: 0 !important;
        }}
        .st-key-sd_topbar_actions .stButton > button {{
            height: 34px !important; min-height: 34px !important;
            border-radius: 8px !important; font-size: 11px !important;
            font-weight: 600 !important; padding: 0 10px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }}
        .st-key-sd_topbar_actions .stButton > button[kind="secondary"] {{
            background: #fff !important; border: 1px solid #D7DEE7 !important;
            color: #475667 !important;
        }}
        .st-key-sd_topbar_actions .stButton > button[kind="secondary"]:disabled {{
            background: #EAEEF3 !important; border-color: #E2E7EE !important;
            color: #AEB8C4 !important;
        }}
        .st-key-sd_topbar_actions .stButton > button[kind="primary"] {{
            background: {acento} !important; border: 1px solid {acento_oscuro} !important;
        }}
        .st-key-sd_topbar_actions .stButton > button[kind="primary"]:disabled {{
            background: #EAEEF3 !important; border-color: #E2E7EE !important;
            color: #AEB8C4 !important;
        }}

        /* ── Pipeline banner (main) ── */
        .sd-pipeline-main {{
            margin-bottom: 20px;
        }}
        .sd-pipeline-main .stButton > button {{
            width: 100% !important;
            min-height: 68px !important;
            height: auto !important;
            border-radius: 0 !important;
            border: none !important;
            border-right: 1px solid #EEF1F6 !important;
            background: #fff !important;
            color: {TEXTO} !important;
            text-align: left !important;
            justify-content: flex-start !important;
            align-items: flex-start !important;
            padding: 13px 16px !important;
            white-space: pre-line !important;
            line-height: 1.35 !important;
            font-family: 'DM Sans', sans-serif !important;
            font-size: 12.5px !important;
            font-weight: 600 !important;
            box-shadow: none !important;
        }}
        .sd-pipeline-main .stButton > button:hover {{
            background: #F8FAFC !important;
        }}
        .sd-pipeline-main .stButton > button[kind="primary"] {{
            background: #F2F7FC !important;
            color: {acento_oscuro} !important;
            box-shadow: inset 3px 0 0 {acento} !important;
        }}
        .sd-pipeline-main [data-testid="column"]:last-child .stButton > button {{
            border-right: none !important;
        }}
        .sd-pipeline-frame {{
            border: 1px solid {BORDE}; border-radius: 11px; overflow: hidden;
            background: #fff;
        }}

        /* ── Chips de bloque (varias filas ordenadas, sin scroll horizontal) ── */
        .st-key-sd_chip_scroll {{
            margin-bottom: 18px;
        }}
        .st-key-sd_chip_scroll [data-testid="stHorizontalBlock"] {{
            margin-bottom: 8px;
        }}
        .st-key-sd_chip_scroll [data-testid="column"]:not(:has(.stButton)) {{
            display: none !important;
        }}
        .st-key-sd_chip_scroll .stButton {{
            margin-bottom: 0 !important;
        }}
        .st-key-sd_chip_scroll .stButton > button {{
            border-radius: 9px !important;
            font-size: 11.5px !important; font-weight: 500 !important;
            padding: 0 10px !important; min-height: 32px !important;
            height: 32px !important; white-space: nowrap !important;
            background: #fff !important; border: 1px solid #DCE3EC !important;
            color: #475667 !important;
            box-shadow: none !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }}
        .st-key-sd_chip_scroll .stButton > button[kind="primary"] {{
            border-color: #185FA5 !important;
            background: #EAF2FA !important;
            color: #0C447C !important;
            font-weight: 600 !important;
        }}

        .sd-editor-footer {{
            display: flex; align-items: center; justify-content: space-between;
            gap: 18px; padding: 13px 0 0; margin-top: 8px;
            border-top: 1px solid #EAEEF3;
        }}

        div[class*="st-key-sd_input_dashed_"] .stButton > button {{
            margin-top: 12px !important;
            height: 38px !important;
            border-radius: 8px !important;
            border: 1.5px dashed #C3D0DF !important;
            background: #F8FAFC !important;
            color: #185FA5 !important;
            font-size: 12.5px !important;
            font-weight: 600 !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-sd_input_dashed_"] .stButton > button:hover {{
            background: #EAF2FA !important;
            border-color: {acento} !important;
            color: {acento_oscuro} !important;
        }}

        /* ── "Nueva visualización" y flecha del mapa curricular: mismo patrón
           a prueba de bombas que la tarjeta de asignatura (fondo y color en
           literal, color:inherit en cada hijo, sin depender del tema nativo). ── */
        div[class*="st-key-prs_nueva_"] .stButton > button,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button {{
            background-color: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: {TEXTO_SEC} !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-prs_nueva_"] .stButton > button:hover,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button:hover {{
            background-color: #F8FAFC !important;
            border-color: {acento} !important;
            color: {acento_oscuro} !important;
        }}
        div[class*="st-key-prs_nueva_"] .stButton > button p,
        div[class*="st-key-prs_nueva_"] .stButton > button span,
        div[class*="st-key-prs_nueva_"] .stButton > button div,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button p,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button span,
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button div {{
            color: inherit !important;
            background-color: transparent !important;
        }}

        div[class*="st-key-sd_composer_row_"] [data-testid="stVerticalBlock"] textarea {{
            min-height: 64px !important;
        }}
        div[class*="st-key-sd_composer_row_"] .stButton > button[kind="secondary"],
        div[class*="st-key-sd_composer_row_"] .stButton > button:not([kind="primary"]) {{
            background: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: #475667 !important;
            font-weight: 600 !important;
            box-shadow: none !important;
        }}
        div[class*="st-key-sd_composer_row_"] .stButton > button[kind="secondary"]:disabled {{
            background: #EAEEF3 !important;
            color: #AEB8C4 !important;
        }}

        .st-key-sd_card_rail_export .stButton > button[kind="secondary"],
        .st-key-sd_card_rail_export .stButton > button:not([kind="primary"]) {{
            background: #fff !important;
            border: 1px solid #D7DEE7 !important;
            color: #475667 !important;
            font-weight: 600 !important;
            min-height: 38px !important;
            box-shadow: none !important;
        }}
        .st-key-sd_card_rail_export .stButton > button[kind="secondary"]:hover {{
            background: #F8FAFC !important;
            border-color: {acento} !important;
            color: {acento_oscuro} !important;
        }}
        .st-key-sd_card_rail_export .stButton > button p,
        .st-key-sd_card_rail_export .stButton > button span {{
            color: inherit !important;
        }}

        /* ── Tabs estilo segmented ── */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 4px; background: #F1F4F8; border-radius: 9px; padding: 4px;
            border-bottom: none !important;
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 7px !important; font-size: 12.5px !important;
            font-weight: 500 !important; padding: 6px 14px !important;
            color: {TEXTO_ATENUADO} !important;
            background: transparent !important;
        }}
        .stTabs [aria-selected="true"] {{
            background: #fff !important;
            color: {acento_oscuro} !important;
            font-weight: 600 !important;
            box-shadow: 0 1px 2px rgba(16,32,46,.06) !important;
        }}
        .stTabs [data-baseweb="tab-highlight"] {{ display: none !important; }}
        .stTabs [data-baseweb="tab-border"] {{ display: none !important; }}

        /* ── Tarjetas genéricas montadas sobre st.container(key=...) ──
           En Streamlit, abrir un <div> en un st.markdown y cerrarlo en otra
           llamada NO anida los widgets intermedios (cada llamada crea su propio
           nodo hermano). Por eso estas tarjetas se montan con st.container(key=...)
           y el estilo de "tarjeta" se aplica directamente al contenedor real. */
        div[class*="st-key-sd_card_"] {{
            background: #fff; border: 1px solid {BORDE}; border-radius: 12px;
            padding: 16px 18px 14px; margin-bottom: 14px;
        }}
        .st-key-sd_card_editor .stTabs {{ margin-bottom: 12px; }}
        /* Panel "Vista previa" del modo Dividido: mismo alto que el text_area
           de la izquierda (400px) y con scroll propio, para que ambos paneles
           crezcan igual en vez de que uno se alargue sin límite. */
        div[class*="st-key-sd_render_box_"] {{
            height: 400px !important; overflow-y: auto !important;
            border: 1px solid {BORDE}; border-radius: 8px;
            padding: 10px 14px; background: #fff;
            color: {TEXTO} !important;
        }}
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"],
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] p,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] li,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] span,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] td,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] th,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] h1,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] h2,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] h3,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] h4,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] strong,
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] em {{
            color: {TEXTO} !important;
        }}
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] code {{
            color: {TEXTO_SEC} !important;
            background: #F1F4F8 !important;
        }}
        div[class*="st-key-sd_render_box_"] [data-testid="stMarkdownContainer"] a {{
            color: {acento} !important;
        }}
        .st-key-sd_card_cov_panel {{ position: sticky !important; top: 88px !important; padding: 18px 20px !important; }}
        .st-key-sd_card_rail_viz, .st-key-sd_card_rail_iter, .st-key-sd_card_rail_export {{
            padding: 18px 20px !important;
        }}
        .st-key-sd_card_rail_viz {{ position: sticky !important; top: 88px !important; }}
        .st-key-sd_card_preview {{ padding: 0 !important; overflow: hidden; }}
        div[class*="st-key-sd_card_inputs_"] {{ padding: 18px 20px !important; }}

        /* ── Botón aprobar verde ── */
        div[class*="st-key-sd_btn_aprobar_"] .stButton > button {{
            background: #2E815A !important; border-color: #257349 !important;
            color: #fff !important; font-weight: 600 !important;
        }}
        div[class*="st-key-sd_btn_aprobar_"] .stButton > button:disabled {{
            background: #E3F1EA !important;
            border-color: #C5E0D0 !important;
            color: #2E815A !important;
        }}

        /* ── Topbar legacy (deprecated) ── */
        .sd-topbar {{
            position: sticky; top: 0; z-index: 100;
            background: rgba(241,244,248,.92); backdrop-filter: blur(10px);
            border-bottom: 1px solid #E1E7EF;
            padding: 14px 0; margin: 0 -1rem 0 -1rem;
            padding-left: 1rem; padding-right: 1rem;
        }}
        .sd-topbar .curso {{ font-size: 11px; color: {TEXTO_ATENUADO}; font-weight: 500; }}
        .sd-topbar .asig-titulo {{
            font-size: 20px; font-weight: 600; letter-spacing: -.02em;
            color: {TEXTO}; margin-top: 1px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }}

        /* ── Pipeline banner ── */
        .sd-banner {{
            display: flex; background: {SUPERFICIE};
            border: 1px solid {BORDE}; border-radius: 11px; overflow: hidden;
            margin-bottom: 22px;
        }}
        .sd-banner-step {{
            flex: 1; display: flex; align-items: center; gap: 11px;
            padding: 13px 16px; border: none; background: transparent;
            cursor: pointer; font-family: 'DM Sans', sans-serif; text-align: left;
            border-right: 1px solid #EEF1F6;
        }}
        .sd-banner-step:last-child {{ border-right: none; }}
        .sd-banner-step:hover {{ background: #F8FAFC; }}
        .sd-banner-step.activo {{
            background: #F2F7FC;
            box-shadow: inset 3px 0 0 {acento};
        }}
        .sd-banner-num {{
            width: 26px; height: 26px; border-radius: 7px; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            font-size: 12px; font-weight: 700;
            background: #EDF2F8; color: {acento_oscuro};
        }}
        .sd-banner-step.activo .sd-banner-num {{ background: {acento}; color: #fff; }}

        /* ── KPI cards ── */
        .sd-kpi {{
            background: {SUPERFICIE}; border: 1px solid {BORDE};
            border-radius: 11px; padding: 16px 18px;
        }}
        .sd-kpi .label {{ font-size: 11px; color: {TEXTO_ATENUADO}; font-weight: 500; }}
        .sd-kpi .valor {{
            font-size: 26px; font-weight: 700; letter-spacing: -.02em;
            font-variant-numeric: tabular-nums; margin-top: 7px;
        }}
        .sd-kpi .unidad {{ font-size: 12px; color: #8A98A8; margin-left: 4px; font-weight: 400; }}

        /* ── Tabla mapa curricular ── */
        .sd-tabla, .st-key-sd_tabla_mapa {{
            background: {SUPERFICIE}; border: 1px solid {BORDE};
            border-radius: 12px; overflow: hidden;
        }}
        .st-key-sd_tabla_mapa [data-testid="stMarkdownContainer"] {{ margin: 0; }}
        .sd-tabla-header {{
            display: grid; grid-template-columns: minmax(0,1.55fr) 52px minmax(0,0.9fr) minmax(0,0.9fr) minmax(0,0.9fr) minmax(88px,1fr);
            gap: 10px; padding: 11px 18px; background: #F7F9FC;
            border-bottom: 1px solid #E8EDF3;
            font-size: 10px; font-weight: 600; color: {TEXTO_ATENUADO};
            text-transform: uppercase; letter-spacing: .04em;
        }}
        .sd-tabla-row {{
            display: grid; grid-template-columns: minmax(0,1.55fr) 52px minmax(0,0.9fr) minmax(0,0.9fr) minmax(0,0.9fr) minmax(88px,1fr);
            gap: 10px; padding: 13px 18px; align-items: center;
            border-bottom: 1px solid #EEF1F6; background: #fff;
        }}
        .sd-tabla-row .col-bloque {{ min-width: 0; }}
        .sd-tabla-row .bloque-tit {{
            display: flex; align-items: center; gap: 9px;
        }}
        .sd-tabla-row .bloque-nombre {{
            font-size: 13px; font-weight: 600; color: #1B2937;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }}
        .sd-tabla-row .bloque-sub {{
            font-size: 11px; color: #8693A3; margin-top: 5px; margin-left: 33px;
        }}
        .sd-tabla-row .col-horas {{
            font-size: 12.5px; color: {TEXTO_SEC}; font-variant-numeric: tabular-nums;
        }}
        .sd-tabla-row .col-est {{
            font-size: 10.5px; min-width: 0; overflow: hidden;
        }}
        .sd-tabla-row .col-pill {{ text-align: right; min-width: 0; }}
        .sd-tabla-row:last-child {{ border-bottom: none; }}
        .sd-bloque-num {{
            width: 24px; height: 24px; border-radius: 6px; flex-shrink: 0;
            background: #EDF2F8; color: {acento_oscuro};
            font-size: 12px; font-weight: 700;
            display: inline-flex; align-items: center; justify-content: center;
        }}
        .sd-estado-pill {{
            display: inline-flex; align-items: center; gap: 4px;
            padding: 3px 8px; border-radius: 20px;
            font-size: 10px; font-weight: 600;
            white-space: nowrap; max-width: 100%;
        }}
        .sd-estado-inline {{
            display: inline-flex; align-items: center; gap: 4px;
            font-size: 10.5px; font-weight: 500;
            white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; max-width: 100%;
        }}
        .sd-estado-inline .dot {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}

        /* ── Tarjetas genéricas ── */
        .sd-card {{
            background: {SUPERFICIE}; border: 1px solid {BORDE};
            border-radius: 12px; padding: 18px 20px;
        }}
        .sd-card-header {{
            background: #F7F9FC; border-bottom: 1px solid #E8EDF3;
            padding: 13px 18px; margin: -18px -20px 16px;
            border-radius: 12px 12px 0 0;
        }}
        .sd-vista-titulo {{
            font-size: 15px; font-weight: 600; letter-spacing: -.01em;
            color: {TEXTO}; margin: 0 0 4px;
        }}
        .sd-vista-desc {{
            font-size: 12.5px; color: {TEXTO_ATENUADO}; margin: 0 0 18px;
        }}

        /* ── Chips de bloque ── */
        .sd-chip-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 18px; }}
        .sd-chip {{
            display: inline-flex; align-items: center; gap: 6px;
            padding: 7px 14px; border-radius: 20px;
            border: 1px solid {BORDE}; background: #fff;
            font-size: 12px; font-weight: 500; color: {TEXTO_SEC};
            cursor: pointer; font-family: 'DM Sans', sans-serif;
        }}
        .sd-chip.activo {{
            border-color: {acento}; background: #EAF2FA; color: {acento_oscuro};
        }}
        .sd-chip .dot {{ width: 6px; height: 6px; border-radius: 50%; }}

        /* ── Inputs file tag ── */
        .sd-file-tag {{
            width: 30px; height: 36px; border-radius: 5px; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            font-size: 8.5px; font-weight: 700;
        }}
        .sd-file-tag.pdf {{ background: #FBE9E7; color: #C0392B; }}
        .sd-file-tag.pptx {{ background: #FDEFE0; color: #C0700E; }}

        /* ── Cobertura checklist ── */
        .sd-cob-item {{
            display: flex; align-items: flex-start; gap: 10px;
            padding: 7px 0; font-size: 12.5px; color: {TEXTO_SEC};
        }}
        .sd-cob-icon {{
            width: 16px; height: 16px; border-radius: 4px; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
            font-size: 10px; font-weight: 700;
        }}
        .sd-cob-icon.ok {{ background: #E3F1EA; color: #2E815A; }}
        .sd-cob-icon.parcial {{ background: #FBF1DD; color: #9A6608; }}
        .sd-cob-icon.pend {{ background: #EDF1F6; color: #94A3B8; }}

        /* ── Mod badge ── */
        .sd-mod-badge {{
            display: inline-flex; align-items: center; gap: 6px;
            padding: 4px 12px; border-radius: 20px;
            background: #FBF1DD; color: #9A6608;
            font-size: 11px; font-weight: 600;
        }}

        /* ── Preview window chrome ── */
        .sd-preview-bar {{
            display: flex; align-items: center; gap: 8px;
            padding: 10px 14px; background: #F7F9FC;
            border-bottom: 1px solid #E8EDF3;
            border-radius: 12px 12px 0 0;
        }}
        .sd-preview-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
        .sd-preview-dot.r {{ background: #FF5F57; }}
        .sd-preview-dot.a {{ background: #FEBC2E; }}
        .sd-preview-dot.v {{ background: #28C840; }}

        /* ── Botones export deshabilitados ── */
        .sd-export-hint {{
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 11px; font-weight: 500;
        }}

        /* ── Landing (sin asignatura) ── */
        .sd-landing-wrap {{ text-align: center; padding: 56px 24px 8px; }}
        .sd-landing-badge {{
            display: inline-flex; align-items: center; gap: 6px; padding: 5px 14px;
            border-radius: 20px; background: #EAF2FA; color: {acento_oscuro};
            font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
        }}
        .sd-landing-title {{
            margin: 18px 0 6px; font-size: 32px; font-weight: 700;
            color: {TEXTO}; letter-spacing: -.01em;
        }}
        .sd-landing-sub {{ margin: 0; font-size: 14px; font-weight: 600; color: {TEXTO_SEC}; }}
        .sd-landing-escuela {{ margin: 4px 0 0; font-size: 12.5px; color: #8693A3; }}
        .sd-landing-footer {{
            text-align: center; font-size: 11px; color: #9AA7B6; margin-top: 32px;
        }}
        .sd-landing-card {{
            border: 1px solid {BORDE}; border-radius: 14px; padding: 26px 22px;
            background: #fff; text-align: center; min-height: 168px;
            display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px;
        }}
        .sd-landing-card .icono {{ font-size: 26px; margin-bottom: 4px; }}
        .sd-landing-card .tit {{ font-size: 15px; font-weight: 700; }}
        .sd-landing-card .desc {{ font-size: 12px; color: {TEXTO_ATENUADO}; line-height: 1.45; }}
        .sd-landing-card.nuevo {{ background: #F3FAF6; border-color: #CFE9DA; }}
        .sd-landing-card.nuevo .tit {{ color: #1F7A4D; }}
        .sd-landing-card.cargar {{ background: #F2F7FC; border-color: #D6E4F2; }}
        .sd-landing-card.cargar .tit {{ color: {acento_oscuro}; }}

        /* ── Markdown mono en editor ── */
        textarea[data-testid="stTextArea"] {{
            font-family: 'DM Mono', ui-monospace, Menlo, monospace !important;
            font-size: 12.5px !important;
        }}

        /* ── Sticky panel (cobertura / rail) ── */
        .sd-sticky-panel {{
            position: sticky; top: 80px;
        }}

        /* ── Rail presentación ── */
        .sd-rail-item {{
            padding: 10px 0; border-bottom: 1px solid #F0F3F7;
            font-size: 12.5px;
        }}
        .sd-rail-item .tit {{ font-weight: 600; color: {TEXTO}; }}
        .sd-rail-item .ancla {{ font-size: 11px; color: {TEXTO_ATENUADO}; }}

        /* ── Iteración historial ── */
        .sd-iter {{
            padding: 6px 10px; border-radius: 6px; font-size: 12px;
            color: {TEXTO_SEC}; margin-bottom: 4px;
        }}
        .sd-iter.activa {{ background: #E7F0FA; color: {acento}; font-weight: 600; }}

        /* ── Dashed add button area ── */
        .sd-dashed-hint {{
            margin-top: 12px; padding: 10px;
            border: 1.5px dashed #C3D0DF; border-radius: 8px;
            background: #F8FAFC; text-align: center;
            font-size: 12.5px; color: {acento}; font-weight: 600;
        }}

        /* ── Ocultar título de página por defecto cuando hay topbar ── */
        .sd-hide-default-title + div {{ margin-top: 0 !important; }}

        /* ── Sidebar: refuerzo final (anula fugas de estilos globales) ── */
        section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {{
            background-color: rgba(255,255,255,.08) !important;
            color: #C5D4E8 !important;
            border-color: rgba(255,255,255,.12) !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background-color: {SIDEBAR_ACTIVO} !important;
            color: #F0F5FA !important;
            border-color: rgba(61,139,212,.35) !important;
        }}
        section[data-testid="stSidebar"] .stButton > button * {{
            color: inherit !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="secondary"] *,
        section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) * {{
            color: #C5D4E8 !important;
        }}
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] * {{
            color: #F0F5FA !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_button_fix(
    acento: str = ACENTO,
    acento_oscuro: str = ACENTO_OSCURO,
    texto: str = TEXTO,
) -> None:
    """Fix de botones negros — inyectar al FINAL del script (después de widgets)."""
    st.markdown(
        f"""
        <style id="sd-button-fix">
        /* Vence clases Emotion dinámicas en el propio <button> */
        .stApp [data-testid="stAppViewContainer"] section.main button[class*="st-emotion-cache"][kind="secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[class*="st-emotion-cache"][data-testid="baseButton-secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[class*="st-emotion-cache"][data-testid="stBaseButton-secondary"] {{
            background-color: #FFFFFF !important;
            background-image: none !important;
            background: #FFFFFF !important;
            color: #334155 !important;
            border: 1px solid #D7DEE7 !important;
            box-shadow: none !important;
        }}
        /* ── FIX GLOBAL botones negros (vence estilos Emotion de Streamlit) ── */
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="stBaseButton-secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main .stButton button[kind="secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main .stButton button[data-testid="baseButton-secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main div[data-testid="stButton"] button[kind="secondary"],
        .stApp [data-testid="stAppViewContainer"] section.main div[data-testid="stButton"] button[data-testid="baseButton-secondary"] {{
            background-color: #FFFFFF !important;
            background-image: none !important;
            background: #FFFFFF !important;
            color: #334155 !important;
            border: 1px solid #D7DEE7 !important;
            box-shadow: none !important;
        }}
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="secondary"] p,
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="secondary"] span,
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="secondary"] div,
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-secondary"] p,
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-secondary"] span,
        .stApp [data-testid="stAppViewContainer"] section.main .stButton button p,
        .stApp [data-testid="stAppViewContainer"] section.main .stButton button span {{
            color: inherit !important;
            background: transparent !important;
            background-color: transparent !important;
        }}
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="primary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-primary"],
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="stBaseButton-primary"] {{
            background-color: {acento} !important;
            background: {acento} !important;
            color: #FFFFFF !important;
            border-color: {acento_oscuro} !important;
        }}
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="primary"] p,
        .stApp [data-testid="stAppViewContainer"] section.main button[kind="primary"] span,
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-primary"] p,
        .stApp [data-testid="stAppViewContainer"] section.main button[data-testid="baseButton-primary"] span {{
            color: #FFFFFF !important;
            background: transparent !important;
        }}

        /* ── File uploader: botón "Browse files" y botón de borrar fichero ── */
        .stApp [data-testid="stFileUploaderDropzone"] button[class*="st-emotion-cache"] {{
            background-color: #FFFFFF !important;
            background: #FFFFFF !important;
            color: #334155 !important;
            border: 1px solid #D7DEE7 !important;
            box-shadow: none !important;
        }}
        .stApp [data-testid="stFileUploaderDeleteBtn"] button[class*="st-emotion-cache"] {{
            background-color: transparent !important;
            background: transparent !important;
            color: #475667 !important;
            border: none !important;
        }}

        /* Excepciones por componente */
        div[class*="st-key-landing_btn_nuevo"] .stButton > button {{
            background: #F3FAF6 !important; border-color: #CFE9DA !important; color: #1F7A4D !important;
        }}
        div[class*="st-key-landing_btn_cargar"] .stButton > button {{
            background: #F2F7FC !important; border-color: #D6E4F2 !important; color: {acento_oscuro} !important;
        }}
        div[class*="st-key-sd_asig_item_"] div[class*="st-key-sd_asig_btn_"] .stButton > button {{
            background: #fff !important; border: none !important; color: {texto} !important;
        }}
        div[class*="st-key-banner_nav_"] .stButton > button[kind="primary"] {{
            background: #F2F7FC !important; color: {acento_oscuro} !important;
            border-color: #B8D4EF !important; box-shadow: inset 3px 0 0 {acento} !important;
        }}
        .st-key-sd_tabla_mapa div[class*="st-key-mapa_btn_"] .stButton > button {{
            background: #fff !important; border: 1px solid #D7DEE7 !important; color: {acento} !important;
        }}
        div[class*="st-key-prs_nueva_"] .stButton > button {{
            background-color: #fff !important; border: 1px solid #D7DEE7 !important; color: {texto} !important;
        }}
        [data-testid="stProgress"] [data-baseweb="progress-bar"] > div > div {{
            background-color: #E0E6EE !important;
        }}
        [data-testid="stProgress"] [data-baseweb="progress-bar"] > div > div > div {{
            background-color: {acento} !important;
        }}
        div[class*="st-key-sd_input_dashed_"] .stButton > button {{
            background: #F8FAFC !important; border: 1.5px dashed #C3D0DF !important;
            color: {acento} !important;
        }}
        div[class*="st-key-sd_btn_aprobar_"] .stButton > button:not(:disabled) {{
            background: #2E815A !important; border-color: #257349 !important; color: #fff !important;
        }}
        .st-key-sd_chip_scroll .stButton > button[kind="primary"] {{
            background: #E7F0FA !important; color: {acento_oscuro} !important;
            border-color: {acento} !important;
        }}
        .st-key-sd_topbar_actions .stButton > button[kind="primary"] {{
            background: {acento} !important; color: #fff !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
