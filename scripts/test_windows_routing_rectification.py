"""Vérifie la reproductibilité et les garde-fous du rectificatif Forge Windows."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_windows_routing_rectification as rectifier  # noqa: E402


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _accepted(contract: dict, name: str, action: str | None = None) -> bool:
    for item in contract["accepted"]:
        if item["name"] != name:
            continue
        expected = item.get("action")
        if expected is None:
            return action is None
        return action is not None and action in expected.split("|")
    return False


def main() -> int:
    generated_contract = rectifier.build_contract_payload()
    stored_contract = _read(rectifier.CONTRACT_OUTPUT)
    assert generated_contract == stored_contract
    assert stored_contract["catalog_tool_count"] == 364
    assert stored_contract["methodology"]["historical_commit"] == rectifier.HISTORICAL_COMMIT
    assert stored_contract["methodology"]["routing_results_used_to_build_matrix"] is False
    assert len(stored_contract["intent_matrix"]) == 120

    contracts = stored_contract["contracts"]
    software = contracts["software.install"]
    assert _accepted(software, "winget_search")
    assert _accepted(software, "winget_install")
    assert not _accepted(software, "winget_uninstall")
    assert not _accepted(software, "windows_task", "software.list")

    discovery = contracts["filesystem.search_by_name"]
    assert _accepted(discovery, "file_find")
    assert _accepted(discovery, "system_search")
    assert _accepted(discovery, "unified_search")
    assert not _accepted(discovery, "system_search_content")

    mutation = contracts["filesystem.move"]
    preparatory_find = next(item for item in mutation["accepted"] if item["name"] == "file_find")
    assert preparatory_find["condition"] == "source_path_unresolved"
    assert _accepted(mutation, "file_move")
    assert not _accepted(mutation, "file_search_text")

    process_stop = contracts["process.stop"]
    assert _accepted(process_stop, "pc_process_kill")
    assert _accepted(process_stop, "windows_task", "process.stop")
    assert not _accepted(process_stop, "windows_task", "process.list")

    visual = contracts["desktop.visual_interaction"]
    assert _accepted(visual, "computer_control", "observe")
    assert _accepted(visual, "computer_control", "click")
    assert _accepted(visual, "pc_gui_read")
    assert "windows_task" in visual["explicit_rejections"]
    assert not _accepted(visual, "windows_task", "application.launch")

    text_only = contracts["text.only"]
    assert text_only["accepted"] == []
    assert {"windows_task", "computer_control", "pc_run_powershell"} <= set(
        text_only["explicit_rejections"]
    )

    generated_rectification = rectifier.build_rectification(stored_contract)
    stored_rectification = _read(rectifier.RECTIFICATION_OUTPUT)
    original_sha = stored_rectification.pop("original_acceptance_report_sha256")
    assert generated_rectification == stored_rectification
    preserved = rectifier.PRESERVED_REPORT.read_bytes()
    assert hashlib.sha256(preserved).hexdigest() == original_sha
    original = json.loads(preserved.decode("utf-8"))
    assert "interpretation_caveat" not in original

    primary = _read(rectifier.ORIGINAL_REPORT)
    caveat = primary["interpretation_caveat"]
    assert caveat["status"] == "superseded_for_general_routing_only"
    assert caveat["routing_policy"] == "windows_task"
    assert caveat["e2e_verdict_unchanged"] is True
    assert caveat["original_report_sha256"] == original_sha

    development = generated_rectification["splits"]["development"]
    holdout = generated_rectification["splits"]["holdout"]
    dev_sources = development["source_verification"]
    holdout_sources = holdout["source_verification"]
    assert dev_sources["corpus_matches_reference_commit"] is True
    assert holdout_sources["corpus_matches_reference_commit"] is True
    assert dev_sources["provenance_complete"] is False
    assert holdout_sources["provenance_complete"] is False
    assert dev_sources["exact_matches"] == 5
    assert holdout_sources["exact_matches"] == 6
    assert {
        name
        for name, evidence in dev_sources["sources"].items()
        if not evidence["matches_reference_commit"]
    } == {"agent.py", "tools.py", "routing_runner.py"}
    assert {
        name
        for name, evidence in holdout_sources["sources"].items()
        if not evidence["matches_reference_commit"]
    } == {"agent.py", "tools.py"}
    assert development["historical_adoption_summary"]["success_rate"] == 0.55
    assert holdout["historical_adoption_summary"]["success_rate"] == 0.4083
    dev_corrected = development["retrospective_tool_name_compatibility"]
    holdout_corrected = holdout["retrospective_tool_name_compatibility"]
    assert dev_corrected["compatible_tool_name_rate"] == 0.7375
    assert holdout_corrected["compatible_tool_name_rate"] == 0.5167
    assert dev_corrected["nonexistent_tool_runs"] == 8
    assert holdout_corrected["nonexistent_tool_runs"] == 8
    assert dev_corrected["by_family"]["file_mutation"]["compatible_tool_name_rate"] == 0.5238
    assert holdout_corrected["by_family"]["file_mutation"]["compatible_tool_name_rate"] == 0.2222
    assert generated_rectification["e2e_verdict_unchanged"] is True
    assert generated_rectification["independent_validation_score"] is None

    print(
        "Windows routing rectification OK - snapshot Git, matrice 120 intentions, "
        "sanité bidirectionnelle et erratum vérifiés."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
