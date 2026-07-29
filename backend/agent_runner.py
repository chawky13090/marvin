"""État explicite et observable de la boucle d'exécution agentique Marvin."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RunnerState:
    started_at: float = field(default_factory=time.monotonic)
    steps_used: int = 0
    stop_reason: str | None = None
    executed_tool_names: set[str] = field(default_factory=set)
    successful_tools: int = 0
    failed_tools: int = 0
    trace: list[str] = field(default_factory=list)
    attempted_calls: list[str] = field(default_factory=list)
    successful_calls: list[dict[str, str]] = field(default_factory=list)
    successful_results: list[dict[str, Any]] = field(default_factory=list)
    blocking_outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    long_chain_reported: bool = False
    nudged: bool = False
    empty_response_nudged: bool = False
    exhausted_tool_budgets: set[str] = field(default_factory=set)

    @property
    def tool_count(self) -> int:
        return self.successful_tools + self.failed_tools

    @property
    def succeeded(self) -> bool:
        return self.failed_tools == 0

    def begin_step(
        self,
        step_index: int,
        max_wall_seconds: int,
        *,
        now: float | None = None,
    ) -> bool:
        current = time.monotonic() if now is None else now
        if step_index > 0 and current - self.started_at >= max_wall_seconds:
            self.stop_reason = "max_wall_seconds"
            return False
        self.steps_used = step_index + 1
        return True

    def record_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        *,
        tooling_failure: bool,
    ) -> bool:
        """Enregistre un résultat et signale une seule fois une chaîne supérieure à 8."""
        self.attempted_calls.append(tool_name)
        self.executed_tool_names.add(tool_name)
        if tooling_failure:
            self.failed_tools += 1
            error = (
                result.get("error") or result.get("stderr") or "échec"
                if isinstance(result, dict)
                else str(result)
            )
            args = json.dumps(arguments, ensure_ascii=False)[:140]
            self.trace.append(f"❌ {tool_name}({args}) → ERREUR: {str(error)[:200]}")
        else:
            self.successful_tools += 1
            self.trace.append(f"✅ {tool_name} OK")
            compact = {key: value for key, value in (arguments or {}).items() if key != "confirmed"}
            self.successful_calls.append({
                "tool": tool_name,
                "args": json.dumps(compact, ensure_ascii=False)[:90] if compact else "",
            })
            if isinstance(result, dict):
                self.successful_results.append({
                    "tool": tool_name,
                    "answer": str(result.get("answer") or "")[:16_000],
                    "code": str(result.get("code") or "")[:500_000],
                    "language": str(result.get("language") or "")[:40],
                    "artifacts": (
                        result.get("artifacts")
                        if isinstance(result.get("artifacts"), dict)
                        else {}
                    ),
                    "sources": [
                        {
                            "title": str(source.get("title") or "")[:300],
                            "url": str(source.get("url") or "")[:2_000],
                        }
                        for source in (result.get("sources") or [])[:50]
                        if isinstance(source, dict)
                    ],
                    "candidates": (
                        [
                            {
                                "name": str(candidate.get("name") or "")[:128],
                                "namespace": str(
                                    candidate.get("namespace") or ""
                                )[:80],
                            }
                            for candidate in (result.get("candidates") or [])[:20]
                            if isinstance(candidate, dict) and candidate.get("name")
                        ]
                        if tool_name == "tool_search"
                        else []
                    ),
                })
        if not self.long_chain_reported and self.tool_count > 8:
            self.long_chain_reported = True
            return True
        return False

    def update_blocking_outcome(self, tool_name: str, result: Any) -> None:
        accepted = (
            isinstance(result, dict)
            and result.get("success") is True
            and (tool_name != "ai_test_forge" or result.get("production_ready") is True)
        )
        if accepted:
            self.blocking_outcomes.pop(tool_name, None)
        else:
            self.blocking_outcomes[tool_name] = (
                result if isinstance(result, dict) else {"error": str(result)}
            )

    def finish_reason(self) -> str:
        if not self.stop_reason:
            self.stop_reason = "max_tool_steps"
        return self.stop_reason

    def successful_call_count(self, tool_name: str) -> int:
        return sum(
            1
            for call in self.successful_calls
            if call.get("tool") == tool_name
        )

    def attempted_call_count(self, tool_name: str) -> int:
        return self.attempted_calls.count(tool_name)

    def budget_usage(self, stop_reason: str | None = None) -> dict[str, Any]:
        return {
            "tool_steps": self.steps_used,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
            "stop_reason": stop_reason or self.stop_reason or "criteria_satisfied",
        }
