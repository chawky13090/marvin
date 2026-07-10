"""
Apprentissage continu de Marvin (100 % local, sans ré-entraînement).

Deux bases de connaissances vectorielles (Qdrant + nomic-embed-text) :
  - learned_facts : faits durables sur l'utilisateur / son contexte (préférences,
                    noms, infos pro…), extraits automatiquement des échanges.
  - learned_qa    : paires question→réponse RÉUTILISABLES produites par le LLM
                    (« apprendre des LLM qu'il utilise ») — réinjectées comme
                    référence quand une question proche revient.

À chaque tour de conversation :
  1. recall(query)              → injecte les connaissances pertinentes au prompt.
  2. learn_from_exchange(...)   → en arrière-plan, le « professeur » (le meilleur
                                  modèle dispo) extrait faits + Q/R réutilisables.

Tout est best-effort : si Qdrant/embeddings indisponibles → ne fait rien (jamais cassé).
"""
import json
import re
import uuid

import vector_store as vs

_FACTS = "learned_facts"
_QA = "learned_qa"


def _ensure(name: str):
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


async def add_fact(text: str):
    text = (text or "").strip()
    if len(text) < 4:
        return
    client = _ensure(_FACTS)
    if client is None:
        return
    vec = await vs.embed(text)
    if not vec:
        return
    from qdrant_client.models import PointStruct
    # Anti-doublon : si un fait quasi identique existe déjà (>0.95), on n'ajoute pas.
    try:
        r = client.query_points(collection_name=_FACTS, query=vec, limit=1, with_payload=True)
        if r.points and r.points[0].score > 0.95:
            return
    except Exception:
        pass
    client.upsert(collection_name=_FACTS, points=[PointStruct(id=str(uuid.uuid4()), vector=vec, payload={"text": text})])


async def add_qa(question: str, answer: str):
    q = (question or "").strip()
    a = (answer or "").strip()
    if len(q) < 4 or len(a) < 4:
        return
    client = _ensure(_QA)
    if client is None:
        return
    vec = await vs.embed(q)
    if not vec:
        return
    from qdrant_client.models import PointStruct
    client.upsert(collection_name=_QA, points=[PointStruct(id=str(uuid.uuid4()), vector=vec,
                  payload={"q": q, "a": a[:1200]})])


async def recall(query: str, max_facts: int = 5, max_qa: int = 2,
                 min_fact: float = 0.42, min_qa: float = 0.68) -> dict:
    out = {"facts": [], "qa": []}
    client = vs.get_client()
    if client is None or not (query or "").strip():
        return out
    vec = await vs.embed(query)
    if not vec:
        return out
    try:
        r = client.query_points(collection_name=_FACTS, query=vec, limit=max_facts, with_payload=True)
        out["facts"] = [h.payload.get("text") for h in r.points if h.score >= min_fact and h.payload.get("text")]
    except Exception:
        pass
    try:
        r = client.query_points(collection_name=_QA, query=vec, limit=max_qa, with_payload=True)
        out["qa"] = [(h.payload.get("q"), h.payload.get("a")) for h in r.points if h.score >= min_qa and h.payload.get("a")]
    except Exception:
        pass
    return out


def recall_block(recalled: dict) -> str:
    """Formate les connaissances rappelées pour injection dans le prompt système."""
    parts = []
    if recalled.get("facts"):
        parts.append("CE QUE TU SAIS DÉJÀ SUR L'UTILISATEUR (sers-t'en pour répondre DIRECTEMENT, "
                     "ne redemande pas ce que tu sais déjà) :\n" + "\n".join(f"- {f}" for f in recalled["facts"]))
    if recalled.get("qa"):
        parts.append("Réponses pertinentes déjà fournies (réutilise/adapte si utile) :\n"
                     + "\n".join(f"• Q : {q}\n  R : {a}" for q, a in recalled["qa"]))
    if not parts:
        return ""
    return "\n\n🧠 MÉMOIRE À LONG TERME :\n" + "\n\n".join(parts)


async def learn_from_exchange(user_msg: str, assistant_msg: str, generate_fn):
    """Extrait, via le LLM 'professeur', des faits durables + une Q/R réutilisable.
    generate_fn : async (prompt:str) -> str."""
    user_msg = (user_msg or "").strip()
    assistant_msg = (assistant_msg or "").strip()
    if len(user_msg) < 3 or len(assistant_msg) < 12:
        return
    prompt = (
        "Tu es le module de mémoire d'un assistant. Analyse cet échange et renvoie "
        "UNIQUEMENT un JSON, sans texte autour :\n"
        '{"facts": ["fait durable et utile sur l\'utilisateur/son contexte"], '
        '"reusable": true/false, "qa": {"q": "question générique", "a": "réponse concise réutilisable"}}\n'
        "Règles strictes :\n"
        "- facts : PHRASES COMPLÈTES à la 3e personne décrivant des infos DURABLES sur l'utilisateur "
        "(ex : « L'utilisateur s'appelle Chaouki. », « L'utilisateur est technicien informatique chez KOIOS. », "
        "« L'utilisateur préfère des réponses courtes. »). [] si rien de durable. PAS de format clé:valeur.\n"
        "- EXCLUS ABSOLUMENT les états TRANSITOIRES/momentanés : un problème en cours, une tâche du moment, "
        "« le PC est en cours de diagnostic », « je suis en train de… », l'heure, la météo, un résultat ponctuel. "
        "Ne garde QUE ce qui sera encore vrai dans des SEMAINES (identité, métier, préférences stables, équipement possédé).\n"
        "- reusable=true UNIQUEMENT si la réponse est une connaissance factuelle réutilisable (pas une action ponctuelle, "
        "pas un résultat éphémère).\n"
        "- N'inclus JAMAIS de données sensibles (mots de passe, codes, n° carte).\n"
        "- Sois concis.\n\n"
        f"UTILISATEUR : {user_msg[:800]}\n"
        f"ASSISTANT : {assistant_msg[:1400]}\n\nJSON :"
    )
    try:
        raw = await generate_fn(prompt)
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        if not m:
            return
        data = json.loads(m.group(0))
    except Exception:
        return
    # Filet de sécurité : rejette les faits qui sentent le TRANSITOIRE (états momentanés)
    _TRANSIENT = ("en cours", "actuellement", "en train de", "aujourd'hui", "ce matin", "ce soir",
                  "maintenant", "pour l'instant", "en ce moment", "vient de", "est en train")
    for f in (data.get("facts") or [])[:5]:
        if isinstance(f, str) and f.strip():
            if any(t in f.lower() for t in _TRANSIENT):
                continue   # état transitoire → on ne mémorise pas
            await add_fact(f)
    if data.get("reusable") and isinstance(data.get("qa"), dict):
        await add_qa(data["qa"].get("q", ""), data["qa"].get("a", ""))


# ── Consultation / gestion (pour l'UI) ─────────────────────────────────────────
def list_learned(kind: str = "facts", limit: int = 100) -> list:
    client = vs.get_client()
    if client is None:
        return []
    col = _FACTS if kind == "facts" else _QA
    try:
        points, _ = client.scroll(collection_name=col, limit=limit, with_payload=True)
        if kind == "facts":
            return [{"id": str(p.id), "text": p.payload.get("text", "")} for p in points]
        return [{"id": str(p.id), "q": p.payload.get("q", ""), "a": p.payload.get("a", "")} for p in points]
    except Exception:
        return []


def delete_learned(kind: str, point_id: str):
    client = vs.get_client()
    if client is None:
        return
    col = _FACTS if kind == "facts" else _QA
    try:
        client.delete(collection_name=col, points_selector=[point_id])
    except Exception:
        pass


def count_learned() -> dict:
    client = vs.get_client()
    if client is None:
        return {"facts": 0, "qa": 0}
    out = {}
    for k, col in (("facts", _FACTS), ("qa", _QA)):
        try:
            out[k] = client.count(collection_name=col).count
        except Exception:
            out[k] = 0
    return out
