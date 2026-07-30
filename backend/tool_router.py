"""
Routing INTELLIGENT des outils.

Deux signaux complémentaires des mots-clés (qui ratent les paraphrases) :
  1. Sémantique  — compare le SENS de la demande aux descriptions d'outils
                   (embeddings nomic-embed-text + Qdrant).
  2. Appris      — se souvient des outils qui ont DÉJÀ bien répondu à des
                   demandes similaires → Marvin s'améliore avec l'usage.

Tout est best-effort : si Qdrant ou l'embedding sont indisponibles, on renvoie
des ensembles vides et l'agent retombe sur le routing par mots-clés (jamais cassé).
"""
import hashlib
import json
import uuid

import vector_store as vs
import database as db
from capability_discovery import (
    DISCOVERY_SCHEMA_VERSION,
    parameter_text,
    profile_for,
)

_TOOL_COLLECTION = "tool_index"
_FEEDBACK_COLLECTION = "routing_feedback"
_indexed = False


def _ensure_collection(name: str):
    client = vs.get_client()
    if client is None:
        return None
    from qdrant_client.models import Distance, VectorParams
    try:
        existing = {c.name for c in client.get_collections().collections}
        if name not in existing:
            client.create_collection(name, vectors_config=VectorParams(size=768, distance=Distance.COSINE))
    except Exception:
        pass
    return client


async def ensure_tool_index(tools_spec: list) -> bool:
    """Indexe les descriptions d'outils (une fois ; réindexe si le set d'outils change)."""
    global _indexed
    client = _ensure_collection(_TOOL_COLLECTION)
    if client is None:
        return False
    index_documents = tool_index_documents(tools_spec)
    h = tool_index_fingerprint(tools_spec)
    if _indexed and db.get_setting("tool_index_hash") == h:
        return True
    if db.get_setting("tool_index_hash") != h:
        from qdrant_client.models import PointStruct
        points = []
        for name, document in index_documents:
            vec = await vs.embed(document)
            if vec:
                points.append(PointStruct(
                    id=vs._safe_id("tool::" + name),
                    vector=vec,
                    payload={
                        "name": name,
                        "discovery_schema": DISCOVERY_SCHEMA_VERSION,
                    },
                ))
        if points:
            # upsert par lots de 64
            for i in range(0, len(points), 64):
                client.upsert(collection_name=_TOOL_COLLECTION, points=points[i:i + 64])
            db.set_setting("tool_index_hash", h)
    _indexed = True
    return True


def tool_index_documents(tools_spec: list) -> list[tuple[str, str]]:
    """Produit les documents indexés sans dépendre de Qdrant."""
    index_documents: list[tuple[str, str]] = []
    for specification in tools_spec:
        function = specification.get("function", {})
        name = str(function.get("name") or "")
        if not name:
            continue
        summary = " ".join(str(function.get("description") or "").split())
        profile = profile_for(name)
        index_documents.append((
            name,
            profile.semantic_document(name, summary, parameter_text(function)),
        ))
    return index_documents


def tool_index_fingerprint(tools_spec: list) -> str:
    """Invalide l'index si un nom, texte, paramètre ou profil change."""
    serialized = json.dumps(
        {
            "schema": DISCOVERY_SCHEMA_VERSION,
            "documents": sorted(tool_index_documents(tools_spec)),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def route_tools(
    query: str,
    k_sem: int = 8,
    k_learn: int = 5,
    min_semantic: float = 0.40,
    min_learn: float = 0.72,
) -> dict:
    """Renvoie {'semantic': set, 'learned': set} pour une requête.
    'learned' = outils ayant réussi sur des demandes TRÈS proches par le passé."""
    out = {"semantic": set(), "learned": set(), "semantic_scores": {}}
    client = vs.get_client()
    if client is None or not (query or "").strip():
        return out
    vec = await vs.embed(query)
    if not vec:
        return out
    # 1) Sémantique : outils dont la description colle au sens de la demande
    try:
        resp = client.query_points(collection_name=_TOOL_COLLECTION, query=vec, limit=k_sem, with_payload=True)
        scores = {
            h.payload.get("name"): float(h.score)
            for h in resp.points
            if h.payload.get("name") and float(h.score) >= min_semantic
        }
        out["semantic_scores"] = scores
        out["semantic"] = set(scores)
    except Exception:
        pass
    # 2) Appris : outils qui ont déjà bien marché sur des demandes similaires
    try:
        resp = client.query_points(collection_name=_FEEDBACK_COLLECTION, query=vec, limit=k_learn, with_payload=True)
        out["learned"] = {h.payload.get("tool") for h in resp.points if h.score >= min_learn and h.payload.get("tool")}
    except Exception:
        pass
    return out


async def record_success(query: str, tool_name: str):
    """Mémorise qu'un outil a bien répondu à une demande (apprentissage du routing)."""
    if not (query or "").strip() or not tool_name:
        return
    client = _ensure_collection(_FEEDBACK_COLLECTION)
    if client is None:
        return
    vec = await vs.embed(query)
    if not vec:
        return
    from qdrant_client.models import PointStruct
    try:
        client.upsert(collection_name=_FEEDBACK_COLLECTION,
                      points=[PointStruct(id=str(uuid.uuid4()), vector=vec,
                                          payload={"tool": tool_name, "query": (query or "")[:200]})])
    except Exception:
        pass
