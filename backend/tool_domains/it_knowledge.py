"""Base de connaissances IT locale et recommandations deterministes."""

from __future__ import annotations

import re
from typing import Any

import database as db


async def search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    try:
        limit = max(1, min(int(args.get("limit", 12)), 100))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'limit' invalide : entier attendu entre 1 et 100."}
    try:
        results = db.it_kb_search(query, limit) if query else db.it_kb_list(args.get("category"))
        return {
            "success": True,
            "query": query,
            "count": len(results),
            "tools": results,
            "categories": db.it_kb_categories(),
        }
    except Exception as exc:
        return {"error": str(exc)}


async def list_entries(args: dict[str, Any]) -> dict[str, Any]:
    try:
        entries = db.it_kb_list(args.get("category"))
        by_category: dict[str, list[str]] = {}
        for entry in entries:
            by_category.setdefault(entry["category"], []).append(entry["name"])
        return {
            "success": True,
            "count": len(entries),
            "categories": db.it_kb_categories(),
            "by_category": by_category,
            "tools": entries,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _score(entry: dict[str, Any], *, wants_free: bool, wants_sovereign: bool) -> float:
    score = float(entry.get("rating") or 0) + int(entry.get("times_used") or 0) * 0.5
    if wants_free and entry.get("pricing_model") in {"opensource", "free", "freemium"}:
        score += 3
    searchable = (str(entry.get("tags") or "") + str(entry.get("best_for") or "")).lower()
    if wants_sovereign and any(
        keyword in searchable
        for keyword in ("souverain", "rgpd", "anssi", "français", "auto-héberg")
    ):
        score += 3
    return score


async def recommend(args: dict[str, Any]) -> dict[str, Any]:
    need = str(args.get("need") or args.get("query") or "").strip()
    if not need:
        return {"error": "Paramètre 'need' requis (ex: 'sauvegarde pour une mairie, budget limité')."}
    text = need.lower()
    stop_words = {
        "pour", "une", "un", "des", "de", "la", "le", "les", "du", "avec", "et",
        "outil", "logiciel", "solution", "besoin", "client", "quel", "quelle", "meilleur",
        "gratuit", "gratuite", "budget", "open", "source", "opensource", "souverain",
        "souveraine", "rgpd", "anssi", "français", "française", "france", "limité", "limite",
        "pas", "cher", "économique", "economique", "petit", "auto", "hébergé", "heberge",
        "mairie", "collectivité", "collectivite", "pme", "tpe", "entreprise", "association",
    }
    words = [
        word
        for word in re.findall(r"[a-zàâçéèêëîïôûùüÿñ0-9]{3,}", text)
        if word not in stop_words
    ]
    try:
        hits: list[dict[str, Any]] = []
        seen: set[str] = set()
        for word in words:
            for entry in db.it_kb_search(word, 8):
                entry_id = str(entry["id"])
                if entry_id not in seen:
                    seen.add(entry_id)
                    hits.append(entry)
        wants_free = any(
            keyword in text
            for keyword in ("gratuit", "budget", "open source", "opensource", "sans coût", "pas cher", "économ")
        )
        wants_sovereign = any(
            keyword in text
            for keyword in ("souverain", "rgpd", "français", "france", "anssi", "auto-héberg", "auto heberg")
        )
        hits.sort(
            key=lambda entry: _score(
                entry, wants_free=wants_free, wants_sovereign=wants_sovereign
            ),
            reverse=True,
        )
        top = hits[:5]
        for entry in top:
            db.it_kb_increment_usage(entry["id"])
        if not top:
            return {
                "success": True,
                "need": need,
                "from_kb": 0,
                "message": (
                    "Aucun outil en base pour ce besoin. Lancez une recherche web "
                    "(web_search) puis ajoutez le résultat avec it_kb_add."
                ),
                "hint": "billing_product_reviews / billing_market_research pour évaluer une piste.",
            }
        recommendations = [
            {
                "name": entry["name"],
                "category": entry["category"],
                "vendor": entry.get("vendor", ""),
                "why": entry.get("best_for") or entry.get("use_cases", ""),
                "pricing": entry.get("pricing_model"),
                "typical_price": entry.get("typical_price", ""),
                "platforms": entry.get("platforms", ""),
                "url": entry.get("official_url", ""),
            }
            for entry in top
        ]
        best = recommendations[0]
        return {
            "success": True,
            "need": need,
            "from_kb": len(top),
            "recommendations": recommendations,
            "advice": (
                f"Recommandé : **{best['name']}** ({best['category']}) — {best['why']}. "
                + ("Priorité gratuit/open source. " if wants_free else "")
                + ("Priorité souveraineté/RGPD. " if wants_sovereign else "")
                + "Comparez les avis via billing_product_reviews avant de proposer."
            ),
        }
    except Exception as exc:
        return {"error": str(exc)}


async def add(args: dict[str, Any]) -> dict[str, Any]:
    if not args.get("name"):
        return {"error": "Paramètre 'name' requis."}
    try:
        entry = db.it_kb_upsert(args)
        return {
            "success": True,
            "message": f"« {entry['name']} » enregistré dans la base IT.",
            "tool": entry,
        }
    except Exception as exc:
        return {"error": str(exc)}
