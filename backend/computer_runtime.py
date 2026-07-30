"""Façade unifiée de contrôle du poste pour la boucle agentique.

Cette couche ne contourne jamais le gateway. Elle transforme une intention UI
bornée en appels vers les domaines PC/Web existants, puis produit une observation
fraîche permettant au LLM de vérifier l'effet et de poursuivre ou réparer.
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable


Executor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
_executors: dict[str, Executor] = {}

READ_ACTIONS = frozenset({"observe", "verify", "screenshot", "list_windows"})
MUTATING_ACTIONS = frozenset(
    {"open", "focus", "click", "type", "keypress", "scroll", "navigate"}
)
ACTIONS = READ_ACTIONS | MUTATING_ACTIONS


def configure(executors: dict[str, Executor]) -> None:
    required = {
        "pc_app_launch",
        "pc_window_list",
        "pc_window_focus",
        "pc_gui_read",
        "pc_gui_click",
        "pc_gui_type",
        "pc_screenshot",
        "web_browser_open",
    }
    missing = required - set(executors)
    if missing:
        raise RuntimeError(
            "Computer Runtime incomplet : " + ", ".join(sorted(missing))
        )
    _executors.clear()
    _executors.update({name: executors[name] for name in required})


async def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    executor = _executors.get(name)
    if executor is None:
        return {"error": f"Moteur indisponible : {name}"}
    result = await executor(arguments)
    return result if isinstance(result, dict) else {"success": True, "result": result}


async def _observe(window: str, max_elements: int) -> dict[str, Any]:
    if window:
        ui = await _call(
            "pc_gui_read",
            {"window": window, "max_elements": max_elements},
        )
        return {"engine": "windows_uia", "ui": ui}
    windows = await _call("pc_window_list", {})
    return {"engine": "windows_uia", "windows": windows}


def _evidence_text(observation: dict[str, Any]) -> str:
    chunks: list[str] = []
    stack: list[Any] = [observation]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value[:500])
        elif isinstance(value, (str, int, float, bool)):
            chunks.append(str(value))
    return "\n".join(chunks).casefold()


async def execute(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return {
            "error": "Action invalide.",
            "allowed_actions": sorted(ACTIONS),
        }
    window = str(args.get("window") or "").strip()
    surface = str(args.get("surface") or "auto").strip().lower()
    if surface not in {"auto", "desktop", "browser"}:
        return {"error": "surface doit valoir auto, desktop ou browser."}
    expected = str(args.get("expected") or "").strip()
    try:
        max_elements = max(1, min(int(args.get("max_elements", 80)), 100))
    except (TypeError, ValueError):
        return {"error": "max_elements doit être un entier entre 1 et 100."}

    started = time.monotonic()
    before = None
    if action in MUTATING_ACTIONS and bool(args.get("capture_before", True)):
        if surface == "browser" or action == "navigate":
            import web_browser
            before = {
                "engine": "playwright",
                "browser": await web_browser.computer_observe(max_elements),
            }
        else:
            before = await _observe(window, max_elements)

    if action in {"observe", "list_windows"}:
        result = await _observe(window if action == "observe" else "", max_elements)
    elif action == "screenshot":
        result = await _call(
            "pc_screenshot",
            {"embed": bool(args.get("embed", True))},
        )
    elif action == "verify":
        result = await _observe(window, max_elements)
    elif action == "open":
        result = await _call(
            "pc_app_launch",
            {"app_name": str(args.get("target") or "").strip()},
        )
    elif action == "navigate":
        try:
            import web_browser
            result = await web_browser.computer_navigate(
                str(args.get("target") or "").strip()
            )
        except Exception as exc:
            result = {"error": str(exc)}
    elif action == "focus":
        result = await _call(
            "pc_window_focus",
            {"search": window or str(args.get("target") or "").strip()},
        )
    elif action in {"click", "type"} and surface != "browser":
        call_args = {
            "window": window,
            "control_type": str(args.get("control_type") or "").strip(),
            "name": str(args.get("name") or "").strip(),
            "automation_id": str(args.get("automation_id") or "").strip(),
            "match_index": args.get("match_index", 0),
            "confirmed": bool(args.get("confirmed")),
        }
        if action == "type":
            call_args["text"] = str(args.get("text") or "")
        result = await _call(f"pc_gui_{action}", call_args)
    elif action in {"click", "type", "keypress", "scroll"} and surface == "browser":
        try:
            import web_browser
            result = await web_browser.computer_act(
                action,
                control_type=str(args.get("control_type") or ""),
                name=str(args.get("name") or ""),
                match_index=int(args.get("match_index", 0)),
                text=str(args.get("text") or ""),
            )
        except Exception as exc:
            result = {"error": str(exc)}
    else:
        return {
            "error": (
                f"L'action {action} n'est pas disponible pour la surface "
                f"{surface}. Utilisez desktop ou browser explicitement."
            ),
            "capability_status": "degraded",
        }

    after = None
    if action in MUTATING_ACTIONS and not result.get("error"):
        # La navigation Playwright renvoie déjà l'état rendu de la page. Une
        # observation UIA du bureau à ce stade regarderait une autre surface et
        # produirait une fausse vérification négative.
        if action == "navigate" or surface == "browser":
            after = {"engine": "playwright", "browser": result}
        else:
            after = await _observe(window, max_elements)
    observation = after or result
    verified = None
    if expected:
        verified = expected.casefold() in _evidence_text(observation)

    return {
        "success": not bool(result.get("error")),
        "action": action,
        "engine": (
            "playwright"
            if action == "navigate" or surface == "browser"
            else observation.get("engine", "windows_uia")
            if isinstance(observation, dict)
            else "windows_uia"
        ),
        "result": result,
        "before": before,
        "observation": observation,
        "expected": expected or None,
        "verified": verified,
        "needs_repair": verified is False,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }
