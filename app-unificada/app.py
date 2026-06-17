"""App Streamlit unificada de la suite de agentes docentes del TFG.

Punto de entrada único que reúne los tres agentes (Organizador, Contenido,
Presentación) sobre la base de datos compartida `database/db.py`.

Arranque:
    streamlit run app-unificada/app.py
"""

import difflib
from datetime import datetime
import importlib.util as _importlib_util
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import streamlit as st

# =============================================================================
# Rutas del monorepo
# =============================================================================

RAIZ_MONOREPO = str(Path(__file__).resolve().parent.parent)
RAIZ_ORGANIZADOR = os.path.join(RAIZ_MONOREPO, "agente-organizador")

if RAIZ_MONOREPO not in sys.path:
    sys.path.insert(0, RAIZ_MONOREPO)

from database import db  # noqa: E402

RUTA_DB = os.path.join(RAIZ_MONOREPO, "data", "tfg.db")

# =============================================================================
# Identidad visual
# =============================================================================

ACENTO = "#185FA5"
ACENTO_OSCURO = "#0C447C"

VISTAS = ["Resumen", "Inputs", "Organizador", "Contenido", "Presentación", "Base de datos"]

TITULOS_SECCION = {
    "Resumen": "Resumen del pipeline",
    "Inputs": "Inputs almacenados",
    "Organizador": "Agente organizador",
    "Contenido": "Agente de contenido",
    "Presentación": "Agente de presentación",
    "Base de datos": "Base de datos",
}

ICONOS_VISTA = {
    "Resumen": "📊",
    "Inputs": "📁",
    "Organizador": "🗂️",
    "Contenido": "📝",
    "Presentación": "🎨",
    "Base de datos": "🗄️",
}

# =============================================================================
# Carga aislada de los módulos de los tres agentes vía importlib
#
# Problema: los tres agentes tienen archivos con el mismo nombre genérico
# (config.py y prompts.py en Contenido y Presentación, además de "parser" que
# colisiona con un nombre de stdlib). Si se registran en sys.modules bajo su
# nombre genérico, cargar un agente después de otro sobreescribe esa clave y
# puede romper silenciosamente al agente anterior si vuelve a resolver ese módulo.
#
# Solución: cada módulo se registra de forma PERMANENTE bajo una clave única con
# prefijo de agente ("organizador_config", "contenido_config", "presentacion_config"…).
# El nombre genérico ("config", "cleaner", …) se registra solo TEMPORALMENTE durante
# la carga del propio agente, porque los imports cruzados internos de sus archivos
# —que no podemos modificar— usan ese nombre genérico (p.ej. extractor hace
# `from cleaner import …`). Al terminar el lote se restaura el estado previo de
# sys.modules para esos nombres genéricos, de modo que cargar un agente nunca
# afecte a los módulos ya cargados de otro, sin importar el orden de carga.
# =============================================================================

RAIZ_CONTENIDO = os.path.join(RAIZ_MONOREPO, "agente-contenido")
RAIZ_PRESENTACION = os.path.join(RAIZ_MONOREPO, "agente-presentacion")


def _cargar_modulos_agente(raiz: str, prefijo: str, nombres: list[str]) -> dict:
    """Carga los módulos de un agente con aislamiento en sys.modules.

    `nombres` debe listarse en orden de dependencia (las dependencias primero,
    para que el nombre genérico de cada una esté disponible cuando un módulo
    dependiente la importe). Devuelve {nombre_genérico: módulo}.

    Claves permanentes: f"{prefijo}_{nombre}" (aisladas por agente).
    Claves genéricas: temporales durante el lote; se restauran al final.
    """
    previos: dict[str, object] = {}
    genericos_tocados: list[str] = []
    cargados: dict[str, object] = {}
    try:
        for name in nombres:
            ruta = os.path.join(raiz, f"{name}.py")
            spec = _importlib_util.spec_from_file_location(f"{prefijo}_{name}", ruta)
            mod = _importlib_util.module_from_spec(spec)
            # Clave permanente prefijada — nunca colisiona con otro agente.
            sys.modules[f"{prefijo}_{name}"] = mod
            # Clave genérica TEMPORAL — solo para resolver imports cruzados internos.
            if name not in previos:
                previos[name] = sys.modules.get(name)
                genericos_tocados.append(name)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            cargados[name] = mod
        return cargados
    finally:
        # Restaurar el estado previo de las claves genéricas: elimina toda
        # posibilidad de colisión entre agentes una vez cargado este lote.
        for name in genericos_tocados:
            anterior = previos.get(name)
            if anterior is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = anterior


# ── Agente Organizador (sin imports cruzados entre los módulos cargados) ──────
try:
    _org_mods = _cargar_modulos_agente(
        RAIZ_ORGANIZADOR, "organizador", ["agente", "parser", "prompts"]
    )
    _org_agente = _org_mods["agente"]
    _org_parser = _org_mods["parser"]
    _org_prompts = _org_mods["prompts"]
    _ORG_ERROR: str | None = None
except Exception as _e:
    _org_agente = _org_parser = _org_prompts = None
    _ORG_ERROR = str(_e)


# ── Agente Contenido (extractor←cleaner; chunker/classifier/validator←config) ─
try:
    _cnt_mods = _cargar_modulos_agente(
        RAIZ_CONTENIDO, "contenido",
        ["config", "cleaner", "extractor", "chunker", "classifier", "assembler", "validator"],
    )
    _cnt_config = _cnt_mods["config"]
    _cnt_cleaner = _cnt_mods["cleaner"]
    _cnt_extractor = _cnt_mods["extractor"]
    _cnt_chunker = _cnt_mods["chunker"]
    _cnt_classifier = _cnt_mods["classifier"]
    _cnt_assembler = _cnt_mods["assembler"]
    _cnt_validator = _cnt_mods["validator"]
    _CNT_ERROR: str | None = None
except Exception as _ce:
    _cnt_config = _cnt_cleaner = _cnt_extractor = _cnt_chunker = _cnt_classifier = None
    _cnt_assembler = _cnt_validator = None
    _CNT_ERROR = str(_ce)


# ── Agente Presentación (detector/generador_html←config, prompts) ─────────────
# Documentación de cambio de firma: _generar_bloque no se modifica; en su lugar
# _prs_generar_html_subbloque() (más abajo) llama directamente a
# build_generador_message + API con el patrón y los parámetros elegidos por el
# profesor como argumentos explícitos, sin volver a pasar por el razonador.
try:
    _prs_mods = _cargar_modulos_agente(
        RAIZ_PRESENTACION, "presentacion",
        ["config", "prompts", "generador_html", "detector"],
    )
    _prs_config = _prs_mods["config"]
    _prs_prompts = _prs_mods["prompts"]
    _prs_generador_html = _prs_mods["generador_html"]
    _prs_detector = _prs_mods["detector"]
    _PRS_ERROR: str | None = None
except Exception as _pe:
    _prs_config = _prs_prompts = _prs_generador_html = _prs_detector = None
    _PRS_ERROR = str(_pe)


# =============================================================================
# Funciones puras copiadas de agente-organizador/app.py
#
# No se importa app.py del Organizador directamente porque ejecutaría
# st.set_page_config() al nivel de módulo, lo que rompería la app unificada.
# Estas cuatro funciones son puras (solo re + unicodedata) y no cambian.
# =============================================================================

def _extraer_horas_docencia(texto_guia: str) -> dict[str, int]:
    """Extraído literalmente de agente-organizador/app.py (líneas 26-249)."""

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
        tiene_practica = ("practic" in linea_norm) or bool(re.search(r"\bpract\b", linea_norm))
        tiene_aula = "aula" in linea_norm
        tiene_seminario = "seminar" in linea_norm
        tiene_taller = "taller" in linea_norm
        tiene_laboratorio = "laborator" in linea_norm or re.search(r"\blab\b", linea_norm) is not None
        tiene_campo = "campo" in linea_norm
        tiene_informatica = "informatica" in linea_norm
        tiene_idiomas = "idioma" in linea_norm
        tiene_teoria = ("expositiv" in linea_norm) or ("teoric" in linea_norm) or ("magistral" in linea_norm)
        if tiene_laboratorio or (tiene_practica and (tiene_campo or tiene_informatica or tiene_idiomas)):
            return "laboratorio"
        if tiene_practica and (tiene_aula or tiene_seminario or tiene_taller):
            return "aula"
        if tiene_teoria and not tiene_practica:
            return "teoria"
        return None

    def fuerza_fila_pa(linea_norm: str) -> int:
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
        if "sesion" in linea_norm or "sesiones" in linea_norm:
            return False
        numeros = re.findall(r"\d+(?:[.,]\d+)?", linea_original)
        if not numeros:
            return False
        letras = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", linea_original)
        return len(letras) <= 3

    def extraer_primera_hora_fila_tabla(linea_original: str) -> int | None:
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

    lineas_originales = [l.strip() for l in (texto_guia or "").splitlines() if l.strip()]
    lineas_norm = [norm(l) for l in lineas_originales]

    horas: dict[str, int] = {"teoria": 0, "aula": 0, "laboratorio": 0}

    indices_headers = [i for i, ln in enumerate(lineas_norm) if linea_parece_header_tabla(ln)]
    mejor_ventana = None

    for idx_header in indices_headers:
        local: dict[str, int] = {"teoria": 0, "aula": 0, "laboratorio": 0}
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
            mejor_ventana = (puntuacion, idx_header, local)

    if mejor_ventana is not None:
        horas = mejor_ventana[2]

    if 0 in horas.values():
        for linea_original, linea_norm_item in zip(lineas_originales, lineas_norm):
            categoria = categoria_fila_modalidad(linea_norm_item)
            if categoria is None or horas[categoria] != 0:
                continue
            if not es_contexto_horario(linea_norm_item):
                continue
            valor = extraer_hora_fila(linea_original)
            if valor is not None:
                horas[categoria] = int(valor)

    return {
        "horas_teoria": horas["teoria"],
        "horas_aula": horas["aula"],
        "horas_laboratorio": horas["laboratorio"],
    }


def _normalizar_horas_output(markdown: str, total_horas: float) -> tuple[str, dict | None]:
    """Extraído literalmente de agente-organizador/app.py (líneas 252-354)."""
    if not total_horas or total_horas <= 0:
        return markdown, None

    FILA_RE = re.compile(r"^\| (.+?) \| ([\d]+(?:[.,]\d+)?)h? \| (.+?) \|\s*$")
    HDR_RE = re.compile(r"^(## Bloque \d+ — .+? · )([\d.]+)(h.*)$")
    _CABECERAS = {
        "subtema", "topic", "horas", "hours",
        "justificación", "justificacion", "justification",
        "origen", "origin",
    }

    lineas = markdown.splitlines(keepends=True)
    indices_filas: list[tuple[int, float]] = []
    for i, linea in enumerate(lineas):
        m = FILA_RE.match(linea.rstrip("\r\n"))
        if not m:
            continue
        col1 = m.group(1).strip().lower()
        col2_val = m.group(2).strip()
        if col1 in _CABECERAS or re.match(r"^-+$", col1) or re.match(r"^-+$", col2_val):
            continue
        try:
            indices_filas.append((i, float(col2_val.replace(",", "."))))
        except ValueError:
            pass

    if not indices_filas:
        return markdown, None

    horas_originales = [h for _, h in indices_filas]
    suma_actual = sum(horas_originales)

    if abs(suma_actual - total_horas) < 0.01:
        return markdown, None

    diferencia = suma_actual - total_horas
    factor = total_horas / suma_actual
    horas_nuevas = [round(h * factor * 2) / 2 for h in horas_originales]
    residuo = total_horas - sum(horas_nuevas)
    if abs(residuo) >= 0.01:
        idx_max = horas_nuevas.index(max(horas_nuevas))
        horas_nuevas[idx_max] = round((horas_nuevas[idx_max] + residuo) * 2) / 2

    def fmt(v: float) -> str:
        return str(int(v)) if v == int(v) else f"{v:.1f}"

    ajustes: dict[str, dict] = {}
    nuevas_lineas = list(lineas)

    for (idx_linea, h_antes), h_nueva in zip(indices_filas, horas_nuevas):
        linea_orig = lineas[idx_linea]
        m = FILA_RE.match(linea_orig.rstrip("\r\n"))
        if not m:
            continue
        if abs(h_antes - h_nueva) >= 0.05:
            nombre_sub = m.group(1).strip()
            ajustes[nombre_sub] = {"antes": h_antes, "despues": h_nueva}
        ending = linea_orig[len(linea_orig.rstrip("\r\n")):]
        nuevas_lineas[idx_linea] = f"| {m.group(1)} | {fmt(h_nueva)}h | {m.group(3)} |{ending}"

    indices_hdrs = [i for i, l in enumerate(nuevas_lineas) if HDR_RE.match(l.rstrip("\r\n"))]
    indices_hdrs.append(len(nuevas_lineas))

    for k in range(len(indices_hdrs) - 1):
        inicio_bloque = indices_hdrs[k]
        fin_bloque = indices_hdrs[k + 1]
        horas_bloque = [
            horas_nuevas[sub_idx]
            for sub_idx, (idx_linea, _) in enumerate(indices_filas)
            if inicio_bloque < idx_linea < fin_bloque
        ]
        if not horas_bloque:
            continue
        linea_hdr = nuevas_lineas[inicio_bloque]
        m = HDR_RE.match(linea_hdr.rstrip("\r\n"))
        if m:
            ending = linea_hdr[len(linea_hdr.rstrip("\r\n")):]
            nuevas_lineas[inicio_bloque] = m.group(1) + fmt(sum(horas_bloque)) + m.group(3) + ending

    return "".join(nuevas_lineas), {
        "diferencia": diferencia,
        "suma_antes": suma_actual,
        "ajustes": ajustes,
    }


def _contar_bloques_output(markdown_text: str) -> int:
    return len(re.findall(r"^## Bloque\s+\d+", markdown_text, re.MULTILINE))


def _construir_nombre_descarga(texto_guia: str) -> str:
    m = re.search(r"NOMBRE\s+(.+?)\s+C[ÓO]DIGO", texto_guia or "", flags=re.IGNORECASE | re.DOTALL)
    if not m:
        return "Propuesta_asignatura.md"
    nombre_limpio = re.sub(r'[\\/:\*\?"<>\|]', "", m.group(1).strip())
    nombre_limpio = re.sub(r"\s+", "_", nombre_limpio).strip("_")
    return f"Propuesta_{nombre_limpio}.md" if nombre_limpio else "Propuesta_asignatura.md"


# =============================================================================
# parsear_bloques_organizador — parsing puro, sin LLM
# =============================================================================

# Cabeceras de tabla que no son filas de datos
_CABECERAS_TABLA = {
    "subtema", "topic", "horas", "hours",
    "justificación", "justificacion", "justification",
    "origen", "origin",
    "evidencia", "evidence",
}

# Contrato de formato del Agente Organizador (ver CLAUDE.md del monorepo):
#   ## Bloque N — NOMBRE · Xh
_HDR_BLOQUE_RE = re.compile(
    r"^##\s+Bloque\s+(\d+)\s+[—\-]+\s+(.+?)\s*[·•]\s*([\d.,]+)h",
    re.MULTILINE,
)
# Captura todas las celdas de una fila de tabla Markdown (separadas por '|').
_FILA_TABLA_COMPLETA_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)


def _parsear_celdas(linea: str) -> list[str]:
    """Extrae celdas de una línea de tabla Markdown como lista de strings limpios."""
    partes = linea.strip().strip("|").split("|")
    return [p.strip() for p in partes]


def parsear_bloques_organizador(markdown: str) -> list[dict]:
    """Extrae la lista de bloques y subtemas del output del Agente Organizador.

    Compatible con los formatos de tabla del Organizador:
      - 3 columnas: | Subtema | Horas | Origen |
      - 4 columnas: | Subtema | Horas | Evidencia | Origen |
      - antiguo 3 cols: | Subtema | Horas | Justificación |

    Returns:
        list[dict] con claves: numero (int), nombre (str), horas (float),
        subtemas (list[dict{nombre, horas, orden, evidencia, origen, es_fallback}])
    """
    bloques: list[dict] = []
    matches = list(_HDR_BLOQUE_RE.finditer(markdown))

    for i, m in enumerate(matches):
        numero = int(m.group(1))
        nombre = m.group(2).strip()
        horas_bloque = float(m.group(3).replace(",", "."))

        inicio = m.end()
        fin = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        seccion = markdown[inicio:fin]

        subtemas: list[dict] = []
        for fm in _FILA_TABLA_COMPLETA_RE.finditer(seccion):
            celdas = _parsear_celdas(fm.group(0))
            if len(celdas) < 2:
                continue
            col1 = celdas[0]
            col2 = celdas[1] if len(celdas) > 1 else ""
            # Saltar cabeceras, separadores y filas vacías.
            if col1.lower() in _CABECERAS_TABLA:
                continue
            if re.match(r"^-+$", col1) or re.match(r"^-+$", col2):
                continue
            if not col1:
                continue

            # Extraer horas del subtema (col2 puede tener "h" al final).
            horas_sub_raw = re.sub(r"[^\d.,]", "", col2)
            try:
                horas_sub = float(horas_sub_raw.replace(",", ".")) if horas_sub_raw else 0.0
            except ValueError:
                horas_sub = 0.0

            # Columnas opcionales: Evidencia (col3) y Origen (col4 ó col3).
            if len(celdas) >= 4:
                evidencia = celdas[2]
                origen = celdas[3]
            elif len(celdas) == 3:
                # Formato antiguo o 3-cols: tercera columna es Origen/Justificación.
                evidencia = ""
                origen = celdas[2]
            else:
                evidencia = ""
                origen = "Detectado"

            # Fallback: evidencia vacía o marcador explícito.
            _ev_norm = evidencia.strip().lower()
            es_fallback = int(
                _ev_norm in {"sin señal verificable", "sin senal verificable", "fallback", ""}
                and origen.strip().lower() in {"fallback", "sin señal", "sin senal", ""}
            )

            subtemas.append({
                "nombre": col1,
                "horas": horas_sub,
                "orden": len(subtemas) + 1,
                "evidencia": evidencia,
                "origen": origen,
                "es_fallback": es_fallback,
            })

        bloques.append({
            "numero": numero,
            "nombre": nombre,
            "horas": horas_bloque,
            "subtemas": subtemas,
        })

    return bloques


# =============================================================================
# Helpers de base de datos
# =============================================================================

def _slugify(nombre: str) -> str:
    """Convierte un nombre de asignatura a slug para nombres de carpeta."""
    s = unicodedata.normalize("NFD", nombre)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _get_asignatura_id(nombre: str) -> int | None:
    conn = db.get_connection(RUTA_DB)
    try:
        fila = conn.execute(
            "SELECT id FROM asignaturas WHERE nombre = ?", (nombre,)
        ).fetchone()
    finally:
        conn.close()
    return fila["id"] if fila else None


def _db_registrar_input(asignatura_id: int, tipo: str, nombre_fichero: str, ruta_disco: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO inputs (asignatura_id, tipo, nombre_fichero, ruta_disco)
               VALUES (?, ?, ?, ?)""",
            (asignatura_id, tipo, nombre_fichero, ruta_disco),
        )
        conn.commit()
    finally:
        conn.close()


def _db_crear_ejecucion(asignatura_id: int) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO ejecuciones (asignatura_id, agente, estado)
               VALUES (?, 'organizador', 'en_progreso')""",
            (asignatura_id,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_actualizar_ejecucion(ejecucion_id: int, estado: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE ejecuciones SET estado = ? WHERE id = ?", (estado, ejecucion_id)
        )
        conn.commit()
    finally:
        conn.close()


def _db_crear_ejecucion_contenido(asignatura_id: int) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO ejecuciones (asignatura_id, agente, estado)
               VALUES (?, 'contenido', 'en_progreso')""",
            (asignatura_id,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_registrar_validacion(
    ejecucion_id: int | None,
    tipo: str,
    descripcion: str,
    valor_afectado: float | None,
    bloqueante: int = 0,
) -> None:
    """Persiste un aviso de validación automática ligado a una ejecución.

    Solo añade la fila; la lógica que calcula la cobertura (Organizador) o la
    fidelidad léxica (Contenido) no se altera — esto es únicamente persistencia.
    """
    if ejecucion_id is None:
        return
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            """INSERT INTO validaciones
               (ejecucion_id, tipo, descripcion, valor_afectado, bloqueante)
               VALUES (?, ?, ?, ?, ?)""",
            (ejecucion_id, tipo, descripcion, valor_afectado, bloqueante),
        )
        conn.commit()
    finally:
        conn.close()


def _db_guardar_organizador_output(
    asignatura_id: int,
    ejecucion_id: int,
    markdown_path: str,
    version: int,
    feedback_texto: str | None = None,
) -> int:
    conn = db.get_connection(RUTA_DB)
    try:
        cur = conn.execute(
            """INSERT INTO organizador_outputs
               (asignatura_id, ejecucion_id, markdown_path, feedback_texto, version)
               VALUES (?, ?, ?, ?, ?)""",
            (asignatura_id, ejecucion_id, markdown_path, feedback_texto, version),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _db_confirmar_organizacion(asignatura_id: int, output_id: int, bloques: list[dict]) -> None:
    """Borra temas/subbloques anteriores e inserta los de la versión confirmada.

    Cada subtema puede incluir horas, evidencia, origen y es_fallback cuando
    procede del nuevo formato del Agente Organizador (v2+).
    """
    conn = db.get_connection(RUTA_DB)
    try:
        temas_existentes = conn.execute(
            "SELECT id FROM temas WHERE asignatura_id = ?", (asignatura_id,)
        ).fetchall()
        for tema in temas_existentes:
            conn.execute("DELETE FROM subbloques WHERE tema_id = ?", (tema["id"],))
        conn.execute("DELETE FROM temas WHERE asignatura_id = ?", (asignatura_id,))

        for orden, bloque in enumerate(bloques, start=1):
            cur = conn.execute(
                """INSERT INTO temas
                   (asignatura_id, organizador_output_id, nombre, horas, bloque, orden)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    asignatura_id, output_id,
                    bloque["nombre"], bloque["horas"],
                    f"Bloque {bloque['numero']}", orden,
                ),
            )
            tema_id = cur.lastrowid
            for subtema in bloque["subtemas"]:
                conn.execute(
                    """INSERT INTO subbloques
                       (tema_id, nombre, orden, horas, evidencia, origen, es_fallback)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tema_id,
                        subtema["nombre"],
                        subtema.get("orden", 0),
                        subtema.get("horas", 0.0),
                        subtema.get("evidencia", ""),
                        subtema.get("origen", "Detectado"),
                        subtema.get("es_fallback", 0),
                    ),
                )

        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Organizador — gestión de session_state
# =============================================================================

_ORG_KEYS: dict[str, object] = {
    "org_ultimo_output": None,
    "org_historial_feedback": [],
    "org_iteracion": 1,
    "org_ultimos_archivos_teoria": [],
    "org_ultimos_archivos_contexto": [],
    "org_ultimas_horas_teoria": None,
    "org_ultimas_horas_totales": None,
    "org_session_id_archivos": "",
    "org_ultimo_nombre_descarga": "Propuesta_asignatura.md",
    "org_warning_cardinalidad": None,
    "org_warning_normalizacion": None,
    "org_subtemas_editor": [],
    "org_fase": None,
    "org_ejecucion_id": None,
    "org_version_actual": 0,
    "org_output_id": None,
    "org_confirmada": False,
    "org_inputs_registrados": set(),  # {"{slug}:{filename}"}
}


def _org_init_state() -> None:
    for k, v_default in _ORG_KEYS.items():
        if k not in st.session_state:
            st.session_state[k] = v_default() if callable(v_default) else v_default


def _org_reset_state() -> None:
    for k, v_default in _ORG_KEYS.items():
        st.session_state[k] = v_default() if callable(v_default) else v_default


# =============================================================================
# Organizador — persistencia de archivos
# =============================================================================

def _org_registrar_archivos(guia_docente, materiales_teoria, asignatura_id: int, slug: str) -> None:
    """Guarda en disco y registra en BD los archivos que sean nuevos en esta sesión."""
    dir_inputs = os.path.join(RAIZ_MONOREPO, "data", slug, "inputs")
    os.makedirs(dir_inputs, exist_ok=True)

    def _registrar(archivo, tipo: str) -> None:
        clave = f"{slug}:{archivo.name}"
        if clave in st.session_state["org_inputs_registrados"]:
            return
        ruta = os.path.join(dir_inputs, archivo.name)
        with open(ruta, "wb") as f:
            f.write(archivo.getvalue())
        try:
            _db_registrar_input(asignatura_id, tipo, archivo.name, ruta)
        except Exception:
            pass
        st.session_state["org_inputs_registrados"].add(clave)

    if guia_docente is not None:
        _registrar(guia_docente, "guia_docente")
    for mat in (materiales_teoria or []):
        _registrar(mat, "material_teoria")


def _org_detectar_cambio(guia_docente, materiales_teoria) -> None:
    """Resetea el output y la fase si el conjunto de archivos cambió."""
    nombres: list[str] = []
    if guia_docente is not None:
        nombres.append(f"guia:{guia_docente.name}")
    for f in (materiales_teoria or []):
        nombres.append(f"mat:{f.name}")
    session_id = "|".join(sorted(nombres))

    if session_id and session_id != st.session_state["org_session_id_archivos"]:
        st.session_state["org_ultimo_output"] = None
        st.session_state["org_historial_feedback"] = []
        st.session_state["org_iteracion"] = 1
        st.session_state["org_warning_cardinalidad"] = None
        st.session_state["org_warning_normalizacion"] = None
        st.session_state["org_subtemas_editor"] = []
        st.session_state["org_fase"] = None
        st.session_state["org_ejecucion_id"] = None
        st.session_state["org_version_actual"] = 0
        st.session_state["org_output_id"] = None
        st.session_state["org_confirmada"] = False
        st.session_state["org_session_id_archivos"] = session_id


# =============================================================================
# Organizador — lógica de generación (adaptada de agente-organizador/app.py)
# =============================================================================

def _texto_warning_cobertura(esperados: int, generados: int) -> str:
    """Texto exacto del aviso de cobertura incompleta guía-vs-materiales.

    Único origen del texto: lo usa tanto la vista (st.warning) como la
    persistencia en `validaciones`, para que `descripcion` sea idéntica a lo
    que ve el profesor.
    """
    return (
        f"⚠️ **Discrepancia de bloques detectada:** el output contiene "
        f"**{generados} bloques** pero se esperaban **{esperados}** "
        f"(uno por archivo de teoría subido). "
        f"El modelo probablemente elevó una subsección a bloque independiente. "
        f"Usa el campo de feedback para indicar qué bloque debe reintegrarse como subtema "
        f"y pulsa Regenerar."
    )


def _org_validar_y_persistir(
    resultado: str,
    n_esperados: int,
    asignatura_id: int,
    slug: str,
    version: int,
    ejecucion_id: int,
    feedback_texto: str | None = None,
    nombre_descarga: str | None = None,
) -> None:
    n_generados = _contar_bloques_output(resultado)
    st.session_state["org_warning_cardinalidad"] = (
        {"esperados": n_esperados, "generados": n_generados}
        if n_generados != n_esperados
        else None
    )

    # Registrar el aviso de cobertura incompleta en `validaciones`. El cálculo de
    # cobertura (bloques esperados = un material de teoría por bloque) no se toca;
    # aquí solo se persiste. valor_afectado = bloques sin cubrir (esperados − generados):
    # la métrica determinista de cobertura de este agente es por bloque, no por hora.
    if st.session_state["org_warning_cardinalidad"]:
        bloques_sin_cubrir = max(0, n_esperados - n_generados)
        _db_registrar_validacion(
            ejecucion_id=ejecucion_id,
            tipo="cobertura_incompleta",
            descripcion=_texto_warning_cobertura(n_esperados, n_generados),
            valor_afectado=float(bloques_sin_cubrir),
            bloqueante=0,
        )

    st.session_state["org_ultimo_output"] = resultado
    if nombre_descarga:
        st.session_state["org_ultimo_nombre_descarga"] = nombre_descarga

    # Guardar markdown en disco
    dir_out = os.path.join(RAIZ_MONOREPO, "data", slug, "outputs", "organizador")
    os.makedirs(dir_out, exist_ok=True)
    ruta_md = os.path.join(dir_out, f"v{version}.md")
    with open(ruta_md, "w", encoding="utf-8") as fh:
        fh.write(resultado)

    output_id = _db_guardar_organizador_output(
        asignatura_id=asignatura_id,
        ejecucion_id=ejecucion_id,
        markdown_path=ruta_md,
        version=version,
        feedback_texto=feedback_texto,
    )
    st.session_state["org_output_id"] = output_id
    st.session_state["org_version_actual"] = version


def _org_extraer_y_detectar(guia_docente, materiales_teoria) -> bool:
    """Fase 1: extrae texto y detecta subtemas sin llamar al LLM."""
    if guia_docente is None or not materiales_teoria:
        st.error("Debes subir guía docente y materiales de teoría.")
        return False

    with st.status("Extrayendo y detectando subtemas...", expanded=True) as status:
        try:
            st.write("📄 Extrayendo texto de la guía docente...")
            texto_guia = _org_parser.extraer_texto(guia_docente.getvalue(), guia_docente.name)
            candidatos_guia = _org_parser.extraer_subtemas_candidatos(texto_guia)

            st.write("📚 Extrayendo y clasificando materiales de teoría...")
            textos_teoria_raw: list[str] = []
            archivos_teoria: list[str] = []
            archivos_contexto: list[str] = []

            for archivo in materiales_teoria:
                try:
                    texto_material = _org_parser.extraer_texto(archivo.getvalue(), archivo.name)
                    categoria = _org_parser.clasificar_archivo(archivo.name, texto_material)
                    if categoria == "contexto":
                        archivos_contexto.append(archivo.name)
                        st.write(f"  → {archivo.name} → contexto")
                    else:
                        textos_teoria_raw.append(texto_material)
                        archivos_teoria.append(archivo.name)
                        st.write(f"  → {archivo.name} → teoría")
                except Exception as err:
                    st.warning(f"No se pudo procesar '{archivo.name}': {err}")

            if not textos_teoria_raw:
                status.update(label="❌ Error", state="error")
                st.error("No se pudo extraer texto válido de ningún material de teoría.")
                return False

            st.write("🔍 Detectando subtemas por numeración jerárquica...")
            editor_data: list[dict] = []
            for texto_mat, nombre_arch in zip(textos_teoria_raw, archivos_teoria):
                cands_mat = _org_parser.extraer_subtemas_candidatos(texto_mat)
                if cands_mat:
                    candidatos = cands_mat
                    origen_base = "material"
                    discrepancia = _org_parser.hay_discrepancia(cands_mat, candidatos_guia)
                elif candidatos_guia:
                    candidatos = candidatos_guia
                    origen_base = "guia"
                    discrepancia = False
                else:
                    candidatos = []
                    origen_base = "ninguno"
                    discrepancia = False
                editor_data.append({
                    "archivo": nombre_arch,
                    "candidatos": candidatos,
                    "candidatos_mat_orig": cands_mat,
                    "origen": origen_base,
                    "discrepancia": discrepancia,
                })

            horas_docencia = _extraer_horas_docencia(texto_guia)
            st.session_state["org_ultimas_horas_teoria"] = horas_docencia
            st.session_state["org_ultimos_archivos_teoria"] = archivos_teoria
            st.session_state["org_ultimos_archivos_contexto"] = archivos_contexto
            st.session_state["org_subtemas_editor"] = editor_data
            st.session_state["org_fase"] = "editar"

            status.update(
                label="✅ Subtemas detectados — revisa y confirma en el área principal",
                state="complete",
            )
            return True
        except Exception as err:
            status.update(label="❌ Error en la extracción", state="error")
            st.error(f"Error durante la extracción: {err}")
            return False


def _org_generar_organizacion(
    guia_docente,
    materiales_teoria,
    asignatura_id: int,
    slug: str,
    feedback_previo: list[str] | None = None,
    subtemas_confirmados: list[list[dict]] | None = None,
) -> bool:
    output_previo = st.session_state.get("org_ultimo_output")

    # ── Camino rápido: refinamiento ────────────────────────────────────────────
    if feedback_previo and output_previo:
        with st.status("Aplicando ajuste...", expanded=True) as status:
            try:
                horas_totales = st.session_state.get("org_ultimas_horas_totales")
                n_esperados = len(st.session_state.get("org_ultimos_archivos_teoria", []))
                prompt = _org_prompts.construir_prompt_refinamiento(
                    output_previo=output_previo,
                    feedback_previo=feedback_previo,
                    horas_totales=horas_totales,
                )
                st.write("🤖 Aplicando ajuste sobre la organización actual...")
                resultado = _org_agente.ejecutar_agente(prompt)
                resultado, info_norm = _normalizar_horas_output(resultado, horas_totales or 0)
                st.session_state["org_warning_normalizacion"] = info_norm

                version = st.session_state.get("org_version_actual", 1) + 1
                ejecucion_id = st.session_state.get("org_ejecucion_id")
                feedback_texto = feedback_previo[-1] if feedback_previo else None

                _org_validar_y_persistir(
                    resultado, n_esperados, asignatura_id, slug,
                    version, ejecucion_id, feedback_texto=feedback_texto,
                )
                status.update(label="✅ Ajuste aplicado", state="complete")
                return True
            except Exception as err:
                status.update(label="❌ Error al aplicar el ajuste", state="error")
                st.error(f"Error durante el refinamiento: {err}")
                return False

    # ── Camino completo: primera generación ───────────────────────────────────
    if guia_docente is None:
        st.error("Debes subir una guía docente para generar la organización.")
        return False
    if not materiales_teoria:
        st.error("Debes subir al menos un material de teoría.")
        return False

    ejecucion_id = _db_crear_ejecucion(asignatura_id)
    st.session_state["org_ejecucion_id"] = ejecucion_id

    with st.status("Procesando documentos...", expanded=True) as status:
        try:
            st.write("📄 Extrayendo texto de la guía docente...")
            texto_guia = _org_parser.extraer_texto(guia_docente.getvalue(), guia_docente.name)

            st.write("📚 Extrayendo y clasificando materiales de teoría...")
            textos_teoria: list[str] = []
            textos_contexto: list[str] = []
            archivos_teoria: list[str] = []
            archivos_contexto: list[str] = []

            for archivo in materiales_teoria:
                try:
                    texto_material = _org_parser.extraer_texto(archivo.getvalue(), archivo.name)
                    categoria = _org_parser.clasificar_archivo(archivo.name, texto_material)
                    if categoria == "contexto":
                        textos_contexto.append(texto_material)
                        archivos_contexto.append(archivo.name)
                        st.write(f"  → {archivo.name} → contexto")
                    else:
                        textos_teoria.append(texto_material)
                        archivos_teoria.append(archivo.name)
                        st.write(f"  → {archivo.name} → teoría")
                except Exception as err:
                    st.warning(f"No se pudo procesar '{archivo.name}': {err}")

            if not textos_teoria:
                _db_actualizar_ejecucion(ejecucion_id, "error")
                status.update(label="❌ Error en el proceso", state="error")
                st.error("No se pudo extraer texto válido de ningún material de teoría.")
                return False

            longitud_total = sum(len(t) for t in textos_teoria) + sum(len(t) for t in textos_contexto)
            if longitud_total > 120000:
                textos_teoria = [t[:20000] for t in textos_teoria]
                textos_contexto = [t[:20000] for t in textos_contexto]
                st.info("Materiales truncados a 20.000 caracteres por archivo para no superar el límite del modelo.")

            st.session_state["org_ultimos_archivos_teoria"] = archivos_teoria
            st.session_state["org_ultimos_archivos_contexto"] = archivos_contexto

            st.write("🕐 Detectando horas lectivas (TE + PA) y laboratorio...")
            horas_docencia = _extraer_horas_docencia(texto_guia)
            horas_teoria = horas_docencia["horas_teoria"]
            horas_aula = horas_docencia["horas_aula"]
            horas_laboratorio = horas_docencia["horas_laboratorio"]
            horas_totales = horas_teoria + horas_aula

            if horas_totales == 0:
                st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")
            st.session_state["org_ultimas_horas_teoria"] = horas_docencia
            st.session_state["org_ultimas_horas_totales"] = horas_totales if horas_totales > 0 else None

            st.write("🌐 Detectando idioma de los materiales...")
            prompt, _idioma = _org_prompts.construir_prompt(
                texto_guia=texto_guia,
                textos_teoria=textos_teoria,
                textos_contexto=textos_contexto,
                horas_totales=horas_totales if horas_totales > 0 else None,
                horas_laboratorio=horas_laboratorio,
                subtemas_por_material=subtemas_confirmados,
            )

            st.write("🤖 Consultando al agente (esto puede tardar ~15s)...")
            resultado = _org_agente.ejecutar_agente(prompt)

            resultado, info_norm = _normalizar_horas_output(resultado, horas_totales if horas_totales else 0)
            st.session_state["org_warning_normalizacion"] = info_norm

            _org_validar_y_persistir(
                resultado,
                n_esperados=len(textos_teoria),
                asignatura_id=asignatura_id,
                slug=slug,
                version=1,
                ejecucion_id=ejecucion_id,
                feedback_texto=None,
                nombre_descarga=_construir_nombre_descarga(texto_guia),
            )
            _db_actualizar_ejecucion(ejecucion_id, "completado")
            status.update(label="✅ Organización generada", state="complete")
            return True
        except Exception as err:
            _db_actualizar_ejecucion(ejecucion_id, "error")
            status.update(label="❌ Error en el proceso", state="error")
            st.error(f"Error durante la generación: {err}")
            return False


# =============================================================================
# Helpers de base de datos — Contenido
# =============================================================================

def _db_cnt_get_temas(asignatura_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre, horas, bloque, orden FROM temas "
                "WHERE asignatura_id = ? ORDER BY orden",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_subbloques(tema_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre, orden FROM subbloques WHERE tema_id = ? ORDER BY orden",
                (tema_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_cnt_get_contenido_subbloque(subbloque_id: int) -> dict | None:
    conn = db.get_connection(RUTA_DB)
    try:
        r = conn.execute(
            "SELECT id, markdown_borrador, markdown_final, porcentaje_editado, "
            "estado, fecha_actualizacion "
            "FROM contenido_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _db_cnt_get_rutas_material(asignatura_id: int) -> list[str]:
    """Rutas de archivos material_teoria guardadas en disco (filtra los que no existen)."""
    conn = db.get_connection(RUTA_DB)
    try:
        filas = conn.execute(
            "SELECT ruta_disco FROM inputs "
            "WHERE asignatura_id = ? AND tipo = 'material_teoria'",
            (asignatura_id,),
        ).fetchall()
    finally:
        conn.close()
    return [r["ruta_disco"] for r in filas if os.path.exists(r["ruta_disco"])]


def _db_cnt_upsert_borrador(subbloque_id: int, markdown_borrador: str) -> None:
    """Guarda el borrador generado por IA y actualiza el estado a 'generado'."""
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET markdown_borrador = ?, estado = 'generado', "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE subbloque_id = ?",
                (markdown_borrador, subbloque_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_subbloque (subbloque_id, markdown_borrador, estado) "
                "VALUES (?, ?, 'generado')",
                (subbloque_id, markdown_borrador),
            )
        conn.commit()
    finally:
        conn.close()


def _db_cnt_guardar_final(
    subbloque_id: int, markdown_final: str, porcentaje_editado: float
) -> None:
    """Guarda el contenido final editado por el profesor.

    Estado resultante:
    - porcentaje_editado == 0 → 'aprobado' (sin cambios sobre el borrador).
    - porcentaje_editado > 0  → 'editado' (el profesor modificó el borrador).
    """
    estado = "aprobado" if porcentaje_editado == 0 else "editado"
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET markdown_final = ?, "
                "porcentaje_editado = ?, estado = ?, "
                "fecha_actualizacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (markdown_final, porcentaje_editado, estado, subbloque_id),
            )
        else:
            conn.execute(
                "INSERT INTO contenido_subbloque "
                "(subbloque_id, markdown_borrador, markdown_final, porcentaje_editado, estado) "
                "VALUES (?, '', ?, ?, ?)",
                (subbloque_id, markdown_final, porcentaje_editado, estado),
            )
        conn.commit()
    finally:
        conn.close()


def _db_cnt_aprobar_subbloque(subbloque_id: int) -> None:
    """Marca un subbloque como 'aprobado' sin cambiar su contenido Markdown."""
    conn = db.get_connection(RUTA_DB)
    try:
        existe = conn.execute(
            "SELECT id FROM contenido_subbloque WHERE subbloque_id = ?", (subbloque_id,)
        ).fetchone()
        if existe:
            conn.execute(
                "UPDATE contenido_subbloque SET estado = 'aprobado', "
                "fecha_actualizacion = CURRENT_TIMESTAMP WHERE subbloque_id = ?",
                (subbloque_id,),
            )
            conn.commit()
    finally:
        conn.close()


# =============================================================================
# Lógica de curación por sub-bloque — Agente Contenido
# =============================================================================

def _cnt_curar_subbloque(
    subbloque_nombre: str,
    tema_nombre: str,
    tema_horas: float | None,
    rutas_material: list[str],
) -> tuple[str, float | None]:
    """Genera markdown curado para un sub-bloque reutilizando la pipeline del Agente Contenido.

    Se prepende un contexto de sub-bloque a cada chunk antes de clasificar, para
    guiar al modelo hacia el alcance concreto sin inventar contenido ausente.
    La SYSTEM_PROMPT y toda la lógica de clasificación/ensamblado son las originales
    de agente-contenido/classifier.py y assembler.py — sin modificar esos archivos.

    Devuelve (markdown, fidelidad). La fidelidad es la media de los coverage_score
    de `validator.validate_items` sobre los chunks originales del sub-bloque (sin el
    prefijo de contexto), o None si no hubo nada que validar. El cálculo de fidelidad
    vive en `agente-contenido/validator.py` — aquí solo se invoca.
    """
    sub_ctx = (
        f"[CONTEXTO SUBTEMA: Este fragmento pertenece al subtema «{subbloque_nombre}» "
        f"del bloque «{tema_nombre}». "
        f"Extrae y estructura únicamente el contenido relevante para este subtema.]\n\n"
    )
    max_w = getattr(_cnt_config, "MAX_WORKERS", 5)

    all_items: list[dict] = []
    all_chunks_raw: list[str] = []  # chunks originales (sin contexto) alineados con all_items

    for ruta in rutas_material:
        if not os.path.exists(ruta):
            continue
        try:
            texto = _cnt_extractor.extract_text(ruta)
        except Exception:
            continue

        chunks = _cnt_chunker.split_into_chunks(texto)
        if not chunks:
            continue

        chunks_con_ctx = [sub_ctx + c for c in chunks]

        # Se preserva el orden (ordered[i]) para que validate_items pueda emparejar
        # cada item con su chunk original por índice — as_completed llega desordenado.
        ordered: list[dict | None] = [None] * len(chunks_con_ctx)
        with ThreadPoolExecutor(max_workers=max_w) as ex:
            future_to_i = {
                ex.submit(_cnt_classifier.classify_and_format, chunk, tema_horas): i
                for i, chunk in enumerate(chunks_con_ctx)
            }
            for fut in as_completed(future_to_i):
                i = future_to_i[fut]
                try:
                    ordered[i] = fut.result()
                except Exception:
                    ordered[i] = None

        for item, chunk_raw in zip(ordered, chunks):
            if item is not None:
                all_items.append(item)
                all_chunks_raw.append(chunk_raw)

    if not all_items:
        return (
            f"# {subbloque_nombre}\n\n*No se pudo extraer contenido del material de entrada.*",
            None,
        )

    markdown = _cnt_assembler.assemble_markdown(all_items, f"{subbloque_nombre}.md")

    fidelidad: float | None = None
    try:
        reporte = _cnt_validator.validate_items(all_items, original_chunks=all_chunks_raw)
        scores = [
            r["coverage_score"]
            for r in (reporte.get("fidelity") or [])
            if r.get("coverage_score") is not None
        ]
        if scores:
            fidelidad = round(sum(scores) / len(scores), 3)
    except Exception:
        fidelidad = None

    return markdown, fidelidad


# =============================================================================
# Vista Contenido
# =============================================================================

def _vista_contenido() -> None:
    if _CNT_ERROR:
        st.error(f"No se pudo cargar el Agente Contenido: {_CNT_ERROR}")
        st.caption("Comprueba que `agente-contenido/.env` tiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    # Reset de claves cnt_ si cambió la asignatura
    if st.session_state.get("cnt_asignatura") != asignatura:
        for k in [k for k in list(st.session_state.keys()) if k.startswith("cnt_")]:
            del st.session_state[k]
        st.session_state["cnt_asignatura"] = asignatura

    # ── Selector de tema ──────────────────────────────────────────────────────
    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos para esta asignatura. "
            "Ejecuta primero el **Agente Organizador** y pulsa "
            "**Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    tema_idx = st.selectbox(
        "Bloque temático:",
        options=range(len(temas)),
        format_func=lambda i: tema_labels[i],
        key="cnt_tema_idx",
    )
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]
    tema_horas: float | None = tema["horas"] or None

    # ── Sub-bloques y materiales disponibles ──────────────────────────────────
    subbloques = _db_cnt_get_subbloques(tema_id)
    if not subbloques:
        st.warning("Este bloque no tiene sub-bloques registrados.")
        return

    rutas_material = _db_cnt_get_rutas_material(asignatura_id)

    sin_borrador = [
        s for s in subbloques
        if _db_cnt_get_contenido_subbloque(s["id"]) is None
    ]

    # ── Botón de generación de borradores ─────────────────────────────────────
    if sin_borrador:
        if not rutas_material:
            st.warning(
                f"Faltan borradores para {len(sin_borrador)} sub-bloques, pero no hay "
                "materiales de teoría en disco. Sube los archivos en el **Agente Organizador** primero."
            )
        else:
            if st.button(
                f"Generar borradores ({len(sin_borrador)} sub-bloques sin procesar)",
                type="primary",
                use_container_width=True,
                key="cnt_btn_generar",
            ):
                umbral = float(getattr(_cnt_config, "FIDELITY_THRESHOLD", 0.85))
                ejecucion_id = _db_crear_ejecucion_contenido(asignatura_id)
                hubo_error = False
                for sub in sin_borrador:
                    with st.status(
                        f"Generando borrador: {sub['nombre']}…", expanded=True
                    ) as status:
                        try:
                            st.write("📚 Extrayendo y clasificando material…")
                            md, fidelidad = _cnt_curar_subbloque(
                                subbloque_nombre=sub["nombre"],
                                tema_nombre=tema_nombre,
                                tema_horas=tema_horas,
                                rutas_material=rutas_material,
                            )
                            _db_cnt_upsert_borrador(sub["id"], md)
                            # Persistir aviso si la fidelidad léxica cae bajo el umbral (0.85).
                            if fidelidad is not None and fidelidad < umbral:
                                _db_registrar_validacion(
                                    ejecucion_id=ejecucion_id,
                                    tipo="fidelidad_baja",
                                    descripcion=(
                                        f"sub-bloque '{sub['nombre']}' con fidelidad {fidelidad}"
                                    ),
                                    valor_afectado=fidelidad,
                                    bloqueante=0,
                                )
                                status.update(
                                    label=(
                                        f"⚠️ Borrador listo (fidelidad {fidelidad} < {umbral}): "
                                        f"{sub['nombre']}"
                                    ),
                                    state="complete",
                                )
                            else:
                                status.update(
                                    label=f"✅ Borrador listo: {sub['nombre']}",
                                    state="complete",
                                )
                        except Exception as err:
                            hubo_error = True
                            status.update(label="❌ Error", state="error")
                            st.error(f"Error en «{sub['nombre']}»: {err}")
                _db_actualizar_ejecucion(
                    ejecucion_id, "error" if hubo_error else "completado"
                )
                st.rerun()

    # ── Sub-bloques — áreas de edición ────────────────────────────────────────
    st.divider()

    # Progreso del bloque en tiempo real.
    prog = db.get_progreso_bloque(tema_id, RUTA_DB)
    _pct = prog["porcentaje"]
    _col_prog, _col_info = st.columns([3, 1])
    with _col_prog:
        st.progress(_pct / 100, text=f"Progreso del bloque: {prog['aprobados']}/{prog['total']} sub-bloques aprobados ({_pct}%)")
    with _col_info:
        st.caption(f"**{len(subbloques)} sub-bloques** del bloque *{tema_nombre}*")

    _ETIQUETAS_ESTADO = {
        "pendiente": "⚪ Sin borrador",
        "generado": "🤖 Borrador generado por IA",
        "editado": "✏️ Editado por el profesor",
        "aprobado": "✅ Aprobado",
    }

    for sub in subbloques:
        cs = _db_cnt_get_contenido_subbloque(sub["id"])
        estado_actual = cs["estado"] if cs else "pendiente"

        if cs is None:
            etiqueta = _ETIQUETAS_ESTADO["pendiente"]
            texto_inicial = ""
        elif estado_actual == "aprobado":
            etiqueta = _ETIQUETAS_ESTADO["aprobado"]
            texto_inicial = cs.get("markdown_final") or cs.get("markdown_borrador") or ""
        elif estado_actual == "editado":
            pct_ed = cs.get("porcentaje_editado") or 0
            etiqueta = f"✏️ Editado ({pct_ed}% modificado)"
            texto_inicial = cs.get("markdown_final") or cs.get("markdown_borrador") or ""
        elif estado_actual == "generado":
            etiqueta = _ETIQUETAS_ESTADO["generado"]
            texto_inicial = cs.get("markdown_borrador") or ""
        else:
            etiqueta = _ETIQUETAS_ESTADO["pendiente"]
            texto_inicial = ""

        with st.expander(
            f"**{sub['nombre']}** — {etiqueta}",
            expanded=bool(cs is not None and cs.get("markdown_borrador")),
        ):
            # El key único por sub-bloque preserva la edición independiente en
            # cada rerender. value solo se aplica la primera vez que aparece el key.
            ta_key = f"contenido_{sub['id']}"
            if ta_key not in st.session_state:
                st.session_state[ta_key] = texto_inicial

            st.text_area(
                "Contenido Markdown:",
                key=ta_key,
                height=350,
                label_visibility="collapsed",
            )

            # Botón "Aprobar" disponible cuando hay borrador generado o contenido
            # editado — no cuando el sub-bloque ya está aprobado.
            if estado_actual in ("generado", "editado") and cs is not None:
                if st.button(
                    "✅ Aprobar este sub-bloque",
                    key=f"cnt_btn_aprobar_{sub['id']}",
                    type="secondary",
                ):
                    _db_cnt_aprobar_subbloque(sub["id"])
                    st.rerun()

    # ── Botón de guardado ─────────────────────────────────────────────────────
    st.divider()
    if st.button(
        "Guardar contenido del bloque",
        type="primary",
        use_container_width=True,
        key="cnt_btn_guardar",
    ):
        guardados = 0
        for sub in subbloques:
            texto_final = st.session_state.get(f"contenido_{sub['id']}", "").strip()
            if not texto_final:
                continue
            cs = _db_cnt_get_contenido_subbloque(sub["id"])
            borrador = (cs["markdown_borrador"] or "") if cs else ""
            ratio = difflib.SequenceMatcher(None, borrador, texto_final).ratio()
            pct = round((1 - ratio) * 100, 1)
            _db_cnt_guardar_final(sub["id"], texto_final, pct)
            guardados += 1
        if guardados:
            st.success(f"✅ {guardados} sub-bloque(s) guardados.")
        else:
            st.info("No había contenido en los text-areas para guardar.")
        st.rerun()


# =============================================================================
# Helpers de base de datos — Presentación
# =============================================================================

def _db_prs_get_presentacion_subbloque(subbloque_id: int) -> dict | None:
    conn = db.get_connection(RUTA_DB)
    try:
        r = conn.execute(
            "SELECT id, patron_visualizacion, elegido_por_profesor, html_path "
            "FROM presentacion_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _db_prs_upsert_presentacion_subbloque(
    subbloque_id: int,
    patron: str,
    elegido_por_profesor: int,
) -> int:
    """Inserta o actualiza presentacion_subbloque. Devuelve el id de la fila."""
    conn = db.get_connection(RUTA_DB)
    try:
        existing = conn.execute(
            "SELECT id FROM presentacion_subbloque WHERE subbloque_id = ?",
            (subbloque_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE presentacion_subbloque SET patron_visualizacion = ?, "
                "elegido_por_profesor = ?, fecha_generacion = CURRENT_TIMESTAMP "
                "WHERE subbloque_id = ?",
                (patron, elegido_por_profesor, subbloque_id),
            )
            row_id = existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO presentacion_subbloque "
                "(subbloque_id, patron_visualizacion, elegido_por_profesor) "
                "VALUES (?, ?, ?)",
                (subbloque_id, patron, elegido_por_profesor),
            )
            row_id = cur.lastrowid
        conn.commit()
        return row_id
    finally:
        conn.close()


def _db_prs_update_html_path(subbloque_id: int, html_path: str) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE presentacion_subbloque SET html_path = ?, "
            "fecha_generacion = CURRENT_TIMESTAMP WHERE subbloque_id = ?",
            (html_path, subbloque_id),
        )
        conn.commit()
    finally:
        conn.close()


def _db_prs_get_parametros(presentacion_subbloque_id: int) -> list[dict]:
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, nombre_parametro, simbolo, es_slider, "
                "valor_min, valor_max, valor_predeterminado "
                "FROM parametros_subbloque WHERE presentacion_subbloque_id = ? "
                "ORDER BY id",
                (presentacion_subbloque_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _db_prs_insert_parametros(
    presentacion_subbloque_id: int,
    parametros: list[dict],
) -> None:
    """Inserta parámetros solo si la tabla está vacía para ese presentacion_subbloque_id."""
    conn = db.get_connection(RUTA_DB)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM parametros_subbloque WHERE presentacion_subbloque_id = ?",
            (presentacion_subbloque_id,),
        ).fetchone()[0]
        if count:
            return
        for p in parametros:
            conn.execute(
                "INSERT INTO parametros_subbloque "
                "(presentacion_subbloque_id, nombre_parametro, simbolo, "
                "es_slider, valor_min, valor_max, valor_predeterminado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    presentacion_subbloque_id,
                    p.get("nombre_parametro") or p.get("simbolo", "x"),
                    p.get("simbolo", "x"),
                    1,
                    p.get("valor_min"),
                    p.get("valor_max"),
                    p.get("valor_predeterminado"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _db_prs_update_parametro(
    param_id: int,
    es_slider: int,
    valor_min: float | None,
    valor_max: float | None,
    valor_pred: float | None,
) -> None:
    conn = db.get_connection(RUTA_DB)
    try:
        conn.execute(
            "UPDATE parametros_subbloque SET es_slider = ?, valor_min = ?, "
            "valor_max = ?, valor_predeterminado = ? WHERE id = ?",
            (es_slider, valor_min, valor_max, valor_pred, param_id),
        )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Lógica del Agente Presentación — razonador y generador por sub-bloque
# =============================================================================

_CHIP_LABELS = [
    "curva simple", "familia de curvas", "región / criterio",
    "mapa 2d", "trayectoria", "respuesta en frecuencia", "ninguna",
]
# Chip → valor DB (minúscula snake_case, igual que el CHECK del esquema)
_CHIP_TO_PATRON = {
    "curva simple": "curva_simple",
    "familia de curvas": "familia_curvas",
    "región / criterio": "region_criterio",
    "mapa 2d": "mapa_2d",
    "trayectoria": "trayectoria",
    "respuesta en frecuencia": "respuesta_frecuencial",
    "ninguna": "ninguna",
}
_PATRON_TO_CHIP = {v: k for k, v in _CHIP_TO_PATRON.items()}

# Conversión entre valor DB (lowercase) y valor API del razonador (UPPERCASE)
_PATRON_DB_TO_API = {
    "curva_simple": "CURVA_SIMPLE",
    "familia_curvas": "FAMILIA_CURVAS",
    "region_criterio": "REGION_CRITERIO",
    "mapa_2d": "MAPA_2D",
    "trayectoria": "TRAYECTORIA",
    "respuesta_frecuencial": "RESPUESTA_FRECUENCIAL",
    "ninguna": "ninguna",
}
_PATRON_API_TO_DB = {v: k for k, v in _PATRON_DB_TO_API.items()}


def _prs_elemento_desde_markdown(nombre: str, markdown: str) -> dict:
    """Construye un dict 'elemento' compatible con el razonador desde texto Markdown."""
    block_m = re.search(r"\$\$([\s\S]+?)\$\$", markdown)
    inline_m = re.search(r"(?<!\$)\$([^$\n]{3,}?)\$(?!\$)", markdown)
    expresion = ""
    if block_m:
        expresion = block_m.group(1).strip()
    elif inline_m:
        expresion = inline_m.group(1).strip()
    return {
        "nombre": nombre,
        "expresion": expresion,
        "contexto": markdown[:3000],
        "seccion": nombre,
        "tipo": "relacion" if expresion else "texto",
        "es_bloque": bool(block_m),
        "advertencia": None,
    }


def _prs_razonar_subbloque(subbloque_nombre: str, markdown: str) -> dict:
    """Llama al razonador Sonnet (del Agente Presentación) sobre el markdown del sub-bloque.

    Devuelve el dict de visualización con PATRON, PARAMETROS_SLIDER y RANGO_VARIABLES.
    Si el razonador devuelve VISUALIZABLE=NO o falla, devuelve patron='ninguna'.
    """
    import anthropic as _ant
    client = _ant.Anthropic(
        api_key=_prs_config.ANTHROPIC_API_KEY,
        timeout=float(_prs_config.REQUEST_TIMEOUT_SECONDS),
    )
    elemento = _prs_elemento_desde_markdown(subbloque_nombre, markdown)
    try:
        viz = _prs_generador_html._razonar_visualizacion(elemento, client, verbose=False)
        if viz.get("VISUALIZABLE") == "NO":
            return {"PATRON": "ninguna", "PARAMETROS_SLIDER": "", "RANGO_VARIABLES": ""}
        # Convertir PATRON a formato DB (lowercase snake_case) antes de devolver
        patron_api = viz.get("PATRON", "ninguna")
        viz["PATRON"] = _PATRON_API_TO_DB.get(patron_api, "ninguna")
        return viz
    except Exception:
        return {"PATRON": "ninguna", "PARAMETROS_SLIDER": "", "RANGO_VARIABLES": ""}


def _prs_extraer_parametros_desde_viz(viz: dict) -> list[dict]:
    """Extrae los parámetros candidatos del dict de visualización del razonador."""
    params_raw = viz.get("PARAMETROS_SLIDER") or ""
    rangos_raw = viz.get("RANGO_VARIABLES") or ""
    rangos = _prs_generador_html._parse_rango_variables(rangos_raw)
    slider_names = [p.strip() for p in re.split(r"[,;]", params_raw) if p.strip()]
    parametros = []
    for nombre in slider_names:
        rango = rangos.get(nombre, {})
        parametros.append({
            "nombre_parametro": nombre,
            "simbolo": nombre,
            "valor_min": rango.get("min"),
            "valor_max": rango.get("max"),
            "valor_predeterminado": rango.get("default"),
        })
    if not parametros:
        for nombre, rango in rangos.items():
            parametros.append({
                "nombre_parametro": nombre,
                "simbolo": nombre,
                "valor_min": rango.get("min"),
                "valor_max": rango.get("max"),
                "valor_predeterminado": rango.get("default"),
            })
    return parametros


def _prs_generar_html_subbloque(
    subbloque_nombre: str,
    markdown: str,
    patron: str,
    parametros_db: list[dict],
) -> str:
    """Genera el HTML del sub-bloque usando el patrón y parámetros guardados en BD.

    No llama al razonador: construye el dict visualizacion directamente desde los
    datos de parametros_subbloque y llama al generador Sonnet via build_generador_message.
    Aplica aplicar_rangos y validar_bloque_html igual que _generar_bloque, pero
    saltándose el paso del razonador (el patrón ya lo eligió el profesor en la UI).
    """
    import anthropic as _ant

    elemento = _prs_elemento_desde_markdown(subbloque_nombre, markdown)
    slug = _prs_generador_html._slug(subbloque_nombre)

    sliders_activos = [p for p in parametros_db if p["es_slider"]]
    parametros_slider_str = ", ".join(p["simbolo"] for p in sliders_activos)

    rango_lines = []
    for p in sliders_activos:
        mn = p["valor_min"] if p["valor_min"] is not None else 0.0
        mx = p["valor_max"] if p["valor_max"] is not None else 100.0
        df = p["valor_predeterminado"] if p["valor_predeterminado"] is not None else (mn + mx) / 2
        rango_lines.append(f"{p['simbolo']}: min={mn}, max={mx}, default={df}")
    rango_variables_str = "\n".join(rango_lines)

    # El generador Sonnet espera el patrón en formato API (UPPERCASE)
    patron_api = _PATRON_DB_TO_API.get(patron, "CURVA_SIMPLE")
    visualizacion = {
        "VISUALIZABLE": "SI",
        "PATRON": patron_api,
        "EJE_X": "x",
        "EJE_Y": "y",
        "PARAMETROS_SLIDER": parametros_slider_str,
        "ESCALA_LOG_X": "NO",
        "ESCALA_LOG_Y": "NO",
        "JUSTIFICACION": f"Patrón seleccionado: {patron_api}",
        "RANGO_VARIABLES": rango_variables_str,
        "ZONA_VALIDEZ": "ninguna",
    }

    client = _ant.Anthropic(
        api_key=_prs_config.ANTHROPIC_API_KEY,
        timeout=float(_prs_config.REQUEST_TIMEOUT_SECONDS),
    )
    tabla_variables = _prs_generador_html.construir_tabla_variables(elemento, client)
    user_msg = _prs_prompts.build_generador_message(
        elemento, visualizacion, slug, tabla_variables, requiere_autoarranque=True,
    )
    rangos_esperados = _prs_generador_html._parse_rango_variables(rango_variables_str)

    motivo_fallo = ""
    for attempt in range(3):
        mensaje = user_msg
        if attempt and motivo_fallo:
            mensaje = (
                f"{user_msg}\n\nCORRECCIÓN — rechazado por: {motivo_fallo}.\n"
                f"Incluye obligatoriamente window['initBloque_{slug}'] = function() {{ ... }}; "
                f"y al final del script: "
                f"document.addEventListener('DOMContentLoaded', function() {{"
                f" try {{ window['initBloque_{slug}'](); }} catch(e) {{"
                f" console.error('Error en initBloque_{slug}:', e); }} }});"
            )
        try:
            response = client.messages.create(
                model=_prs_config.MODEL_SMART,
                max_tokens=8192,
                system=_prs_prompts.PROMPT_GENERADOR_HTML,
                messages=[{"role": "user", "content": mensaje}],
            )
            raw = response.content[0].text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw).strip()
            if getattr(response, "stop_reason", None) == "max_tokens":
                motivo_fallo = "respuesta truncada (max_tokens)"
                continue
            if _prs_generador_html._is_valid_html(raw):
                if rangos_esperados:
                    raw = _prs_generador_html.aplicar_rangos(
                        raw, rangos_esperados, parametros_slider=parametros_slider_str,
                    )
                es_valido, motivo = _prs_generador_html.validar_bloque_html(raw, slug)
                if es_valido:
                    return raw
                motivo_fallo = motivo
        except Exception as exc:
            motivo_fallo = str(exc)

    return _prs_generador_html._bloque_placeholder(slug, subbloque_nombre, motivo_fallo)


# =============================================================================
# Vista Presentación
# =============================================================================

def _vista_presentacion() -> None:
    if _PRS_ERROR:
        st.error(f"No se pudo cargar el Agente Presentación: {_PRS_ERROR}")
        st.caption("Comprueba que `agente-presentacion/.env` tiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    if st.session_state.get("prs_asignatura") != asignatura:
        for k in [k for k in list(st.session_state.keys()) if k.startswith("prs_")]:
            del st.session_state[k]
        st.session_state["prs_asignatura"] = asignatura

    # CSS para chips (radio horizontal con estilo pill), acotado al área principal
    st.markdown(f"""
    <style>
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] > div[role="radiogroup"] {{
        flex-wrap: wrap; gap: 6px;
    }}
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] label {{
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 20px !important;
        padding: 4px 14px !important;
        font-size: 13px !important;
        cursor: pointer;
    }}
    section[data-testid="stAppViewContainer"] div[data-testid="stRadio"] label:has(input:checked) {{
        background: {ACENTO} !important;
        color: #ffffff !important;
        border-color: {ACENTO} !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    # ── Selector de tema (igual que en Contenido) ─────────────────────────────
    temas = _db_cnt_get_temas(asignatura_id)
    if not temas:
        st.info(
            "No hay bloques temáticos. Ejecuta primero el **Agente Organizador** "
            "y pulsa **Confirmar organización**."
        )
        return

    tema_labels = [f"{t['bloque']} — {t['nombre']} ({t['horas']}h)" for t in temas]
    tema_idx = st.selectbox(
        "Bloque temático:",
        options=range(len(temas)),
        format_func=lambda i: tema_labels[i],
        key="prs_tema_idx",
    )
    tema = temas[tema_idx]
    tema_id: int = tema["id"]
    tema_nombre: str = tema["nombre"]

    subbloques = _db_cnt_get_subbloques(tema_id)
    if not subbloques:
        st.warning("Este bloque no tiene sub-bloques registrados.")
        return

    _paso_prs = 1
    for _s in subbloques:
        _prs_r = _db_prs_get_presentacion_subbloque(_s["id"])
        if _prs_r and _prs_r.get("html_path"):
            _paso_prs = 2
            break
    _render_stepper(["Bloque", "Configuración", "Generación"], _paso_prs)

    st.divider()

    for sub in subbloques:
        sub_id: int = sub["id"]
        sub_nombre: str = sub["nombre"]

        # Contenido del sub-bloque (markdown_final prioritario sobre borrador)
        cs = _db_cnt_get_contenido_subbloque(sub_id)
        markdown_sub = ""
        if cs:
            markdown_sub = cs.get("markdown_final") or cs.get("markdown_borrador") or ""

        # Obtener o crear fila en presentacion_subbloque
        prs_row = _db_prs_get_presentacion_subbloque(sub_id)

        if prs_row is None and not markdown_sub:
            with st.expander(f"**{sub_nombre}** — sin contenido"):
                st.caption("Genera el contenido en la vista **Contenido** primero.")
            continue

        if prs_row is None:
            # Primera visita: ejecutar razonador para sugerir patrón
            with st.spinner(f"Analizando «{sub_nombre}» con el razonador…"):
                viz = _prs_razonar_subbloque(sub_nombre, markdown_sub)
            patron_sugerido = viz.get("PATRON", "ninguna")
            # viz["PATRON"] ya viene en formato DB (lowercase) desde _prs_razonar_subbloque
            if patron_sugerido not in _CHIP_TO_PATRON.values():
                patron_sugerido = "ninguna"
            prs_id = _db_prs_upsert_presentacion_subbloque(sub_id, patron_sugerido, 0)
            if patron_sugerido != "ninguna":
                params = _prs_extraer_parametros_desde_viz(viz)
                if params:
                    _db_prs_insert_parametros(prs_id, params)
            prs_row = {
                "id": prs_id,
                "patron_visualizacion": patron_sugerido,
                "elegido_por_profesor": 0,
                "html_path": None,
            }

        patron_actual: str = prs_row["patron_visualizacion"] or "ninguna"
        elegido: int = prs_row["elegido_por_profesor"]
        prs_id: int = prs_row["id"]

        # Badge de estado junto al título
        if elegido:
            badge = (
                f'<span style="font-size:11px;background:#E6F1FB;color:{ACENTO};'
                f'border-radius:20px;padding:2px 10px;font-weight:500;margin-left:8px;">'
                f'elegido por el profesor</span>'
            )
        else:
            badge = (
                '<span style="font-size:11px;background:rgba(128,128,128,0.12);'
                'color:var(--text-color);border-radius:20px;padding:2px 10px;margin-left:8px;">'
                'automático</span>'
            )

        with st.expander(f"**{sub_nombre}**", expanded=True):
            st.markdown(
                f'<div style="margin-bottom:10px;font-size:14px;font-weight:600;">'
                f'{sub_nombre}{badge}</div>',
                unsafe_allow_html=True,
            )

            # ── Chips de patrón ────────────────────────────────────────────────
            chip_actual = _PATRON_TO_CHIP.get(patron_actual, "ninguna")
            chip_key = f"prs_chip_{sub_id}"
            if chip_key not in st.session_state:
                st.session_state[chip_key] = chip_actual

            nuevo_chip = st.radio(
                "Patrón:",
                options=_CHIP_LABELS,
                index=_CHIP_LABELS.index(st.session_state.get(chip_key, chip_actual))
                      if st.session_state.get(chip_key, chip_actual) in _CHIP_LABELS else 6,
                horizontal=True,
                key=chip_key,
                label_visibility="collapsed",
            )
            nuevo_patron = _CHIP_TO_PATRON.get(nuevo_chip, "ninguna")
            if nuevo_patron != patron_actual:
                _db_prs_upsert_presentacion_subbloque(sub_id, nuevo_patron, 1)
                patron_actual = nuevo_patron
                elegido = 1
                prs_row["patron_visualizacion"] = nuevo_patron
                st.rerun()

            # ── Tabla de parámetros (solo si patrón != ninguna) ────────────────
            if patron_actual != "ninguna":
                parametros = _db_prs_get_parametros(prs_id)

                if not parametros and markdown_sub:
                    with st.spinner("Detectando parámetros del sub-bloque…"):
                        viz2 = _prs_razonar_subbloque(sub_nombre, markdown_sub)
                    params2 = _prs_extraer_parametros_desde_viz(viz2)
                    if not params2:
                        params2 = [{
                            "nombre_parametro": "x", "simbolo": "x",
                            "valor_min": 0.0, "valor_max": 100.0, "valor_predeterminado": 50.0,
                        }]
                    _db_prs_insert_parametros(prs_id, params2)
                    parametros = _db_prs_get_parametros(prs_id)

                if parametros:
                    st.markdown(
                        "<p style='font-size:11px;font-weight:500;color:var(--text-color);"
                        "opacity:0.55;text-transform:uppercase;letter-spacing:0.08em;"
                        "margin:10px 0 4px;'>Parámetros de la visualización</p>",
                        unsafe_allow_html=True,
                    )
                    col_h1, col_h2, col_h3, col_h4 = st.columns([2, 1.3, 1.3, 1.3])
                    col_h1.caption("Parámetro")
                    col_h2.caption("mín")
                    col_h3.caption("máx")
                    col_h4.caption("defecto")

                    for p in parametros:
                        pid = p["id"]
                        c1, c2, c3, c4 = st.columns([2, 1.3, 1.3, 1.3])
                        with c1:
                            es_slider = st.checkbox(
                                f"{p['nombre_parametro']} `{p['simbolo']}`",
                                value=bool(p["es_slider"]),
                                key=f"prs_slider_{pid}",
                            )
                        if es_slider:
                            v_min = c2.number_input(
                                "mín",
                                value=float(p["valor_min"]) if p["valor_min"] is not None else 0.0,
                                key=f"prs_min_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            v_max = c3.number_input(
                                "máx",
                                value=float(p["valor_max"]) if p["valor_max"] is not None else 100.0,
                                key=f"prs_max_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            dfl = p["valor_predeterminado"]
                            if dfl is None:
                                mn = p["valor_min"] or 0.0
                                mx = p["valor_max"] or 100.0
                                dfl = (mn + mx) / 2
                            v_def = c4.number_input(
                                "defecto",
                                value=float(dfl),
                                key=f"prs_def_{pid}",
                                step=0.1,
                                label_visibility="collapsed",
                            )
                            _db_prs_update_parametro(pid, 1, v_min, v_max, v_def)
                        else:
                            _db_prs_update_parametro(
                                pid, 0, p["valor_min"], p["valor_max"], p["valor_predeterminado"]
                            )

                # ── Botón de generación HTML ───────────────────────────────────
                html_path = prs_row.get("html_path")
                if html_path and os.path.exists(str(html_path)):
                    st.success(f"HTML listo: `{os.path.basename(html_path)}`")
                    try:
                        with open(html_path, encoding="utf-8") as _f:
                            st.download_button(
                                "Descargar HTML",
                                data=_f.read(),
                                file_name=os.path.basename(html_path),
                                mime="text/html",
                                key=f"prs_dl_{sub_id}",
                            )
                    except OSError:
                        pass

                if st.button(
                    f"Generar HTML de este sub-bloque",
                    type="primary",
                    key=f"prs_gen_{sub_id}",
                    use_container_width=True,
                ):
                    if not markdown_sub:
                        st.error("Sin contenido generado. Ve a la vista **Contenido** primero.")
                    else:
                        params_para_generar = _db_prs_get_parametros(prs_id)
                        with st.status(
                            f"Generando HTML de «{sub_nombre}»…", expanded=True
                        ) as status:
                            try:
                                st.write("Llamando al generador Sonnet…")
                                html_bloque = _prs_generar_html_subbloque(
                                    subbloque_nombre=sub_nombre,
                                    markdown=markdown_sub,
                                    patron=patron_actual,
                                    parametros_db=params_para_generar,
                                )
                                html_pagina = _prs_generador_html._construir_pagina(
                                    [(sub_nombre, html_bloque)],
                                    titulo_tema=f"{tema_nombre} — {sub_nombre}",
                                )
                                html_dir = os.path.join(
                                    RAIZ_MONOREPO, "data", "html", _slugify(asignatura)
                                )
                                os.makedirs(html_dir, exist_ok=True)
                                html_path_nuevo = os.path.join(
                                    html_dir, f"subbloque_{sub_id}.html"
                                )
                                with open(html_path_nuevo, "w", encoding="utf-8") as _f:
                                    _f.write(html_pagina)
                                _db_prs_update_html_path(sub_id, html_path_nuevo)
                                status.update(label="HTML generado correctamente", state="complete")
                            except Exception as _err:
                                status.update(label="Error en la generación", state="error")
                                st.error(str(_err))
                        st.rerun()


# =============================================================================
# Stepper contextual — flujos multi-paso
# =============================================================================

def _render_stepper(pasos: list[str], paso_actual: int) -> None:
    """Fila de tarjetas conectadas por flechas: activo en color de acento, resto en gris."""
    partes: list[str] = []
    for i, paso in enumerate(pasos):
        if i < paso_actual:
            estilo = (
                f"background:rgba(24,95,165,0.08);color:{ACENTO};"
                "border-radius:8px;padding:5px 15px;font-size:12px;font-weight:500;"
                "font-family:'DM Sans',sans-serif;opacity:0.7;"
            )
        elif i == paso_actual:
            estilo = (
                f"background:{ACENTO};color:#ffffff;"
                "border-radius:8px;padding:5px 15px;font-size:12px;font-weight:600;"
                "font-family:'DM Sans',sans-serif;"
            )
        else:
            estilo = (
                "background:rgba(128,128,128,0.08);color:var(--text-color);"
                "border-radius:8px;padding:5px 15px;font-size:12px;"
                "font-family:'DM Sans',sans-serif;opacity:0.4;"
            )
        partes.append(f'<span style="{estilo}">{paso}</span>')
        if i < len(pasos) - 1:
            partes.append(
                '<span style="color:rgba(128,128,128,0.3);font-size:16px;'
                'padding:0 2px;line-height:1;">›</span>'
            )
    st.markdown(
        '<div style="display:flex;align-items:center;gap:4px;margin:0 0 18px 0;flex-wrap:wrap;">'
        + "".join(partes)
        + "</div>",
        unsafe_allow_html=True,
    )


# =============================================================================
# Vista Organizador
# =============================================================================

def _vista_organizador() -> None:
    if _ORG_ERROR:
        st.error(f"No se pudo cargar el Agente Organizador: {_ORG_ERROR}")
        st.caption(f"Comprueba que `agente-organizador/.env` existe y contiene `ANTHROPIC_API_KEY`.")
        return

    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    slug = _slugify(asignatura)

    # Reset si la asignatura cambió entre reruns
    if st.session_state.get("org_asignatura") != asignatura:
        _org_reset_state()
        st.session_state["org_asignatura"] = asignatura

    _org_init_state()

    if st.session_state.get("org_ultimo_output"):
        _paso_org = 2
    elif st.session_state.get("org_fase") == "editar":
        _paso_org = 1
    else:
        _paso_org = 0
    _render_stepper(["Guía docente", "Subtemas", "Propuesta"], _paso_org)

    # ── Uploaders ──────────────────────────────────────────────────────────────
    st.markdown(
        "<div style='font-family:\"DM Sans\",sans-serif; font-size:11px; font-weight:500; "
        "color:var(--text-color); opacity:0.55; letter-spacing:0.1em; text-transform:uppercase; "
        "margin-bottom:10px;'>Archivos de entrada</div>",
        unsafe_allow_html=True,
    )
    col_guia, col_mat = st.columns([1, 2])
    with col_guia:
        guia_docente = st.file_uploader(
            "Guía docente (PDF)", type=["pdf"], accept_multiple_files=False,
            key="org_uploader_guia",
        )
    with col_mat:
        materiales_teoria = st.file_uploader(
            "Materiales de teoría (PDF / PPTX)", type=["pdf", "pptx"],
            accept_multiple_files=True, key="org_uploader_materiales",
        )

    _org_registrar_archivos(guia_docente, materiales_teoria, asignatura_id, slug)
    _org_detectar_cambio(guia_docente, materiales_teoria)

    puede_generar = guia_docente is not None and bool(materiales_teoria)

    # ── Expanders de validación ────────────────────────────────────────────────
    with st.expander("⏱️ Validación de horas detectadas", expanded=False):
        horas_info = st.session_state.get("org_ultimas_horas_teoria") or {}
        h_te = int(horas_info.get("horas_teoria", 0))
        h_pa = int(horas_info.get("horas_aula", 0))
        h_pl = int(horas_info.get("horas_laboratorio", 0))
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Horas TE detectadas", f"{h_te}h")
        col2.metric("Horas PA detectadas", f"{h_pa}h")
        col3.metric("Horas PL (informativo)", f"{h_pl}h")
        col4.metric("Total TE + PA", f"{h_te + h_pa}h")
        if h_te + h_pa <= 0 and st.session_state.get("org_ultimas_horas_teoria"):
            st.warning("⚠️ No se detectaron horas lectivas (TE/PA) en la guía docente.")

    if st.session_state["org_ultimos_archivos_teoria"] or st.session_state["org_ultimos_archivos_contexto"]:
        with st.expander("📋 Clasificación de archivos detectada", expanded=False):
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Teoría")
                for n in st.session_state["org_ultimos_archivos_teoria"]:
                    st.write(f"- {n}")
                if not st.session_state["org_ultimos_archivos_teoria"]:
                    st.write("Sin archivos clasificados como teoría.")
            with c2:
                st.subheader("Contexto/Outline")
                for n in st.session_state["org_ultimos_archivos_contexto"]:
                    st.write(f"- {n}")
                if not st.session_state["org_ultimos_archivos_contexto"]:
                    st.write("Sin archivos clasificados como contexto.")

    st.divider()

    # ── Botón de generación ───────────────────────────────────────────────────
    if st.button(
        "Generar organización", disabled=not puede_generar,
        use_container_width=True, type="primary", key="org_btn_generar",
    ):
        st.session_state["org_historial_feedback"] = []
        st.session_state["org_iteracion"] = 1
        st.session_state["org_ultimo_output"] = None
        st.session_state["org_fase"] = None
        st.session_state["org_confirmada"] = False
        if _org_extraer_y_detectar(guia_docente, materiales_teoria):
            st.rerun()

    if not puede_generar and not st.session_state.get("org_ultimo_output"):
        st.info("Sube los archivos arriba y pulsa **Generar organización** para comenzar.")

    # ── Fase: editor de subtemas ──────────────────────────────────────────────
    if st.session_state.get("org_fase") == "editar" and not st.session_state.get("org_ultimo_output"):
        editor_data = st.session_state.get("org_subtemas_editor", [])
        if editor_data:
            st.markdown("### Subtemas detectados — revisa y confirma")
            st.caption(
                "Los subtemas se han detectado por numeración jerárquica en los materiales "
                "(ej. '3.2. Título'). Edita la lista antes de generar la propuesta."
            )
            for i, bloque_info in enumerate(editor_data):
                nombre_archivo = bloque_info["archivo"]
                candidatos = bloque_info["candidatos"]
                discrepancia = bloque_info.get("discrepancia", False)

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
                if not candidatos:
                    st.info(
                        "No se detectó numeración de subtemas en este material. "
                        "Indica manualmente los subtemas del bloque (uno por línea)."
                    )
                st.text_area(
                    "Subtemas (uno por línea):",
                    value="\n".join(candidatos),
                    key=f"org_subtemas_ta_{i}",
                    height=max(100, min(300, 30 * len(candidatos) + 60)),
                )

            st.divider()
            if st.button(
                "Confirmar subtemas y generar propuesta",
                type="primary", use_container_width=True, key="org_btn_confirmar_subs",
            ):
                subtemas_confirmados: list[list[dict]] = []
                for i, bloque_info in enumerate(editor_data):
                    ta_valor = st.session_state.get(f"org_subtemas_ta_{i}", "")
                    lineas = [l.strip() for l in ta_valor.splitlines() if l.strip()]
                    cands_orig_norm = {
                        _org_parser.normalizar_subtema(c)
                        for c in bloque_info.get("candidatos_mat_orig", [])
                    }
                    lista: list[dict] = []
                    for linea in lineas:
                        origen = (
                            "Detectado"
                            if _org_parser.normalizar_subtema(linea) in cands_orig_norm
                            else "Manual"
                        )
                        lista.append({"nombre": linea, "origen": origen})
                    subtemas_confirmados.append(lista)

                if _org_generar_organizacion(
                    guia_docente, materiales_teoria,
                    asignatura_id=asignatura_id, slug=slug,
                    subtemas_confirmados=subtemas_confirmados,
                ):
                    st.rerun()

    # ── Output generado ────────────────────────────────────────────────────────
    if st.session_state.get("org_ultimo_output"):
        w = st.session_state.get("org_warning_cardinalidad")
        if w:
            st.warning(_texto_warning_cobertura(w["esperados"], w["generados"]))

        wn = st.session_state.get("org_warning_normalizacion")
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

        st.markdown("### Propuesta generada")
        st.caption(
            f"Versión {st.session_state['org_version_actual']} · "
            f"guardada en `data/{slug}/outputs/organizador/v{st.session_state['org_version_actual']}.md`"
        )
        st.markdown(st.session_state["org_ultimo_output"])
        st.download_button(
            label="Descargar resultado (.md)",
            data=st.session_state["org_ultimo_output"],
            file_name=st.session_state.get("org_ultimo_nombre_descarga", "Propuesta_asignatura.md"),
            mime="text/markdown",
            key="org_download",
        )

        st.divider()

        # ── Confirmar organización ─────────────────────────────────────────────
        st.subheader("¿La organización es correcta?")

        if st.session_state.get("org_confirmada"):
            st.success(
                f"✅ Organización confirmada y guardada en la base de datos "
                f"(versión {st.session_state['org_version_actual']})."
            )
        else:
            if st.button(
                "✅ Confirmar organización como definitiva",
                type="primary", use_container_width=True, key="org_btn_confirmar_org",
            ):
                output_id = st.session_state.get("org_output_id")
                if not output_id:
                    st.error("No hay output registrado en la base de datos — genera la organización primero.")
                else:
                    try:
                        bloques = parsear_bloques_organizador(st.session_state["org_ultimo_output"])
                        if not bloques:
                            st.warning(
                                "No se pudieron extraer bloques del output. "
                                "Revisa que el formato sigue el patrón '## Bloque N — Nombre · Xh'."
                            )
                        else:
                            _db_confirmar_organizacion(asignatura_id, output_id, bloques)
                            st.session_state["org_confirmada"] = True
                            n_sub = sum(len(b["subtemas"]) for b in bloques)
                            st.success(
                                f"✅ {len(bloques)} bloques y {n_sub} subtemas guardados en la base de datos."
                            )
                            st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar en la base de datos: {e}")

        st.divider()

        # ── Loop de feedback ───────────────────────────────────────────────────
        feedback = st.text_area(
            "Si quieres mejorar algo, descríbelo aquí (opcional):",
            placeholder=(
                "Ejemplos:\n"
                "- 'Aumenta las horas de [subtema] porque a los alumnos les cuesta más'\n"
                "- 'Divide [subtema] en dos partes separadas'\n"
                "- 'El bloque [N] necesita más granularidad'"
            ),
            key=f"org_feedback_{st.session_state['org_iteracion']}",
        )

        col_regen, col_info = st.columns([1, 4])
        with col_regen:
            regenerar = (
                st.button("🔄 Regenerar", type="secondary", key="org_btn_regen")
                if st.session_state["org_iteracion"] < 5
                else False
            )
        with col_info:
            if st.session_state["org_iteracion"] > 1:
                st.caption(
                    f"Iteración {st.session_state['org_iteracion']} — "
                    f"{len(st.session_state['org_historial_feedback'])} refinamiento(s) aplicado(s)"
                )

        if st.session_state["org_iteracion"] >= 5:
            st.info("Has alcanzado el máximo de 5 iteraciones. Descarga el resultado o reinicia subiendo nuevos archivos.")

        if regenerar:
            entrada = feedback.strip() if feedback and feedback.strip() else "[Sin feedback — regeneración directa]"
            st.session_state["org_historial_feedback"].append(entrada)
            st.session_state["org_iteracion"] += 1
            st.session_state["org_confirmada"] = False
            if _org_generar_organizacion(
                guia_docente, materiales_teoria,
                asignatura_id=asignatura_id, slug=slug,
                feedback_previo=st.session_state["org_historial_feedback"],
            ):
                st.rerun()


# =============================================================================
# Vista Resumen — métricas agregadas de la asignatura activa
# =============================================================================

def _db_resumen_metricas(asignatura_id: int) -> dict:
    """Consulta las métricas agregadas de la asignatura para la vista Resumen.

    - fidelidad_media: AVG de los scores de fidelidad guardados (validaciones
      tipo 'fidelidad_baja'); son los únicos scores que se persisten.
    - n_outputs: organizador_outputs + presentacion_outputs.
    - n_avisos: todas las validaciones ligadas a ejecuciones de la asignatura.
    - ultima_ejecucion: fecha de inicio de la ejecución más reciente (cualquier agente).
    """
    conn = db.get_connection(RUTA_DB)
    try:
        fid = conn.execute(
            "SELECT AVG(v.valor_afectado) AS media, COUNT(*) AS n "
            "FROM validaciones v JOIN ejecuciones e ON v.ejecucion_id = e.id "
            "WHERE e.asignatura_id = ? AND v.tipo = 'fidelidad_baja' "
            "AND v.valor_afectado IS NOT NULL",
            (asignatura_id,),
        ).fetchone()
        n_org = conn.execute(
            "SELECT COUNT(*) FROM organizador_outputs WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        n_prs = conn.execute(
            "SELECT COUNT(*) FROM presentacion_outputs WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        n_avisos = conn.execute(
            "SELECT COUNT(*) FROM validaciones v JOIN ejecuciones e "
            "ON v.ejecucion_id = e.id WHERE e.asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        ultima = conn.execute(
            "SELECT MAX(fecha_inicio) FROM ejecuciones WHERE asignatura_id = ?",
            (asignatura_id,),
        ).fetchone()[0]
        return {
            "fidelidad_media": fid["media"] if fid else None,
            "n_fidelidad": fid["n"] if fid else 0,
            "n_outputs": n_org + n_prs,
            "n_org": n_org,
            "n_prs": n_prs,
            "n_avisos": n_avisos,
            "ultima_ejecucion": ultima,
        }
    finally:
        conn.close()


def _db_resumen_avisos(asignatura_id: int) -> list[dict]:
    """Avisos de validación de la asignatura (los más recientes primero)."""
    conn = db.get_connection(RUTA_DB)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT v.tipo, v.descripcion, v.valor_afectado, v.bloqueante, "
                "v.created_at, e.agente "
                "FROM validaciones v JOIN ejecuciones e ON v.ejecucion_id = e.id "
                "WHERE e.asignatura_id = ? ORDER BY v.id DESC",
                (asignatura_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _vista_resumen() -> None:
    asignatura = st.session_state.get("asignatura_actual")
    if not asignatura:
        st.warning("Selecciona una asignatura en la barra lateral para comenzar.")
        return

    asignatura_id = _get_asignatura_id(asignatura)
    if asignatura_id is None:
        st.error("Asignatura no encontrada en la base de datos.")
        return

    m = _db_resumen_metricas(asignatura_id)

    fidelidad_txt = (
        f"{m['fidelidad_media']:.3f}" if m["fidelidad_media"] is not None else "—"
    )
    if m["ultima_ejecucion"]:
        try:
            _dt = datetime.strptime(m["ultima_ejecucion"], "%Y-%m-%d %H:%M:%S")
            ultima_txt = f"{_dt.day} {_dt.strftime('%b, %H:%M')}"
            _delta_s = int((datetime.now() - _dt).total_seconds())
            if _delta_s < 60:
                _relativo = "ahora mismo"
            elif _delta_s < 3600:
                _relativo = f"hace {_delta_s // 60} min"
            elif _delta_s < 86400:
                _relativo = f"hace {_delta_s // 3600}h"
            else:
                _d = _delta_s // 86400
                _relativo = f"hace {_d} día{'s' if _d != 1 else ''}"
        except ValueError:
            ultima_txt = m["ultima_ejecucion"]
            _relativo = None
    else:
        ultima_txt = "—"
        _relativo = None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Fidelidad media",
        fidelidad_txt,
        help=(
            "Media de los scores de fidelidad léxica guardados "
            f"({m['n_fidelidad']} sub-bloque(s) por debajo de 0.85). "
            "Si no hay ninguno marcado, no hay scores que promediar."
        ),
    )
    c2.metric(
        "Outputs generados",
        m["n_outputs"],
        help=f"organizador_outputs ({m['n_org']}) + presentacion_outputs ({m['n_prs']}).",
    )
    c3.metric(
        "Avisos de validación",
        m["n_avisos"],
        help="Filas en `validaciones` ligadas a ejecuciones de esta asignatura.",
    )
    c4.metric("Última ejecución", ultima_txt)
    if _relativo:
        c4.caption(_relativo)

    st.divider()

    avisos = _db_resumen_avisos(asignatura_id)
    st.markdown(f"**Avisos de validación registrados** ({len(avisos)})")
    if not avisos:
        st.caption("Sin avisos de validación para esta asignatura todavía.")
        return

    _ICONO_TIPO = {"cobertura_incompleta": "🧩", "fidelidad_baja": "📉"}
    for a in avisos:
        icono = _ICONO_TIPO.get(a["tipo"], "⚠️")
        valor = a["valor_afectado"]
        valor_txt = f" · valor: {valor}" if valor is not None else ""
        bloq_txt = " · 🔴 bloqueante" if a["bloqueante"] else ""
        with st.expander(
            f"{icono} `{a['tipo']}` — {a['agente']}{valor_txt}{bloq_txt}",
            expanded=False,
        ):
            st.markdown(a["descripcion"])
            st.caption(f"Registrado: {a['created_at']}")


# =============================================================================
# Vista Base de datos — navegador de solo lectura del esquema SQLite
# =============================================================================

# Nombres de columna que se interpretan como marca temporal del registro.
_COLS_FECHA = {"fecha_subida", "fecha_inicio", "fecha_generacion",
               "fecha_actualizacion", "created_at"}


def _db_info_tablas() -> list[dict]:
    """Para cada tabla del esquema: filas, columna de fecha y fecha más reciente.

    Los nombres de tabla/columna provienen de `sqlite_master`/`PRAGMA`, no de
    entrada del usuario, por lo que su interpolación en el SQL es segura.
    """
    conn = db.get_connection(RUTA_DB)
    try:
        tablas = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]
        info: list[dict] = []
        for t in tablas:
            columnas = [
                {"nombre": c["name"], "tipo": c["type"] or "—"}
                for c in conn.execute(f"PRAGMA table_info({t})").fetchall()
            ]
            fecha_col = next(
                (c["nombre"] for c in columnas if c["nombre"].lower() in _COLS_FECHA),
                None,
            )
            n_filas = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            ultima = None
            if fecha_col:
                ultima = conn.execute(f"SELECT MAX({fecha_col}) FROM {t}").fetchone()[0]
            info.append({
                "tabla": t,
                "n_filas": n_filas,
                "fecha_col": fecha_col,
                "ultima_fecha": ultima,
                "columnas": columnas,
            })
        return info
    finally:
        conn.close()


def _vista_base_datos() -> None:
    info = _db_info_tablas()
    st.caption(f"`{RUTA_DB}` — {len(info)} tablas (navegador de solo lectura).")

    h1, h2, h3 = st.columns([2.2, 1, 2])
    h1.markdown("**Tabla**")
    h2.markdown("**Filas**")
    h3.markdown("**Registro más reciente**")
    st.divider()

    for t in info:
        c1, c2, c3 = st.columns([2.2, 1, 2])
        c1.markdown(f"`{t['tabla']}`")
        c2.markdown(str(t["n_filas"]))
        if t["fecha_col"]:
            c3.markdown(t["ultima_fecha"] or "—")
        else:
            c3.caption("sin columna de fecha")

    st.divider()
    with st.expander("Ver esquema completo", expanded=False):
        for t in info:
            st.markdown(f"**`{t['tabla']}`** — {t['n_filas']} fila(s)")
            filas_esquema = [
                {"columna": c["nombre"], "tipo": c["tipo"]} for c in t["columnas"]
            ]
            st.table(filas_esquema)


# =============================================================================
# Configuración de página + inicialización
# =============================================================================

st.set_page_config(layout="wide", page_title="Pipeline TFG")


@st.cache_resource
def _preparar_bd():
    db.init_db(RUTA_DB)
    db.seed_asignaturas(RUTA_DB)
    return True


_preparar_bd()


# =============================================================================
# CSS — identidad visual compartida
# =============================================================================

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;500&family=DM+Sans:wght@400;500&display=swap');

    .marca {{
        display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
    }}
    .marca .icono {{
        width: 34px; height: 34px; border-radius: 8px; background: {ACENTO}; flex-shrink: 0;
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
        background: rgba(24, 95, 165, 0.10) !important; color: {ACENTO} !important;
        opacity: 1 !important; font-weight: 500 !important;
    }}
    section[data-testid="stSidebar"] div[data-testid="stRadio"] label p {{
        margin: 0 !important; line-height: 1.4 !important;
    }}
    .file-chip {{
        display: inline-block; padding: 3px 10px; margin: 2px 4px 2px 0;
        border-radius: 12px; background: rgba(24, 95, 165, 0.08);
        color: {ACENTO_OSCURO}; font-family: 'DM Sans', sans-serif; font-size: 12px;
    }}
    .seccion {{
        display: flex; align-items: center; gap: 12px; margin: 4px 0 18px 0;
    }}
    .seccion .barra {{
        width: 3px; height: 30px; background: {ACENTO}; border-radius: 2px; flex-shrink: 0;
    }}
    .seccion .titulo {{
        font-family: 'Playfair Display', serif; font-size: 26px; font-weight: 500;
        color: var(--text-color); line-height: 1.1;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# Barra lateral
# =============================================================================

def _cargar_asignaturas() -> list[str]:
    conn = db.get_connection(RUTA_DB)
    try:
        filas = conn.execute("SELECT nombre FROM asignaturas ORDER BY id").fetchall()
    finally:
        conn.close()
    return [f["nombre"] for f in filas]


with st.sidebar:
    st.markdown(
        """
        <div class="marca">
            <div class="icono"></div>
            <div><div class="nombre">Pipeline</div><div class="sub">TFG</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    asignaturas = _cargar_asignaturas()
    if asignaturas:
        st.selectbox("Asignatura", asignaturas, key="asignatura_actual")
    else:
        st.caption("No hay asignaturas en la base de datos.")

    st.divider()

    if "vista_actual" not in st.session_state:
        st.session_state["vista_actual"] = VISTAS[0]

    vista = st.radio(
        "Navegación",
        VISTAS,
        key="vista_actual",
        label_visibility="collapsed",
        format_func=lambda v: f"{ICONOS_VISTA.get(v, '·')} {v}",
    )


# =============================================================================
# Área principal — despacho de vistas
# =============================================================================

vista = st.session_state["vista_actual"]

st.markdown(
    f'<div class="seccion"><div class="barra"></div>'
    f'<div class="titulo">{TITULOS_SECCION[vista]}</div></div>',
    unsafe_allow_html=True,
)

if vista == "Resumen":
    _vista_resumen()
elif vista == "Organizador":
    _vista_organizador()
elif vista == "Contenido":
    _vista_contenido()
elif vista == "Presentación":
    _vista_presentacion()
elif vista == "Base de datos":
    _vista_base_datos()
else:
    st.info("Vista en construcción — se integra en el siguiente paso.")
