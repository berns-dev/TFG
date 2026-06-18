# Base de datos — Estado del módulo

**Monorepo:** `berns-dev/TFG`
**Última actualización:** 2026-06-18

---

## Propósito

Capa de persistencia transversal a los tres agentes. Almacena la jerarquía curricular,
el contenido curado por bloque, las visualizaciones interactivas aprobadas y el progreso
(calculado en tiempo real, nunca almacenado como campo).

---

## Motor y ubicación

- **Motor:** SQLite (`sqlite3` stdlib)
- **Archivo:** `data/tfg.db` (generado, `.gitignore`)
- **Código:** `database/db.py`
- **Versión de esquema:** `user_version = 7` (`VERSION_SCHEMA = 7`)

---

## Esquema — tablas clave (v7)

### Jerarquía curricular (Organizador)

```
asignaturas → temas (bloques) → subbloques (apartados / checklist)
```

Los `subbloques` siguen generándose al confirmar la organización. En Contenido sirven
como **guía de cobertura**, no como unidad de almacenamiento del markdown curado.

### Contenido curado por bloque (v7)

```
contenido_tema(tema_id UNIQUE, markdown_borrador, markdown_final,
               porcentaje_editado, puntuacion_profesor, estado, ...)
```

Ciclo de vida: `pendiente` → `generado` → `editado` → `aprobado`

**Progreso:** un bloque cuenta como aprobado si `contenido_tema.estado = 'aprobado'`.

### Visualizaciones interactivas (v7)

```
visualizacion_interactiva(tema_id, titulo, prompt_inicial, historial_json,
                          html_fragment, seccion_ancla, estado, orden, ...)
```

Estados: `borrador` | `aprobado`. Solo las aprobadas entran en el HTML final.

### Legado (sin uso en UI actual)

- `contenido_subbloque` — markdown por subtema (v1–v6)
- `presentacion_subbloque`, `parametros_subbloque` — chips de patrón por subtema

---

## Migraciones

| Versión | Cambio principal |
|---------|------------------|
| v6 | UNIQUE en inputs; deduplicación |
| **v7** | `contenido_tema`, `visualizacion_interactiva`; progreso por bloque |

```bash
py -3 database/db.py
py -3 database/validar_esquema.py
```

---

## API pública (v7)

### Contenido

```python
db.get_contenido_tema(tema_id)
db.upsert_contenido_tema_borrador(tema_id, markdown)
db.guardar_contenido_tema_edicion(tema_id, markdown, pct_editado)
db.aprobar_contenido_tema(tema_id, markdown, pct, puntuacion)
```

### Presentación

```python
db.listar_visualizaciones_tema(tema_id)
db.insertar_visualizacion_borrador(...)
db.actualizar_visualizacion_borrador(...)
db.aprobar_visualizacion(viz_id, seccion_ancla)
db.listar_visualizaciones_aprobadas(tema_id)
```

### Progreso

```python
db.get_progreso_bloque(tema_id)      # total=1, aprobados 0|1
db.get_progreso_asignatura(asig_id)  # bloques aprobados / total bloques
db.get_desglose_progreso_asignatura(asig_id)
```

### Valoración

| Agente | Almacén | Granularidad |
|--------|---------|--------------|
| Organizador | `valoraciones_profesor` | Global por asignatura |
| Contenido | `contenido_tema.puntuacion_profesor` | Por bloque |

---

## Cómo escriben los agentes (app-unificada)

**Organizador:** `_db_confirmar_organizacion` → `temas` + `subbloques`

**Contenido:** `upsert_contenido_tema_borrador` → edición → `aprobar_contenido_tema`

**Presentación:** taller → `insertar/actualizar_visualizacion_borrador` → `aprobar_visualizacion`

---

## Invariantes

1. Progreso siempre calculado al consultar.
2. Un markdown curado por bloque (`contenido_tema`), no por subtema.
3. Visualizaciones aprobadas llevan `seccion_ancla` para el ensamblaje HTML.
4. `tiene_interactivo` (tabla legada) no afecta al progreso.
