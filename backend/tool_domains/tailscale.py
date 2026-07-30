"""État et ouverture vérifiée de l'application Windows Tailscale."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import psutil


def _discover_paths() -> dict[str, Path | None]:
    roots = {
        Path(value) / "Tailscale"
        for value in (
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramW6432"),
            os.environ.get("LOCALAPPDATA"),
        )
        if value
    }
    names = {
        "cli": "tailscale.exe",
        "gui": "tailscale-ipn.exe",
        "daemon": "tailscaled.exe",
    }
    return {
        role: next(
            (root / executable for root in roots if (root / executable).is_file()),
            None,
        )
        for role, executable in names.items()
    }


def _service_state() -> dict[str, Any]:
    try:
        data = psutil.win_service_get("Tailscale").as_dict()
        return {
            "installed": True,
            "status": str(data.get("status") or "unknown"),
            "start_type": str(data.get("start_type") or "unknown"),
        }
    except (psutil.NoSuchProcess, OSError):
        return {"installed": False, "status": "not_installed", "start_type": None}
    except Exception as exc:
        return {
            "installed": None,
            "status": "unknown",
            "start_type": None,
            "error": type(exc).__name__,
        }


def _run_status_json(cli_path: Path | None) -> dict[str, Any]:
    if cli_path is None:
        return {"available": False, "error": "cli_not_found"}
    try:
        completed = subprocess.run(
            [str(cli_path), "status", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            return {
                "available": True,
                "error": "status_command_failed",
                "returncode": completed.returncode,
            }
        raw = json.loads(completed.stdout)
    except subprocess.TimeoutExpired:
        return {"available": True, "error": "status_timeout"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": True, "error": type(exc).__name__}

    health = raw.get("Health") if isinstance(raw.get("Health"), list) else []
    addresses = (
        raw.get("TailscaleIPs") if isinstance(raw.get("TailscaleIPs"), list) else []
    )
    node = raw.get("Self") if isinstance(raw.get("Self"), dict) else {}
    return {
        "available": True,
        "version": str(raw.get("Version") or ""),
        "backend_state": str(raw.get("BackendState") or "Unknown"),
        "tun": bool(raw.get("TUN")),
        "authenticated": bool(raw.get("HaveNodeKey")),
        "ip_count": len(addresses),
        "online": bool(node.get("Online")),
        "active": bool(node.get("Active")),
        "health": [str(item)[:500] for item in health[:10]],
    }


def _gui_evidence() -> dict[str, Any]:
    process_ids: list[int] = []
    for process in psutil.process_iter(["pid", "name"]):
        try:
            if str(process.info.get("name") or "").lower() == "tailscale-ipn.exe":
                process_ids.append(int(process.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue

    windows: list[str] = []
    try:
        import win32gui

        def collect(hwnd: int, _: object) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if "tailscale" in title.lower():
                    windows.append(title[:200])

        win32gui.EnumWindows(collect, None)
    except Exception:
        pass
    return {
        "running": bool(process_ids),
        "process_ids": sorted(process_ids),
        "window_visible": bool(windows),
        "window_titles": windows,
    }


def _operational_state(
    paths: dict[str, Path | None],
    service: dict[str, Any],
    connection: dict[str, Any],
) -> str:
    if not any(paths.values()):
        return "not_installed"
    if service.get("status") != "running":
        return "service_stopped"
    if (
        connection.get("backend_state") == "Running"
        and connection.get("online")
        and connection.get("ip_count", 0) > 0
    ):
        return "connected"
    if connection.get("backend_state") in {"Starting", "NeedsLogin", "NoState"}:
        return "starting"
    return "disconnected"


async def status(_: dict | None = None) -> dict[str, Any]:
    paths = _discover_paths()
    service = _service_state()
    connection = _run_status_json(paths["cli"])
    gui = _gui_evidence()
    state = _operational_state(paths, service, connection)
    return {
        "success": True,
        "installed": any(paths.values()),
        "state": state,
        "capability_status": "available" if paths["gui"] else "degraded",
        "service": service,
        "connection": connection,
        "gui": gui,
    }


async def open_ui(_: dict | None = None) -> dict[str, Any]:
    paths = _discover_paths()
    gui_path = paths["gui"]
    before = _gui_evidence()
    if gui_path is None:
        return {
            "success": False,
            "dispatched": False,
            "verified": False,
            "needs_repair": True,
            "error": "Interface Tailscale introuvable (tailscale-ipn.exe).",
            "tailscale_status": await status(),
        }

    try:
        os.startfile(str(gui_path))
    except OSError as exc:
        return {
            "success": False,
            "dispatched": False,
            "verified": False,
            "needs_repair": True,
            "error": f"Impossible de lancer l'interface Tailscale : {exc}",
            "resolved": str(gui_path),
            "tailscale_status": await status(),
        }

    after = before
    for _attempt in range(15):
        await asyncio.sleep(0.25)
        after = _gui_evidence()
        if after["running"] or after["window_visible"]:
            break
    verified = bool(after["running"] or after["window_visible"])
    return {
        "success": verified,
        "dispatched": True,
        "verified": verified,
        "needs_repair": not verified,
        "message": (
            "Interface Tailscale lancée et processus graphique vérifié."
            if verified
            else "Commande envoyée, mais aucune interface Tailscale n'a été vérifiée."
        ),
        "method": "tailscale_gui",
        "resolved": str(gui_path),
        "before": before,
        "after": after,
        "tailscale_status": await status(),
    }
