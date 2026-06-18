# Base de datos — Estado del módulo

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-18

---

## Propósito

Capa de persistencia transversal a los tres agentes (Organizador, Contenido, Presentación).
Almacena la jerarquía curricular, el estado del ciclo de vida de cada subbloque y los
metadatos necesarios para calcular el progreso en tiempo real. No almacena el porcentaje
de progreso como campo — siempre se calcula al consultar para evitar inconsistencias.

---

## Motor y ubicación

- **Motor:** SQLite (`sqlite3` de stdlib — sin dependencias externas)
- **Archivo:** `data/tfg.db` (generado, no versionado — está en `.gitignore`)
- **Código:** `database/db.py`
- **Versión de esquema actual:** `user_version = 6` (ver `VERSION_SCHEMA` en `db.py`)

---

## Esquema — tablas y columnas clave

*(Resumen; el esquema completo y migraciones están en `db.py`.)*

### Jerarquía curricular

```
asignaturas(id, nombre)
    └── temas(id, asignatura_id, organizador_output_id, nombre, horas, bloque, orden)
            └── subbloques(id, tema_id, nombre, orden, horas, evidencia, origen, es_fallback)
```

**`subbloques` — columnas v2:**
- `horas REAL` — horas asignadas al subbloque (del output del Organizador)
- `evidencia TEXT` — referencia estructural que justifica el subbloque: "Sección 3.2",
  "Slide 5", "Sin señal verificable" (caso fallback), o "" (añadido manualmente)
- `origen TEXT` — "Detectado", "Manual (profesor)", "Guía docente", "Fallback"
- `es_fallback INTEGER (0/1)` — 1 si el bloque no tenía señales estructurales y el
  subbloque es el propio bloque completo (decisión del Organizador, no inventada)

### Estado del contenido curado

```
contenido_subbloque(id, subbloque_id, markdown_borrador, markdown_final,
                    porcentaje_editado, puntuacion_profesor, estado, fecha_actualizacion)
```

**Ciclo de vida del campo `estado`:**
```
pendiente → generado → aprobado
               ↓           ↑
            editado ────────┘
```

- `pendiente` — sin borrador; la API no ha generado nada todavía
- `generado` — la API produjo un borrador; pendiente de revisión del profesor
- `editado` — el profesor modificó el Markdown (porcentaje_editado > 0)
- `aprobado` — el profesor aceptó el contenido (sin o con ediciones previas)
- `puntuacion_profesor INTEGER (1-10)` — v4: nota del profesor al confirmar el sub-bloque.
  **Solo Contenido (y Presentación en el futuro).** No confundir con `valoraciones_profesor`.

El progreso se calcula exclusivamente sobre `estado = 'aprobado'`.

### Valoración del profesor — granularidad por agente

La puntuación 1-10 **no** usa el mismo almacén en todos los agentes. Es intencional:

| Agente | Dónde vive la nota | Granularidad |
|--------|-------------------|--------------|
| Organizador | `valoraciones_profesor` (`UNIQUE(asignatura_id, agente)`) | Global por asignatura — la organización se evalúa como conjunto curricular |
| Contenido | `contenido_subbloque.puntuacion_profesor` | Por sub-bloque — cada pieza de Markdown se revisa y puntúa de forma independiente |
| Presentación (futuro) | Por sub-bloque (mismo patrón que Contenido) | Por sub-bloque — cada pieza de presentación es independiente |

**No unificar** estas dos tablas/columnas sin decisión explícita de diseño: el Organizador
sigue usando `valoraciones_profesor`; Contenido **no** escribe en esa tabla.

### Contenido interactivo

```
presentacion_subbloque(id, subbloque_id, patron_visualizacion, elegido_por_profesor,
                       html_path, tiene_interactivo, fecha_generacion)
```

- `tiene_interactivo INTEGER (0/1)` — v2: 1 si hay un HTML interactivo generado
- `html_path TEXT` — ruta relativa al HTML interactivo (si lo hay)
- **El campo `tiene_interactivo` NO entra en el cálculo de progreso.** Es informativo.

---

## Migraciones

El módulo usa `PRAGMA user_version` para versionar el esquema. La función `init_db()`
aplica automáticamente las migraciones pendientes al arrancar la app.

Versiones:
- `v1` (implícita) — esquema inicial sin horas/evidencia/estado/interactivo
- `v2` — añade columnas mediante `ALTER TABLE ADD COLUMN`; sentencias idempotentes
- `v3` — tabla `valoraciones_profesor` (nota global Organizador/Presentación/Contenido a nivel asignatura; en la práctica solo la usa Organizador)
- `v4` (actual) — columna `puntuacion_profesor` en `contenido_subbloque`

Para forzar una migración en caliente sobre una BD existente:
```bash
py -3 database/db.py
```

---

## API pública del módulo

### Inicialización

```python
from database import db

db.init_db(ruta)            # crea/migra la BD; devuelve VERSION_SCHEMA
db.seed_asignaturas(ruta)   # inserta las tres asignaturas conocidas (idempotente)
db.get_connection(ruta)     # conexión sqlite3 con row_factory y FK activadas
```

### Estado del ciclo de vida

```python
db.upsert_estado_subbloque(subbloque_id, estado, markdown=None, ruta=...)
# estado in {'pendiente', 'generado', 'editado', 'aprobado'}

db.get_estado_subbloque(subbloque_id, ruta=...)
# -> str — estado actual ('pendiente' si no hay fila)
```

### Progreso (calculado en tiempo real, nunca almacenado)

```python
db.get_progreso_bloque(tema_id, ruta=...)
# -> {"total": int, "aprobados": int, "porcentaje": float}

db.get_progreso_asignatura(asignatura_id, ruta=...)
# -> {"total": int, "aprobados": int, "porcentaje": float}

db.get_desglose_progreso_asignatura(asignatura_id, ruta=...)
# -> list[dict] con {tema_id, nombre, horas, total_sub, aprobados, porcentaje}
```

### Contenido interactivo

```python
db.set_interactivo_subbloque(subbloque_id, html_path=None, ruta=...)
# tiene_interactivo = 1 si html_path no es None ni vacío; no altera progreso
```

---

## Cómo leen y escriben los agentes

### Agente Organizador (app-unificada/app.py)

- Al confirmar la organización: `_db_confirmar_organizacion(asignatura_id, output_id, bloques)`
  - Borra temas/subbloques anteriores de la asignatura
  - Inserta los nuevos con `horas`, `evidencia`, `origen`, `es_fallback` desde el output del Organizador
- Esta operación solo puede hacerse mientras la organización está en fase `resultado` o anterior
  (no después de `cerrado`). El schema no impone este bloqueo — lo gestiona la UI.

### Agente Contenido (app-unificada/app.py)

- Al generar borrador: `_db_cnt_upsert_borrador(subbloque_id, markdown)` → estado `generado`
  (solo sub-bloques sin borrador previo; el profesor elige cuáles con checkboxes)
- Al guardar (profesor edita): `_db_cnt_guardar_final(subbloque_id, markdown, pct_editado)`
  - `pct_editado == 0` → estado `aprobado`
  - `pct_editado > 0` → estado `editado`
- Al confirmar: `_db_cnt_aprobar_subbloque(subbloque_id, puntuacion)` → estado `aprobado`
  y `puntuacion_profesor` en la fila del sub-bloque
- **No usa** `valoraciones_profesor` — ver sección «Valoración del profesor» arriba

### Agente Presentación (app-unificada/app.py)

- Al generar HTML interactivo: `_db_prs_update_html_path(subbloque_id, html_path)`
- Para marcar `tiene_interactivo`: `db.set_interactivo_subbloque(subbloque_id, html_path)`

---

## Invariantes de diseño

1. **Progreso nunca almacenado.** El porcentaje se calcula al consultar. Nunca se persiste
   un campo `progreso` o `porcentaje` como columna calculada.

2. **Estructura congelada tras la fase de Contenido.** Una vez que el Organizador marca la
   organización como cerrada (`fase = 'cerrado'`), la jerarquía temas/subbloques no cambia.
   El esquema no tiene lógica para reconciliar cambios estructurales con contenido ya aprobado —
   ese caso está descartado por diseño.

3. **Fallback es el caso general.** Un bloque con un único subbloque (fallback del Organizador)
   se trata exactamente igual que un bloque con varios subbloques. El denominador del progreso
   es la suma de todos los subbloques sin distinción. No hay tratamiento especial.

4. **`tiene_interactivo` es informativo.** El campo indica si el Agente Presentación generó
   un HTML interactivo para el subbloque. No entra en ningún cálculo de progreso ni bloquea
   transiciones de estado.

---

## Validación

El script `database/validar_esquema.py` simula:
1. Carga de una asignatura completa (Tecnología de Materiales — 4 bloques, 9 subbloques)
2. Progreso inicial = 0%
3. Aprobación parcial + verificación por bloque
4. Bloque fallback con 1 único subbloque (100% al aprobar ese único subbloque)
5. Marcado de interactivo sin alterar progreso
6. Aprobación total → 100%
7. Desglose por bloque

Ejecutar: `py -3 database/validar_esquema.py` desde `TFG/TFG/`.
