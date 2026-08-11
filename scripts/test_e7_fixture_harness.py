from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "scripts" / "e7_fixture_harness"
BASE = ROOT / "benchmarks" / "tool-evidence" / "v1.1"
MANIFEST = BASE / "pilot-fixture-harness-manifest.json"
PACKAGE_NAME = "e7_fixture_harness"
ALLOWED_LOCAL = {PACKAGE_NAME}
ALLOWED_STDLIB = set(sys.stdlib_module_names)
FORBIDDEN_CALLS = {"exec", "compile", "eval"}


def _imports_and_calls(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
            elif node.level > 0:
                imports.add(PACKAGE_NAME)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    return imports, calls


def _run_canary(mode: str) -> subprocess.CompletedProcess[str]:
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT / "scripts")}
    if os.name == "nt":
        for name in (
            "LOCALAPPDATA", "PATH", "ProgramFiles", "ProgramFiles(x86)",
            "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "WINDIR",
        ):
            if name in os.environ:
                env[name] = os.environ[name]
    return subprocess.run(
        [sys.executable, "-I", str(PACKAGE / "guard_subprocess.py"), mode],
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


def main() -> int:
    files = sorted(PACKAGE.glob("*.py"))
    assert {p.name for p in files} == {
        "__init__.py", "core.py", "pilot_fixtures.py", "guard_subprocess.py",
        "windows_executable_policy.py",
    }
    for path in files:
        imports, calls = _imports_and_calls(path)
        assert not (imports - ALLOWED_LOCAL - ALLOWED_STDLIB), (path, imports)
        if path.name != "guard_subprocess.py":
            assert not (calls & FORBIDDEN_CALLS), (path, calls & FORBIDDEN_CALLS)

    stdlib_root = Path(sysconfig.get_paths()["stdlib"]).resolve()
    for name in sorted(ALLOWED_STDLIB & {"argparse", "dataclasses", "hashlib", "importlib", "inspect", "json", "pathlib", "subprocess", "sysconfig", "typing"}):
        spec = __import__(name).__spec__
        origin = str(getattr(spec, "origin", ""))
        if origin not in {"built-in", "frozen"}:
            assert stdlib_root in Path(origin).resolve().parents or Path(origin).resolve() == stdlib_root

    allowed = _run_canary("allowed")
    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout) == {"accepted": True, "plans": 6}
    denied_import = _run_canary("forbidden-import")
    assert denied_import.returncode != 0
    assert "fixture_import_denied:backend" in denied_import.stderr
    denied_dynamic = _run_canary("forbidden-dynamic-code")
    assert denied_dynamic.returncode != 0
    assert "fixture_dynamic_code_denied:compile" in denied_dynamic.stderr
    denied_spawn = _run_canary("forbidden-spawn")
    assert denied_spawn.returncode != 0
    assert "fixture_spawn_denied:subprocess.Popen" in denied_spawn.stderr
    recursive_child = _run_canary("recursive-child")
    assert recursive_child.returncode == 0, recursive_child.stderr
    child_result = json.loads(recursive_child.stdout)
    assert child_result["child_guard_active"] is True
    assert "fixture_import_denied:backend" in child_result["denied"]
    if sys.platform == "win32":
        signed = _run_canary("signed-system-binary")
        assert signed.returncode == 0, signed.stderr
        signed_result = json.loads(signed.stdout)
        assert signed_result["accepted"] is True
        assert signed_result["id"] == "windows.winget"
        assert signed_result["status"] == "Valid"
        assert "Microsoft Corporation" in signed_result["publisher"]

    sys.path.insert(0, str(ROOT / "scripts"))
    from e7_fixture_harness import build_pilot_plans
    plans = build_pilot_plans()
    frozen_pilot = json.loads((BASE / "direct-fixture-pilot.json").read_text(encoding="utf-8"))["contracts"]
    frozen_contracts = {
        (item["tool"], item["action"]): item
        for item in json.loads((BASE / "direct-fixture-contracts.json").read_text(encoding="utf-8"))["contracts"]
    }
    assert {(p["tool"], p["action"]) for p in plans} == {(p["tool"], p["action"]) for p in frozen_pilot}
    for plan in plans:
        frozen = frozen_contracts[(plan["tool"], plan["action"])]
        assert plan["e7_class"] == frozen["class"]
        assert plan["surface_profile"] == frozen["surface_profile"]
        assert plan["isolation"] == frozen["isolation"]["kind"]
        assert plan["allowed_delta"] == frozen["allowed_delta"]
        assert plan["execution_authorized"] is False
        assert plan["host_execution_forbidden"] is True
    by_pair = {(p["tool"], p["action"]): p for p in plans}
    assert by_pair[("bulk_rename", "preview")]["permitted_executables"] == ()
    winget_permission = by_pair[("winget_uninstall", "__default__")]["permitted_executables"][0]
    assert winget_permission["shell"] is False
    assert {"LOCALAPPDATA", "PATH", "TEMP", "SYSTEMROOT"} <= set(winget_permission["allowed_environment"])
    process_permission = by_pair[("pc_process_kill", "__default__")]["permitted_executables"][0]
    assert process_permission["isolated_flag"] == "-I"
    assert process_permission["forbid_dash_c"] is True
    assert process_permission["forbid_dash_m"] is True

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["tool_execution_authorized"] is False
    assert manifest["host_execution_forbidden"] is True
    for relative, evidence in manifest["files"].items():
        path = ROOT / relative
        assert path.stat().st_size == evidence["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]

    print("E7 Pilot Fixture Harness OK - 6 plans, guarded Python child and attested Winget probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
