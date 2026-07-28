"""Frontier Arena: deterministic, provider-neutral comparison of agent outputs."""
from __future__ import annotations

import math
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import evidence_fabric
import forge
from config import DATA_DIR
from durable_evidence_store import DuplicateEvidenceError, DurableEvidenceStore


SUBMISSIONS_PATH = Path(DATA_DIR) / "frontier_arena_submissions.jsonl"
MATCHES_PATH = Path(DATA_DIR) / "frontier_arena_matches.jsonl"
VOTES_PATH = Path(DATA_DIR) / "frontier_arena_votes.jsonl"
_SUBMISSION_ID = re.compile(r"^arena-[0-9a-f]{12}$")
_MATCH_ID = re.compile(r"^match-[0-9a-f]{12}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(path: Path) -> DurableEvidenceStore:
    if path == SUBMISSIONS_PATH:
        name = "marvin.frontier_arena.submissions"
    elif path == MATCHES_PATH:
        name = "marvin.frontier_arena.matches"
    elif path == VOTES_PATH:
        name = "marvin.frontier_arena.votes"
    else:
        raise ValueError("Chemin de registre Arena inconnu.")
    return DurableEvidenceStore(path, stream_name=name)


def evidence_integrity() -> dict[str, dict[str, Any]]:
    return {
        "submissions": _store(SUBMISSIONS_PATH).verify(),
        "matches": _store(MATCHES_PATH).verify(),
        "votes": _store(VOTES_PATH).verify(),
    }


def _require_valid_evidence(*paths: Path) -> None:
    invalid = [
        _store(path).stream_name
        for path in paths
        if not _store(path).verify()["valid"]
    ]
    if invalid:
        raise RuntimeError(
            "L'intégrité d'un registre Arena est compromise; opération refusée."
        )


def _bounded_int(value: Any, *, name: str, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} doit être un entier.") from exc
    if normalized < 0 or normalized > maximum:
        raise ValueError(f"{name} doit être compris entre 0 et {maximum}.")
    return normalized


def _bounded_cost(value: Any) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Le coût doit être un nombre.") from exc
    if not math.isfinite(normalized) or normalized < 0 or normalized > 1_000_000:
        raise ValueError("Le coût doit être fini et compris entre 0 et 1000000.")
    return normalized


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("Les sources doivent être une liste limitée à 200 éléments.")
    normalized: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("Chaque source Arena doit être un objet.")
        raw_citations = raw.get("citations") or []
        if not isinstance(raw_citations, list) or len(raw_citations) > 50:
            raise ValueError("Les alias d'une source sont limités à 50.")
        url = str(raw.get("url") or "").strip()[:4000]
        if url:
            try:
                parsed = urlparse(url)
                port = parsed.port
            except ValueError as exc:
                raise ValueError("URL de source invalide.") from exc
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or (parsed.scheme == "http" and port not in (None, 80))
                or (parsed.scheme == "https" and port not in (None, 443))
            ):
                raise ValueError("Une source doit utiliser une URL HTTP(S) sans identifiants.")
            url = evidence_fabric.normalize_url(url)
        observed = str(raw.get("excerpt") or raw.get("text") or raw.get("snippet") or "")[:12_000]
        normalized.append({
            "citation": str(raw.get("citation") or raw.get("id") or "")[:80],
            "citations": [str(item)[:80] for item in raw_citations if str(item).strip()],
            "title": str(raw.get("title") or "")[:300],
            "url": url,
            "excerpt": observed,
            "published_at": str(raw.get("published_at") or "")[:80] or None,
        })
    return normalized


def submit(
    *,
    scenario_id: str,
    system: str,
    answer: str,
    sources: list[dict[str, Any]] | None = None,
    duration_ms: int | None = None,
    cost: float | None = None,
    human_interventions: int = 0,
    privacy_violations: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    scenario = forge.get_scenario(scenario_id)
    if scenario is None:
        raise ValueError("Scénario Forge introuvable.")
    system = str(system or "").strip()[:120]
    answer = str(answer or "").strip()
    if not system:
        raise ValueError("Le nom du système est requis.")
    if not answer or len(answer) > 100_000:
        raise ValueError("La réponse est requise et limitée à 100000 caractères.")
    normalized_sources = _normalize_sources(sources)
    normalized_duration = (
        None
        if duration_ms is None
        else _bounded_int(duration_ms, name="duration_ms", maximum=86_400_000)
    )
    normalized_cost = _bounded_cost(cost)
    normalized_interventions = _bounded_int(
        human_interventions,
        name="human_interventions",
        maximum=10_000,
    )
    normalized_privacy = _bounded_int(
        privacy_violations,
        name="privacy_violations",
        maximum=10_000,
    )

    trace_grade = forge.grade_trace(
        scenario,
        [{"type": "text", "content": answer}, {"type": "done"}],
        duration_ms=normalized_duration,
    )
    fabric = evidence_fabric.build_bundle(answer, sources=normalized_sources, reviewed=False)
    expectations = scenario.get("expectations") or {}
    evidence_required = bool(
        expectations.get("required_event_types")
        or expectations.get("required_any_tools")
        or expectations.get("required_tools")
        or (scenario.get("cortex") or {}).get("evidence") in {"web", "primary", "connected"}
    )
    outcome_checks = [
        item for item in trace_grade["checks"]
        if item["name"].startswith(("done", "no_error", "contains:", "excludes:", "max_duration_ms"))
    ]
    outcome_score = (
        sum(bool(item["passed"]) for item in outcome_checks) / len(outcome_checks)
        if outcome_checks else 1.0
    )
    if fabric["claim_count"]:
        citation_coverage = fabric["sourced_count"] / fabric["claim_count"]
        verified_coverage = fabric["lexically_supported_count"] / fabric["claim_count"]
        evidence_score = citation_coverage * 0.6 + verified_coverage * 0.4
    else:
        evidence_score = 1.0
    privacy_score = 1.0 if normalized_privacy <= 0 else 0.0
    quality_score = (
        outcome_score * 0.6
        + (evidence_score * 0.3 if evidence_required else 0.3)
        + privacy_score * 0.1
    )
    success = (
        outcome_score == 1.0
        and normalized_privacy <= 0
        and (not evidence_required or fabric["unsupported_count"] == 0)
    )
    submission = {
        "id": "arena-" + uuid.uuid4().hex[:12],
        "created_at": _utc_now(),
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "system": system,
        "answer": answer,
        "sources": normalized_sources,
        "duration_ms": normalized_duration,
        "cost": normalized_cost,
        "human_interventions": normalized_interventions,
        "privacy_violations": normalized_privacy,
        "notes": str(notes or "")[:1000],
        "success": success,
        "quality_score": round(quality_score, 4),
        "outcome_score": round(outcome_score, 4),
        "evidence_score": round(evidence_score, 4),
        "epistemic_debt": fabric["epistemic_debt"],
        "evidence": fabric,
        "checks": outcome_checks,
    }
    return _store(SUBMISSIONS_PATH).append(submission)


def list_submissions(*, limit: int = 500, scenario_id: str | None = None) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _store(SUBMISSIONS_PATH).recent(100_000)
        if not scenario_id or row.get("scenario_id") == scenario_id
    ]
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[: max(1, min(int(limit), 5000))]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(reversed(_store(path).recent(100_000)))


def _append_jsonl(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    return _store(path).append(row)


def _submission_by_id(submission_id: str) -> dict[str, Any] | None:
    if not _SUBMISSION_ID.fullmatch(str(submission_id or "")):
        return None
    return next((item for item in list_submissions(limit=5000) if item.get("id") == submission_id), None)


def create_blind_match(
    *,
    scenario_id: str | None = None,
    submission_ids: list[str] | None = None,
) -> dict[str, Any]:
    _require_valid_evidence(SUBMISSIONS_PATH, MATCHES_PATH)
    selected: list[dict[str, Any]] = []
    if submission_ids:
        if len(submission_ids) != 2 or submission_ids[0] == submission_ids[1]:
            raise ValueError("Deux soumissions distinctes sont requises.")
        selected = [_submission_by_id(item) for item in submission_ids]
        if any(item is None for item in selected):
            raise ValueError("Une soumission Arena est introuvable.")
    else:
        candidates = list_submissions(limit=5000, scenario_id=scenario_id)
        groups: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            groups.setdefault(str(candidate.get("scenario_id") or ""), []).append(candidate)
        eligible = [
            items
            for items in groups.values()
            if len({str(item.get("system") or "") for item in items}) >= 2
        ]
        if not eligible:
            raise ValueError("Aucune paire de systèmes distincts n'est disponible pour ce scénario.")
        group = secrets.choice(eligible)
        left = secrets.choice(group)
        right = secrets.choice([
            item for item in group if item.get("system") != left.get("system")
        ])
        selected = [left, right]
    left, right = selected
    if left["scenario_id"] != right["scenario_id"]:
        raise ValueError("Un duel doit comparer le même scénario.")
    if left["system"] == right["system"]:
        raise ValueError("Un duel doit comparer deux systèmes distincts.")
    if secrets.randbelow(2):
        left, right = right, left
    scenario = forge.get_scenario(left["scenario_id"])
    if scenario is None:
        raise ValueError("Scénario Forge introuvable.")
    match = {
        "id": "match-" + uuid.uuid4().hex[:12],
        "created_at": _utc_now(),
        "scenario_id": scenario["id"],
        "scenario_name": scenario["name"],
        "prompt": scenario["prompt"],
        "slots": {"A": left["id"], "B": right["id"]},
    }
    _append_jsonl(MATCHES_PATH, match)
    return get_blind_match(match["id"])


def _vote_for_match(match_id: str) -> dict[str, Any] | None:
    return next((item for item in reversed(_read_jsonl(VOTES_PATH)) if item.get("match_id") == match_id), None)


def get_blind_match(match_id: str, *, reveal: bool = False) -> dict[str, Any] | None:
    if not _MATCH_ID.fullmatch(str(match_id or "")):
        return None
    _require_valid_evidence(SUBMISSIONS_PATH, MATCHES_PATH, VOTES_PATH)
    match = next((item for item in _read_jsonl(MATCHES_PATH) if item.get("id") == match_id), None)
    if not match:
        return None
    vote = _vote_for_match(match_id)
    reveal = bool(reveal or vote)
    candidates = {}
    for slot in ("A", "B"):
        submission = _submission_by_id(str((match.get("slots") or {}).get(slot) or ""))
        if not submission:
            continue
        candidates[slot] = {
            "answer": submission["answer"],
            "sources": submission.get("sources") or [],
            **({
                "submission_id": submission["id"],
                "system": submission["system"],
                "quality_score": submission.get("quality_score"),
                "evidence_score": submission.get("evidence_score"),
                "epistemic_debt": submission.get("epistemic_debt"),
            } if reveal else {}),
        }
    return {
        "id": match["id"],
        "created_at": match["created_at"],
        "scenario_id": match["scenario_id"],
        "scenario_name": match["scenario_name"],
        "prompt": match["prompt"],
        "candidates": candidates,
        "voted": bool(vote),
        "vote": vote if reveal else None,
    }


def vote_blind_match(
    match_id: str,
    *,
    winner: str,
    scores: dict[str, dict[str, int]],
    notes: str = "",
) -> dict[str, Any]:
    _require_valid_evidence(SUBMISSIONS_PATH, MATCHES_PATH, VOTES_PATH)
    match = get_blind_match(match_id)
    if not match:
        raise ValueError("Duel Arena introuvable.")
    if match["voted"]:
        raise ValueError("Ce duel a déjà été évalué.")
    winner = str(winner or "").upper()
    if winner not in {"A", "B", "TIE"}:
        raise ValueError("Le gagnant doit être A, B ou TIE.")
    dimensions = ("correctness", "completeness", "evidence", "usefulness")
    if not isinstance(scores, dict) or set(scores) != {"A", "B"}:
        raise ValueError("Les notes doivent contenir exactement les réponses A et B.")
    normalized: dict[str, dict[str, int]] = {}
    for slot in ("A", "B"):
        values = scores.get(slot) if isinstance(scores, dict) else None
        if not isinstance(values, dict):
            raise ValueError(f"Notes manquantes pour la réponse {slot}.")
        normalized[slot] = {}
        for dimension in dimensions:
            value = int(values.get(dimension, 0))
            if value < 1 or value > 5:
                raise ValueError("Chaque note doit être comprise entre 1 et 5.")
            normalized[slot][dimension] = value
    vote = {
        "id": "vote-" + uuid.uuid4().hex[:12],
        "match_id": match_id,
        "created_at": _utc_now(),
        "winner": winner,
        "scores": normalized,
        "notes": str(notes or "")[:1000],
    }
    try:
        _store(VOTES_PATH).append_unique(vote, unique_fields=("match_id",))
    except DuplicateEvidenceError as exc:
        raise ValueError("Ce duel a déjà été évalué.") from exc
    return get_blind_match(match_id, reveal=True)


def blind_stats() -> dict[str, Any]:
    integrity = evidence_integrity()
    if not all(item["valid"] for item in integrity.values()):
        return {"matches": 0, "votes": 0, "pending": 0, "trusted": False}
    matches = _read_jsonl(MATCHES_PATH)
    votes = _read_jsonl(VOTES_PATH)
    return {
        "matches": len(matches),
        "votes": len(votes),
        "pending": max(0, len(matches) - len({item.get("match_id") for item in votes})),
        "trusted": True,
    }


def leaderboard() -> dict[str, Any]:
    integrity = evidence_integrity()
    if not all(item["valid"] for item in integrity.values()):
        return {
            "systems": [],
            "submissions": 0,
            "scenarios": 0,
            "blind": {"matches": 0, "votes": 0, "pending": 0, "trusted": False},
            "evidence_integrity": integrity,
            "blocked_reason": "arena_evidence_integrity_invalid",
        }
    rows = list_submissions(limit=5000)
    submissions_by_id = {
        str(item.get("id") or ""): item for item in rows if item.get("id")
    }
    matches = {item["id"]: item for item in _read_jsonl(MATCHES_PATH) if item.get("id")}
    votes = _read_jsonl(VOTES_PATH)
    human: dict[str, dict[str, float]] = {}
    for vote in votes:
        match = matches.get(str(vote.get("match_id") or ""))
        if not match:
            continue
        winner = vote.get("winner")
        for slot in ("A", "B"):
            submission = submissions_by_id.get(
                str((match.get("slots") or {}).get(slot) or "")
            )
            if not submission:
                continue
            stats = human.setdefault(submission["system"], {"matches": 0, "wins": 0, "score": 0.0})
            stats["matches"] += 1
            stats["wins"] += 1 if winner == slot else 0.5 if winner == "TIE" else 0
            values = (vote.get("scores") or {}).get(slot) or {}
            stats["score"] += sum(float(values.get(key) or 0) for key in (
                "correctness", "completeness", "evidence", "usefulness"
            )) / 20
    systems: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        systems.setdefault(str(row.get("system") or "unknown"), []).append(row)
    ranking = []
    for system, items in systems.items():
        count = len(items)
        durations = [int(item["duration_ms"]) for item in items if item.get("duration_ms") is not None]
        costs = [float(item["cost"]) for item in items if item.get("cost") is not None]
        human_stats = human.get(system) or {"matches": 0, "wins": 0, "score": 0.0}
        quality = round(sum(float(item.get("quality_score") or 0) for item in items) / count, 4)
        qualified_human = (
            round(human_stats["score"] / human_stats["matches"], 4)
            if human_stats["matches"] >= 3 else None
        )
        ranking.append({
            "system": system,
            "submissions": count,
            "scenarios": len({item.get("scenario_id") for item in items}),
            "success_rate": round(sum(bool(item.get("success")) for item in items) / count, 4),
            "quality_score": quality,
            "evidence_score": round(sum(float(item.get("evidence_score") or 0) for item in items) / count, 4),
            "epistemic_debt": round(
                sum(float((item.get("epistemic_debt") or {}).get("score") or 0) for item in items) / count, 4
            ),
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "avg_cost": round(sum(costs) / len(costs), 4) if costs else None,
            "human_interventions": sum(int(item.get("human_interventions") or 0) for item in items),
            "privacy_violations": sum(int(item.get("privacy_violations") or 0) for item in items),
            "blind_matches": int(human_stats["matches"]),
            "blind_win_rate": round(human_stats["wins"] / human_stats["matches"], 4) if human_stats["matches"] else None,
            "human_score": round(human_stats["score"] / human_stats["matches"], 4) if human_stats["matches"] else None,
            "qualified_human_score": qualified_human,
            "arena_score": round(quality * 0.7 + qualified_human * 0.3, 4) if qualified_human is not None else quality,
        })
    ranking.sort(
        key=lambda item: (
            -item["success_rate"],
            -item["arena_score"],
            item["epistemic_debt"],
            item["avg_duration_ms"] if item["avg_duration_ms"] is not None else 10**12,
        )
    )
    return {
        "systems": ranking,
        "submissions": len(rows),
        "scenarios": len({row.get("scenario_id") for row in rows}),
        "blind": blind_stats(),
        "evidence_integrity": integrity,
    }
