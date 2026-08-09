"""Opérateur Windows typé compilant une intention vers un exécuteur connu.

Le LLM choisit une action et des paramètres métier. Ce module refuse toute
commande libre, appelle un exécuteur déjà enregistré, puis vérifie une
postcondition indépendante avant d'annoncer la réussite.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Awaitable, Callable


Executor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

READ_ACTIONS = frozenset(
    {
        "process.list",
        "service.list",
        "security.firewall.status",
        "network.status",
        "software.list",
    }
)
MUTATING_ACTIONS = frozenset(
    {
        "application.launch",
        "process.stop",
        "filesystem.create_folder",
        "filesystem.rename",
        "filesystem.copy",
    }
)
ACTIONS = READ_ACTIONS | MUTATING_ACTIONS

_EXECUTOR_BY_ACTION = {
    "process.list": "pc_process_list",
    "application.launch": "pc_app_launch",
    "process.stop": "pc_process_kill",
    "service.list": "win_services_list",
    "security.firewall.status": "win_firewall_status",
    "network.status": "win_network_config",
    "software.list": "winget_list_installed",
    "filesystem.create_folder": "file_create_folder",
    "filesystem.rename": "file_rename",
    "filesystem.copy": "file_copy",
}
_executors: dict[str, Executor] = {}


def configure(executors: dict[str, Executor]) -> None:
    required = set(_EXECUTOR_BY_ACTION.values())
    missing = required - set(executors)
    if missing:
        raise RuntimeError(
            "Windows Task incomplet : " + ", ".join(sorted(missing))
        )
    _executors.clear()
    _executors.update({name: executors[name] for name in required})


def _required_text(args: dict[str, Any], field: str) -> str:
    value = str(args.get(field) or "").strip()
    if not value:
        raise ValueError(f"Paramètre '{field}' requis pour cette action.")
    return value


def _compile(action: str, args: dict[str, Any]) -> dict[str, Any]:
    if action in READ_ACTIONS:
        return {}
    if action == "application.launch":
        return {"app_name": _required_text(args, "target")}
    if action == "process.stop":
        pid = args.get("pid")
        name = str(args.get("name") or "").strip()
        if pid in (None, "") and not name:
            raise ValueError("Paramètre 'pid' ou 'name' requis pour process.stop.")
        compiled: dict[str, Any] = {"confirmed": bool(args.get("confirmed"))}
        if pid not in (None, ""):
            try:
                compiled["pid"] = int(pid)
            except (TypeError, ValueError) as exc:
                raise ValueError("Paramètre 'pid' invalide : entier attendu.") from exc
            if compiled["pid"] <= 0:
                raise ValueError("Paramètre 'pid' invalide : entier positif attendu.")
        if name:
            compiled["name"] = name
        return compiled
    if action == "filesystem.create_folder":
        return {"path": _required_text(args, "target")}
    if action in {"filesystem.rename", "filesystem.copy"}:
        return {
            "source": _required_text(args, "source"),
            "destination": _required_text(args, "destination"),
        }
    raise ValueError(f"Action Windows inconnue : {action}")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(
    action: str,
    compiled: dict[str, Any],
    result: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if result.get("error") or result.get("requiresConfirmation"):
        return False, {"state": "executor_rejected"}
    if action == "process.list":
        count = int(result.get("count") or 0)
        return count > 0, {"process_count": count}
    if action == "application.launch":
        verified = result.get("verified") is True
        return verified, {"application_verified": verified}
    if action == "process.stop":
        state = str((result.get("verification") or {}).get("state") or "")
        return state == "absent", {"process_state": state or "unknown"}
    if action == "service.list":
        count = int(result.get("count") or 0)
        return count > 0, {"service_count": count}
    if action == "security.firewall.status":
        count = len(result.get("profiles") or [])
        return count >= 3, {"profile_count": count}
    if action == "network.status":
        count = int(result.get("count") or 0)
        return count > 0, {"adapter_count": count}
    if action == "software.list":
        count = int(result.get("count") or 0)
        return count > 0, {"software_count": count}
    if action == "filesystem.create_folder":
        path = Path(str(result.get("path") or compiled["path"]))
        exists = path.is_dir()
        return exists, {"target": str(path), "directory_exists": exists}
    if action == "filesystem.rename":
        source = Path(compiled["source"])
        target = Path(str(result.get("new_path") or compiled["destination"]))
        verified = target.is_file() and not source.exists()
        return verified, {
            "source_absent": not source.exists(),
            "target_exists": target.is_file(),
        }
    if action == "filesystem.copy":
        source = Path(compiled["source"])
        target = Path(str(result.get("destination") or compiled["destination"]))
        comparable = source.is_file() and target.is_file()
        verified = comparable and _hash(source) == _hash(target)
        return verified, {
            "source_exists": source.is_file(),
            "target_exists": target.is_file(),
            "sha256_equal": verified,
        }
    return False, {"state": "missing_verifier"}


async def execute(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().casefold()
    if action not in ACTIONS:
        return {"error": "Action invalide.", "allowed_actions": sorted(ACTIONS)}
    if action in MUTATING_ACTIONS and not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Autoriser l'action Windows typée « {action} » ?",
        }
    try:
        compiled = _compile(action, args)
    except ValueError as exc:
        return {"error": str(exc), "validation_failed": True}

    executor_name = _EXECUTOR_BY_ACTION[action]
    executor = _executors.get(executor_name)
    if executor is None:
        return {"error": f"Exécuteur Windows indisponible : {executor_name}"}
    result = await executor(compiled)
    if not isinstance(result, dict):
        return {"error": f"Contrat invalide retourné par {executor_name}."}
    verified, evidence = _verify(action, compiled, result)
    if not verified:
        if result.get("requiresConfirmation"):
            return result
        return {
            "error": result.get("error") or "Effet Windows non vérifié.",
            "action": action,
            "executor": executor_name,
            "effect_verified": False,
            "evidence": evidence,
            "needs_repair": True,
        }
    return {
        "success": True,
        "action": action,
        "executor": executor_name,
        "effect_verified": True,
        "evidence": evidence,
        "result": result,
    }
