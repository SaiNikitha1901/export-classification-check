"""The loaded index: chunk store, BM25 keyword index, Chroma dense index (via LangChain), hybrid fusion,
and the metadata lookups behind /clause, /notes/applicable and /policy.

Why hybrid (spec §3): a dense embedding of "stainless steel vacuum flask" lands near the *material* headings
of Chapter 73. BM25 matches the literal article name, so heading 9617 ("VACUUM FLASKS…") ranks high on the
keyword side. Reciprocal-rank fusion keeps both signals.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from retriever import metrics
from retriever.cache import Cache, digest
from retriever.config import Settings
from retriever.ingest import pipeline

log = logging.getLogger("index")

PASSAGE_FIELDS = ("passage_id", "clause_id", "kind", "section", "chapter", "heading", "title", "text", "doc_id",
                  "doc_version", "page")
CHAPTER_SECTION = {"73": "XV", "96": "XX"}
RRF_K = 60
# Part of every search-cache key. Bump it whenever ranking code changes: the index built_at does not change
# then, so without this the cache would keep serving rankings from the old code (found in testing).
RANKER_VERSION = "2"
_STOP = set("a an and are as at be by for from in into is it its of on or other than that the their thereof "
            "these this to with without whether not".split())


def tokenize(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP:
            continue
        if len(w) > 3 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def keyword_text(c: dict) -> str:
    """What BM25 indexes. A tariff line counts only its *own* label: its stored text also repeats the heading
    wording and parent path (useful for reading and for the dense side), but for keyword scoring that would let
    five 9617 lines outrank heading 9617 itself on "vacuum flask"."""
    text = c["text"].split("\n", 1)[0] if c["kind"] == "tariff_line" else c["text"]
    compact = " ".join(x.replace(" ", "") for x in re.findall(r"\d{4} \d{2} \d{2}", text))
    title = None if c["kind"] == "tariff_line" else c.get("title")
    return " ".join(filter(None, [title, text, c["clause_id"], compact]))


def to_passage(c: dict, score: Optional[float] = None) -> dict:
    p = {k: c.get(k) for k in PASSAGE_FIELDS}
    p["score"] = None if score is None else round(float(score), 6)
    return p


def _note_order(c: dict) -> tuple:
    m = re.search(r"NOTE-(\d+)", c["clause_id"])
    return (0 if c["kind"] == "section_note" else 1, int(m.group(1)) if m else 0, c.get("meta", {}).get("part", 0))


@dataclass
class Loaded:
    chunks: list[dict]
    by_id: dict[str, dict]
    by_clause: dict[str, list[dict]]
    bm25: object
    store: object
    embeddings: object
    collection: str
    embed_model: str
    manifest: dict
    stamp: tuple


class Index:
    def __init__(self, settings: Settings, cache: Cache) -> None:
        self.settings = settings
        self.cache = cache
        self._lock = threading.Lock()
        self.data: Optional[Loaded] = None

    # ------------------------------------------------------------ loading

    def _stamp(self) -> tuple:
        s = self.settings
        return tuple(p.stat().st_mtime_ns if p.exists() else 0
                     for p in (s.active_path, s.manifest_path, s.chunks_path))

    def ensure_loaded(self) -> Optional[Loaded]:
        """Load on first use, and reload if `ingest build/reembed` changed the files (atomic switch)."""
        stamp = self._stamp()
        if self.data and self.data.stamp == stamp:
            return self.data
        with self._lock:
            if self.data and self.data.stamp == stamp:
                return self.data
            if 0 in stamp:
                return self.data
            self.data = self._load(stamp)
            return self.data

    def _load(self, stamp: tuple) -> Loaded:
        from rank_bm25 import BM25Okapi

        s = self.settings
        active = pipeline.read_json(s.active_path)
        manifest = pipeline.read_json(s.manifest_path) or {}
        chunks = pipeline.read_chunks(s.chunks_path)
        by_clause: dict[str, list[dict]] = {}
        for c in chunks:
            by_clause.setdefault(c["clause_id"], []).append(c)
        embeddings = pipeline.embeddings_for(active["embed_model"], s.index_dir / "hf_cache")
        store = pipeline.vector_store(s, active["collection"], embeddings)
        bm25 = BM25Okapi([tokenize(keyword_text(c)) for c in chunks])
        metrics.index_chunks.set(len(chunks))
        if manifest.get("built_at"):
            metrics.index_built.set(datetime.fromisoformat(manifest["built_at"]).timestamp())
        if manifest.get("chunks_per_second"):
            metrics.ingest_cps.set(manifest["chunks_per_second"])
        metrics.index_loaded.set(1)
        log.info("index loaded", extra={"event": "index_loaded", "collection": active["collection"],
                                        "chunks": len(chunks), "built_at": manifest.get("built_at")})
        return Loaded(chunks, {c["passage_id"]: c for c in chunks}, by_clause, bm25, store, embeddings,
                      active["collection"], active["embed_model"], manifest, stamp)

    # ------------------------------------------------------------ search

    def _embed_query(self, d: Loaded, query: str) -> list[float]:
        key = digest(d.embed_model, query)
        vec = self.cache.get("embedding", key)
        if vec is None:
            vec = d.embeddings.embed_query(query)
            self.cache.set("embedding", key, vec)
        return vec

    @staticmethod
    def _allowed(c: dict, kinds: Optional[list[str]], chapters: Optional[list[str]]) -> bool:
        if kinds and c["kind"] not in kinds:
            return False
        # Chapter-less passages (GRI, DGFT general notes) apply to every chapter, so a chapter filter keeps them.
        if chapters and c.get("chapter") and c["chapter"] not in chapters:
            return False
        return True

    def _keyword_rank(self, d: Loaded, query: str, kinds, chapters) -> list[tuple[dict, float]]:
        scores = d.bm25.get_scores(tokenize(query))
        ranked = sorted(((d.chunks[i], s) for i, s in enumerate(scores) if s > 0), key=lambda x: -x[1])
        return [(c, s) for c, s in ranked if self._allowed(c, kinds, chapters)]

    def _dense_rank(self, d: Loaded, query: str, kinds, chapters) -> list[tuple[dict, float]]:
        vec = self._embed_query(d, query)
        hits = d.store.similarity_search_by_vector_with_relevance_scores(vec, k=len(d.chunks))
        out = []
        for doc, score in hits:
            c = d.by_id.get(doc.metadata.get("passage_id"))
            if c and self._allowed(c, kinds, chapters):
                out.append((c, score))
        return out

    def search(self, query: str, k: int = 8, kinds: Optional[list[str]] = None,
               chapters: Optional[list[str]] = None, mode: str = "hybrid") -> tuple[list[dict], bool]:
        d = self.ensure_loaded()
        if d is None:
            raise RuntimeError("index not loaded")
        key = digest(RANKER_VERSION, d.manifest.get("built_at"), d.collection, query, k, sorted(kinds or []),
                     sorted(chapters or []), mode)
        cached = self.cache.get("retrieval", key)
        if cached is not None:
            return cached, True
        t0 = time.perf_counter()
        if mode == "keyword":
            ranked = self._keyword_rank(d, query, kinds, chapters)[:k]
        elif mode == "dense":
            ranked = self._dense_rank(d, query, kinds, chapters)[:k]
        else:
            fused: dict[str, float] = {}
            for ranking in (self._keyword_rank(d, query, kinds, chapters), self._dense_rank(d, query, kinds, chapters)):
                for rank, (c, _) in enumerate(ranking):
                    fused[c["passage_id"]] = fused.get(c["passage_id"], 0.0) + 1.0 / (RRF_K + rank + 1)
            ranked = sorted(((d.by_id[pid], s) for pid, s in fused.items()), key=lambda x: -x[1])[:k]
        metrics.retrieval_latency.labels(mode).observe(time.perf_counter() - t0)
        passages = [to_passage(c, s) for c, s in ranked]
        self.cache.set("retrieval", key, passages)
        return passages, False

    # ------------------------------------------------------------ lookups by metadata

    @staticmethod
    def normalise_clause_id(clause_id: str) -> str:
        """Upper-case the ID but keep sub-rule letters lower case: "gri-3(B)" -> "GRI-3(b)"."""
        cid = clause_id.strip().upper()
        return re.sub(r"\(([A-Z]{1,2})\)", lambda m: f"({m.group(1).lower()})", cid)

    def clause(self, clause_id: str) -> list[dict]:
        d = self.ensure_loaded()
        cid = self.normalise_clause_id(clause_id)
        hits = d.by_clause.get(cid)
        if not hits:
            # "GRI-3" returns GRI-3(a), GRI-3(b), GRI-3(c).
            hits = [c for k, v in d.by_clause.items() if k.startswith(cid + "(") for c in v]
        return [to_passage(c) for c in sorted(hits, key=lambda c: (c["clause_id"], c.get("meta", {}).get("part", 0)))]

    def known_tariff_item(self, code8: str) -> bool:
        return f"TL-{code8}" in self.ensure_loaded().by_clause

    def applicable_notes(self, clause_id: str) -> Optional[dict]:
        """Section + chapter notes that legally apply to a heading or tariff item (metadata, not similarity)."""
        d = self.ensure_loaded()
        cid = clause_id.strip().upper()
        m = re.match(r"^(?:HDG|TL|EXP)-(\d{4})(\d{4})?$", cid)
        if not m:
            return None
        chapter = m.group(1)[:2]
        if chapter not in CHAPTER_SECTION or (cid not in d.by_clause and f"HDG-{m.group(1)}" not in d.by_clause):
            return None
        section = CHAPTER_SECTION[chapter]
        notes = [c for c in d.chunks if (c["kind"] == "section_note" and c.get("section") == section)
                 or (c["kind"] == "chapter_note" and c.get("chapter") == chapter)]
        return {"clause_id": cid, "chapter": chapter, "section": section,
                "passages": [to_passage(c) for c in sorted(notes, key=_note_order)]}

    def policy(self, hs_code: str) -> Optional[dict]:
        """Schedule 2 row for the 8-digit code, else 6, else 4 digits; else the General Note 1 default."""
        d = self.ensure_loaded()
        code = re.sub(r"\D", "", hs_code)
        if len(code) not in (4, 6, 8) or code[:2] not in CHAPTER_SECTION:
            return None
        rows = [c for c in d.chunks if c["kind"] == "export_policy" and c["clause_id"].startswith("EXP-")
                and re.fullmatch(r"EXP-\d{8}", c["clause_id"])]
        for n in (8, 6, 4):
            if len(code) >= n:
                hit = [c for c in rows if c["clause_id"][4:4 + n] == code[:n]]
                if hit:
                    return {"hs_code": code, "basis": "schedule_row", "matched_digits": n,
                            "policy": hit[0].get("meta", {}).get("policy", "unknown"),
                            "tariff_item_exists": self.known_tariff_item(code) if len(code) == 8 else None,
                            "passages": [to_passage(c) for c in hit]}
        default = d.by_clause.get("EXP-GN-1", [])
        return {"hs_code": code, "basis": "default", "matched_digits": 0, "policy": "Free" if default else "unknown",
                "tariff_item_exists": self.known_tariff_item(code) if len(code) == 8 else None,
                "passages": [to_passage(c) for c in default]}

    def info(self) -> dict:
        d = self.ensure_loaded()
        if d is None:
            return {"built_at": None, "sources": [], "chunk_count": 0, "embed_model": None, "loaded": False}
        m = d.manifest
        return {"built_at": m.get("built_at"), "sources": m.get("sources", []), "chunk_count": len(d.chunks),
                "embed_model": d.embed_model, "collection": d.collection, "chunking": m.get("chunking"),
                "chunks_by_kind": m.get("chunks_by_kind"), "last_checked_at": m.get("last_checked_at"),
                "duration_seconds": m.get("duration_seconds"), "chunks_per_second": m.get("chunks_per_second"),
                "loaded": True}
