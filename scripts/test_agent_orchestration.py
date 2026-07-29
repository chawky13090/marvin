"""Contrat de la façade commutable des orchestrateurs Marvin."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_orchestration import (  # noqa: E402
    OrchestratorMode,
    configured_mode,
    dispatch_agent,
    request_mode,
    resolve_mode,
)


def encode_event(event: dict[str, object]) -> str:
    return json.dumps(event, sort_keys=True)


async def collect(mode: OrchestratorMode, *, native=False, shadow=False):
    calls: list[str] = []

    async def deterministic_runner():
        calls.append("deterministic")
        yield "deterministic:event"

    async def native_runner():
        calls.append("native")
        yield "native:event"

    async def shadow_runner():
        calls.append("shadow")
        yield "shadow:event"

    events = [
        item
        async for item in dispatch_agent(
            deterministic_factory=deterministic_runner,
            native_factory=native_runner if native else None,
            shadow_factory=shadow_runner if shadow else None,
            encode_event=encode_event,
            requested=mode,
        )
    ]
    await asyncio.sleep(0)
    return calls, events


async def main() -> None:
    assert configured_mode({}) is OrchestratorMode.DETERMINISTIC
    assert configured_mode({"MARVIN_ORCHESTRATOR": "invalid"}) is OrchestratorMode.DETERMINISTIC
    assert configured_mode(
        {"MARVIN_ORCHESTRATOR": "llm_native_shadow"}
    ) is OrchestratorMode.LLM_NATIVE_SHADOW
    assert request_mode(
        ultra_unrestricted=False,
        environ={},
    ) is OrchestratorMode.DETERMINISTIC
    assert request_mode(
        ultra_unrestricted=True,
        environ={},
    ) is OrchestratorMode.LLM_NATIVE_CANARY
    assert request_mode(
        ultra_unrestricted=True,
        environ={"MARVIN_ORCHESTRATOR": "deterministic"},
    ) is OrchestratorMode.DETERMINISTIC

    unavailable = resolve_mode(
        OrchestratorMode.LLM_NATIVE,
        native_available=False,
        shadow_available=False,
    )
    assert unavailable.effective is OrchestratorMode.DETERMINISTIC
    assert unavailable.degraded is True

    calls, events = await collect(OrchestratorMode.DETERMINISTIC)
    assert calls == ["deterministic"]
    assert events[-1] == "deterministic:event"

    calls, events = await collect(
        OrchestratorMode.LLM_NATIVE_SHADOW,
        shadow=True,
    )
    assert sorted(calls) == ["deterministic", "shadow"]
    assert "shadow:event" not in events
    assert events[-1] == "deterministic:event"

    calls, events = await collect(OrchestratorMode.LLM_NATIVE, native=True)
    assert calls == ["native"]
    assert events[-1] == "native:event"

    calls, events = await collect(OrchestratorMode.LLM_NATIVE)
    assert calls == ["deterministic"]
    assert json.loads(events[0])["degraded"] is True

    print("OK - façade d'orchestration commutable, shadow isolé et repli fermé")


if __name__ == "__main__":
    asyncio.run(main())
