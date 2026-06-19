# Handoff: Suite Docente IA — rediseño de UI

## Overview
Suite de tres agentes de IA para que profesores universitarios de ingeniería preparen material docente a partir de PDFs/PPTX de teoría. El flujo es lineal y supervisado:

1. **Organizador** — extrae la distribución temática (bloques, horas, subtemas) de la guía docente.
2. **Contenido** — cura el material de cada bloque en Markdown estructurado, que el profesor revisa y aprueba.
3. **Presentación** — taller iterativo donde el profesor genera visualizaciones interactivas (Chart.js + MathJax) y las ancla a secciones del Markdown.

Este paquete documenta el **rediseño visual** de la interfaz. La meta del trabajo es **recrear este diseño en la app Streamlit existente**, mejorando la experiencia sin cambiar la lógica ni el stack.

## ⚠️ Restricción de stack (IMPORTANTE)
La aplicación destino está hecha en **Python + Streamlit** y NO debe cambiarse de stack. El archivo HTML adjunto (`Suite Docente.dc.html`) es una **referencia de diseño** — un prototipo que muestra el aspecto y comportamiento deseados, **no código para copiar tal cual**. La tarea es reproducir ese diseño dentro de Streamlit usando sus mecanismos:

- **Tema** vía `.streamlit/config.toml`.
- **CSS global** inyectado con `st.markdown("<style>…</style>", unsafe_allow_html=True)`.
- **Maquetación** con `st.columns`, `st.container`, `st.tabs`, `st.expander`.
- **Componentes Streamlit nativos**: `st.data_editor` (tabla editable), `st.text_area`, `st.slider`, `st.selectbox`, `st.button`, `st.progress`, `st.metric`.
- **HTML embebido** con `st.components.v1.html(...)` para el preview del taller de visualización (es el propio HTML que genera el agente).
- Toda la lógica, navegación entre vistas y la BD **SQLite** existente se mantienen intactas. La navegación de vistas se gestiona con `st.session_state`.

## Fidelidad
**Alta fidelidad (hi-fi).** Colores, tipografía, espaciados y estados son finales. Reprodúcelos lo más fielmente que permita Streamlit. Donde Streamlit no llegue nativamente (ver "Limitaciones conocidas"), prioriza la jerarquía visual y el lenguaje de color de estado por encima del píxel exacto.

---

## Design Tokens

### Tipografía
- Familia: **DM Sans** (Google Fonts; pesos 400/500/600/700). Fallback: `system-ui, sans-serif`.
- Monoespaciada (fuente del editor Markdown): `'DM Mono', ui-monospace, Menlo, monospace`.
- Escala usada:
  - Título de asignatura (topbar): 20px / 600 / letter-spacing −0.02em
  - Título de sección (h2 vista): 15px / 600
  - Título de tarjeta: 12.5–13.5px / 600
  - Cuerpo: 12.5–13.5px / 400–500
  - Meta / etiquetas: 10.5–12px / 500
  - Etiquetas de sección (uppercase): 10–10.5px / 600 / letter-spacing 0.08–0.09em
  - KPI numérico: 26px / 700 / tabular-nums

### Colores — base
| Token | Hex | Uso |
|---|---|---|
| Fondo app | `#F1F4F8` | fondo del área principal |
| Superficie | `#FFFFFF` | tarjetas, paneles |
| Borde | `#E4E9F0` | bordes de tarjeta |
| Borde sutil / divisor | `#EEF1F6` / `#F2F5F8` | separadores de fila |
| Texto principal | `#16202E` | |
| Texto secundario | `#475667` | |
| Texto atenuado | `#6B7A8D` / `#8693A3` | metadatos |
| Acento institucional | `#185FA5` | primario, botones, líneas de datos |
| Acento oscuro | `#0C447C` | bordes de botón primario, títulos de énfasis |
| Sidebar (fondo) | `#0C2E54` | navy institucional |
| Sidebar activo | `#15406E` | item/tarjeta seleccionada |
| Sidebar acento | `#185FA5` / `#3D8BD4` | badges, barra de progreso |
| Sidebar texto | `#E7EEF6` (claro) / `#A9BACE` / `#7E93AE` (atenuado) | |

### Colores — lenguaje de estado (crítico, usar en todos los badges/puntos)
| Estado | Texto | Fondo (badge) | Punto |
|---|---|---|---|
| Pendiente | `#64748B` | `#EDF1F6` | `#94A3B8` |
| Generado / Borrador IA | `#185FA5` | `#E7F0FA` | `#185FA5` |
| Editado | `#9A6608` | `#FBF1DD` | `#D6960F` |
| Aprobado | `#2E815A` | `#E3F1EA` | `#2E815A` |

Flujo de estado por bloque: **pendiente → generado → editado → aprobado**.

### Espaciado, radios, sombras
- Radio de tarjeta: 12px. Radio de botón/input: 8–9px. Chip/pill: 16–20px. Badge numérico de bloque: 6–7px.
- Padding de tarjeta: 16–20px. Padding de vista (área principal): 24–28px arriba/abajo, 36px laterales. Ancho máx. de contenido: 1240px centrado.
- Gap entre tarjetas/columnas: 14–18px.
- Sombra: muy sutil; `0 1px 2px rgba(16,32,46,.04–.12)` solo donde haga falta elevación (ej. pestaña activa). El diseño se apoya en bordes 1px, no en sombras.
- Altura de botón: 34–42px. Altura de chip: 30–34px.

### config.toml sugerido
```toml
[theme]
primaryColor = "#185FA5"
backgroundColor = "#F1F4F8"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#16202E"
font = "sans serif"
```

---

## Layout general (app shell)
Dos columnas a pantalla completa (`height: 100vh`):
- **Sidebar** fija, 272px, fondo navy `#0C2E54`, en flex-column. En Streamlit = `st.sidebar` con CSS para el color de fondo y texto.
- **Main** scrollable, fondo `#F1F4F8`, con una **topbar sticky** arriba y el contenido de la vista debajo.

### Sidebar (de arriba a abajo)
1. **Cabecera**: cuadrado 36×36 radio 9px fondo `#185FA5` con "SD" en blanco 700 + bloque de texto "Suite Docente IA" (14/600) y "U. de Oviedo · EPI Gijón" (11px `#93A6C0`). Borde inferior `rgba(255,255,255,.09)`.
2. **"ASIGNATURAS"** (etiqueta uppercase atenuada). Una tarjeta-botón por asignatura:
   - Título (12.5/600) + % de progreso a la derecha (10.5px atenuado).
   - Barra de progreso fina (4px, fondo `rgba(255,255,255,.13)`, relleno `#3D8BD4` o `#3FAE6B` si 100%) + curso a la derecha (10px).
   - Activa: fondo `#15406E` + barra-acento izquierda `inset 3px 0 0 #3D8BD4`.
3. Divisor.
4. **"NAVEGACIÓN"**: items planos (Resumen, Inputs) — punto + label. Activo: fondo `#15406E`, texto `#E7EEF6`, peso 600.
5. **"PIPELINE DOCENTE"**: los 3 agentes como pasos numerados (badge 24×24 radio 7px). Cada item: nº + título (12.5/600) + subtítulo de estado (10.5px) — ej. "Confirmado", "1/6 aprobados", "5 visualizaciones". Activo: badge `#185FA5` blanco, fondo `#15406E`.
6. **Pie**: avatar circular 28px + "Prof. J. Martínez" / "Dpto. Ciencia de Materiales".

### Topbar (sticky, dentro de Main)
Fila con `justify-content: space-between`, fondo `rgba(241,244,248,.9)` + `backdrop-filter: blur(10px)`, borde inferior `#E1E7EF`, padding 14px/36px.
- **Izquierda**: curso·código (11px atenuado) + título de asignatura (20/600, con ellipsis si no cabe).
- **Derecha**: barra de progreso global (84px) + % en `#0C447C` 700; luego los dos botones de export (ver Interacciones → Export gating).

### Banner de pipeline (opcional, bajo la topbar)
Tarjeta horizontal con los 3 pasos (Organizador / Contenido / Presentación), cada uno badge numerado + título + subtítulo. El paso de la vista activa se resalta: fondo `#F2F7FC`, badge `#185FA5`, borde-izquierda `3px solid #185FA5`. Es un stepper contextual; clicable para navegar.

---

## Vistas

### 1. Resumen (Dashboard)
**Propósito**: lo primero que ve el profesor; orientación de qué falta.
**Layout**:
- Fila de 4 KPIs (`st.columns(4)` / tarjetas): "Bloques temáticos" (total), "Aprobados" (n de N, número en `#2E815A`), "Horas lectivas" (suma, "h"), "Visualizaciones" (total, número en `#185FA5`). Número 26/700 tabular + unidad atenuada.
- Encabezado "Mapa curricular" + "N bloques · estado por agente".
- **Tabla** (tarjeta con cabecera `#F7F9FC`): columnas `Bloque temático | Horas | Organizador | Contenido | Presentación | Estado`. Cada fila:
  - Bloque: badge nº (24×24, fondo `#EDF2F8`, texto `#0C447C`) + título + debajo "N subtemas".
  - Horas: "N h".
  - Organizador/Contenido/Presentación: punto de color + label de estado (usar tabla de estado). Organizador siempre "Confirmado" (verde). Contenido = estado del bloque. Presentación = "Sin generar" (gris) o "N viz." (azul).
  - Estado: badge-pill con color de estado.
  - Fila clicable → navega a Contenido de ese bloque.

### 2. Inputs
**Propósito**: documentos de origen por asignatura.
**Layout**: 2 columnas. Cada tarjeta = un grupo ("Guía docente", "Materiales de teoría") con contador de archivos. Cada archivo: etiqueta de tipo (PDF rojo `#FBE9E7`/`#C0392B`, PPTX naranja `#FDEFE0`/`#C0700E`, 30×36 radio 5px) + nombre + meta (tamaño · páginas/diapos). Botón inferior dashed "+ Añadir documento".

### 3. Organizador
**Propósito**: revisar/editar/aprobar la estructura curricular extraída por la IA.
**Layout**: encabezado + descripción. Una tarjeta por bloque:
- Cabecera `#F7F9FC`: badge nº (azul) + título (13.5/600) + "N h lectivas".
- Filas de subtema: botón-check (26×26; activo = fondo `#2E815A` con ✓ blanco; inactivo = borde gris, vacío) + texto del subtema (gris si desactivado) + botón ✕ a la derecha.
- Botón dashed "+ Añadir subtema" por bloque.
- Acciones finales: "Confirmar estructura curricular" (primario) + "+ Añadir bloque".
- **Implementación Streamlit**: lo ideal es `st.data_editor` por bloque, o filas con `st.columns` + `st.checkbox`/`st.button`. (Ver limitaciones.)

### 4. Contenido (vista central)
**Propósito**: revisar y aprobar el Markdown curado por bloque.
**Layout**:
- Fila de **chips de bloque** (scroll horizontal): "B{n} · {título}" + punto de estado. Activo: borde `#185FA5`, fondo `#EAF2FA`, texto `#0C447C`.
- Grid de 2 columnas (≈268px / resto):
  - **Izquierda — Cobertura curricular** (tarjeta sticky): título + descripción + barra de % (relleno `#2E815A`) + % a la derecha. Lista de apartados (del Organizador): cada uno con un cuadro-icono 16×16 según cobertura — `✓` (cubierto, verde `#E3F1EA`/`#2E815A`), `~` (parcial, ámbar `#FBF1DD`/`#9A6608`), `·` (pendiente, gris) — + texto.
  - **Derecha — Editor** (tarjeta):
    - Cabecera: `st.tabs(["Dividido", "Vista previa", "Markdown"])` (segmented) + badge **"Modificado X% vs. borrador IA"** (pill ámbar `#FBF1DD`/`#9A6608` con punto). El % es el diff respecto al borrador IA.
    - Cuerpo: en "Dividido" → izquierda `st.text_area` con el Markdown fuente (fuente mono), derecha Markdown renderizado (`st.markdown`). "Vista previa" = solo render. "Markdown" = solo fuente.
    - Footer: "Valoración" + `st.slider(1,10)` (accent `#185FA5`) + valor "X/10" en `#0C447C` 700; a la derecha botones "Regenerar con IA" (secundario) y **"Aprobar contenido"** (primario; al aprobar pasa a verde "✓ Aprobado X/10" y el estado del bloque → aprobado).

### 5. Presentación (Taller)
**Propósito**: generar/refinar visualizaciones interactivas y anclarlas a secciones.
**Layout**:
- Misma fila de chips de bloque.
- Grid 2 columnas (resto / 300px):
  - **Izquierda (preview amplio + composer)**:
    - Tarjeta de preview: barra tipo "ventana" (3 puntos rojo/ámbar/verde + "preview · visualización interactiva" + etiqueta "Chart.js + MathJax"). Cuerpo = la visualización embebida con `st.components.v1.html(html_aprobado, height=...)`. En el prototipo es una curva tensión–deformación con un `slider` de fuerza que mueve un punto sobre la curva y muestra σ en MPa y la zona (elástica/fluencia/resistencia máx./estricción).
    - **Composer** (tarjeta, accesible sin scroll, justo bajo el preview): fila de chips de refinado ("Añadir anotaciones", "Cambiar a escala log", "Resaltar límite elástico", "Tema institucional") + `st.text_area` de prompt + botones "Refinar →" (secundario) y **"Aprobar y anclar"** (primario) + `st.selectbox` "Ancla:" con las secciones del Markdown.
  - **Derecha (rail sticky)**: tarjeta "Visualizaciones ancladas" (miniatura + título + "↳ {sección}"), tarjeta "Iteraciones" (historial numerado; la actual resaltada en `#185FA5`), y botón "Exportar presentación del bloque".

---

## Interacciones & comportamiento
- **Navegación de vistas**: sidebar + banner cambian `st.session_state["view"]`. La vista activa se resalta (fondo `#15406E` en sidebar; borde-izquierda azul en banner).
- **Selección de asignatura**: cambia `session_state["asignatura"]`, recarga bloques y reinicia el bloque seleccionado al primero.
- **Selección de bloque**: chips en Contenido/Presentación; clic en fila del Resumen lleva a Contenido de ese bloque.
- **Toggle de subtema** (Organizador): alterna aprobado/no aprobado (✓ verde ↔ vacío).
- **Slider de valoración** (Contenido): 1–10; el valor se muestra en vivo.
- **Aprobar contenido**: marca el bloque como aprobado; el botón pasa a verde "✓ Aprobado X/10" y el estado se propaga al Resumen y a los contadores del pipeline.
- **Slider de fuerza** (Presentación): mueve el marcador sobre la curva y actualiza σ y la zona en vivo.
- **Enviar prompt / Refinar**: añade una iteración al historial (la nueva pasa a ser la "actual").
- **Export gating (topbar)** — comportamiento confirmado con el usuario:
  - Mientras NO todos los bloques estén aprobados: botones "Presentación HTML" y "Descargar PDF" **deshabilitados** (gris: borde `#E2E7EE`/`#D7DEE7`, fondo `#fff`/`#EAEEF3`, texto `#AEB8C4`, cursor not-allowed) + indicador "n/total aprobados" con punto gris `#9AA7B6`.
  - Al llegar a 100%: botones **activos** ("Descargar PDF" = primario azul, "Presentación HTML" = secundario) + indicador "Listo para exportar" en verde `#2E815A`.
  - En Streamlit: `st.button(..., disabled=not export_ready)`.

## State management
Variables en `st.session_state`:
- `view`: "resumen" | "inputs" | "organizador" | "contenido" | "presentacion"
- `asignatura_id`, `bloque_id`
- `markdown_view`: "dividido" | "previsualizacion" | "edicion" (pestaña del editor)
- `valoracion` (1–10), `fuerza` (0–100, demo), `prompt`
- Estado/aprobaciones por bloque y subtemas activos → ya en SQLite (tablas `temas`, `subbloques`, `contenido_tema`, `visualizacion_interactiva`).
- `export_ready` = (bloques_aprobados == total_bloques and total > 0), derivado de la BD.

## Limitaciones conocidas en Streamlit (y cómo abordarlas)
- **Tabla editable del Organizador** con botones ✓/✕ estilizados: `st.data_editor` da la edición pero no ese look exacto. Alternativas: (a) `st.data_editor` aceptando el estilo nativo, (b) filas con `st.columns` + `st.checkbox`/`st.button`, o (c) un componente custom HTML/JS si se quiere fidelidad total.
- **Sticky/columnas anidadas y backdrop-blur**: requieren CSS inyectado; la topbar sticky y el blur pueden simplificarse si dan problemas.
- **Chips con scroll horizontal**: vía CSS sobre un contenedor de `st.columns` o HTML inyectado; si no, usar `st.radio` horizontal estilizado.
- Prioriza siempre: jerarquía, lenguaje de color de estado, y que el pipeline Organizador→Contenido→Presentación sea el eje visual.

## Idioma
Toda la interfaz en **español**. Tono sobrio e institucional (Universidad de Oviedo, EPI Gijón) — no estilo startup/SaaS.

## Files
- `Suite Docente.dc.html` — prototipo de referencia hi-fi con las 5 vistas, navegación y micro-interacciones. Ábrelo en un navegador para ver el comportamiento exacto (estados, sliders, gating de export, toggles). Es una referencia de diseño; la implementación va en Streamlit.
