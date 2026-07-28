"""Régressions déterministes Model Market et Research Swarm, sans appel cloud."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cortex
import cloud_routing
import model_market
import research_swarm
import tools


def main() -> int:
    models = [
        "deepseek-v4:cloud", "qwen3.5:cloud", "glm-5:cloud",
        "nemotron:cloud", "mistral-large:cloud",
    ]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=[]),
    ):
        catalog = model_market.catalog("research")
        assert len(catalog["models"]) == 5
        assert catalog["policy"] == "passive_real_calls_only"
        selected = model_market.recommend("research", count=5, distinct_families=True)
        assert len(selected) == 5
        assert len({item["family"] for item in selected}) == 5
        assert model_market.recommend("verification")[0]["family"] == "mistral"

    role_models = [
        "deepseek-v4-pro:cloud", "glm-5.2:cloud", "kimi-k2.7-code:cloud",
        "minimax-m3:cloud", "qwen3.5:397b-cloud",
        "mistral-large-3:675b-cloud", "nemotron-3-super:cloud",
    ]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=[]),
    ):
        assert model_market.recommend("reasoning")[0]["family"] == "deepseek"
        assert model_market.recommend("agentic")[0]["model"] == "minimax-m3:cloud"
        assert model_market.recommend("code_implementation")[0]["family"] == "kimi"
        assert model_market.recommend("code_architecture")[0]["family"] == "glm"
        assert model_market.recommend("vision")[0]["model"] == "minimax-m3:cloud"
        assert model_market.recommend("multilingual")[0]["family"] == "qwen"

    failed_kimi = [{
        "at": "2026-07-16T00:00:00+00:00",
        "model": "kimi-k2.7-code:cloud",
        "family": "kimi",
        "need": "code",
        "success": False,
        "duration_ms": 600000,
        "phase": "implementation",
    }]
    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_model_capabilities", return_value={}),
        patch.object(model_market, "list_observations", return_value=failed_kimi),
    ):
        assert model_market.recommend("code_implementation")[0]["family"] == "glm"

    assert cloud_routing.detect_task("Recherche web avec sources officielles") == "research"
    assert cloud_routing.detect_task("Crée une présentation PowerPoint") == "productivity"
    assert cloud_routing.detect_task("Traduis ce texte en allemand") == "multilingual"
    assert cloud_routing.detect_task("Compare plusieurs architectures") == "reasoning"
    assert cloud_routing.detect_task("Crée un workflow en plusieurs étapes") == "agentic"
    assert cloud_routing.is_cloud_model("gemma4:e4b") is True

    with (
        patch.object(model_market.cloud_routing, "list_installed_cloud_models", return_value=role_models),
        patch.object(model_market.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(model_market, "_auto_sync_enabled", return_value=True),
        patch.object(model_market, "pull_cloud_model", return_value={"success": True, "model": "x:cloud"}),
    ):
        fleet = model_market.fleet_status()
        assert any(item["model"].startswith("mistral-large-3") for item in fleet["recommended"])
        sync = asyncio.run(model_market.sync_recommended_cloud_models())
        assert sync["success"] is True
    try:
        model_market._validate_cloud_model_name("../../bad")
        raise AssertionError("Le nom dangereux aurait dû être refusé.")
    except ValueError:
        pass

    market_rows = [
        {"model": model, "family": model.split("-", 1)[0].split(":", 1)[0], "score": 70 - index}
        for index, model in enumerate(models)
    ]
    with (
        patch.object(research_swarm.cloud_routing, "get_cloud_config", return_value=(True, {})),
        patch.object(research_swarm.cloud_routing, "is_local_only_lockdown", return_value=False),
        patch.object(research_swarm.cloud_routing, "is_sensitive_text", return_value=False),
        patch.object(research_swarm.model_market, "recommend", return_value=market_rows),
    ):
        plan = research_swarm.build_plan("Comparer deux architectures publiques")
        assert len(plan["cells"]) == 5
        assert len({cell["family"] for cell in plan["cells"]}) == 5
        assert "official documentation" in plan["cells"][0]["query"]
        focused_query = research_swarm._search_query(
            "Recherche la documentation officielle actuelle puis crée un script Bash pour Zabbix Server HTTPS Debian 13",
            "sources_primaires",
        )
        assert focused_query.startswith("Bash Zabbix Server HTTPS Debian 13")
        zabbix_priority = research_swarm._source_priority(
            {"url": "https://www.zabbix.com/documentation/current/", "title": "Documentation"},
            "Installer Zabbix sur Debian 13",
        )
        generic_priority = research_swarm._source_priority(
            {"url": "https://example.net/article", "title": "Article"},
            "Installer Zabbix sur Debian 13",
        )
        assert zabbix_priority > generic_priority

    with patch.object(research_swarm.cloud_routing, "get_cloud_config", return_value=(False, {})):
        error, _ = research_swarm.validate_runtime("Question publique")
        assert "cloud" in error.lower()
    oversized, _ = research_swarm.validate_runtime("x" * 12_001)
    assert "12000" in oversized

    with tempfile.TemporaryDirectory() as temporary:
        old_observations = model_market.OBSERVATIONS_PATH
        old_runs = research_swarm.RUNS_PATH
        model_market.OBSERVATIONS_PATH = Path(temporary) / "observations.jsonl"
        research_swarm.RUNS_PATH = Path(temporary) / "runs.jsonl"
        try:
            receipt = model_market.record_observation(
                "deepseek-v4-pro:cloud",
                "research",
                True,
                1234,
                phase="research stage with spaces",
            )
            assert receipt and receipt["sequence"] == 1
            assert receipt["phase"] == "research_stage_with_spaces"
            assert model_market.evidence_integrity()["integrity_level"] == "tamper_evident"

            run = research_swarm._record_run({
                "id": "swarm-" + uuid.uuid4().hex[:12],
                "created_at": "2026-07-28T00:00:00+00:00",
                "question": "Question publique",
                "answer": "Réponse sourcée.",
                "success": True,
            })
            assert run["evidence_persisted"] is True
            assert run["sequence"] == 1 and len(run["record_hash"]) == 64
            assert research_swarm.list_runs(10)[0]["id"] == run["id"]

            observation_rows = model_market.OBSERVATIONS_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            altered_observation = json.loads(observation_rows[0])
            altered_observation["success"] = False
            observation_rows[0] = json.dumps(altered_observation)
            model_market.OBSERVATIONS_PATH.write_text(
                "\n".join(observation_rows) + "\n",
                encoding="utf-8",
            )
            with (
                patch.object(
                    model_market.cloud_routing,
                    "list_installed_cloud_models",
                    return_value=role_models,
                ),
                patch.object(
                    model_market.cloud_routing,
                    "get_model_capabilities",
                    return_value={},
                ),
            ):
                fallback_catalog = model_market.catalog("research")
            assert fallback_catalog["telemetry_trusted"] is False
            assert fallback_catalog["observation_count"] == 0
            assert all(
                item["observations"]["calls"] == 0
                for item in fallback_catalog["models"]
            )

            run_rows = research_swarm.RUNS_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            altered_run = json.loads(run_rows[0])
            altered_run["answer"] = "Réponse falsifiée."
            run_rows[0] = json.dumps(altered_run, ensure_ascii=False)
            research_swarm.RUNS_PATH.write_text(
                "\n".join(run_rows) + "\n",
                encoding="utf-8",
            )
            with patch.object(research_swarm.bug_log, "log_bug"):
                unpersisted = research_swarm._record_run({
                    "id": "swarm-" + uuid.uuid4().hex[:12],
                    "created_at": "2026-07-28T00:01:00+00:00",
                    "question": "Autre question publique",
                    "answer": "Résultat utile malgré la panne de preuve.",
                    "success": True,
                })
            assert unpersisted["evidence_persisted"] is False
            assert unpersisted["evidence_error"] == "RuntimeError"

            async def exercise_model_transport() -> None:
                public_page = SimpleNamespace(
                    status_code=200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    content=(
                        b"<html><head><title>Official</title></head>"
                        b"<body><script>ignore()</script><main>Useful text</main></body></html>"
                    ),
                    url="https://docs.example.org/guide",
                )
                with patch.object(
                    research_swarm.outbound_http,
                    "fetch_public",
                    new=AsyncMock(return_value=public_page),
                ) as fetch_public:
                    source = await research_swarm._fetch_public_source(
                        "https://docs.example.org/guide"
                    )
                assert source == {
                    "title": "Official",
                    "url": "https://docs.example.org/guide",
                    "text": "Useful text",
                }
                assert fetch_public.await_args.kwargs["max_bytes"] == 1_000_000

                binary_page = SimpleNamespace(
                    status_code=200,
                    headers={"content-type": "application/octet-stream"},
                    content=b"binary",
                    url="https://docs.example.org/archive",
                )
                with patch.object(
                    research_swarm.outbound_http,
                    "fetch_public",
                    new=AsyncMock(return_value=binary_page),
                ):
                    try:
                        await research_swarm._fetch_public_source(
                            "https://docs.example.org/archive"
                        )
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("Une source non textuelle doit être refusée.")

                success_transport = httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        json={"response": "Réponse bornée."},
                    )
                )
                with patch.object(model_market, "record_observation"):
                    async with httpx.AsyncClient(transport=success_transport) as client:
                        success = await research_swarm._model_call(
                            client,
                            "deepseek-v4-pro:cloud",
                            "Question",
                            "test",
                            "research",
                        )
                assert success["ok"] is True and success["answer"] == "Réponse bornée."

                oversized_transport = httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        content=b"x" * (research_swarm.MAX_MODEL_RESPONSE_BYTES + 1),
                    )
                )
                with (
                    patch.object(model_market, "record_observation"),
                    patch.object(research_swarm.bug_log, "log_bug"),
                ):
                    async with httpx.AsyncClient(transport=oversized_transport) as client:
                        oversized_result = await research_swarm._model_call(
                            client,
                            "deepseek-v4-pro:cloud",
                            "Question",
                            "test",
                            "research",
                        )
                assert oversized_result["ok"] is False
                assert oversized_result["error"] == "ValueError"

            asyncio.run(exercise_model_transport())
        finally:
            model_market.OBSERVATIONS_PATH = old_observations
            research_swarm.RUNS_PATH = old_runs

    swarm = cortex.compile_contract("Recherche cette technologie", {"review": "swarm"})
    assert swarm["forced_tools"] == ["ai_research_swarm"]
    assert "ai_research_swarm" in tools.TOOLS_REGISTRY
    assert "ai_research_swarm" in {item["function"]["name"] for item in tools.TOOLS_SPEC}
    print("Model Market OK - scorecards passives, diversité des familles et contrat Research Swarm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
