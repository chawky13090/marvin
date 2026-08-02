"""Classification autoritaire des flux persistants contenant potentiellement des personnes."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PrivacyStream:
    module: str
    file_pattern: str
    data_class: str
    content_fields: tuple[str, ...]
    subject_selectors: tuple[str, ...]
    export_strategy: str
    erasure_strategy: str


STREAMS: tuple[PrivacyStream, ...] = (
    PrivacyStream("backend/audit.py", "audit.jsonl", "indirect_identifier", (), (), "retention_window", "retention_expiry"),
    PrivacyStream("backend/bug_log.py", "bug_log.jsonl", "indirect_identifier", ("message", "context"), (), "retention_window", "retention_expiry"),
    PrivacyStream("backend/skills.py", "skills_match_log.jsonl", "free_text", ("query",), (), "retention_window", "retention_expiry"),
    PrivacyStream("backend/api_observability.py", "api_requests.jsonl", "indirect_identifier", (), ("trace_id",), "exact_selector", "retention_expiry"),
    PrivacyStream("backend/coding_mission.py", "events.jsonl", "free_text", ("payload",), ("mission_id", "payload.conversation_id"), "owner_or_exact_selector", "owner_delete_or_rechain"),
    PrivacyStream("backend/engineering_radar.py", "events.jsonl", "public_reference", ("payload.url",), ("payload.id",), "exact_selector", "owner_delete_or_rechain"),
    PrivacyStream("backend/mission_os.py", "mission_events.jsonl", "free_text", ("payload.arguments", "payload.result_summary"), ("mission_id", "payload.conversation_id", "payload.action_id"), "exact_selector", "rechain_required"),
    PrivacyStream("backend/forge.py", "forge_runs.jsonl", "free_text", ("response_preview", "checks[].detail"), ("id", "scenario_id"), "exact_selector", "rechain_required"),
    PrivacyStream("backend/frontier_arena.py", "frontier_arena_submissions.jsonl", "free_text", ("answer", "sources", "notes", "evidence"), ("id", "scenario_id"), "exact_selector", "rechain_required"),
    PrivacyStream("backend/frontier_arena.py", "frontier_arena_matches.jsonl", "free_text", ("prompt",), ("id", "scenario_id"), "exact_selector", "rechain_required"),
    PrivacyStream("backend/frontier_arena.py", "frontier_arena_votes.jsonl", "free_text", ("notes",), ("id", "match_id"), "exact_selector", "rechain_required"),
    PrivacyStream("backend/model_market.py", "model_market_observations.jsonl", "technical_metadata", (), ("model",), "exact_selector", "rechain_required"),
    PrivacyStream("backend/research_swarm.py", "research_swarm_runs.jsonl", "free_text", ("question", "answer", "cells", "verification.answer", "synthesis.answer", "sources"), ("id",), "exact_selector", "rechain_required"),
    PrivacyStream("backend/truth_ledger.py", "truth_ledger.jsonl", "free_text", ("claims[].claim", "claims[].sources"), ("id", "conversation_id", "claims[].id"), "exact_selector", "rechain_required"),
)


def public_inventory() -> list[dict[str, object]]:
    """Expose uniquement la classification, jamais les enregistrements métier."""
    return [asdict(stream) for stream in STREAMS]
