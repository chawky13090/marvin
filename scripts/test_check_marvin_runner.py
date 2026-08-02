from __future__ import annotations

import json
import ast
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_marvin


assert all(
    not any(part.startswith(".venv") for part in path.relative_to(check_marvin.BACKEND).parts)
    for path in check_marvin.backend_python_files(check_marvin.BACKEND)
)

unsafe_text_subprocesses: list[str] = []
for source_root in (ROOT / "backend", ROOT / "scripts"):
    for path in source_root.rglob("*.py"):
        if any(part.startswith(".venv") or part == "__pycache__" for part in path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute) or function.attr != "run":
                continue
            keywords = {item.arg: item.value for item in node.keywords if item.arg}
            text_mode = keywords.get("text")
            if isinstance(text_mode, ast.Constant) and text_mode.value is True and "errors" not in keywords:
                unsafe_text_subprocesses.append(f"{path.relative_to(ROOT)}:{node.lineno}")
assert not unsafe_text_subprocesses, (
    "subprocess textuels sans decode de repli : " + ", ".join(unsafe_text_subprocesses)
)


original_run_stage = check_marvin.run_stage
try:
    outcomes = {"ok-1": True, "bad": False, "ok-2": True}

    def fake_run_stage(stage: check_marvin.Stage) -> tuple[bool, float]:
        return outcomes[stage.name], 0.25

    check_marvin.run_stage = fake_run_stage
    selected = [
        check_marvin.Stage("ok-1", ("fake",)),
        check_marvin.Stage("bad", ("fake",)),
        check_marvin.Stage("ok-2", ("fake",)),
    ]
    exhaustive = check_marvin.execute_stages(selected, fail_fast=False)
    assert [item.name for item in exhaustive] == ["ok-1", "bad", "ok-2"]
    assert [item.success for item in exhaustive] == [True, False, True]

    stopped = check_marvin.execute_stages(selected, fail_fast=True)
    assert [item.name for item in stopped] == ["ok-1", "bad"]

    report_path = ROOT / "artifacts" / "runner-contract-test.json"
    check_marvin.write_report(
        exhaustive,
        expected_count=3,
        quick=True,
        live=False,
        fail_fast=False,
        output_path=report_path,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["executed_stages"] == 3
    assert report["failed"] == 1
    assert report["success"] is False
    report_path.unlink()

    try:
        check_marvin.write_report(
            exhaustive,
            expected_count=3,
            quick=True,
            live=False,
            fail_fast=False,
            output_path=ROOT / "runner-report-outside-artifacts.json",
        )
        raise AssertionError("Un rapport hors artifacts aurait du etre refuse.")
    except ValueError:
        pass
finally:
    check_marvin.run_stage = original_run_stage

print("Check Marvin exhaustive runner tests passed.")
