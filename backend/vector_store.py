"""
SecretaryAI Backend — Qdrant vector store (mode local, sans Docker).
Utilise Ollama nomic-embed-text pour les embeddings.
"""
import json
import re as _re
import time as _time
import uuid
import httpx
from typing import Any
from config import QDRANT_PATH, OLLAMA_URL, EMBEDDING_MODEL
import memory_cipher

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    )
    _qdrant_available = True
except ImportError:
    _qdrant_available = False

# ── Initialisation du client ──────────────────────────────────────────────────

_client: Any = None
_memory_payloads_migrated = False

def get_client():
    global _client, _memory_payloads_migrated
    if not _qdrant_available:
        return None
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
        _ensure_collections()
    if not _memory_payloads_migrated:
        _migrate_memory_payloads(_client)
        _memory_payloads_migrated = True
    return _client


def close_client() -> None:
    """Ferme explicitement le stockage local lors d'un runtime court/hors ligne."""
    global _client, _memory_payloads_migrated
    client, _client = _client, None
    _memory_payloads_migrated = False
    if client is not None:
        client.close()


COLLECTIONS = {
    "memories": 768,    # nomic-embed-text = 768 dims
    "notes": 768,
    "documents": 768,
}

def _ensure_collections():
    client = _client
    existing = {c.name for c in client.get_collections().collections}
    for name, dim in COLLECTIONS.items():
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )


def _memory_payload_text(payload: dict[str, Any]) -> str:
    protected = payload.get("text_protected")
    if protected is not None:
        return memory_cipher.unprotect_text(str(protected))
    return str(payload.get("text") or "")


def _migrate_memory_payloads(client: Any) -> int:
    """Retire le texte clair historique de Qdrant après vérification DPAPI."""
    migrated = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name="memories",
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = dict(point.payload or {})
            if payload.get("text_protected") is not None:
                memory_cipher.unprotect_text(str(payload["text_protected"]))
                if "text" not in payload:
                    continue
            elif payload.get("text"):
                payload["text_protected"] = memory_cipher.protect_text(
                    str(payload["text"])
                )
            else:
                continue
            payload.pop("text", None)
            client.overwrite_payload(
                collection_name="memories",
                payload=payload,
                points=[point.id],
            )
            migrated += 1
        if offset is None:
            break
    return migrated


def rollback_memory_payload_protection(client: Any) -> int:
    """Restaure les payloads texte attendus par les versions antérieures."""
    changed = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name="memories",
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = dict(point.payload or {})
            protected = payload.get("text_protected")
            if protected is None:
                continue
            payload["text"] = memory_cipher.unprotect_text(str(protected))
            payload.pop("text_protected", None)
            client.overwrite_payload(
                collection_name="memories",
                payload=payload,
                points=[point.id],
            )
            changed += 1
        if offset is None:
            break
    return changed


def inspect_memory_index(expected_hashes: dict[str, str]) -> dict[str, Any]:
    """Compare Qdrant à SQLite sans retourner le contenu des souvenirs."""
    client = get_client()
    if client is None:
        return {
            "available": False,
            "count": 0,
            "missing": sorted(expected_hashes),
            "orphan": [],
            "stale": [],
            "unprotected": [],
            "corrupt": [],
        }
    indexed: dict[str, dict[str, Any]] = {}
    unprotected: list[str] = []
    corrupt: list[str] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name="memories",
            limit=128,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = dict(point.payload or {})
            memory_id = str(payload.get("original_id") or "")
            if not memory_id:
                corrupt.append(str(point.id))
                continue
            indexed[memory_id] = payload
            if payload.get("text_protected") is None:
                unprotected.append(memory_id)
            else:
                try:
                    memory_cipher.unprotect_text(str(payload["text_protected"]))
                except memory_cipher.MemoryCipherError:
                    corrupt.append(memory_id)
        if offset is None:
            break
    expected_ids = set(expected_hashes)
    indexed_ids = set(indexed)
    stale = sorted(
        memory_id
        for memory_id in expected_ids & indexed_ids
        if str(indexed[memory_id].get("content_sha256") or "")
        != expected_hashes[memory_id]
    )
    return {
        "available": True,
        "count": len(indexed),
        "missing": sorted(expected_ids - indexed_ids),
        "orphan": sorted(indexed_ids - expected_ids),
        "stale": stale,
        "unprotected": sorted(set(unprotected)),
        "corrupt": sorted(set(corrupt)),
    }


# ── Embeddings via Ollama ─────────────────────────────────────────────────────

async def embed(text: str) -> list[float] | None:
    """Génère un embedding via Ollama nomic-embed-text."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": EMBEDDING_MODEL, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama embed API returns {"embeddings": [[...]]}
            embeddings = data.get("embeddings") or data.get("embedding")
            if isinstance(embeddings, list) and len(embeddings) > 0:
                first = embeddings[0]
                if isinstance(first, list):
                    return first
                return embeddings
    except Exception as e:
        print(f"[VectorStore] Erreur embedding: {e}")
    return None


# ── Recherche hybride : index BM25 lexical, en complément du vecteur ──────────
# v2.115 — le vecteur seul rate parfois un passage pertinent formulé avec des mots-clés
# EXACTS de la requête mais un sens légèrement différent (le cosinus les éloigne). BM25
# (lexical pur) et le vecteur (sémantique pur) se complètent — fusionnés par Reciprocal
# Rank Fusion (RRF), pattern documenté comme le plus gros gain de qualité sur un RAG
# naïf (recherche web, session 2026-07-09). Index reconstruit à la demande avec un TTL
# court (le corpus de notes/mémoires/documents d'un utilisateur reste petit — quelques
# centaines à quelques milliers de fragments — reconstruire coûte peu).
_BM25_CACHE: dict[str, tuple[float, Any, list[dict]]] = {}  # collection -> (ts, bm25, records)
_BM25_TTL = 60  # secondes


def _tokenize(text: str) -> list[str]:
    return _re.findall(r"\w+", (text or "").lower())


def _get_bm25_index(collection: str):
    """Construit (ou récupère depuis le cache) un index BM25 pour une collection.
    Renvoie (bm25_index, records) ou (None, []) si rank_bm25 est indisponible ou la
    collection est vide."""
    now = _time.time()
    cached = _BM25_CACHE.get(collection)
    if cached and now - cached[0] < _BM25_TTL:
        return cached[1], cached[2]

    client = get_client()
    if client is None:
        return None, []
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        return None, []

    records = []
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                collection_name=collection, limit=256, offset=offset, with_payload=True,
            )
            for p in points:
                text = (
                    _memory_payload_text(p.payload)
                    if collection == "memories"
                    else p.payload.get("text", "")
                )
                if text:
                    records.append({
                        "collection": collection,
                        "text": text,
                        "metadata": {
                            k: v for k, v in p.payload.items()
                            if k not in ("text", "text_protected")
                        },
                    })
            if offset is None:
                break
    except Exception as e:
        print(f"[VectorStore] BM25 scroll error in {collection}: {e}")
        return None, []

    if not records:
        _BM25_CACHE[collection] = (now, None, [])
        return None, []

    bm25 = BM25Okapi([_tokenize(r["text"]) for r in records])
    _BM25_CACHE[collection] = (now, bm25, records)
    return bm25, records


def _bm25_search(query: str, collections: list[str], pool_limit: int) -> list[dict]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    out = []
    for col in collections:
        bm25, records = _get_bm25_index(col)
        if bm25 is None:
            continue
        scores = bm25.get_scores(tokens)
        ranked = sorted(range(len(records)), key=lambda i: scores[i], reverse=True)[:pool_limit]
        for i in ranked:
            if scores[i] <= 0:
                continue
            out.append({**records[i], "bm25_score": round(float(scores[i]), 4)})
    return out


def _rrf_fuse(vector_results: list[dict], bm25_results: list[dict], k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion : combine deux classements sans avoir à harmoniser leurs
    échelles de score (cosinus 0-1 vs BM25 sans borne supérieure) — chaque item gagne
    1/(k+rang) dans chaque liste où il apparaît, fusionné par texte identique."""
    scores: dict[str, float] = {}
    items: dict[str, dict] = {}
    for rank, r in enumerate(vector_results):
        key = r["text"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        items.setdefault(key, r)
    for rank, r in enumerate(bm25_results):
        key = r["text"]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in items:
            items[key] = r
        else:
            items[key] = {**items[key], "bm25_score": r.get("bm25_score")}
    fused = sorted(items.values(), key=lambda r: scores[r["text"]], reverse=True)
    for r in fused:
        r["rrf_score"] = round(scores[r["text"]], 5)
    return fused


# ── Opérations CRUD ───────────────────────────────────────────────────────────

async def upsert_document(
    collection: str,
    doc_id: str,
    text: str,
    metadata: dict | None = None,
) -> bool:
    """Indexe un document dans Qdrant."""
    client = get_client()
    if client is None:
        return False
    vector = await embed(text)
    if vector is None:
        return False
    client.upsert(
        collection_name=collection,
        points=[PointStruct(
            id=_safe_id(doc_id),
            vector=vector,
            payload={"text": text, **(metadata or {}), "original_id": doc_id},
        )]
    )
    return True


async def search(
    query: str,
    collections: list[str] | None = None,
    limit: int = 5,
    rerank_results: bool = True,
    hybrid: bool = True,
) -> list[dict]:
    """Recherche sémantique dans une ou plusieurs collections.

    v2.115 — pipeline en 3 étages, chacun best-effort (jamais bloquant si une brique
    manque) :
    1. Vecteur (Qdrant) + BM25 lexical (rank_bm25), chacun sur un pool élargi.
    2. Fusion Reciprocal Rank Fusion (RRF) des deux classements — le vecteur seul rate
       parfois un passage aux mots-clés exacts mais formulé différemment ; BM25 seul
       rate les paraphrases. Ensemble ils se couvrent mutuellement.
    3. Reranker cross-encoder local (reranker.py) sur le pool fusionné → tri final par
       pertinence RÉELLE, pas par proximité de score.
    `hybrid=False` ou `rerank_results=False` désactivent chacun leur étage (ex. pour
    debug, ou si un appelant veut le comportement vecteur-seul historique)."""
    client = get_client()
    if client is None:
        return []
    vector = await embed(query)
    if vector is None:
        return []

    targets = collections or list(COLLECTIONS.keys())
    results = []
    # Pool élargi pour donner à la fusion RRF et au reranker de vraies alternatives.
    pool_limit = max(limit * 4, 20) if (rerank_results or hybrid) else limit

    for col in targets:
        try:
            # qdrant-client ≥ 1.12 : query_points() remplace search() (déprécié → 0 résultat)
            resp = client.query_points(
                collection_name=col,
                query=vector,
                limit=pool_limit,
                with_payload=True,
            )
            for h in resp.points:
                text = (
                    _memory_payload_text(h.payload)
                    if col == "memories"
                    else h.payload.get("text", "")
                )
                results.append({
                    "collection": col,
                    "score": round(h.score, 4),
                    "text": text,
                    "metadata": {
                        k: v for k, v in h.payload.items()
                        if k not in ("text", "text_protected")
                    },
                })
        except Exception as e:
            print(f"[VectorStore] search error in {col}: {e}")

    results.sort(key=lambda x: x["score"], reverse=True)

    if hybrid:
        try:
            bm25_results = _bm25_search(query, targets, pool_limit)
            if bm25_results:
                results = _rrf_fuse(results, bm25_results)
        except Exception as e:
            print(f"[VectorStore] BM25 hybrid fusion échouée ({e}) — repli sur le vecteur seul.")

    if not rerank_results:
        return results[:limit]

    import reranker as _reranker
    return _reranker.rerank(query, results, text_key="text", top_k=limit)


async def delete_document(collection: str, doc_id: str):
    client = get_client()
    if client is None:
        return
    client.delete(collection_name=collection, points_selector=[_safe_id(doc_id)])
    _BM25_CACHE.pop(collection, None)


def _safe_id(raw_id: str) -> str:
    """Qdrant IDs must be UUID strings or unsigned integers."""
    try:
        uuid.UUID(raw_id)
        return raw_id
    except ValueError:
        # Deterministic UUID from the string
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_id))


async def index_memory(memory_id: str, content: str, category: str):
    import memory_mesh

    client = get_client()
    if client is None:
        return False
    vector = await embed(content)
    if vector is None:
        return False
    client.upsert(
        collection_name="memories",
        points=[PointStruct(
            id=_safe_id(memory_id),
            vector=vector,
            payload={
                "text_protected": memory_cipher.protect_text(content),
                "category": category,
                "original_id": memory_id,
                "content_sha256": memory_mesh.content_sha256(content),
            },
        )],
    )
    _BM25_CACHE.pop("memories", None)
    return True


async def index_note(note_id: str, title: str, content: str, tags: list):
    text = f"{title}\n{content}"
    await upsert_document("notes", note_id, text, {"title": title, "tags": tags, "original_id": note_id})


async def index_file(path: str, content: str):
    from pathlib import Path as P
    name = P(path).name
    await upsert_document("documents", path, content, {"path": path, "name": name, "original_id": path})


async def index_chunks(doc_id: str, name: str, path: str, chunks: list[str]) -> int:
    """Indexe une liste de fragments d'un même document (RAG)."""
    client = get_client()
    if client is None:
        return 0
    points = []
    for i, ch in enumerate(chunks):
        vec = await embed(ch)
        if vec is None:
            continue
        points.append(PointStruct(
            id=_safe_id(f"{doc_id}::{i}"),
            vector=vec,
            payload={"text": ch, "name": name, "path": path, "doc_id": doc_id, "chunk": i},
        ))
    if points:
        client.upsert(collection_name="documents", points=points)
    return len(points)


def delete_doc_chunks(doc_id: str):
    """Supprime tous les fragments d'un document (par doc_id)."""
    client = get_client()
    if client is None:
        return
    try:
        client.delete(
            collection_name="documents",
            points_selector=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]),
        )
    except Exception:
        pass
