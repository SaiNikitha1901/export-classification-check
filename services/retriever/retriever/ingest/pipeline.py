"""Idempotent ingestion pipeline (D2, L1): parse -> chunks.jsonl -> embed -> Chroma collection -> manifest.

* Chunk IDs are hashes of (doc_id, doc_version, clause_id, text), so re-running `build` on the same corpus
  embeds nothing and leaves the index (and built_at) unchanged.
* A changed document only changes its own chunk IDs; only those are embedded, and stale IDs are deleted.
* Each embedding model has its own Chroma collection. `reembed --model X` fills a new collection next to the
  old one from the stored chunks.jsonl (no re-parsing), then switches `active.json` atomically.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from retriever.config import Settings
from retriever.ingest.parsers import Chunk, parse_corpus

log = logging.getLogger("ingest")
BATCH = 64
# Telemetry is off (ANONYMIZED_TELEMETRY=False), but chromadb 0.5.x still calls posthog and logs a harmless
# signature error at ERROR level on every client start. Silence that logger so real errors stay visible.
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)


def collection_name(model: str, chunking: str = "structure") -> str:
    """Chroma names: 3-63 chars, alphanumeric at both ends. A short hash keeps long model names distinct."""
    import hashlib

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model.split("/")[-1]).lower()[:32].strip("-")
    h = hashlib.sha256(model.encode("utf-8")).hexdigest()[:8]
    base = f"chunks-{slug}-{h}"
    return base if chunking == "structure" else f"{base}-{chunking}"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def write_chunks(path: Path, chunks: list[Chunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".chunks.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_json(), ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def read_chunks(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def chroma_metadata(c: dict) -> dict:
    """Chroma metadata values must be str/int/float/bool (no None, no nested objects)."""
    keys = ("passage_id", "clause_id", "kind", "section", "chapter", "heading", "title", "doc_id", "doc_version",
            "page")
    return {k: ("" if c.get(k) is None else c[k]) for k in keys}


def embeddings_for(model: str, cache_dir: Optional[Path] = None):
    from langchain_huggingface import HuggingFaceEmbeddings

    kwargs = {"device": "cpu"}
    return HuggingFaceEmbeddings(model_name=model, model_kwargs=kwargs,
                                 encode_kwargs={"normalize_embeddings": True},
                                 cache_folder=str(cache_dir) if cache_dir else None)


def vector_store(settings: Settings, collection: str, embeddings):
    from langchain_chroma import Chroma

    return Chroma(collection_name=collection, embedding_function=embeddings,
                  persist_directory=str(settings.chroma_dir), collection_metadata={"hnsw:space": "cosine"})


def sync_collection(settings: Settings, collection: str, model: str, chunks: list[dict]) -> dict:
    """Make `collection` hold exactly `chunks`. Embeds only the chunk IDs it does not already have."""
    store = vector_store(settings, collection, embeddings_for(model, settings.index_dir / "hf_cache"))
    existing = set(store.get(include=[])["ids"])
    wanted = {c["passage_id"]: c for c in chunks}
    new_ids = [pid for pid in wanted if pid not in existing]
    stale = [pid for pid in existing if pid not in wanted]
    t0 = time.perf_counter()
    for i in range(0, len(new_ids), BATCH):
        batch = [wanted[pid] for pid in new_ids[i:i + BATCH]]
        store.add_texts(texts=[embed_text(c) for c in batch], metadatas=[chroma_metadata(c) for c in batch],
                        ids=[c["passage_id"] for c in batch])
    if stale:
        store.delete(ids=stale)
    embed_s = time.perf_counter() - t0
    return {"embedded": len(new_ids), "deleted": len(stale), "embed_seconds": round(embed_s, 3),
            "chunks_per_second": round(len(new_ids) / embed_s, 2) if new_ids and embed_s > 0 else None}


def embed_text(c: dict) -> str:
    """What the dense model sees: the title first (heading wording), then the passage."""
    title = c.get("title") or ""
    return f"{title}\n{c['text']}" if title and title not in c["text"] else c["text"]


def build(settings: Settings, model: Optional[str] = None, if_missing: bool = False) -> dict:
    model = model or settings.embed_model
    if not model:
        raise SystemExit("EMBED_MODEL is not set (see .env.example)")
    old = read_json(settings.manifest_path)
    if if_missing and old and settings.chunks_path.exists() and read_json(settings.active_path):
        log.info("index present; skipping build", extra={"event": "ingest_skip", "built_at": old.get("built_at")})
        return old

    t0 = time.perf_counter()
    if settings.chunking == "fixed":
        from retriever.ingest.fixed import fixed_chunks
        parsed, sources = fixed_chunks(settings.corpus_dir)
    else:
        parsed, sources = parse_corpus(settings.corpus_dir)
    chunks = [c.to_json() for c in parsed]
    parse_s = time.perf_counter() - t0

    collection = collection_name(model, settings.chunking)
    sync = sync_collection(settings, collection, model, chunks)

    ids_now = sorted(c["passage_id"] for c in chunks)
    ids_old = sorted(c["passage_id"] for c in read_chunks(settings.chunks_path)) if settings.chunks_path.exists() else None
    active_old = read_json(settings.active_path) or {}
    changed = ids_now != ids_old or active_old.get("collection") != collection
    if changed:
        write_chunks(settings.chunks_path, parsed)
    _atomic_write_json(settings.active_path, {"collection": collection, "embed_model": model,
                                              "chunking": settings.chunking,
                                              "switched_at": _now() if changed else active_old.get("switched_at")})
    duration = time.perf_counter() - t0
    kinds: dict[str, int] = {}
    for c in chunks:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    manifest = {
        "built_at": _now() if changed or not old else old["built_at"],
        "last_checked_at": _now(),
        "sources": [{"doc_id": s["doc_id"], "version": s["version"], "sha256": s["sha256"], "chunks": s["chunks"]}
                    for s in sources],
        "chunk_count": len(chunks),
        "chunks_by_kind": kinds,
        "embed_model": model,
        "collection": collection,
        "chunking": settings.chunking,
        "changed": changed,
        "embedded_chunks": sync["embedded"],
        "deleted_chunks": sync["deleted"],
        "parse_seconds": round(parse_s, 3),
        "embed_seconds": sync["embed_seconds"],
        "duration_seconds": round(duration, 3),
        # Throughput of the whole pipeline over all chunks (parse + embed), and of embedding alone.
        "chunks_per_second": round(len(chunks) / duration, 2) if duration > 0 else None,
        "embed_chunks_per_second": sync["chunks_per_second"],
    }
    if not changed and old:
        # Keep the throughput of the last real build; a no-op run says nothing about throughput.
        for k in ("chunks_per_second", "embed_chunks_per_second", "duration_seconds", "embed_seconds"):
            manifest[k] = old.get(k)
        manifest["noop_duration_seconds"] = round(duration, 3)
    _atomic_write_json(settings.manifest_path, manifest)
    log.info("build done", extra={"event": "ingest_build", **{k: manifest[k] for k in
             ("built_at", "chunk_count", "embedded_chunks", "deleted_chunks", "changed", "duration_seconds")}})
    return manifest


def reembed(settings: Settings, model: str) -> dict:
    """Embed the stored chunks with another model into a new collection, then switch atomically."""
    if not settings.chunks_path.exists():
        raise SystemExit("no chunks.jsonl yet; run `build` first")
    chunks = read_chunks(settings.chunks_path)
    active = read_json(settings.active_path) or {}
    chunking = active.get("chunking", settings.chunking)
    collection = collection_name(model, chunking)
    t0 = time.perf_counter()
    sync = sync_collection(settings, collection, model, chunks)
    _atomic_write_json(settings.active_path, {"collection": collection, "embed_model": model, "chunking": chunking,
                                              "switched_at": _now(), "previous": active.get("collection")})
    manifest = read_json(settings.manifest_path) or {}
    manifest.update({"built_at": _now(), "embed_model": model, "collection": collection,
                     "embedded_chunks": sync["embedded"], "embed_seconds": sync["embed_seconds"],
                     "embed_chunks_per_second": sync["chunks_per_second"],
                     "duration_seconds": round(time.perf_counter() - t0, 3),
                     "reembedded_from": active.get("collection")})
    _atomic_write_json(settings.manifest_path, manifest)
    log.info("reembed done", extra={"event": "ingest_reembed", "collection": collection,
                                    "previous": active.get("collection"), "embedded": sync["embedded"]})
    return manifest


def status(settings: Settings) -> dict:
    manifest = read_json(settings.manifest_path)
    active = read_json(settings.active_path)
    if not manifest or not active:
        return {"index": "missing", "index_dir": str(settings.index_dir)}
    import chromadb

    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    collections = {c.name: c.count() for c in (client.get_collection(n) for n in _collection_names(client))}
    return {"index": "present", "active": active, "collections": collections,
            **{k: manifest.get(k) for k in ("built_at", "last_checked_at", "chunk_count", "chunks_by_kind",
                                            "embed_model", "chunking", "duration_seconds", "chunks_per_second",
                                            "sources")}}


def _collection_names(client) -> list[str]:
    cols = client.list_collections()
    return [c if isinstance(c, str) else c.name for c in cols]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
