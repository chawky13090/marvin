"""Shared Code Workspace service used by the API, UI and Marvin chat tools."""
from __future__ import annotations

import re
import time
from typing import Any, Literal

import coding_jobs
import coding_mission
import coding_scratch
import coding_workspace
import repository_intelligence


class CodingServiceError(RuntimeError):
    pass


_LINUX = re.compile(r"\b(?:linux|debian|ubuntu|rhel|rocky|bash|shell|systemd|apt|dnf|zabbix)\b", re.I)
_WINDOWS = re.compile(r"\b(?:windows|powershell|win32|win64|\.net|wpf|winui|msi|hyper-v)\b", re.I)
_CAPABILITY_CACHE: dict[str, Any] = {"at": 0.0, "value": {}}


def _execution_capabilities() -> dict[str, Any]:
    now = time.monotonic()
    cached = dict(_CAPABILITY_CACHE.get("value") or {})
    if cached and now - float(_CAPABILITY_CACHE.get("at") or 0) < 30:
        return cached
    import hyperv_test_runner
    import linux_test_runner
    import test_forge

    value: dict[str, Any] = {}
    for name, probe in (
        ("docker_linux", test_forge.docker_status),
        ("debian_vm", linux_test_runner.status),
        ("windows_vm", hyperv_test_runner.status),
    ):
        try:
            value[name] = probe()
        except (OSError, RuntimeError, ValueError) as exc:
            value[name] = {"available": False, "ready": False, "error": str(exc)[:1_000]}
    _CAPABILITY_CACHE.update({"at": now, "value": value})
    return value


def _artifact_preview(mission_id: str, *, max_chars: int = 100_000) -> dict[str, Any]:
    files = coding_mission.latest_files(mission_id)
    remaining = max(1, int(max_chars))
    previews: list[dict[str, Any]] = []
    truncated = False
    for path, content in sorted(files.items()):
        excerpt = content[:remaining]
        previews.append({
            "path": path,
            "content": excerpt,
            "bytes": len(content.encode("utf-8")),
            "content_truncated": len(excerpt) < len(content),
        })
        remaining -= len(excerpt)
        if remaining <= 0:
            truncated = len(previews) < len(files) or len(excerpt) < len(content)
            break
    return {
        "source": "mission_snapshot",
        "files": previews,
        "file_count": len(files),
        "truncated": truncated,
        "note": "Ces fichiers viennent du dernier snapshot et peuvent ne pas être appliqués au worktree tant que les gates refusent le livrable.",
    }


def infer_targets(request: str) -> list[str]:
    linux = bool(_LINUX.search(str(request or "")))
    windows = bool(_WINDOWS.search(str(request or "")))
    if linux and not windows:
        return ["linux"]
    if windows and not linux:
        return ["windows"]
    return ["windows", "linux"]


def _targets(request: str, target_mode: str, explicit: list[str] | None) -> list[str]:
    if explicit:
        values = list(dict.fromkeys(str(item).casefold() for item in explicit))
        if not values or any(item not in {"windows", "linux"} for item in values):
            raise CodingServiceError("Les cibles autorisées sont windows et linux.")
        return values
    if target_mode == "windows":
        return ["windows"]
    if target_mode == "linux":
        return ["linux"]
    if target_mode == "both":
        return ["windows", "linux"]
    return infer_targets(request)


def start(
    request: str,
    *,
    repository_path: str = "",
    target_mode: Literal["auto", "windows", "linux", "both"] = "auto",
    target_platforms: list[str] | None = None,
    autonomy: Literal["supervised", "autonomous"] = "autonomous",
    max_duration_minutes: int = 120,
    max_iterations: int = 12,
    max_files_changed: int = 50,
    max_consecutive_failures: int = 3,
    create_worktree: bool = True,
    start_auto: bool = True,
    confirmed: bool = False,
    conversation_id: str = "",
) -> dict[str, Any]:
    cleaned = str(request or "").strip()
    if len(cleaned) < 3:
        raise CodingServiceError("La demande de code doit contenir au moins trois caractères.")
    if not confirmed:
        return {
            "requiresConfirmation": True,
            "message": "Confirme la création du projet isolé et le démarrage de la mission de code.",
            "request": cleaned,
            "repository_path": str(repository_path or "").strip() or None,
        }

    try:
        contract = (
            repository_intelligence.inspect(repository_path)
            if str(repository_path or "").strip()
            else coding_scratch.create(cleaned, confirmed=True)
        )
        targets = _targets(cleaned, target_mode, target_platforms)
        mission = coding_mission.create(
            cleaned,
            target_platforms=targets,
            autonomy=autonomy,
            budget={
                "max_duration_minutes": max(5, min(int(max_duration_minutes), 1_440)),
                "max_iterations": max(1, min(int(max_iterations), 100)),
                "max_files_changed": max(1, min(int(max_files_changed), 1_000)),
                "max_consecutive_failures": max(1, min(int(max_consecutive_failures), 10)),
            },
            repository={
                "root": contract["root"], "name": contract["name"],
                "contract_hash": contract["contract_hash"],
                "git_head": contract["git"].get("head"),
                "git_dirty": contract["git"].get("dirty", False),
                "instructions": [item["path"] for item in contract["instructions"]],
                "scratch": not bool(str(repository_path or "").strip()),
            },
            conversation_id=str(conversation_id or "").strip() or None,
        )
        workspace = None
        if create_worktree:
            try:
                workspace = coding_workspace.create(mission["id"], contract["root"], confirmed=True)
            except coding_workspace.WorkspaceError as exc:
                coding_mission.checkpoint(
                    mission["id"], "failed",
                    state={"stage": "workspace_creation", "error": str(exc)},
                )
                raise
        auto_job = None
        if autonomy == "autonomous" and start_auto:
            auto_job = coding_jobs.create_job(mission["id"])
        return {
            "success": True,
            "mission_id": mission["id"],
            "job_id": auto_job.get("id") if auto_job else None,
            "status": auto_job.get("status") if auto_job else mission.get("status"),
            "project": mission, "workspace": workspace,
            "repository": contract, "auto_job": auto_job,
            "scratch_repository": not bool(str(repository_path or "").strip()),
            "target_platforms": targets,
        }
    except (OSError, ValueError, repository_intelligence.RepositoryError,
            coding_workspace.WorkspaceError, coding_scratch.ScratchRepositoryError) as exc:
        raise CodingServiceError(str(exc)) from exc


def status(mission_id: str = "") -> dict[str, Any]:
    cleaned = str(mission_id or "").strip()
    if not cleaned:
        return {
            "success": True,
            "projects": coding_mission.list_missions(limit=100),
            "jobs": coding_jobs.list_jobs(limit=100),
            "execution_capabilities": _execution_capabilities(),
        }
    mission = coding_mission.get(cleaned)
    if mission is None:
        raise CodingServiceError("Coding Mission introuvable.")
    return {
        "success": True,
        "mission_id": cleaned,
        "project": mission,
        "manifest": coding_mission.latest_manifest(cleaned),
        "events": coding_mission.list_events(cleaned, limit=500),
        "workspace": coding_workspace.status(cleaned) if coding_workspace.get(cleaned) else None,
        "auto_job": coding_jobs.latest_for_mission(cleaned),
        "artifacts": _artifact_preview(cleaned),
        "execution_capabilities": _execution_capabilities(),
        "delivery_pack": coding_mission.read_delivery_pack(cleaned),
    }


def control(mission_id: str, action: Literal["resume", "cancel"], *, confirmed: bool) -> dict[str, Any]:
    if action not in {"resume", "cancel"}:
        raise CodingServiceError("Action Code Workspace invalide; valeurs permises : resume, cancel.")
    if not confirmed:
        return {"requiresConfirmation": True, "message": f"Confirme l'action {action} sur la Coding Mission."}
    latest = coding_jobs.latest_for_mission(str(mission_id or "").strip())
    if not latest:
        raise CodingServiceError("Aucun job Auto associé à cette Coding Mission.")
    result = coding_jobs.resume_job(latest["id"]) if action == "resume" else coding_jobs.cancel_job(latest["id"])
    if not result:
        raise CodingServiceError(f"Action {action} impossible sur le job Auto.")
    return {"success": True, "job": result, "project": coding_mission.get(mission_id)}
