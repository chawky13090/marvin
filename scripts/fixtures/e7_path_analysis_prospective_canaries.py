"""Canaris prospectifs generiques geles avant l'analyseur E7 v1.4."""

import os
from pathlib import Path
from typing import Any


def early_return(args: dict[str, Any], root: Path) -> dict[str, Any]:
    if not args.get("confirmed"):
        return {"preview": True}
    root.joinpath("mutation.txt").write_text("mutated", encoding="utf-8")
    return {"success": True}


def nested_action(args: dict[str, Any], root: Path) -> dict[str, Any]:
    action = str(args.get("action") or "status").casefold()
    if action == "status":
        return {"status": "idle"}
    if action != "apply":
        return {"error": "invalid"}
    return _nested_mutation(root)


def _nested_mutation(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    return {"success": True}


def dynamic_guard(args: dict[str, Any], root: Path) -> dict[str, Any]:
    predicate = args["predicate"]
    if predicate():
        root.touch()
    return {"done": True}


def process_observation(pid: int) -> bool:
    return os.path.exists(f"/proc/{pid}")
