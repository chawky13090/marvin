"""Apprentissage durable de Marvin, avec SQLite autoritatif et Qdrant projeté."""

from __future__ import annotations

import json
import re
import threading
from typing import Any

import vector_store as vs
from repositories.learned_knowledge import repository


_FACTS = "learned_facts"
_QA = "learned_qa"
_MIGRATION_LOCK = threading.Lock()
_LEGACY_MIGRATED = False
_TRANSIENT = (
    "en cours",
    "actuellement",
    "en train de",
    "aujourd'hui",
    "ce matin",
    "ce soir",
    "maintenant",
    "pour l'instant",
    "en ce moment",
    "vient de",
    "est en train",
)


def _ensure(name: str):
    client = vs.get_client()
    if client is None:
        return None
    from qdrant_client.models import Distance, VectorParams

    existing = {collection.name for collection in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            name,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
    return client


def _migrate_legacy() -> None:
    """Importe une fois les anciennes collections Qdrant dans SQLite."""
    global _LEGACY_MIGRATED
    if _LEGACY_MIGRATED:
        return
    with _MIGRATION_LOCK:
        if _LEGACY_MIGRATED:
            return
        client = vs.get_client()
        if client is None:
            return
        completed = True
        for kind, collection in (("fact", _FACTS), ("qa", _QA)):
            offset = None
            while True:
                try:
                    points, offset = client.scroll(
                        collection_name=collection,
                        limit=100,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                    )
                except Exception:
                    completed = False
                    break
                for point in points:
                    payload = point.payload if isinstance(point.payload, dict) else {}
                    try:
                        if kind == "fact":
                            repository.upsert(
                                "fact",
                                payload.get("text", ""),
                                source="legacy_qdrant",
                                knowledge_id=str(point.id),
                            )
                        else:
                            repository.upsert(
                                "qa",
                                payload.get("q", ""),
                                payload.get("a", ""),
                                source="legacy_qdrant",
                                knowledge_id=str(point.id),
                            )
                    except (TypeError, ValueError):
                        continue
                if offset is None:
                    break
        _LEGACY_MIGRATED = completed


async def _project(record: dict[str, Any]) -> bool:
    try:
        collection = _FACTS if record["kind"] == "fact" else _QA
        client = _ensure(collection)
        if client is None:
            return False
        vector = await vs.embed(str(record["question"]))
        if not vector:
            return False
        from qdrant_client.models import PointStruct

        payload = {
            "source": record["source"],
            "fingerprint": record["fingerprint"],
        }
        if record["kind"] == "fact":
            payload["text"] = record["question"]
        else:
            payload["q"] = record["question"]
            payload["a"] = record["answer"]
        client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=str(record["id"]),
                    vector=vector,
                    payload=payload,
                )
            ],
        )
    except Exception:
        return False
    return True


async def add_fact(text: str, *, source: str = "automatic_learning") -> dict | None:
    normalized = str(text or "").strip()
    if len(normalized) < 4:
        return None
    _migrate_legacy()
    record, created = repository.upsert("fact", normalized, source=source)
    projected = await _project(record)
    return {**record, "created": created, "projected": projected}


async def add_qa(
    question: str,
    answer: str,
    *,
    source: str = "automatic_learning",
) -> dict | None:
    normalized_question = str(question or "").strip()
    normalized_answer = str(answer or "").strip()
    if len(normalized_question) < 4 or len(normalized_answer) < 4:
        return None
    _migrate_legacy()
    record, created = repository.upsert(
        "qa",
        normalized_question,
        normalized_answer,
        source=source,
    )
    projected = await _project(record)
    return {**record, "created": created, "projected": projected}


def _lexical_score(query: str, text: str) -> float:
    query_terms = set(re.findall(r"\w{3,}", query.lower()))
    if not query_terms:
        return 0.0
    text_terms = set(re.findall(r"\w{3,}", text.lower()))
    return len(query_terms & text_terms) / len(query_terms)


async def recall(
    query: str,
    max_facts: int = 5,
    max_qa: int = 2,
    min_fact: float = 0.42,
    min_qa: float = 0.68,
) -> dict:
    out: dict[str, list] = {"facts": [], "qa": []}
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return out
    _migrate_legacy()
    facts = repository.list("fact", 1_000)
    qa = repository.list("qa", 1_000)
    facts_by_id = {str(item["id"]): item for item in facts}
    qa_by_id = {str(item["id"]): item for item in qa}
    vector = await vs.embed(normalized_query)
    client = vs.get_client()
    if vector and client is not None:
        try:
            result = client.query_points(
                collection_name=_FACTS,
                query=vector,
                limit=max(1, min(int(max_facts), 20)),
                with_payload=True,
            )
            for hit in result.points:
                record = facts_by_id.get(str(hit.id))
                payload = hit.payload if isinstance(hit.payload, dict) else {}
                if (
                    record
                    and hit.score >= min_fact
                    and (
                        payload.get("fingerprint") == record["fingerprint"]
                        or payload.get("text") == record["question"]
                    )
                ):
                    out["facts"].append(record["question"])
        except Exception:
            pass
        try:
            result = client.query_points(
                collection_name=_QA,
                query=vector,
                limit=max(1, min(int(max_qa), 10)),
                with_payload=True,
            )
            for hit in result.points:
                record = qa_by_id.get(str(hit.id))
                payload = hit.payload if isinstance(hit.payload, dict) else {}
                if (
                    record
                    and hit.score >= min_qa
                    and (
                        payload.get("fingerprint") == record["fingerprint"]
                        or (
                            payload.get("q") == record["question"]
                            and payload.get("a") == record["answer"]
                        )
                    )
                ):
                    out["qa"].append((record["question"], record["answer"]))
        except Exception:
            pass
    if len(out["facts"]) < max_facts:
        candidates = sorted(
            facts,
            key=lambda item: (
                _lexical_score(normalized_query, item["question"]),
                item["created_at"],
            ),
            reverse=True,
        )
        for item in candidates:
            if _lexical_score(normalized_query, item["question"]) <= 0:
                continue
            if item["question"] not in out["facts"]:
                out["facts"].append(item["question"])
            if len(out["facts"]) >= max_facts:
                break
    if len(out["qa"]) < max_qa:
        candidates = sorted(
            qa,
            key=lambda item: (
                _lexical_score(normalized_query, item["question"]),
                item["created_at"],
            ),
            reverse=True,
        )
        for item in candidates:
            pair = (item["question"], item["answer"])
            if _lexical_score(normalized_query, item["question"]) <= 0:
                continue
            if pair not in out["qa"]:
                out["qa"].append(pair)
            if len(out["qa"]) >= max_qa:
                break
    return out


def recall_block(recalled: dict) -> str:
    """Formate uniquement les connaissances autoritatives rappelées."""
    parts = []
    if recalled.get("facts"):
        parts.append(
            "CE QUE TU SAIS DÉJÀ SUR L'UTILISATEUR "
            "(sers-t'en pour répondre directement) :\n"
            + "\n".join(f"- {fact}" for fact in recalled["facts"])
        )
    if recalled.get("qa"):
        parts.append(
            "Réponses pertinentes déjà fournies (réutilise/adapte si utile) :\n"
            + "\n".join(
                f"• Q : {question}\n  R : {answer}"
                for question, answer in recalled["qa"]
            )
        )
    return "\n\n🧠 MÉMOIRE À LONG TERME :\n" + "\n\n".join(parts) if parts else ""


async def learn_from_exchange(user_msg: str, assistant_msg: str, generate_fn):
    """Extrait des connaissances durables sans accepter le JSON du LLM comme preuve."""
    user_msg = str(user_msg or "").strip()
    assistant_msg = str(assistant_msg or "").strip()
    if len(user_msg) < 3 or len(assistant_msg) < 12:
        return
    prompt = (
        "Tu es le module de mémoire d'un assistant. Analyse cet échange et renvoie "
        "UNIQUEMENT un JSON, sans texte autour :\n"
        '{"facts": ["fait durable"], "reusable": true, '
        '"qa": {"q": "question générique", "a": "réponse concise"}}\n'
        "Exclus les états transitoires et toutes les données sensibles. "
        "Ne conserve que ce qui sera encore vrai dans plusieurs semaines.\n\n"
        f"UTILISATEUR : {user_msg[:800]}\n"
        f"ASSISTANT : {assistant_msg[:1400]}\n\nJSON :"
    )
    try:
        raw = await generate_fn(prompt)
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not match:
            return
        data = json.loads(match.group(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    facts = data.get("facts")
    if isinstance(facts, list):
        for fact in facts[:5]:
            if not isinstance(fact, str) or not fact.strip():
                continue
            if any(marker in fact.lower() for marker in _TRANSIENT):
                continue
            await add_fact(fact, source="exchange_extraction")
    qa = data.get("qa")
    if data.get("reusable") is True and isinstance(qa, dict):
        await add_qa(
            qa.get("q", ""),
            qa.get("a", ""),
            source="exchange_extraction",
        )


def list_learned(kind: str = "facts", limit: int = 100) -> list:
    _migrate_legacy()
    if kind == "facts":
        return [
            {
                "id": item["id"],
                "text": item["question"],
                "source": item["source"],
            }
            for item in repository.list("fact", limit)
        ]
    return [
        {
            "id": item["id"],
            "q": item["question"],
            "a": item["answer"],
            "source": item["source"],
        }
        for item in repository.list("qa", limit)
    ]


def delete_learned(kind: str, point_id: str) -> bool:
    _migrate_legacy()
    normalized_kind = "fact" if kind == "facts" else "qa"
    deleted = repository.delete(normalized_kind, point_id)
    client = vs.get_client()
    if client is not None:
        try:
            client.delete(
                collection_name=_FACTS if normalized_kind == "fact" else _QA,
                points_selector=[point_id],
            )
        except Exception:
            pass
    return deleted


def count_learned() -> dict:
    _migrate_legacy()
    return repository.counts()
