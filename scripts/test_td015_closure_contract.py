"""Contrat reproductible de clôture de TD-015, avant et après campagne."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "conversation-history" / "td015-closure-policy.json"
FREEZE = ROOT / "benchmarks" / "conversation-history" / "td015-closure-freeze.json"
RESULT = ROOT / "benchmarks" / "conversation-history" / "td015-closure-result.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_cycle_module():
    path = ROOT / "scripts" / "verify_td015_cycle.py"
    spec = importlib.util.spec_from_file_location("verify_td015_cycle_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_policy(policy: dict) -> None:
    assert policy["schema"] == "marvin.td015-closure-policy/1.0"
    assert policy["execution_authorized"] is False
    assert policy["result_publication_authorized"] is False
    assert policy["cold_start"]["required_consecutive_cycles"] == 3
    assert policy["cold_start"]["state_must_equal"] == "ready"
    assert policy["conversation"]["maximum_first_page_transport_bytes"] == 1_048_576
    assert policy["conversation"]["minimum_pages"] >= 2
    assert policy["conversation"]["duplicate_message_ids_allowed"] == 0
    assert policy["detail"]["same_conversation_http"] == 200
    assert policy["detail"]["cross_conversation_http"] == 404
    assert policy["chat_smoke"]["maximum_http_5xx"] == 0
    assert policy["integrity"]["conversation_write_allowed"] is False
    assert policy["integrity"]["database_migration_allowed"] is False
    assert policy["integrity"]["tool_execution_allowed"] is False


def _assert_page_chain_canaries(policy: dict) -> None:
    module = _load_cycle_module()
    first_ids = [f"m{index}" for index in range(41, 81)]
    second_ids = [f"m{index}" for index in range(1, 41)]
    pages = [
        {
            "messages": [{"id": item} for item in first_ids],
            "page": {
                "nextBeforeRowid": 30,
                "hasOlderRows": True,
                "cutoffReason": "row_limit",
            },
        },
        {
            "messages": [{"id": item} for item in second_ids],
            "page": {
                "nextBeforeRowid": 10,
                "hasOlderRows": False,
                "cutoffReason": "none",
            },
        },
    ]
    valid = module.validate_page_chain(pages, policy["conversation"])
    assert valid["duplicate_message_ids"] == 0
    assert valid["cursor_strictly_decreasing"] is True

    duplicated = [dict(page) for page in pages]
    duplicated[1] = {
        **duplicated[1],
        "messages": [{"id": first_ids[0]}, *duplicated[1]["messages"][1:]],
    }
    try:
        module.validate_page_chain(duplicated, policy["conversation"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("Le canari de doublon n'a pas été rejeté.")

    stalled = [dict(page) for page in pages]
    stalled[1] = {
        **stalled[1],
        "page": {**stalled[1]["page"], "nextBeforeRowid": 30},
    }
    try:
        module.validate_page_chain(stalled, policy["conversation"])
    except RuntimeError:
        pass
    else:
        raise AssertionError("Le canari de curseur stagnant n'a pas été rejeté.")


def _assert_smoke_contract() -> None:
    source = (ROOT / "scripts" / "smoke_test_chat.py").read_text(encoding="utf-8")
    assert '"server_error_count"' in source
    assert "not server_errors" in source
    assert "MARVIN_SMOKE_REPORT_PATH" in source


def _assert_freeze(freeze: dict) -> None:
    assert freeze["schema"] == "marvin.td015-closure-freeze/1.0"
    assert freeze["execution_authorized"] is True
    assert freeze["result_publication_authorized"] is True
    assert freeze["policy_sha256"] == _sha256(POLICY)
    commit = subprocess.run(
        ["git", "cat-file", "-e", f'{freeze["source_commit"]}^{{commit}}'],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    assert commit.returncode == 0
    for relative, expected in freeze["source_hashes"].items():
        assert _sha256(ROOT / relative) == expected, relative


def _assert_result(result: dict, policy: dict, freeze: dict) -> None:
    assert result["schema"] == "marvin.td015-closure-result/1.0"
    assert result["passed"] is True
    assert result["data_modified"] is False
    assert result["conversation_identifier_plaintext_published"] is False
    assert result["required_consecutive_cycles"] == 3
    assert result["policy_sha256"] == _sha256(POLICY)
    assert result["freeze_sha256"] == _sha256(FREEZE)
    assert result["source_commit"] == freeze["source_commit"]
    cycles = result["cycles"]
    assert len(cycles) == 3
    assert len({cycle["functional"]["target_id_sha256"] for cycle in cycles}) == 1
    for cycle in cycles:
        assert cycle["state"] == "ready"
        assert cycle["code_workspace_http"] == 200
        assert cycle["vm_lab_http"] == 200
        functional = cycle["functional"]
        assert functional["frontend_http"] == 200
        assert functional["first_page_duration_ms"] <= policy["conversation"]["maximum_first_page_duration_ms"]
        assert functional["first_page_transport_bytes"] <= policy["conversation"]["maximum_first_page_transport_bytes"]
        assert functional["page_chain"]["pages"] >= policy["conversation"]["minimum_pages"]
        assert functional["page_chain"]["duplicate_message_ids"] == 0
        assert functional["page_chain"]["cursor_strictly_decreasing"] is True
        assert functional["page_chain"]["final_has_older_rows"] is False
        assert functional["detail_http"] == 200
        assert functional["cross_conversation_http"] == 404
        assert functional["chat_smoke"]["sample_count"] == 5
        assert functional["chat_smoke"]["server_error_count"] == 0
        assert functional["chat_smoke"]["console_error_count"] == 0
        assert functional["chat_smoke"]["passed"] is True


def main() -> None:
    policy = _load_json(POLICY)
    _assert_policy(policy)
    _assert_page_chain_canaries(policy)
    _assert_smoke_contract()
    if FREEZE.exists():
        freeze = _load_json(FREEZE)
        _assert_freeze(freeze)
        if RESULT.exists():
            _assert_result(_load_json(RESULT), policy, freeze)
    elif RESULT.exists():
        raise AssertionError("Un résultat TD-015 existe sans manifeste de gel.")
    print("TD-015 closure contract OK")


if __name__ == "__main__":
    main()
