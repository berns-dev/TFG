"""Taller de visualizaciones: generación y refinamiento desde prompt del profesor."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import anthropic

from generador_html import (
    _is_valid_html,
    _slug,
    extraer_slug_desde_html,
    instruccion_es_mecanismo_svg,
    sanitizar_chartjs_html,
    validar_bloque_html,
    validar_grafica_taller,
)
from prs_config import (
    ANTHROPIC_API_KEY,
    MODEL_FAST,
    MODEL_SMART,
    REQUEST_TIMEOUT_SECONDS,
)
from prs_prompts import (
    PROMPT_TALLER_GENERADOR,
    PROMPT_TALLER_RAZONADOR,
    PROMPT_TALLER_REFINADOR,
    PROMPT_TALLER_REVISOR_FISICA,
    build_taller_generador_message,
    build_taller_razonador_message,
    build_taller_refinador_message,
    build_taller_revisor_message,
)

_MONOREPO_ROOT = Path(__file__).resolve().parent.parent
if str(_MONOREPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_MONOREPO_ROOT))

from shared.anthropic_client import call_messages  # noqa: E402

logger = logging.getLogger(__name__)

_MAX_TOKENS = 16384
_MAX_TOKENS_REFINADOR = 16384
_MAX_TOKENS_RAZONADOR = 8192
_MAX_TOKENS_REVISOR = 8192
_MAX_SLUG_TALLER = 40
_MAX_REINTENTOS_GRAFICA = 2
_MAX_REINTENTOS_REFINADOR = 2
_KEYWORDS_CONTINUIDAD = (
    "salto", "continu", "cort", "hueco", "discontinu", "vertical", "entera",
    "decrez", "decrec", "suave", "diferencia", "rect", "angul", "estrinc",
    "máximo", "maximo", "monóton", "monoton", "sube", "baja",
)
_KEYWORDS_GRAFICA = (
    "curva", "gráfic", "grafic", "gráfico", "grafico", "chart", "diagrama",
    "serie", "eje", "forma", "trazo", "visualiz", "plot", "representa",
)
_KEYWORDS_SOLO_TEXTO = (
    "solo el texto", "solo texto", "descripción", "descripcion", "explicación",
    "explicacion", "párrafo", "parrafo", "título", "titulo", "leyenda",
)


def _slug_taller(titulo: str | None, instruccion: str) -> str:
    """Slug corto para el taller — evita HTML gigante y errores de truncado."""
    base = _slug((titulo or instruccion)[:50])
    if len(base) > _MAX_SLUG_TALLER:
        base = base[:_MAX_SLUG_TALLER].rstrip("-")
    return base or "viz"


def _slug_para_regeneracion(slug_actual: str, instruccion: str) -> str:
    """Slug corto al regenerar — no reutilizar slugs largos del HTML anterior."""
    if slug_actual and len(slug_actual) <= _MAX_SLUG_TALLER:
        return slug_actual
    return _slug_taller(None, instruccion)


def _extraer_razonamiento_de_mensaje(user_msg: str) -> str:
    marcador = "RAZONAMIENTO PREVIO"
    if marcador not in user_msg:
        return ""
    return user_msg.split(marcador, 1)[1].strip()


def _mensaje_compacto_generador(
    slug: str,
    instruccion: str,
    razonamiento: str = "",
) -> str:
    """Prompt mínimo para reintentos (evita reenviar markdown enorme)."""
    partes = [
        f"SLUG_EXACTO: {slug}",
        f"INSTRUCCIÓN: {instruccion.strip()[:800]}",
    ]
    if razonamiento.strip():
        partes += [
            "",
            "ESPECIFICACIÓN DE MODELADO (implementar con fidelidad):",
            razonamiento.strip()[:6000],
        ]
    return "\n".join(partes)


def _instruccion_pide_corregir_curva(instruccion: str) -> bool:
    """True si el refinamiento debe regenerar la gráfica (no parchear HTML)."""
    low = instruccion.lower()
    if any(k in low for k in _KEYWORDS_SOLO_TEXTO):
        if not any(k in low for k in _KEYWORDS_CONTINUIDAD + _KEYWORDS_GRAFICA):
            return False
    if any(k in low for k in _KEYWORDS_CONTINUIDAD):
        return True
    if any(k in low for k in _KEYWORDS_GRAFICA):
        return any(
            k in low
            for k in (
                "corrige", "ajusta", "mejora", "arregla", "haz", "muestra",
                "completa", "rango", "escala", "sube", "baja", "cambia",
            )
        )
    return False


def _combinar_instrucciones_curva(
    historial: list[dict] | None,
    instruccion: str,
) -> str:
    """Une el historial de prompts del profesor con la instrucción actual."""
    partes: list[str] = []
    for h in historial or []:
        if h.get("rol") == "profesor" and (h.get("texto") or "").strip():
            partes.append(h["texto"].strip())
    if instruccion.strip():
        partes.append(instruccion.strip())
    if not partes:
        return instruccion.strip()
    if len(partes) == 1:
        return partes[0]
    cuerpo = "\n".join(f"- {p}" for p in partes[:-1])
    return (
        "Instrucciones acumuladas del profesor sobre esta visualización:\n"
        f"{cuerpo}\n\n"
        f"Ajuste prioritario ahora: {partes[-1]}"
    )


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=float(REQUEST_TIMEOUT_SECONDS),
    )


def _limpiar_respuesta_html(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw).strip()
    return raw


def _reforzar_suavizado_chartjs(html: str) -> str:
    """Corrige tension: 0 explícito en datasets Chart.js del taller."""
    return sanitizar_chartjs_html(html)


def _llamar_modelo(
    system: str,
    user_message: str,
    max_tokens: int = _MAX_TOKENS,
    model: str = MODEL_SMART,
) -> tuple[str, str]:
    client = _get_client()
    raw, stop = call_messages(
        client,
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    if stop == "max_tokens":
        logger.warning("[TALLER] Respuesta truncada por límite de tokens (%d)", max_tokens)
    return _limpiar_respuesta_html(raw), stop or ""


def _razonar_instruccion(
    instruccion: str,
    markdown_bloque: str,
    texto_original: str | None = None,
) -> tuple[str, bool]:
    """Especificación de modelado (Sonnet). Devuelve (texto, truncado)."""
    try:
        user_msg = build_taller_razonador_message(
            instruccion, markdown_bloque, texto_original
        )
        razonamiento, stop = _llamar_modelo(
            PROMPT_TALLER_RAZONADOR, user_msg, max_tokens=_MAX_TOKENS_RAZONADOR
        )
        truncado = stop == "max_tokens"
        if truncado:
            logger.warning("[TALLER] Razonador truncado — se omitirá el revisor de física")
        logger.info("[TALLER] Razonamiento: %s", razonamiento[:500])
        return razonamiento, truncado
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TALLER] Razonamiento falló: %s", exc)
        return "", False


def _revisar_especificacion(
    instruccion: str,
    razonamiento: str,
    markdown_bloque: str,
) -> str:
    """Revisor de física (Haiku) — corrige la spec antes del generador."""
    if not razonamiento.strip():
        return razonamiento
    try:
        user_msg = build_taller_revisor_message(
            instruccion, razonamiento, markdown_bloque
        )
        revisado, stop = _llamar_modelo(
            PROMPT_TALLER_REVISOR_FISICA,
            user_msg,
            max_tokens=_MAX_TOKENS_REVISOR,
            model=MODEL_FAST,
        )
        if stop == "max_tokens":
            logger.warning("[TALLER] Revisor truncado — se conserva la spec del razonador")
            return razonamiento
        if revisado.strip():
            logger.info("[TALLER] Spec revisada: %s", revisado[:500])
            return revisado
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TALLER] Revisor física falló: %s", exc)
    return razonamiento


def _validar_html_taller(raw: str, slug: str, instruccion: str) -> tuple[bool, str]:
    ok, motivo = validar_bloque_html(raw, slug, requiere_autoarranque=True)
    if not ok:
        return False, motivo
    ok_g, motivo_g = validar_grafica_taller(raw, instruccion)
    if not ok_g:
        return False, motivo_g
    return True, ""


def _generar_html(
    system: str,
    user_msg: str,
    slug: str,
    instruccion: str,
    max_tokens: int = _MAX_TOKENS,
    max_reintentos: int = _MAX_REINTENTOS_GRAFICA,
    razonamiento: str = "",
) -> str:
    spec = (razonamiento or _extraer_razonamiento_de_mensaje(user_msg)).strip()
    raw, stop = _llamar_modelo(system, user_msg, max_tokens=max_tokens)
    raw = _reforzar_suavizado_chartjs(raw)

    for intento in range(max_reintentos + 1):
        if _is_valid_html(raw):
            ok, motivo = _validar_html_taller(raw, slug, instruccion)
            if ok:
                return raw
        else:
            motivo = "la respuesta del modelo no parece HTML válido"
        if intento >= max_reintentos:
            raise ValueError(f"HTML generado inválido: {motivo}")
        logger.warning("[TALLER] Reintento %d — %s", intento + 1, motivo)
        truncado_real = stop == "max_tokens" or "truncado" in motivo
        if truncado_real:
            correccion = (
                "CORRECCIÓN OBLIGATORIA: la respuesta anterior se CORTÓ o quedó incompleta. "
                "Regenera el bloque HTML COMPLETO pero COMPACTO: máximo 1 párrafo de texto, "
                "sin comentarios JS, script mínimo con chart + initBloque. "
                f"OBLIGATORIO: window['initBloque_{slug}'] y DOMContentLoaded; "
                "cierra </script> (puede ir seguido de </div>)."
            )
            user_msg_retry = _mensaje_compacto_generador(slug, instruccion, spec)
            user_msg_retry += f"\n\n{correccion}"
        elif "initBloque" in motivo or "DOMContentLoaded" in motivo:
            correccion = (
                f"CORRECCIÓN OBLIGATORIA: {motivo}. "
                f"Define window['initBloque_{slug}'] como función global y registra "
                f"document.addEventListener('DOMContentLoaded', initBloque_{slug}). "
                "Regenera el bloque HTML completo y compacto."
            )
            user_msg_retry = _mensaje_compacto_generador(slug, instruccion, spec)
            user_msg_retry += f"\n\n{correccion}"
        elif "<svg>" in motivo or "mecanismo" in motivo:
            correccion = (
                f"CORRECCIÓN OBLIGATORIA: {motivo}. "
                "Patrón ANIMACION_MECANISMO: SVG en corte (sin canvas ni Chart.js), "
                "conjunto móvil en un <g> con translate, botones con onclick, "
                f"window['initBloque_{slug}'] y DOMContentLoaded. Script compacto y cerrado."
            )
            user_msg_retry = _mensaje_compacto_generador(slug, instruccion, spec)
            user_msg_retry += f"\n\n{correccion}"
        elif "salto" in motivo or "discontinuidad" in motivo or "exponente" in motivo or "frontera" in motivo:
            correccion = (
                f"CORRECCIÓN OBLIGATORIA: {motivo}. "
                "Recalcula cada frontera entre tramos evaluando f(x) del tramo anterior "
                "y reutiliza el mismo (x,y) al iniciar el siguiente. Usa interpolación "
                "normalizada con exponente ≥1 entre fronteras. Muestreo ≥80 puntos por "
                "serie/tramo. Chart.js: tension: 0 si el muestreo es denso. "
                "Regenera el HTML completo."
            )
            user_msg_retry = f"{user_msg}\n\n{correccion}"
        else:
            correccion = (
                f"CORRECCIÓN OBLIGATORIA: el HTML anterior no pasó validación ({motivo}). "
                "Regenera el bloque completo corrigiendo solo eso."
            )
            user_msg_retry = f"{user_msg}\n\n{correccion}"
        raw, stop = _llamar_modelo(system, user_msg_retry, max_tokens=max_tokens)
        raw = _reforzar_suavizado_chartjs(raw)

    raise ValueError("La respuesta del modelo no parece HTML válido.")


def generar_desde_instruccion(
    instruccion: str,
    markdown_bloque: str,
    titulo: str = "Visualización",
    texto_original: str | None = None,
) -> tuple[str, str, str]:
    """Genera un fragmento HTML interactivo desde el prompt del profesor.

    Returns:
        (slug, html_fragment, razonamiento_spec)
    """
    slug = _slug_taller(titulo, instruccion)
    if instruccion_es_mecanismo_svg(instruccion):
        razonamiento = ""
    else:
        razonamiento, truncado = _razonar_instruccion(
            instruccion, markdown_bloque, texto_original
        )
        if razonamiento.strip() and not truncado:
            razonamiento = _revisar_especificacion(
                instruccion, razonamiento, markdown_bloque
            )

    system = PROMPT_TALLER_GENERADOR.replace("{slug}", slug)
    user_msg = build_taller_generador_message(
        slug, instruccion, markdown_bloque, texto_original, razonamiento
    )
    if instruccion_es_mecanismo_svg(instruccion):
        user_msg += (
            "\n\nPATRÓN OBLIGATORIO: ANIMACION_MECANISMO — SVG en corte transversal, "
            "sin <canvas> ni Chart.js. Botones Avanzar/Retroceder con onclick; "
            "émbolo+vástago en un <g> con translate; requestAnimationFrame."
        )
    raw = _generar_html(
        system, user_msg, slug, instruccion,
        max_tokens=_MAX_TOKENS,
        max_reintentos=_MAX_REINTENTOS_GRAFICA,
        razonamiento=razonamiento,
    )
    return slug, raw, razonamiento


def _regenerar_bloque_curva(
    slug: str,
    instruccion: str,
    markdown_bloque: str,
    texto_original: str | None = None,
    razonamiento_prev: str | None = None,
) -> tuple[str, str]:
    """Regenera el bloque completo (mejor que parchear HTML para correcciones de curva)."""
    spec_prev = (razonamiento_prev or "").strip()
    if spec_prev:
        razonamiento = _revisar_especificacion(instruccion, spec_prev, markdown_bloque)
    else:
        razonamiento, truncado = _razonar_instruccion(
            instruccion, markdown_bloque, texto_original
        )
        if razonamiento.strip() and not truncado:
            razonamiento = _revisar_especificacion(
                instruccion, razonamiento, markdown_bloque
            )
    system = PROMPT_TALLER_GENERADOR.replace("{slug}", slug)
    user_msg = build_taller_generador_message(
        slug, instruccion, markdown_bloque, texto_original, razonamiento
    )
    user_msg += (
        f"\n\nREGENERACIÓN COMPLETA (no parches sobre HTML anterior). "
        f"Mantén exactamente window['initBloque_{slug}'] y el listener DOMContentLoaded. "
        "Implementa las fórmulas de la especificación con muestreo denso."
    )
    raw = _generar_html(
        system, user_msg, slug, instruccion,
        max_tokens=_MAX_TOKENS_REFINADOR,
        max_reintentos=_MAX_REINTENTOS_REFINADOR,
        razonamiento=razonamiento,
    )
    return raw, razonamiento


def refinar_html(
    html_actual: str,
    instruccion: str,
    slug: str,
    razonamiento_spec: str | None = None,
    markdown_bloque: str | None = None,
    historial: list[dict] | None = None,
    texto_original: str | None = None,
) -> tuple[str, str | None]:
    """Refina un fragmento HTML existente según una nueva instrucción del profesor.

    Returns:
        (html_fragment, razonamiento_spec_actualizado o None si no cambió)
    """
    slug_html = extraer_slug_desde_html(html_actual)
    if slug_html:
        slug = slug_html

    if _instruccion_pide_corregir_curva(instruccion) and markdown_bloque:
        slug = _slug_para_regeneracion(slug, instruccion)
        instruccion_combinada = _combinar_instrucciones_curva(historial, instruccion)
        logger.info("[TALLER] Regeneración completa por ajuste de gráfica (slug=%s)", slug)
        html, spec = _regenerar_bloque_curva(
            slug,
            instruccion_combinada,
            markdown_bloque,
            texto_original,
            razonamiento_spec,
        )
        return html, spec

    spec = (razonamiento_spec or "").strip()
    inst_low = instruccion.lower()
    if spec and (
        any(k in inst_low for k in _KEYWORDS_CONTINUIDAD)
        or any(k in inst_low for k in _KEYWORDS_GRAFICA)
    ):
        spec = _revisar_especificacion(instruccion, spec, markdown_bloque or "")
    system = PROMPT_TALLER_REFINADOR.replace("{slug}", slug)
    user_msg = build_taller_refinador_message(
        slug, html_actual, instruccion, spec or None
    )
    if instruccion_es_mecanismo_svg(instruccion):
        user_msg += (
            "\n\nPATRÓN OBLIGATORIO: ANIMACION_MECANISMO — SVG sin <canvas> ni Chart.js."
        )
    html = _generar_html(
        system, user_msg, slug, instruccion,
        max_tokens=_MAX_TOKENS_REFINADOR,
        max_reintentos=_MAX_REINTENTOS_REFINADOR,
        razonamiento=spec,
    )
    return html, None


def sugerir_seccion_ancla(instruccion: str, opciones: list[str]) -> str:
    """Sugiere la opción de ancla (sección o figura) que mejor coincide con el prompt."""
    if not opciones:
        return ""
    inst_norm = instruccion.lower()
    mejor = ""
    mejor_score = 0
    for opcion in opciones:
        if opcion.startswith("[FIGURA:") and opcion.endswith("]"):
            texto = opcion[8:-1].strip()
        else:
            texto = opcion
        texto_low = texto.lower()
        if texto_low in inst_norm or any(w in inst_norm for w in texto_low.split() if len(w) > 3):
            score = len(texto_low)
            if score > mejor_score:
                mejor_score = score
                mejor = opcion
    return mejor or opciones[0]
