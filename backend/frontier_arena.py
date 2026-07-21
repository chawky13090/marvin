"""Frontier Arena: deterministic, provider-neutral comparison of agent outputs."""
from __future__ import annotations

import json
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evidence_fabric
import forge
from config import DATA_DIR


SUBMISSIONS_PATH = Path(DATA_DIR) / "frontier_arena_submissions.jsonl"
MATCHES_PATH = Path(DATA_DIR) / "frontier_arena_matches.jsonl"
VOTES_PATH = Path(DATA_DIR) / "frontier_arena_votes.jsonl"
_LOCK = threading.RLock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

    trace_grade = forge.grade_trace(
        scenario,
        [{"type": "text", "content": answer}, {"type": "done"}],
        duration_ms=duration_ms,
    )
    fabric = evidence_fabric.build_bundle(answer, sources=sources, reviewed=False)
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
    privacy_score = 1.0 if privacy_violations <= 0 else 0.0
    quality_score = (
        outcome_score * 0.6
        + (evidence_score * 0.3 if evidence_required else 0.3)
        + privacy_score * 0.1
    )
    success = (
        outcome_score == 1.0
        and privacy_violations <= 0
        and (not evidence_required or fabric["unsupported_count"] == 0)
    )
    submission = {
        "id": "arena-" + uuid.uuid4().hex[:12],
        "created_at": _utc_now(),
        "scenario_id": scenario_id,
        "scenario_name": scenario["name"],
        "system": system,
        "answer": answer,
        "sources": sources or [],
        "duration_ms": duration_ms,
        "cost": cost,
        "human_interventions": max(0, int(human_interventions)),
        "privacy_violations": max(0, int(privacy_violations)),
        "notes": str(notes or "")[:1000],
        "success": success,
        "quality_score": round(quality_score, 4),
        "outcome_score": round(outcome_score, 4),
        "evidence_score": round(evidence_score, 4),
        "epistemic_debt": fabric["epistemic_debt"],
        "evidence": fabric,
        "checks": outcome_checks,
    }
    SUBMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, SUBMISSIONS_PATH.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(submission, ensure_ascii=False) + "\n")
    return submission


def list_submissions(*, limit: int = 500, scenario_id: str | None = None) -> list[dict[str, Any]]:
    if not SUBMISSIONS_PATH.exists():
        return []
    rows = []
    with _LOCK:
        for line in SUBMISSIONS_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if scenario_id and row.get("scenario_id") != scenario_id:
                continue
            rows.append(row)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[: max(1, min(int(limit), 5000))]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with _LOCK:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _submission_by_id(submission_id: str) -> dict[str, Any] | None:
    return next((item for item in list_submissions(limit=5000) if item.get("id") == submission_id), None)


def create_blind_match(
    *,
    scenario_id: str | None = None,
    submission_ids: list[str] | None = None,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    if submission_ids:
        if len(submission_ids) != 2 or submission_ids[0] == submission_ids[1]:
            raise ValueError("Deux soumissions distinctes sont requises.")
        selected = [_submission_by_id(item) for item in submission_ids]
        if any(item is None for item in selected):
            raise ValueError("Une soumission Arena est introuvable.")
    else:
        candidates = list_submissions(limit=5000, scenario_id=scenario_id)
        pairs = [
            (left, right)
            for index, left in enumerate(candidates)
            for right in candidates[index + 1:]
            if left.get("scenario_id") == right.get("scenario_id")
            and left.get("system") != right.get("system")
        ]
        if not pairs:
            raise ValueError("Aucune paire de systèmes distincts n'est disponible pour ce scénario.")
        selected = list(secrets.choice(pairs))
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
    match = get_blind_match(match_id)
    if not match:
        raise ValueError("Duel Arena introuvable.")
    if match["voted"]:
        raise ValueError("Ce duel a déjà été évalué.")
    winner = str(winner or "").upper()
    if winner not in {"A", "B", "TIE"}:
        raise ValueError("Le gagnant doit être A, B ou TIE.")
    dimensions = ("correctness", "completeness", "evidence", "usefulness")
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
    _append_jsonl(VOTES_PATH, vote)
    return get_blind_match(match_id, reveal=True)


def blind_stats() -> dict[str, Any]:
    matches = _read_jsonl(MATCHES_PATH)
    votes = _read_jsonl(VOTES_PATH)
    return {
        "matches": len(matches),
        "votes": len(votes),
        "pending": max(0, len(matches) - len({item.get("match_id") for item in votes})),
    }


def leaderboard() -> dict[str, Any]:
    rows = list_submissions(limit=5000)
    matches = {item["id"]: item for item in _read_jsonl(MATCHES_PATH) if item.get("id")}
    votes = _read_jsonl(VOTES_PATH)
    human: dict[str, dict[str, float]] = {}
    for vote in votes:
        match = matches.get(str(vote.get("match_id") or ""))
        if not match:
            continue
        winner = vote.get("winner")
        for slot in ("A", "B"):
            submission = _submission_by_id(str((match.get("slots") or {}).get(slot) or ""))
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
    }
