"""Régressions du lot d'outils PARALLÈLE (v2.525).

Avant cette tranche, `execute_tool_batch` exécutait tout séquentiellement, même
les appels manifestement indépendants (ex. lire 3 fichiers, faire 2 recherches
web). `is_parallel_batch_eligible` (agent_tool_dispatch.py) borne strictement le
périmètre : seuls des lots d'au moins 2 appels, dont AUCUN ne figure dans
`ALWAYS_CONFIRM_TOOLS`, sont éligibles — ce qui exclut par construction toute
collision avec le flux d'approbation (une seule approbation active par
conversation, v2.522) et toute relecture modèle concurrente (`critique_action`
n'est invoqué que pour les outils dangereux).

Ces tests prouvent, avec de vraies latences qui se chevauchent (pas de mock
instantané), que l'exécution est réellement concurrente, que l'ordre de
finalisation reste l'ordre D'ORIGINE même quand l'ordre de complétion diffère,
et que le lot bascule en séquentiel dès qu'un seul appel dangereux y figure.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_tool_batch import execute_tool_batch
import tool_activity


class Runner:
    def __init__(self) -> None:
        self.tool_count = 0
        self.seen_order: list[str] = []

    def update_blocking_outcome(self, name, result) -> None:
        pass

    def record_tool(self, name, arguments, result, *, tooling_failure) -> bool:
        self.tool_count += 1
        self.seen_order.append(name)
        return False


def _call(name: str, **arguments) -> dict:
    return {"function": {"name": name, "arguments": arguments}}


def _harness(*, latencies: dict[str, float], messages: list, persisted: list,
             runner: Runner, tool_timeout_seconds: float | None = None):
    """Construit les callbacks communs, paramétrés par une latence PAR OUTIL —
    c'est ce qui permet de prouver le chevauchement réel des exécutions."""
    started_at: dict[str, float] = {}
    finished_at: dict[str, float] = {}

    async def dispatch(request, *, validate, execute):
        return SimpleNamespace(
            result=await execute(request.name, request.arguments, None, None),
            arguments=request.arguments,
        )

    async def execute(name, arguments, _conversation_id, _request_id):
        started_at[name] = time.monotonic()
        await tool_activity.emit("running", f"Exécution {name}")
        await asyncio.sleep(latencies.get(name, 0.05))
        finished_at[name] = time.monotonic()
        return {"success": True, "tool": name, "args": arguments}

    async def postprocess(**kwargs):
        return kwargs["result"]

    async def observe(_value):
        return None

    return dict(
        assistant_content="Je lis plusieurs sources.",
        ollama_messages=messages,
        conversation_id="conv",
        request_id="request",
        user_query="lis ces fichiers",
        active_model="cloud:model",
        permission_level=2,
        explicit_tool_names=set(),
        required_tool_names=set(),
        command_text_only=False,
        read_signatures=set(),
        runner_state=runner,
        dangerous_tools={"file_delete"},
        prepare_tool_call=lambda name, arguments: SimpleNamespace(
            name=name, arguments=dict(arguments), read_signature="",
        ),
        inject_internal_context=lambda _name, arguments, conversation_id: dict(arguments),
        dispatch_tool=dispatch,
        validate_tool_args=lambda _name, _arguments: None,
        execute_registered_tool=execute,
        postprocess_tool_result=postprocess,
        critique_action=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("critique_action ne doit jamais être appelée pour un lot parallèle")
        ),
        scan_document=lambda *_a, **_k: [],
        record_tool_observation=observe,
        record_long_chain=lambda *_a, **_k: None,
        is_tooling_failure=lambda _result: False,
        compact_tool_result=lambda result, **_k: f"compact:{result.get('tool')}",
        create_message=lambda *args, **kwargs: persisted.append((args, kwargs)),
        id_factory=None,
        clock=time.time,
        tool_timeout_seconds=tool_timeout_seconds,
    ), started_at, finished_at


async def _check_real_concurrency() -> None:
    """Trois appels de 0,3 s chacun : séquentiel prendrait ~0,9 s, parallèle ~0,3 s."""
    messages: list = []
    persisted: list = []
    runner = Runner()
    kwargs, started_at, finished_at = _harness(
        latencies={"web_search": 0.3, "file_find": 0.3, "memory_list": 0.3},
        messages=messages, persisted=persisted, runner=runner,
    )
    tool_calls = [_call("web_search"), _call("file_find"), _call("memory_list")]

    wall_start = time.monotonic()
    events = [event async for event in execute_tool_batch(tool_calls=tool_calls, **kwargs)]
    wall_elapsed = time.monotonic() - wall_start

    assert wall_elapsed < 0.6, (
        f"exécution en {wall_elapsed:.2f}s : pas réellement concurrente (attendu < 0,6s pour "
        "3 appels de 0,3s, séquentiel aurait pris ~0,9s)"
    )
    # Chevauchement direct : le 2e appel démarre AVANT que le 1er ne finisse.
    names = ["web_search", "file_find", "memory_list"]
    assert all(name in started_at and name in finished_at for name in names)
    overlaps = any(
        started_at[b] < finished_at[a]
        for a in names for b in names if a != b
    )
    assert overlaps, "aucun chevauchement détecté : les appels se sont exécutés l'un après l'autre"

    starts = [event for event in events if event["type"] == "tool_start"]
    ends = [event for event in events if event["type"] == "tool_end"]
    assert [e["toolName"] for e in starts] == names, "tool_start doit suivre l'ordre d'origine"
    assert {e["toolName"] for e in ends} == set(names)
    assert len(persisted) == 1 + len(names)  # 1 message assistant + 1 par outil


async def _check_finalization_respects_original_order_even_when_completion_differs() -> None:
    """web_search (lent) est demandé AVANT file_find (rapide) : file_find termine
    en premier, mais les messages envoyés au modèle doivent rester dans l'ordre
    DEMANDÉ — Ollama ne relie un résultat à son appel que par la position."""
    messages: list = []
    persisted: list = []
    runner = Runner()
    kwargs, _started, _finished = _harness(
        latencies={"web_search": 0.25, "file_find": 0.02},
        messages=messages, persisted=persisted, runner=runner,
    )
    tool_calls = [_call("web_search"), _call("file_find")]

    events = [event async for event in execute_tool_batch(tool_calls=tool_calls, **kwargs)]

    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert [m["content"] for m in tool_messages] == [
        "compact:web_search", "compact:file_find"
    ], "l'ordre des messages tool doit suivre l'ordre DEMANDÉ, pas l'ordre de complétion"

    ends = [event for event in events if event["type"] == "tool_end"]
    assert [e["toolName"] for e in ends] == ["web_search", "file_find"]
    assert runner.seen_order == ["web_search", "file_find"], (
        "record_tool doit aussi être appelé dans l'ordre d'origine"
    )


async def _check_ineligible_batch_stays_sequential() -> None:
    """Un seul outil dangereux dans le lot désactive tout le parallélisme du lot."""
    messages: list = []
    persisted: list = []
    runner = Runner()
    kwargs, started_at, finished_at = _harness(
        latencies={"web_search": 0.15, "file_delete": 0.15},
        messages=messages, persisted=persisted, runner=runner,
    )
    # file_delete est un outil dangereux : le lot entier doit rester séquentiel,
    # même web_search qui serait sûr seul.
    tool_calls = [_call("web_search"), _call("file_delete", confirmed=True)]

    wall_start = time.monotonic()
    events = [event async for event in execute_tool_batch(tool_calls=tool_calls, **kwargs)]
    wall_elapsed = time.monotonic() - wall_start

    assert wall_elapsed >= 0.28, (
        f"exécuté en {wall_elapsed:.2f}s : un lot contenant un outil dangereux "
        "ne doit JAMAIS s'exécuter en parallèle"
    )
    assert finished_at["web_search"] <= started_at["file_delete"] or (
        started_at["file_delete"] >= finished_at["web_search"]
    ), "le second appel ne doit démarrer qu'après la fin du premier (séquentiel)"


async def _check_group_timeout_cancels_remaining() -> None:
    """Le budget du tour expire pendant l'exécution : les appels encore actifs
    sont annulés proprement, jamais laissés orphelins.

    `execute_tool_batch` impose un PLANCHER de 1,0 s sur `tool_timeout_seconds`
    (`max(1.0, min(...))`, comportement préexistant, pas introduit ici) : le
    scénario doit donc dépasser ce plancher pour être significatif.
    """
    messages: list = []
    persisted: list = []
    runner = Runner()
    kwargs, _started, _finished = _harness(
        latencies={"web_search": 0.05, "file_find": 5.0},
        messages=messages, persisted=persisted, runner=runner,
        tool_timeout_seconds=1.2,
    )
    tool_calls = [_call("web_search"), _call("file_find")]

    wall_start = time.monotonic()
    events = [event async for event in execute_tool_batch(tool_calls=tool_calls, **kwargs)]
    wall_elapsed = time.monotonic() - wall_start

    assert wall_elapsed < 2.0, f"le timeout de groupe n'a pas annulé l'appel lent ({wall_elapsed:.2f}s)"
    ends = {e["toolName"]: e for e in events if e["type"] == "tool_end"}
    assert ends["file_find"]["result"].get("timeout") is True
    assert ends["web_search"]["result"].get("timeout") is not True


async def _run_all() -> None:
    await _check_real_concurrency()
    await _check_finalization_respects_original_order_even_when_completion_differs()
    await _check_ineligible_batch_stays_sequential()
    await _check_group_timeout_cancels_remaining()


def main() -> int:
    asyncio.run(_run_all())
    print(
        "Agent Tool Batch Parallel OK - concurrence reelle prouvee, ordre "
        "d'origine preserve, lot dangereux reste sequentiel, timeout de groupe "
        "annule proprement."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
