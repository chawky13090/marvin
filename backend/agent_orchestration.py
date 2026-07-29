"""Façade commutable des orchestrateurs Marvin.

Ce module ne choisit ni outil ni stratégie métier. Il sélectionne uniquement une
implémentation d'orchestrateur à partir d'une configuration explicite, avec un repli
fermé vers le chemin déterministe tant que le runtime LLM natif n'est pas disponible.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from enum import StrEnum
from typing import AsyncIterator, Callable


class OrchestratorMode(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_NATIVE_SHADOW = "llm_native_shadow"
    LLM_NATIVE_CANARY = "llm_native_canary"
    LLM_NATIVE = "llm_native"


@dataclass(frozen=True, slots=True)
class OrchestratorResolution:
    requested: OrchestratorMode
    effective: OrchestratorMode
    degraded: bool = False
    reason: str = ""

    def event(self) -> dict[str, object]:
        return {
            "type": "orchestration_mode",
            "requested": self.requested.value,
            "effective": self.effective.value,
            "degraded": self.degraded,
            "reason": self.reason,
        }


RunnerFactory = Callable[[], AsyncIterator[str]]
EventEncoder = Callable[[dict[str, object]], str]
_SHADOW_TASKS: set[asyncio.Task[None]] = set()


def configured_mode(environ: dict[str, str] | None = None) -> OrchestratorMode:
    source = os.environ if environ is None else environ
    raw = str(source.get("MARVIN_ORCHESTRATOR") or "deterministic").strip().lower()
    try:
        return OrchestratorMode(raw)
    except ValueError:
        return OrchestratorMode.DETERMINISTIC


def resolve_mode(
    requested: OrchestratorMode,
    *,
    native_available: bool,
    shadow_available: bool,
) -> OrchestratorResolution:
    if requested is OrchestratorMode.DETERMINISTIC:
        return OrchestratorResolution(requested, requested)
    if requested is OrchestratorMode.LLM_NATIVE_SHADOW:
        if shadow_available:
            return OrchestratorResolution(
                requested,
                OrchestratorMode.DETERMINISTIC,
                reason="shadow_observes_without_user_visible_effects",
            )
        return OrchestratorResolution(
            requested,
            OrchestratorMode.DETERMINISTIC,
            degraded=True,
            reason="shadow_runtime_unavailable",
        )
    if native_available:
        return OrchestratorResolution(requested, requested)
    return OrchestratorResolution(
        requested,
        OrchestratorMode.DETERMINISTIC,
        degraded=True,
        reason="native_runtime_unavailable",
    )


async def _consume_shadow(factory: RunnerFactory) -> None:
    """Consomme un shadow run sans jamais propager ses événements au client."""
    try:
        async for _event in factory():
            pass
    except asyncio.CancelledError:
        raise
    except Exception:
        # La télémétrie structurée du runtime shadow enregistrera l'incident. La façade
        # ne doit jamais casser la réponse de production à cause d'une comparaison.
        return


def _start_shadow(factory: RunnerFactory) -> None:
    task = asyncio.create_task(_consume_shadow(factory))
    _SHADOW_TASKS.add(task)
    task.add_done_callback(_SHADOW_TASKS.discard)


async def dispatch_agent(
    *,
    deterministic_factory: RunnerFactory,
    encode_event: EventEncoder,
    native_factory: RunnerFactory | None = None,
    shadow_factory: RunnerFactory | None = None,
    requested: OrchestratorMode | None = None,
) -> AsyncIterator[str]:
    """Route un tour sans élargir silencieusement les capacités disponibles."""
    selected = requested or configured_mode()
    resolution = resolve_mode(
        selected,
        native_available=native_factory is not None,
        shadow_available=shadow_factory is not None,
    )
    yield encode_event(resolution.event())

    if selected is OrchestratorMode.LLM_NATIVE_SHADOW and shadow_factory is not None:
        _start_shadow(shadow_factory)

    if resolution.effective in {
        OrchestratorMode.LLM_NATIVE,
        OrchestratorMode.LLM_NATIVE_CANARY,
    } and native_factory is not None:
        async for event in native_factory():
            yield event
        return

    async for event in deterministic_factory():
        yield event

