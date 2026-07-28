"""Contrats HTTP des routes Cloud et proactives extraites du composition root."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from api import model_selection, proactive


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(model_selection.router)
    app.include_router(proactive.router)
    return app


async def _request(method: str, url: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def _base_config() -> dict:
    return {
        "morning_briefing": {
            "enabled": False,
            "time": "08:00",
            "voice": False,
            "voice_name": "henri",
        },
        "evening_recap": {
            "enabled": False,
            "time": "18:30",
            "voice": False,
            "voice_name": "henri",
        },
        "anticipation": {
            "enabled": False,
            "interval_min": 30,
            "overdue_tasks": True,
            "upcoming_events": True,
            "upcoming_events_min": 30,
            "max_notify": 5,
        },
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
    }


async def _check_model_selection() -> None:
    with (
        patch.object(model_selection.cloud_routing, "pick_best_cloud_model", return_value="glm:cloud") as pick,
        patch.object(
            model_selection.cloud_routing,
            "list_installed_cloud_models",
            return_value=["glm:cloud", "kimi:cloud"],
        ),
    ):
        response = await _request("GET", "/api/cloud/best-model?need=code")
    assert response.status_code == 200
    assert response.json() == {
        "need": "code",
        "model": "glm:cloud",
        "installed": ["glm:cloud", "kimi:cloud"],
    }
    pick.assert_called_once_with("code")
    assert (await _request("GET", "/api/cloud/best-model?need=audio")).status_code == 422


async def _check_config_validation() -> None:
    assert (
        await _request("POST", "/api/proactive", json={"morning_briefing": "yes"})
    ).status_code == 422
    assert (
        (
            await _request(
                "POST",
                "/api/proactive",
                json={"morning_briefing": {"time": "25:99"}},
            )
        ).status_code
        == 422
    )
    assert (
        (
            await _request(
                "POST",
                "/api/proactive",
                json={"anticipation": {"interval_min": 4}},
            )
        ).status_code
        == 422
    )
    assert (await _request("POST", "/api/proactive", json={"unknown": True})).status_code == 422
    assert (await _request("POST", "/api/proactive/run?kind=typo")).status_code == 422


async def _check_config_compatibility() -> None:
    saved: list[tuple[str, dict]] = []
    with (
        patch.object(proactive.proactive_service, "get_config", side_effect=lambda: _base_config()),
        patch.object(proactive.db, "set_setting", side_effect=lambda key, value: saved.append((key, value))),
        patch.object(proactive.audit, "log_action") as audit_log,
    ):
        legacy = await proactive.set_proactive(
            proactive.ProactiveConfigPatch(enabled=True, time="07:45", voice_name="denise")
        )
        nested = await proactive.set_proactive(
            proactive.ProactiveConfigPatch(
                evening_recap=proactive.BriefingPatch(enabled=True, time="19:15"),
                anticipation=proactive.AnticipationPatch(interval_min=15, max_notify=7),
                quiet_hours=proactive.QuietHoursPatch(enabled=True, start="23:00", end="06:30"),
            )
        )
    assert legacy["config"]["morning_briefing"] == {
        "enabled": True,
        "time": "07:45",
        "voice": False,
        "voice_name": "denise",
    }
    assert nested["config"]["morning_briefing"]["enabled"] is False
    assert nested["config"]["evening_recap"]["time"] == "19:15"
    assert nested["config"]["anticipation"]["interval_min"] == 15
    assert nested["config"]["anticipation"]["max_notify"] == 7
    assert nested["config"]["quiet_hours"]["start"] == "23:00"
    assert [key for key, _ in saved] == ["proactive_config", "proactive_config"]
    assert audit_log.call_count == 2


async def _check_briefing_errors_are_redacted() -> None:
    success = AsyncMock(return_value={"success": True, "briefing": "ok"})
    with patch.dict(proactive.tool_module.TOOLS_REGISTRY, {"daily_briefing": success}):
        assert await proactive.daily_briefing() == {"success": True, "briefing": "ok"}

    leaked = "secret-provider-message"
    failure = AsyncMock(return_value={"error": leaked})
    with (
        patch.dict(proactive.tool_module.TOOLS_REGISTRY, {"daily_briefing": failure}),
        patch.object(proactive.bug_log, "log_bug") as log_bug,
    ):
        try:
            await proactive.daily_briefing()
        except HTTPException as exc:
            assert exc.status_code == 500
            assert leaked not in str(exc.detail)
            assert exc.detail["incident_id"]
        else:
            raise AssertionError("Le résultat en échec doit produire une HTTPException.")
    log_bug.assert_called_once()


async def _check_explicit_run_routing() -> None:
    with (
        patch.object(proactive.proactive_service, "get_config", return_value=_base_config()),
        patch.object(
            proactive.proactive_service,
            "run_morning_briefing",
            new=AsyncMock(return_value={"branch": "morning"}),
        ) as morning,
        patch.object(
            proactive.proactive_service,
            "run_evening_recap",
            new=AsyncMock(return_value={"branch": "evening"}),
        ) as evening,
        patch.object(
            proactive.proactive_service,
            "run_anticipation",
            new=AsyncMock(return_value={"branch": "anticipation"}),
        ) as anticipation,
    ):
        assert await proactive.run_proactive_now("evening") == {"branch": "evening"}
        assert await proactive.run_proactive_now("anticipation") == {"branch": "anticipation"}
        assert await proactive.run_proactive_now("morning") == {"branch": "morning"}
    morning.assert_awaited_once()
    evening.assert_awaited_once()
    anticipation.assert_awaited_once_with(_base_config()["anticipation"], force=True)


def _check_composition_root() -> None:
    source = (BACKEND / "main.py").read_text(encoding="utf-8-sig")
    assert "from api.model_selection import router as model_selection_router" in source
    assert "from api.proactive import router as proactive_router" in source
    assert "app.include_router(model_selection_router)" in source
    assert "app.include_router(proactive_router)" in source
    for decorator in (
        '@app.get("/api/cloud/best-model")',
        '@app.get("/api/briefing")',
        '@app.get("/api/proactive")',
        '@app.post("/api/proactive")',
        '@app.post("/api/proactive/run")',
    ):
        assert decorator not in source


def main() -> int:
    asyncio.run(_check_model_selection())
    asyncio.run(_check_config_validation())
    asyncio.run(_check_config_compatibility())
    asyncio.run(_check_briefing_errors_are_redacted())
    asyncio.run(_check_explicit_run_routing())
    _check_composition_root()
    print("Model/Proactive API OK - contrats fermes, compatibilite, routage et erreurs expurgees.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
