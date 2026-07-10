"""
Reranking local pour la recherche sémantique (v2.115).

La recherche vectorielle seule (Qdrant + cosine) rate parfois des passages pertinents
formulés différemment, ou remonte des passages proches en surface mais hors-sujet.
Un reranker cross-encoder (qui compare directement la requête et CHAQUE passage, avec
attention complète, au lieu de comparer deux vecteurs pré-calculés) corrige ça — gain de
pertinence significatif pour un coût quasi nul en local (modèle de quelques Mo, tourne en
CPU en dizaines de ms). Pattern documenté comme le plus rentable pour améliorer un RAG
naïf (recherche web, session 2026-07-09).

Bibliothèque : flashrank (modèles ONNX légers, zéro dépendance GPU). Le modèle est
téléchargé une seule fois dans data/reranker_cache/ (pas dans backend/, pour rester
cohérent avec la convention "tout ce qui est persistant vit sous data/").
"""
from config import RERANKER_CACHE_DIR

_ranker = None
_unavailable = False


def _get_ranker():
    global _ranker, _unavailable
    if _unavailable:
        return None
    if _ranker is None:
        try:
            from flashrank import Ranker
            _ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=RERANKER_CACHE_DIR)
        except Exception as e:
            print(f"[Reranker] Indisponible ({e}) — repli sur le tri par score vectoriel seul.")
            _unavailable = True
            return None
    return _ranker


def rerank(query: str, results: list[dict], text_key: str = "text", top_k: int | None = None) -> list[dict]:
    """Re-score une liste de résultats (dicts avec un champ texte) selon leur pertinence
    RÉELLE par rapport à la requête. Best-effort : si le reranker est indisponible
    (dépendance manquante, modèle non téléchargeable hors-ligne...), renvoie la liste
    d'origine inchangée plutôt que d'échouer — la recherche reste utilisable, juste
    moins affinée."""
    if not results:
        return results
    ranker = _get_ranker()
    if ranker is None:
        return results[:top_k] if top_k else results
    try:
        from flashrank import RerankRequest
        passages = [{"id": i, "text": r.get(text_key, "") or ""} for i, r in enumerate(results)]
        req = RerankRequest(query=query, passages=passages)
        scored = ranker.rerank(req)
        order = sorted(scored, key=lambda s: s["score"], reverse=True)
        out = []
        for s in order:
            item = dict(results[s["id"]])
            item["rerank_score"] = round(float(s["score"]), 4)
            out.append(item)
        return out[:top_k] if top_k else out
    except Exception as e:
        print(f"[Reranker] Échec du rerank ({e}) — repli sur l'ordre d'origine.")
        return results[:top_k] if top_k else results
