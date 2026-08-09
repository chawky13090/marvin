"""Valide le gel, les splits et l'indépendance des fixtures/oracles Forge."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tools import TOOLS_REGISTRY  # noqa: E402
import windows_operator_fixtures as fixtures  # noqa: E402


CONTRACT = ROOT / "benchmarks" / "windows-operator" / "v1.1"


def main() -> int:
    corpus_path = CONTRACT / "intent-corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    items = corpus["items"]
    assert corpus["status"] == "frozen_before_baseline"
    assert len(items) == corpus["total"] == 120
    assert sum(item["split"] == "development" for item in items) == 80
    assert sum(item["split"] == "holdout" for item in items) == 40
    assert len({item["id"] for item in items}) == 120
    for item in items:
        assert item["expected_tools"] or not item["action_expected"]
        assert set(item["expected_tools"]) <= set(TOOLS_REGISTRY)
        assert set(item["forbidden_tools"]) <= set(TOOLS_REGISTRY)
    corpus_hash = hashlib.sha256(corpus_path.read_bytes()).hexdigest()

    manifest = json.loads((CONTRACT / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "frozen_before_baseline"
    assert manifest["holdout_opened"] is False
    for name, expected_hash in manifest["files"].items():
        assert hashlib.sha256((CONTRACT / name).read_bytes()).hexdigest() == expected_hash
    runtime = manifest["runtime_precondition"]
    assert runtime["model"] == "qwen3.5:397b-cloud"
    assert runtime["provider_declared_context_tokens"] == 262_144
    assert runtime["client_context_override"] is None
    evidence = (CONTRACT / runtime["behavioral_evidence"]).resolve()
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == runtime["behavioral_evidence_sha256"]

    live = json.loads((CONTRACT / "live-scenarios.json").read_text(encoding="utf-8"))
    scenarios = live["scenarios"]
    assert len(scenarios) == live["total"] == 15
    assert sum(item["split"] == "development" for item in scenarios) == 10
    assert sum(item["split"] == "holdout" for item in scenarios) == 5
    assert len({item["id"] for item in scenarios}) == 15
    for scenario in scenarios:
        assert scenario["fixture_id"] in fixtures.FIXTURE_IDS
        assert scenario["oracle_id"] in fixtures.ORACLE_IDS
        assert set(scenario["required_capabilities"]) <= set(TOOLS_REGISTRY)
        assert scenario["reversible"] is True

    run_id = "contract-file-roundtrip"
    context = fixtures.setup("fixture.file_absent", run_id=run_id)
    try:
        Path(context["target"]).write_text(context["content"], encoding="utf-8")
        assert fixtures.oracle("oracle.file_content_exact", context)["passed"] is True
    finally:
        root = Path(context["root"])
        fixtures.teardown(context)
        assert not root.exists()

    # Le Bloc-notes empaqueté peut remplacer le PID du lanceur. L'oracle doit
    # suivre toute instance apparue depuis le setup, pas seulement ce premier PID.
    original_pid_exists = fixtures.psutil.pid_exists
    process_context = {
        "fixture_pid": 22,
        "fixture_pids": [22],
    }
    try:
        fixtures.psutil.pid_exists = lambda pid: pid == 22
        still_running = fixtures.oracle("oracle.notepad_absent", process_context)
        assert still_running["passed"] is False
        assert still_running["evidence"]["remaining_fixture_process_count"] == 1
        fixtures.psutil.pid_exists = lambda _pid: False
        assert fixtures.oracle("oracle.notepad_absent", process_context)["passed"] is True
    finally:
        fixtures.psutil.pid_exists = original_pid_exists

    agent_source = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
    assert 'os.getenv("MARVIN_FORGE_ROUTING_ONLY", "0") == "1"' in agent_source
    assert "and _context_decision.forge_locked" in agent_source
    assert '"type": "benchmark_routing"' in agent_source
    assert '"toolNames"' in agent_source

    print(f"Windows operator corpus OK - 120 intentions, 15 scénarios, sha256={corpus_hash}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
