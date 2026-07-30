"""Régressions du lancement Windows vérifié et de l'adaptateur Tailscale."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import pc_control, tailscale  # noqa: E402
from engineering_runtime import normalize_tool_result  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def test_status_states() -> None:
    paths = {
        "cli": Path(r"C:\Program Files\Tailscale\tailscale.exe"),
        "gui": Path(r"C:\Program Files\Tailscale\tailscale-ipn.exe"),
        "daemon": Path(r"C:\Program Files\Tailscale\tailscaled.exe"),
    }
    with (
        patch.object(tailscale, "_discover_paths", return_value=paths),
        patch.object(
            tailscale,
            "_service_state",
            return_value={"installed": True, "status": "running"},
        ),
        patch.object(
            tailscale,
            "_run_status_json",
            return_value={
                "backend_state": "Running",
                "online": True,
                "ip_count": 1,
            },
        ),
        patch.object(
            tailscale,
            "_gui_evidence",
            return_value={"running": False, "window_visible": False},
        ),
    ):
        result = await tailscale.status()
    check(result["state"] == "connected", "Une connexion active doit être reconnue.")

    with (
        patch.object(tailscale, "_discover_paths", return_value=paths),
        patch.object(
            tailscale,
            "_service_state",
            return_value={"installed": True, "status": "running"},
        ),
        patch.object(
            tailscale,
            "_run_status_json",
            return_value={"backend_state": "NoState", "online": False, "ip_count": 0},
        ),
        patch.object(
            tailscale,
            "_gui_evidence",
            return_value={"running": False, "window_visible": False},
        ),
    ):
        result = await tailscale.status()
    check(result["state"] == "starting", "Un service seul ne prouve pas la connexion.")


async def test_tailscale_launch_requires_evidence() -> None:
    paths = {
        "cli": Path(r"C:\Program Files\Tailscale\tailscale.exe"),
        "gui": Path(r"C:\Program Files\Tailscale\tailscale-ipn.exe"),
        "daemon": Path(r"C:\Program Files\Tailscale\tailscaled.exe"),
    }
    missing = {"running": False, "window_visible": False}
    with (
        patch.object(tailscale, "_discover_paths", return_value=paths),
        patch.object(tailscale, "_gui_evidence", return_value=missing),
        patch.object(tailscale.os, "startfile") as start,
        patch.object(tailscale.asyncio, "sleep", new=AsyncMock()),
        patch.object(tailscale, "status", new=AsyncMock(return_value={"state": "starting"})),
    ):
        result = await tailscale.open_ui()
    start.assert_called_once_with(str(paths["gui"]))
    check(result["dispatched"], "La commande doit être distinguée de son résultat.")
    check(not result["success"], "Une commande sans preuve ne doit pas réussir.")
    check(result["needs_repair"], "L'absence de preuve doit déclencher la réparation.")

    visible = {"running": True, "window_visible": False, "process_ids": [42]}
    with (
        patch.object(tailscale, "_discover_paths", return_value=paths),
        patch.object(tailscale, "_gui_evidence", side_effect=[missing, visible]),
        patch.object(tailscale.os, "startfile"),
        patch.object(tailscale.asyncio, "sleep", new=AsyncMock()),
        patch.object(tailscale, "status", new=AsyncMock(return_value={"state": "starting"})),
    ):
        result = await tailscale.open_ui()
    check(result["success"] and result["verified"], "Le processus GUI doit prouver l'ouverture.")
    check(
        "tailscale_status" in result and "status" not in result,
        "Le reçu ne doit pas entrer en collision avec le statut du contrat commun.",
    )
    normalized = normalize_tool_result("pc_app_launch", result, duration_ms=1)
    check(
        normalized["_contract"]["status"] == "succeeded",
        "Le gateway doit pouvoir normaliser la preuve Tailscale.",
    )


async def test_generic_launch_requires_evidence() -> None:
    with (
        patch.object(pc_control, "_find_app_target", return_value=("exe", r"C:\Apps\Demo.exe")),
        patch.object(pc_control, "_application_evidence", return_value={
            "processes": [],
            "window_visible": False,
            "window_titles": [],
        }),
        patch.object(pc_control.os, "startfile"),
        patch.object(pc_control.asyncio, "sleep", new=AsyncMock()),
    ):
        result = await pc_control.execute_pc_app_launch({"app_name": "Demo"})
    check(not result["success"], "Le lanceur générique ne doit plus produire de faux succès.")
    check(result["dispatched"] and result["needs_repair"], "Le résultat doit être réparable.")


async def test_tailscale_routes_to_adapter() -> None:
    with patch.object(
        tailscale,
        "open_ui",
        new=AsyncMock(return_value={"success": True, "verified": True}),
    ) as open_ui:
        result = await pc_control.execute_pc_app_launch({"app_name": "Tailscale"})
    open_ui.assert_awaited_once()
    check(result["verified"], "Tailscale doit utiliser son adaptateur spécialisé.")


async def main() -> None:
    await test_status_states()
    await test_tailscale_launch_requires_evidence()
    await test_generic_launch_requires_evidence()
    await test_tailscale_routes_to_adapter()
    print("Tailscale runtime: OK")


if __name__ == "__main__":
    asyncio.run(main())
