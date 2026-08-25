"""Exercise the complete r7 pipeline offline through selection and atomic output writes."""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_tool_selection_v13_holdout as shared
import generate_tool_selection_v17_holdout_r4 as r4
import generate_tool_selection_v18_holdout_r7 as runner


async def _fake_models() -> dict[str, dict[str, object]]:
    policy = json.loads(runner.POLICY.read_text(encoding="utf-8"))
    return {
        row["model"]: {"digest": row["digest"], "remote_host": "https://offline.invalid"}
        for row in policy["roles"].values()
    }


async def _fake_cloud(model: str, system: str, user: str, *, seed: int):
    if "demandes de test synthétiques" in system:
        match = re.search(r"intent=([a-z_.]+)", user)
        if not match:
            raise ValueError("Préflight auteur sans intention.")
        intent = match.group(1).rstrip(".")
        return {"items": [
            {
                "intent": intent,
                "prompt": f"Formulation locale entièrement inédite {intent} contrôle numéro {index:02d}",
            }
            for index in range(1, 21)
        ]}, {"execution": "offline_preflight_author"}
    if "révises uniquement le texte" in system:
        rows = json.loads(user.rsplit("\nITEMS:\n", 1)[1])
        return {"items": [{"id": row["id"], "valid": True} for row in rows]}, {
            "execution": "offline_preflight_reviewer"
        }
    raise ValueError("Le préflight r7 refuse tout autre appel simulé.")


async def _exercise() -> None:
    original_models = shared._models
    original_cloud = runner._CLOUD_CHAT
    original_paths = (runner.CORPUS, runner.ORACLE, runner.REPORT, runner.DIAGNOSTIC)
    with tempfile.TemporaryDirectory(prefix="marvin-r7-preflight-") as raw:
        temp = Path(raw)
        runner.CORPUS = temp / "corpus.json"
        runner.ORACLE = temp / "oracle.json"
        runner.REPORT = temp / "report.json"
        runner.DIAGNOSTIC = temp / "diagnostic.json"
        shared._models = _fake_models
        runner._CLOUD_CHAT = _fake_cloud
        try:
            report = await runner.run()
            assert report["counts"]["selected"] == 35
            assert report["counts"]["intents"] == {intent: 5 for intent in r4.r3.INTENTS}
            for path in (runner.CORPUS, runner.ORACLE, runner.REPORT, runner.DIAGNOSTIC):
                assert path.exists() and path.stat().st_size > 0
            diagnostic = json.loads(runner.DIAGNOSTIC.read_text(encoding="utf-8"))
            assert diagnostic["status"] == "complete"
            assert all(
                row["survivors_final"] == 20
                for row in diagnostic["counts_by_intent"].values()
            )
        finally:
            shared._models = original_models
            runner._CLOUD_CHAT = original_cloud
            runner.CORPUS, runner.ORACLE, runner.REPORT, runner.DIAGNOSTIC = original_paths


def main() -> None:
    asyncio.run(_exercise())
    print("Tool Selection v1.8 Holdout Full Preflight r7 OK - 35 selected, all writes rehearsed offline")


if __name__ == "__main__":
    main()
