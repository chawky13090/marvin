"""Canal contextuel borné pour publier l'activité réelle d'un outil.

Le canal ne persiste rien et ne transporte ni prompt, ni résultat, ni secret. Le
superviseur agentique lie un récepteur à la durée exacte d'un appel d'outil.
"""

from __future__ import annotations

import contextvars
import inspect
from contextlib import contextmanager
from typing import Any, Callable, Iterator


ProgressSink = Callable[[dict[str, Any]], Any]
_SINK: contextvars.ContextVar[ProgressSink | None] = contextvars.ContextVar(
    "marvin_tool_progress_sink",
    default=None,
)
_ALLOWED_STAGES = {
    "planning",
    "searching",
    "reading",
    "checking",
    "synthesizing",
    "testing",
    "repairing",
    "waiting",
}


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize(event: dict[str, Any]) -> dict[str, Any]:
    """Retourne un événement UI minimal, typé et sans charge arbitraire."""
    stage = _bounded_text(event.get("stage"), 32).lower()
    if stage not in _ALLOWED_STAGES:
        stage = "waiting"
    try:
        current = max(0, int(event.get("current") or 0))
    except (TypeError, ValueError):
        current = 0
    try:
        total = max(0, int(event.get("total") or 0))
    except (TypeError, ValueError):
        total = 0
    if total:
        current = min(current, total)
    metrics: dict[str, int] = {}
    for key, value in dict(event.get("metrics") or {}).items():
        safe_key = _bounded_text(key, 32)
        if not safe_key or len(metrics) >= 8:
            break
        try:
            metrics[safe_key] = max(0, min(int(value), 10_000_000))
        except (TypeError, ValueError):
            continue
    return {
        "stage": stage,
        "label": _bounded_text(event.get("label"), 160) or "Travail en cours",
        "detail": _bounded_text(event.get("detail"), 240),
        "current": current,
        "total": total,
        "metrics": metrics,
    }


@contextmanager
def bind(sink: ProgressSink) -> Iterator[None]:
    token = _SINK.set(sink)
    try:
        yield
    finally:
        _SINK.reset(token)


async def emit(
    stage: str,
    label: str,
    *,
    detail: str = "",
    current: int = 0,
    total: int = 0,
    metrics: dict[str, int] | None = None,
) -> None:
    sink = _SINK.get()
    if sink is None:
        return
    result = sink(normalize({
        "stage": stage,
        "label": label,
        "detail": detail,
        "current": current,
        "total": total,
        "metrics": metrics or {},
    }))
    if inspect.isawaitable(result):
        await result
