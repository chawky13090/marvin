"""Canaris du runner B1 sans appel Cloud benchmark ni outil métier."""
from __future__ import annotations
import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/run_tool_selection_stage_b.py"

def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert "execute_tool" not in text and "execute_" not in text
    assert '"num_ctx" not in options' in text
    assert "business_tool_execution_count" in text and "host_side_effect_count" in text
    assert "asyncio.Semaphore" in text and "range(1, 4)" in text
    assert "build_system_prompt([], 2" in text and "compact=False" in text
    assert "RESULT.exists()" in text and "autorisation à usage unique" in text
    assert "Draft202012Validator" in text
    assert "candidate_matrix_sha256" in text and "argument_schema_assessed_count" in text
    assert not any(isinstance(node, ast.ImportFrom) and node.module == "tools" for node in ast.walk(tree))
    spec = importlib.util.spec_from_file_location("stage_b_runner_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    message = {"tool_calls": [{"function": {"name": "windows_task", "arguments": {"action": "process.list"}}}]}
    assert module._tool_call(message) == ("windows_task", {"action": "process.list"}, 1)
    assert module._tool_call({"tool_calls": []}) == (None, {}, 0)
    accepted = [{"tool": "windows_task", "action": "process.list", "constraints": []}]
    assert module._accepted("windows_task", {"action": "process.list"}, accepted)
    assert not module._accepted("windows_task", {"action": "process.kill"}, accepted)
    assert module.CONFIRMATION_RE.search("Souhaitez-vous confirmer cette action ?")
    assert not module.CONFIRMATION_RE.search("Voici le résultat observé.")
    print("Stage B runner OK - native choice only, no business execution, fail-closed scoring.")

if __name__ == "__main__":
    main()
