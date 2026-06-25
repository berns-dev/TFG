"""Pipeline puro: chunk → classify (parallel) → assemble → validate.

Lógica de orquestación del Agente Contenido, importada por app-unificada/app.py.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from assembler import assemble_markdown, assemble_subbloque_body
from chunker import split_into_chunks
from classifier import classify_and_format
from cnt_config import MAX_WORKERS
from validator import validate_items


def _classify_chunks_parallel(
    chunks: list[str],
    max_workers: int,
) -> tuple[list[dict[str, Any] | None], list[str]]:
    """Clasifica chunks en paralelo; un fallo no aborta el resto."""
    ordered: list[dict[str, Any] | None] = [None] * len(chunks)
    errores: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_i = {
            pool.submit(classify_and_format, chunk, None): i
            for i, chunk in enumerate(chunks)
        }
        for fut in as_completed(future_to_i):
            idx = future_to_i[fut]
            try:
                ordered[idx] = fut.result()
            except Exception as exc:
                errores.append(f"Fragmento {idx + 1}/{len(chunks)}: {exc}")
    return ordered, errores


def procesar_segmento(
    seg_text: str,
    nombre_subbloque: str,
    nombre_archivo: str,
    horas: float | None,
    contexto_prefix: str = "",
    max_workers: int | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Chunk → classify en paralelo → assemble body → validate."""
    if max_workers is None:
        max_workers = MAX_WORKERS

    chunks = split_into_chunks(seg_text)
    if not chunks:
        return [], "", {
            "ok": False,
            "errores": ["No se generaron fragmentos a partir del texto extraído."],
            "fidelity": [],
        }

    chunks_to_classify = [contexto_prefix + c for c in chunks] if contexto_prefix else chunks
    ordered, errores_chunk = _classify_chunks_parallel(chunks_to_classify, max_workers)

    items: list[dict[str, Any]] = []
    chunks_raw: list[str] = []
    for chunk_raw, item in zip(chunks, ordered):
        if item is not None:
            items.append(item)
            chunks_raw.append(chunk_raw)

    if not items:
        errores = errores_chunk or ["Ningún fragmento se clasificó correctamente."]
        return [], "", {
            "ok": False,
            "errores": errores,
            "fidelity": [],
        }

    markdown_body = assemble_subbloque_body(
        items, nombre_subbloque=nombre_subbloque, nombre_del_archivo=nombre_archivo
    )
    validacion = validate_items(items, original_chunks=chunks_raw)
    if errores_chunk:
        validacion["errores"] = list(validacion.get("errores", [])) + errores_chunk
        validacion["ok"] = False
    return items, markdown_body, validacion


def procesar_bloque(
    texto: str,
    nombre_bloque: str,
    nombre_archivo: str,
    horas: float | None,
    max_workers: int | None = None,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Curado de un bloque temático completo → un único markdown con frontmatter."""
    if max_workers is None:
        max_workers = MAX_WORKERS

    chunks = split_into_chunks(texto)
    if not chunks:
        return [], "", {
            "ok": False,
            "errores": ["No se generaron fragmentos a partir del texto extraído."],
            "fidelity": [],
        }

    ordered, errores_chunk = _classify_chunks_parallel(chunks, max_workers)

    items: list[dict[str, Any]] = []
    chunks_raw: list[str] = []
    for chunk_raw, item in zip(chunks, ordered):
        if item is not None:
            items.append(item)
            chunks_raw.append(chunk_raw)

    if not items:
        errores = errores_chunk or ["Ningún fragmento se clasificó correctamente."]
        return [], "", {
            "ok": False,
            "errores": errores,
            "fidelity": [],
        }

    markdown = assemble_markdown(items, nombre_del_archivo=nombre_archivo)
    if nombre_bloque and "tema_detectado: No detectado" in markdown:
        markdown = markdown.replace(
            "tema_detectado: No detectado",
            f"tema_detectado: {nombre_bloque}",
        )
    validacion = validate_items(items, original_chunks=chunks_raw)
    if errores_chunk:
        validacion["errores"] = list(validacion.get("errores", [])) + errores_chunk
        validacion["ok"] = False
    return items, markdown, validacion
