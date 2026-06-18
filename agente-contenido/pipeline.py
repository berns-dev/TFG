"""Pipeline puro: chunk → classify (parallel) → assemble → validate.

Fuente única de la lógica de orquestación compartida entre
agente-contenido/app.py (standalone) y app-unificada/app.py.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from assembler import assemble_markdown, assemble_subbloque_body
from chunker import split_into_chunks
from classifier import classify_and_format
from cnt_config import MAX_WORKERS
from validator import validate_items


def procesar_segmento(
    seg_text: str,
    nombre_subbloque: str,
    nombre_archivo: str,
    horas: float | None,
    contexto_prefix: str = "",
    max_workers: int | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Chunk → classify en paralelo → assemble body → validate.

    Args:
        seg_text: Texto extraído del segmento a procesar.
        nombre_subbloque: Nombre del subbloque; se convierte en H1 del cuerpo.
        nombre_archivo: Nombre de archivo para el assembler (contexto frontmatter).
        horas: Horas lectivas para calibrar densidad en el classifier (None = sin pista).
        contexto_prefix: Si no es vacío, se añade como prefijo de cada chunk antes de
            clasificar. No se incluye en los chunks que se pasan al validator.
        max_workers: Tamaño del pool; por defecto usa config.MAX_WORKERS.

    Returns:
        (items, markdown_body, validacion)
        - items: lista de dicts clasificados (solo chunks que no fallaron)
        - markdown_body: cuerpo del subbloque sin frontmatter YAML, con H1
        - validacion: reporte de validate_items()

    Si seg_text no produce chunks, devuelve estructuras vacías sin llamar a la API.
    """
    if max_workers is None:
        max_workers = MAX_WORKERS

    chunks = split_into_chunks(seg_text)
    if not chunks:
        return [], "", {"ok": True, "errores": [], "fidelity": []}

    chunks_to_classify = [contexto_prefix + c for c in chunks] if contexto_prefix else chunks

    ordered: list[dict[str, Any] | None] = [None] * len(chunks_to_classify)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_i = {
            pool.submit(classify_and_format, chunk, None): i
            for i, chunk in enumerate(chunks_to_classify)
        }
        for fut in as_completed(future_to_i):
            ordered[future_to_i[fut]] = fut.result()

    items: list[dict[str, Any]] = []
    chunks_raw: list[str] = []
    for chunk_raw, item in zip(chunks, ordered):
        if item is not None:
            items.append(item)
            chunks_raw.append(chunk_raw)

    if not items:
        return [], "", {"ok": True, "errores": [], "fidelity": []}

    markdown_body = assemble_subbloque_body(
        items, nombre_subbloque=nombre_subbloque, nombre_del_archivo=nombre_archivo
    )
    validacion = validate_items(items, original_chunks=chunks_raw)
    return items, markdown_body, validacion


def procesar_bloque(
    texto: str,
    nombre_bloque: str,
    nombre_archivo: str,
    horas: float | None,
    max_workers: int | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Curado de un bloque temático completo → un único markdown con frontmatter.

    Extrae y estructura el material original sin calibrar extensión por horas.
    """
    if max_workers is None:
        max_workers = MAX_WORKERS

    chunks = split_into_chunks(texto)
    if not chunks:
        return [], "", {"ok": True, "errores": [], "fidelity": []}

    ordered: list[dict[str, Any] | None] = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_i = {
            pool.submit(classify_and_format, chunk, None): i
            for i, chunk in enumerate(chunks)
        }
        for fut in as_completed(future_to_i):
            ordered[future_to_i[fut]] = fut.result()

    items: list[dict[str, Any]] = []
    chunks_raw: list[str] = []
    for chunk_raw, item in zip(chunks, ordered):
        if item is not None:
            items.append(item)
            chunks_raw.append(chunk_raw)

    if not items:
        return [], "", {"ok": True, "errores": [], "fidelity": []}

    markdown = assemble_markdown(items, nombre_del_archivo=nombre_archivo)
    if nombre_bloque and "tema_detectado: No detectado" in markdown:
        markdown = markdown.replace(
            "tema_detectado: No detectado",
            f"tema_detectado: {nombre_bloque}",
        )
    validacion = validate_items(items, original_chunks=chunks_raw)
    return items, markdown, validacion
