"""Outils de fiches de revision et repetition espacee."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import database as db


Generate = Callable[..., Awaitable[str]]


async def generate(args: dict[str, Any], generate_text: Generate) -> dict[str, Any]:
    topic = str(args.get("topic") or "").strip()
    if not topic:
        return {"error": "Paramètre 'topic' requis (ex: 'Modèle OSI', 'Sous-réseaux IPv4')."}
    try:
        count = max(1, min(int(args.get("count", 5)), 15))
    except (TypeError, ValueError):
        return {"error": "Paramètre 'count' invalide : entier attendu entre 1 et 15."}
    prompt = (
        f"Sujet : {topic}\n\n"
        f"Génère exactement {count} questions de révision de niveau technique (type certification "
        "informatique), avec leur réponse concise et correcte. Réponds UNIQUEMENT en JSON, une liste "
        "d'objets {\"question\": \"...\", \"answer\": \"...\"} — rien d'autre, pas de texte autour."
    )
    try:
        raw = await generate_text(prompt, model=args.get("model"), timeout=90)
    except Exception as exc:
        return {"error": f"Génération impossible : {exc}"}
    match = re.search(r"\[.*\]", raw or "", re.S)
    if not match:
        return {"error": "Réponse du modèle non exploitable (pas de JSON trouvé) — réessaie."}
    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError) as exc:
        return {"error": f"JSON invalide généré par le modèle : {exc}"}
    if not isinstance(items, list):
        return {"error": "Réponse du modèle invalide : une liste JSON est attendue."}

    created: list[dict[str, Any]] = []
    for item in items[:count]:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if question and answer:
            created.append(db.create_flashcard(topic, question, answer))
    if not created:
        return {"error": "Aucune fiche exploitable générée — réessaie ou reformule le sujet."}
    return {
        "success": True,
        "topic": topic,
        "count": len(created),
        "cards": created,
        "message": f"{len(created)} fiche(s) créée(s) sur « {topic} », disponibles via quiz_next.",
    }


async def next_card(args: dict[str, Any]) -> dict[str, Any]:
    topic = str(args.get("topic") or "").strip() or None
    card = db.get_next_flashcard(topic)
    if not card:
        return {
            "success": True,
            "card": None,
            "message": "Aucune fiche" + (f" pour « {topic} »" if topic else "") + " — crée-en avec quiz_generate.",
        }
    return {
        "success": True,
        "card": {"id": card["id"], "topic": card["topic"], "question": card["question"]},
        "message": f"Question ({card['topic']}) : {card['question']}",
    }


async def answer(args: dict[str, Any]) -> dict[str, Any]:
    flashcard_id = str(args.get("id") or "").strip()
    correct = bool(args.get("correct"))
    if not flashcard_id:
        return {"error": "Paramètre 'id' requis (voir quiz_next)."}
    updated = db.answer_flashcard(flashcard_id, correct)
    if not updated:
        return {"error": "Fiche introuvable — vérifie l'id renvoyé par quiz_next."}
    return {
        "success": True,
        "correct": correct,
        "correct_answer": updated["answer"],
        "next_review_in_days": updated["interval_days"],
        "message": (
            f"{'✅ Correct' if correct else '❌ Incorrect'} — réponse attendue : {updated['answer']}. "
            f"Prochaine révision dans {updated['interval_days']} jour(s)."
        ),
    }


async def stats(_args: dict[str, Any]) -> dict[str, Any]:
    values = db.flashcard_stats()
    if not values:
        return {
            "success": True,
            "topics": [],
            "message": "Aucune fiche de révision créée pour l'instant.",
        }
    return {
        "success": True,
        "topics": values,
        "message": (
            f"{len(values)} sujet(s) de révision, "
            f"{sum(value.get('due_now') or 0 for value in values)} fiche(s) due(s) maintenant."
        ),
    }
