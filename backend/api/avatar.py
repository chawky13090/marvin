"""Contrôle local et borné de l'avatar de bureau Electron."""
from __future__ import annotations

import ipaddress
import subprocess
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, HTTPException, Request

import api_errors

router = APIRouter(prefix="/api/avatar", tags=["avatar"])
ROOT = Path(__file__).resolve().parents[2]
ELECTRON = ROOT / "node_modules" / "electron" / "dist" / "electron.exe"
ENTRYPOINT = ROOT / "desktop-avatar" / "main.cjs"


def _is_loopback(host: str | None) -> bool:
    try:
        return bool(host) and ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return str(host or "").casefold() == "localhost"


def _require_local(request: Request) -> None:
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="L'avatar du PC hôte ne peut être activé que localement.")


def _running() -> list[int]:
    expected_entry = str(ENTRYPOINT.resolve()).casefold()
    expected_executable = str(ELECTRON.resolve()).casefold()
    matches: list[int] = []
    for process in psutil.process_iter(["pid", "exe", "cmdline"]):
        try:
            executable = str(process.info.get("exe") or "").casefold()
            command = " ".join(process.info.get("cmdline") or []).casefold()
            if executable == expected_executable and expected_entry in command:
                matches.append(int(process.info["pid"]))
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, TypeError, ValueError):
            continue
    return matches


@router.get("/status")
async def avatar_status(request: Request):
    _require_local(request)
    pids = _running()
    return {
        "available": ELECTRON.is_file() and ENTRYPOINT.is_file(),
        "running": bool(pids),
        "process_ids": pids,
    }


@router.post("/activate")
async def avatar_activate(request: Request):
    _require_local(request)
    if not ELECTRON.is_file() or not ENTRYPOINT.is_file():
        raise HTTPException(status_code=503, detail="Runtime Avatar absent. Relancez INSTALLER-NOUVEAU-PC.bat.")
    was_running = bool(_running())
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(
            [str(ELECTRON), str(ENTRYPOINT)],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=flags,
        )
    except OSError as exc:
        raise api_errors.internal_http_error(
            "avatar_activate", exc, "Activation Avatar impossible."
        ) from exc
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        pids = _running()
        if pids:
            return {"success": True, "running": True, "focus_requested": was_running, "process_ids": pids}
        time.sleep(0.1)
    raise HTTPException(status_code=504, detail="L'avatar a été lancé mais sa fenêtre n'a pas été confirmée.")
