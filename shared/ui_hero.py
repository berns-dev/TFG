"""Hero iframe y estilos globales compartidos entre agentes Streamlit."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

_ARROW_SVG_DEFAULT = (
    '<svg class="arrow" width="20" height="12" viewBox="0 0 20 12" fill="none">'
    '<path d="M0 6h16M12 2l4 4-4 4" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)
_ARROW_SVG_COMPACT = (
    '<svg class="arrow" width="16" height="10" viewBox="0 0 20 12" fill="none">'
    '<path d="M0 6h16M12 2l4 4-4 4" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)

_DARK_LIGHT_SYNC_JS = r"""
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
"""


def _workflow_css(compact: bool) -> str:
    if compact:
        return (
            ".workflow{display:flex;align-items:center;margin-top:28px;padding:16px 20px;"
            "background:var(--card);border:.5px solid var(--border);border-radius:10px;}"
            ".step{display:flex;align-items:center;gap:10px;flex:1;}"
            ".num{width:28px;height:28px;border-radius:50%;background:#185FA5;color:#FFF;"
            "font-size:12px;font-weight:500;display:flex;align-items:center;justify-content:center;"
            "flex-shrink:0;box-shadow:0 2px 8px rgba(24,95,165,.25);}"
            ".lbl{font-size:9px;font-weight:500;color:var(--text3);text-transform:uppercase;"
            "letter-spacing:.08em;margin-bottom:2px;}"
            ".sdesc{font-size:12px;font-weight:500;color:var(--text1);}"
            ".arrow{flex-shrink:0;margin:0 4px;color:var(--arrow);}"
        )
    return (
        ".workflow{display:flex;align-items:center;margin-top:28px;padding:18px 24px;"
        "background:var(--card);border:.5px solid var(--border);border-radius:10px;}"
        ".step{display:flex;align-items:center;gap:12px;flex:1;}"
        ".num{width:30px;height:30px;border-radius:50%;background:#185FA5;color:#FFF;"
        "font-size:13px;font-weight:500;display:flex;align-items:center;justify-content:center;"
        "flex-shrink:0;box-shadow:0 2px 8px rgba(24,95,165,.25);}"
        ".lbl{font-size:10px;font-weight:500;color:var(--text3);text-transform:uppercase;"
        "letter-spacing:.08em;margin-bottom:3px;}"
        ".sdesc{font-size:13px;font-weight:500;color:var(--text1);}"
        ".arrow{flex-shrink:0;margin:0 8px;color:var(--arrow);}"
    )


def _build_hero_html(
    agent_number: str,
    title_before: str,
    title_keyword: str,
    description: str,
    steps: list[str],
    *,
    compact: bool = False,
) -> str:
    arrow = _ARROW_SVG_COMPACT if compact else _ARROW_SVG_DEFAULT
    workflow_parts: list[str] = []
    for idx, label in enumerate(steps):
        if idx > 0:
            workflow_parts.append(arrow)
        workflow_parts.append(
            f'<div class="step">'
            f'<div class="num">{idx + 1}</div>'
            f"<div><div class=\"lbl\">Paso {idx + 1}</div>"
            f'<div class="sdesc">{label}</div></div>'
            f"</div>"
        )
    workflow_html = "\n    ".join(workflow_parts)
    return f"""<!DOCTYPE html><html><head>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
:root{{
  --text1:#2C2C2A;--text2:#5F5E5A;--text3:#888780;
  --card:rgba(0,0,0,0.03);--border:rgba(0,0,0,0.1);--arrow:rgba(0,0,0,0.2);
}}
:root.dark{{
  --text1:#FAFAFA;--text2:rgba(255,255,255,0.65);--text3:rgba(255,255,255,0.4);
  --card:rgba(255,255,255,0.06);--border:rgba(255,255,255,0.1);--arrow:rgba(255,255,255,0.22);
}}
@media(prefers-color-scheme:dark){{:root:not(.light){{
  --text1:#FAFAFA;--text2:rgba(255,255,255,0.65);--text3:rgba(255,255,255,0.4);
  --card:rgba(255,255,255,0.06);--border:rgba(255,255,255,0.1);--arrow:rgba(255,255,255,0.22);
}}}}
body{{background:transparent;font-family:'DM Sans',sans-serif;overflow:hidden;padding:0 2px;}}
.hero{{padding:32px 0 16px 0;}}
.eyebrow{{font-size:11px;font-weight:500;color:#185FA5;letter-spacing:.14em;
  text-transform:uppercase;margin-bottom:12px;}}
.title{{font-family:'Playfair Display',serif;font-size:38px;font-weight:500;
  color:var(--text1);line-height:1.15;margin-bottom:14px;}}
.title .accent{{color:#185FA5;}}
.desc{{font-size:15px;font-weight:400;color:var(--text2);line-height:1.6;max-width:560px;}}
{_workflow_css(compact)}
</style>
<script>
{_DARK_LIGHT_SYNC_JS}
</script>
</head><body>
<div class="hero">
  <div class="eyebrow">Agente {agent_number}</div>
  <div class="title">{title_before}<span class="accent">{title_keyword}</span></div>
  <div class="desc">{description}</div>
  <div class="workflow">
    {workflow_html}
  </div>
</div>
</body></html>"""


def _global_button_css(
    *,
    button_full_width: bool = False,
    upload_zone_background: bool = False,
    disabled_button_styles: bool = False,
) -> str:
    uploader_bg = (
        "    background-color: var(--secondary-background-color) !important;\n"
        if upload_zone_background
        else ""
    )
    button_width = "    width: 100%;\n" if button_full_width else ""
    disabled_block = ""
    if disabled_button_styles:
        disabled_block = """
.stButton > button:disabled {
    background-color: rgba(128,128,128,0.2) !important;
    color: var(--text-color) !important;
    opacity: 0.5 !important;
}
"""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap');

[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] {{
    background-color: var(--background-color) !important;
}}
section[data-testid="stMain"] > div {{
    background-color: var(--background-color) !important;
}}
[data-testid="stSidebar"] {{
    background-color: var(--secondary-background-color) !important;
    border-right: 1px solid rgba(128,128,128,0.2) !important;
}}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
    background-color: var(--secondary-background-color) !important;
    border-radius: 10px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
}}
[data-testid="stFileUploaderDropzone"] {{
    border-radius: 10px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
{uploader_bg}}}
.stButton > button {{
    background-color: #185FA5 !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
{button_width}    letter-spacing: 0.01em;
}}
.stButton > button:hover {{
    background-color: #0C447C !important;
}}
{disabled_block}.stDownloadButton > button {{
    border-radius: 12px !important;
    border: 1px solid rgba(128,128,128,0.2) !important;
    color: #185FA5 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-weight: 500 !important;
}}
.stDownloadButton > button:hover {{
    background-color: rgba(24,95,165,0.05) !important;
}}
[data-testid="stExpander"] {{
    background-color: var(--secondary-background-color) !important;
    border: 0.5px solid rgba(128,128,128,0.2) !important;
    border-radius: 10px !important;
}}
</style>
"""


def render_hero(
    agent_number: str,
    title_keyword: str,
    steps: list[str],
    *,
    description: str,
    title_before: str,
    compact: bool = False,
    button_full_width: bool = False,
    upload_zone_background: bool = False,
    disabled_button_styles: bool = False,
    hero_height: int = 340,
) -> None:
    """Inyecta CSS global de la suite y el hero iframe con sync dark/light."""
    st.markdown(
        _global_button_css(
            button_full_width=button_full_width,
            upload_zone_background=upload_zone_background,
            disabled_button_styles=disabled_button_styles,
        ),
        unsafe_allow_html=True,
    )
    hero_html = _build_hero_html(
        agent_number,
        title_before,
        title_keyword,
        description,
        steps,
        compact=compact,
    )
    components.html(hero_html, height=hero_height, scrolling=False)
