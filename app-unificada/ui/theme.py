"""Inyección de CSS — identidad visual institucional."""

import streamlit as st


def inject_theme(acento: str, acento_oscuro: str) -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap');

        .marca {{
            display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
        }}
        .marca .icono {{
            width: 34px; height: 34px; border-radius: 8px; background: {acento}; flex-shrink: 0;
        }}
        .marca .nombre {{
            font-family: 'Playfair Display', serif; font-size: 15px; font-weight: 500;
            color: var(--text-color); line-height: 1.1;
        }}
        .marca .sub {{
            font-family: 'DM Sans', sans-serif; font-size: 10px;
            color: var(--text-color); opacity: 0.5;
            letter-spacing: 0.12em; text-transform: uppercase;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] > div[role="radiogroup"] {{
            display: flex !important; flex-direction: column !important; gap: 2px !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] input[type="radio"] {{
            display: none !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
            display: flex !important; align-items: center !important;
            padding: 9px 12px !important; border-radius: 8px !important;
            background: transparent !important; border: none !important;
            width: 100% !important; cursor: pointer !important;
            font-family: 'DM Sans', sans-serif !important; font-size: 13px !important;
            color: var(--text-color) !important; opacity: 0.65;
            font-weight: 400 !important; margin: 0 !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:hover {{
            background: rgba(24, 95, 165, 0.06) !important; opacity: 1 !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {{
            background: rgba(24, 95, 165, 0.10) !important; color: {acento} !important;
            opacity: 1 !important; font-weight: 500 !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stRadio"] label p {{
            margin: 0 !important; line-height: 1.4 !important;
        }}
        .file-chip {{
            display: inline-block; padding: 3px 10px; margin: 2px 4px 2px 0;
            border-radius: 12px; background: rgba(24, 95, 165, 0.08);
            color: {acento_oscuro}; font-family: 'DM Sans', sans-serif; font-size: 12px;
        }}
        .seccion {{
            display: flex; align-items: center; gap: 12px; margin: 4px 0 18px 0;
        }}
        .seccion .barra {{
            width: 3px; height: 30px; background: {acento}; border-radius: 2px; flex-shrink: 0;
        }}
        .seccion .titulo {{
            font-family: 'Playfair Display', serif; font-size: 26px; font-weight: 500;
            color: var(--text-color); line-height: 1.1;
        }}
        .asignatura-sidebar-nombre {{
            font-family: 'Playfair Display', serif; font-size: 14px; font-weight: 500;
            color: {acento_oscuro}; line-height: 1.3; margin: 4px 0 10px 2px;
            word-break: break-word;
        }}
        .portfolio-subtitulo {{
            font-family: 'DM Sans', sans-serif; font-size: 14px;
            color: var(--text-color); opacity: 0.6; margin: -8px 0 20px 0;
        }}
        .portfolio-card {{
            background: #F7F8FA;
            border: 1px solid rgba(0,0,0,0.07);
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 10px;
            transition: box-shadow 0.15s ease;
        }}
        .portfolio-card:hover {{
            box-shadow: 0 2px 12px rgba(24, 95, 165, 0.08);
        }}
        .portfolio-card .nombre {{
            font-family: 'Playfair Display', serif; font-size: 17px; font-weight: 500;
            color: var(--text-color); margin-bottom: 6px;
        }}
        .portfolio-card .meta {{
            font-family: 'DM Sans', sans-serif; font-size: 12px;
            color: var(--text-color); opacity: 0.65;
        }}
        .badge {{
            display: inline-block; padding: 2px 10px; border-radius: 20px;
            font-family: 'DM Sans', sans-serif; font-size: 11px; font-weight: 500;
        }}
        .badge-sin-organizar {{ background: #E8EAED; color: #5F6368; }}
        .badge-en-curso {{ background: rgba(24, 95, 165, 0.12); color: {acento_oscuro}; }}
        .badge-completo {{ background: rgba(34, 134, 58, 0.12); color: #1B6B2F; }}
        .inputs-seccion-titulo {{
            font-family: 'DM Sans', sans-serif; font-size: 11px; font-weight: 500;
            letter-spacing: 0.1em; text-transform: uppercase;
            color: var(--text-color); opacity: 0.55; margin: 18px 0 10px 0;
        }}
        .inputs-tabla-header {{
            font-family: 'DM Sans', sans-serif; font-size: 12px; font-weight: 500;
            color: var(--text-color); opacity: 0.5; padding-bottom: 6px;
            border-bottom: 1px solid rgba(0,0,0,0.08);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
