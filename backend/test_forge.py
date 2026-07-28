"""Disposable, network-isolated execution gates for generated code."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import windows_test_runner
import deliverable_bundle
import linux_test_runner


IMAGES = {
    "shellcheck": "koalaman/shellcheck@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d",
    "bats": "bats/bats@sha256:6e4b9369468b7f3fd8f402ac6cc8ea7b2e4903eae28d08785f31a0245eb51a44",
    "python": "python@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b",
    "node": "node@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3",
    "debian13": "debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd",
    "go": "golang@sha256:1ecb7edf62a0408027bd5729dfd6b1b8766e578e8df93995b225dfd0944eb651",
}

FILE_NAMES = {
    "bash": ("main.sh", "test_main.bats"),
    "python": ("main.py", "test_main.py"),
    "javascript": ("main.mjs", "test_main.test.mjs"),
    "json": ("main.json", ""),
    "go": ("main.go", "main_test.go"),
}

_INSTALLER_PATTERNS = re.compile(
    r"(?im)^\s*(?:apt(?:-get)?|dnf|yum|apk|zypper|pacman)\s+(?:install|add)\b"
    r"|\b(?:pip|pip3|npm|pnpm|yarn)\s+install\b"
    r"|\bdpkg\s+-i\b|\bsystemctl\s+(?:enable|start|restart)\b"
)

_NATIVE_LINUX_PATTERNS = re.compile(
    r"(?m)(?:^\s*|[;&|]\s*)(?:sudo\s+)?(?:systemctl|service)\s+|"
    r"\b(?:loginctl|hostnamectl|timedatectl)\b"
)


def requires_online_integration(code: str, language: str) -> bool:
    """Static unit tests cannot certify scripts that install packages or services."""
    return str(language or "").casefold() == "bash" and bool(_INSTALLER_PATTERNS.search(str(code or "")))


def requires_native_linux_runtime(code: str, language: str) -> bool:
    """True quand le parcours nominal exige un vrai init/systemd Linux."""
    return str(language or "").casefold() == "bash" and bool(
        _NATIVE_LINUX_PATTERNS.search(str(code or ""))
    )


def _docker_path(path: Path) -> str:
    return str(path.resolve())


def docker_status() -> dict[str, Any]:
    executable = shutil.which("docker.exe") or shutil.which("docker")
    if not executable:
        return {"available": False, "error": "CLI Docker introuvable."}
    try:
        completed = subprocess.run(
            [executable, "version", "--format", "{{.Server.Version}}"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    version = (completed.stdout or "").strip()
    if completed.returncode != 0 or not version:
        detail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()
        return {"available": False, "error": detail[:500] or "Docker Engine indisponible."}
    return {"available": True, "executable": executable, "server_version": version}


def _base_command(executable: str, image: str, directory: Path) -> list[str]:
    return [
        executable,
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        "128",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--user",
        "65534:65534",
        "--env",
        "HOME=/tmp",
        "--env",
        "GOCACHE=/tmp/go-build",
        "--env",
        "GOMODCACHE=/tmp/go-mod",
        "--env",
        "GOTMPDIR=/work",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=512m",
        "--tmpfs",
        "/work:rw,exec,nosuid,nodev,size=512m",
        "--mount",
        f"type=bind,source={_docker_path(directory)},target=/workspace,readonly",
        "--workdir",
        "/workspace",
        image,
    ]


def _run(
    executable: str,
    image: str,
    directory: Path,
    args: list[str],
    *,
    name: str,
    timeout: int = 60,
    entrypoint: str | None = None,
) -> dict[str, Any]:
    command = _base_command(executable, image, directory)
    if entrypoint:
        image_index = command.index(image)
        command[image_index:image_index] = ["--entrypoint", entrypoint]
    command.extend(args)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(5, min(int(timeout), 180)),
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout = (completed.stdout or "")[-12000:]
        stderr = (completed.stderr or "")[-12000:]
        return {
            "name": name,
            "passed": completed.returncode == 0,
            "exit_code": completed.returncode,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "image": image,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "passed": False,
            "exit_code": 124,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": str(exc.stdout or "")[-12000:],
            "stderr": "Timeout de validation dépassé.",
            "image": image,
        }
    except OSError as exc:
        return {
            "name": name,
            "passed": False,
            "exit_code": 127,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {str(exc)[:1000]}",
            "image": image,
        }


def _run_online_integration(
    executable: str,
    directory: Path,
    *,
    language: str,
    timeout: int,
) -> dict[str, Any]:
    image = IMAGES.get(language, IMAGES["debian13"])
    command = [
        executable,
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "bridge",
        "--security-opt",
        "no-new-privileges=true",
        "--pids-limit",
        "256",
        "--memory",
        "1g",
        "--cpus",
        "2.0",
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,size=256m",
        "--tmpfs",
        "/work:rw,exec,nosuid,nodev,size=512m",
        "--mount",
        f"type=bind,source={_docker_path(directory)},target=/workspace,readonly",
        "--workdir",
        "/work",
        image,
        "/bin/bash",
        "-c",
        (
            "set -Eeuo pipefail; "
            "mkdir -p /work/src; cp -a /workspace/. /work/src/; cd /work/src; "
            "bash ./integration.sh; "
            + {
                "bash": "bats --formatter tap ./test_main.bats; ",
                "python": "python3 ./test_main.py; ",
                "javascript": "node --test ./test_main.test.mjs; ",
                "go": "go test ./...; ",
            }[language]
            + "echo MARVIN_TEST_SUITE_COMPLETE=full"
        ),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=max(30, min(int(timeout), 900)),
            check=False,
        )
        stdout = (completed.stdout or "")[-20000:]
        stderr = (completed.stderr or "")[-20000:]
        marker = "MARVIN_INTEGRATION_COMPLETE=full" in stdout
        test_marker = "MARVIN_TEST_SUITE_COMPLETE=full" in stdout
        return {
            "name": "online_integration",
            "passed": completed.returncode == 0 and marker and test_marker,
            "exit_code": completed.returncode,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": stdout,
            "stderr": (
                stderr
                if (marker and test_marker) or completed.returncode != 0
                else (
                    "Marqueur d'intégration ou de tests absent : "
                    "MARVIN_INTEGRATION_COMPLETE=full / MARVIN_TEST_SUITE_COMPLETE=full."
                )
            ),
            "image": image,
            "network": "bridge",
            "completion_marker": marker,
            "test_completion_marker": test_marker,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": "online_integration",
            "passed": False,
            "exit_code": 124,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": str(exc.stdout or "")[-20000:],
            "stderr": "Timeout du test d'intégration en ligne dépassé.",
            "image": image,
            "network": "bridge",
            "completion_marker": False,
            "test_completion_marker": False,
        }
    except OSError as exc:
        return {
            "name": "online_integration",
            "passed": False,
            "exit_code": 127,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {str(exc)[:1000]}",
            "image": image,
            "network": "bridge",
            "completion_marker": False,
            "test_completion_marker": False,
        }


def _shellcheck_findings(step: dict[str, Any]) -> list[dict[str, Any]]:
    raw = str(step.get("stdout") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    findings = []
    for item in payload[:100]:
        if not isinstance(item, dict):
            continue
        findings.append({
            "line": item.get("line"),
            "column": item.get("column"),
            "level": item.get("level"),
            "code": item.get("code"),
            "message": str(item.get("message") or "")[:500],
        })
    return findings


def _validate_test_shape(language: str, test_code: str) -> str | None:
    if not test_code.strip():
        return "Une suite de tests est obligatoire pour le statut production."
    if language == "bash" and "@test" not in test_code:
        return "La suite Bats ne contient aucun test."
    if language == "python" and not re.search(r"\b(?:unittest|TestCase|assert)\b", test_code):
        return "La suite Python ne contient aucune assertion reconnue."
    if language == "javascript" and not re.search(r"\b(?:test|it)\s*\(", test_code):
        return "La suite Node ne contient aucun test reconnu."
    if language == "go" and not re.search(r"(?m)^\s*func\s+Test\w+\s*\(", test_code):
        return "La suite Go ne contient aucune fonction Test reconnue."
    return None


def _validate_integration_shape(integration_test_code: str) -> str | None:
    code = str(integration_test_code or "")
    if not code.strip():
        return "Une suite d'intégration en ligne est obligatoire pour ce livrable."
    if "MARVIN_INTEGRATION_COMPLETE=full" not in code:
        return "Le harness d'intégration ne contient pas le marqueur de réussite obligatoire."
    if re.search(r"/(?:workspace|work/src)/", code):
        return (
            "Le harness utilise un chemin absolu propre à un runner. "
            "Il doit référencer le livrable relativement au répertoire courant (par exemple ./main.sh)."
        )
    return None


def _validate_integration_runtime_contract(
    language: str,
    integration_test_code: str,
) -> str | None:
    """Refuse les installations de runtime incompatibles avec l'image spécialisée."""
    code = str(integration_test_code or "")
    normalized_language = str(language or "").casefold()
    if normalized_language == "python" and re.search(
        r"(?im)^\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:sudo\s+)?"
        r"(?:apt(?:-get)?|dnf|yum|apk)\s+(?:install|add)\b[^\n]*\bpython3(?:\.\d+)?\b",
        code,
    ):
        return (
            "Le runner Python fournit déjà la version Python certifiée. "
            "Le harness ne doit pas installer python3/python3.X depuis la distribution. "
            "Utiliser python/python3 déjà présent et n'installer que les dépendances requises."
        )
    if normalized_language == "javascript" and re.search(
        r"(?im)^\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:sudo\s+)?"
        r"(?:apt(?:-get)?|dnf|yum|apk)\s+(?:install|add)\b[^\n]*\b(?:nodejs|npm)\b",
        code,
    ):
        return (
            "Le runner Node fournit déjà Node.js et npm. "
            "Le harness ne doit pas réinstaller le runtime depuis la distribution."
        )
    if normalized_language == "go" and re.search(
        r"(?im)^\s*(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:sudo\s+)?"
        r"(?:apt(?:-get)?|dnf|yum|apk)\s+(?:install|add)\b[^\n]*\b(?:golang|go)\b",
        code,
    ):
        return (
            "Le runner Go fournit déjà la toolchain certifiée. "
            "Le harness ne doit pas réinstaller Go depuis la distribution."
        )
    return None


def _powershell_static(
    code: str,
    test_code: str,
    run_id: str,
    files: dict[str, str] | None = None,
) -> dict[str, Any]:
    executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not executable:
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": "powershell",
            "error": "PowerShell est introuvable.",
            "steps": [],
        }
    steps = []
    with tempfile.TemporaryDirectory(prefix="marvin-test-forge-ps-") as temporary:
        directory = Path(temporary)
        script_path = directory / "main.ps1"
        test_path = directory / "main.Tests.ps1"
        script_path.write_text(code, encoding="utf-8-sig")
        for path, content in dict(files or {}).items():
            if path.casefold() in {"main.ps1", "main.tests.ps1"}:
                continue
            destination = directory / Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8-sig")
        if test_code.strip():
            test_path.write_text(test_code, encoding="utf-8-sig")
        quoted_script = str(script_path).replace("'", "''")
        quoted_test = str(test_path).replace("'", "''")
        targets = [
            str(path).replace("'", "''")
            for path in directory.rglob("*")
            if path.suffix.casefold() in {".ps1", ".psm1"}
        ]
        parser_command = (
            "$all=@();"
            + "".join(
                "$tokens=$null;$errors=$null;"
                f"[System.Management.Automation.Language.Parser]::ParseFile('{target}',"
                "[ref]$tokens,[ref]$errors)|Out-Null;$all+=$errors;"
                for target in targets
            )
            + "if($all.Count){$all|ForEach-Object{$_.Message};exit 1}"
        )
        started = time.perf_counter()
        parsed = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", parser_command],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
        )
        steps.append({
            "name": "powershell_parser",
            "passed": parsed.returncode == 0,
            "exit_code": parsed.returncode,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": (parsed.stdout or "")[-12000:],
            "stderr": (parsed.stderr or "")[-12000:],
            "image": None,
        })
        quoted_directory = str(directory).replace("'", "''")
        analyzer_command = (
            "Import-Module PSScriptAnalyzer -RequiredVersion 1.25.0 -ErrorAction Stop;"
            f"$r=Invoke-ScriptAnalyzer -Path '{quoted_directory}' -Recurse -Severity Error,Warning;"
            "$r|ConvertTo-Json -Depth 5 -Compress;"
            "if($r.Count){exit 1}"
        )
        started = time.perf_counter()
        analyzed = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", analyzer_command],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
        steps.append({
            "name": "psscriptanalyzer",
            "passed": analyzed.returncode == 0,
            "exit_code": analyzed.returncode,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "stdout": (analyzed.stdout or "")[-12000:],
            "stderr": (analyzed.stderr or "")[-12000:],
            "image": None,
        })
    failed = [step for step in steps if not step["passed"]]
    if not failed and test_code.strip():
        sandbox_result = windows_test_runner.execute_powershell(
            code,
            test_code,
            files=files,
            timeout_seconds=600,
        )
        sandbox_result["static_steps"] = steps
        return sandbox_result
    return {
        "success": False,
        "production_ready": False,
        "run_id": run_id,
        "language": "powershell",
        "error": (
            "Analyse statique réussie, mais l'exécution Pester reste bloquée tant qu'aucune "
            "VM Windows jetable n'est configurée ou disponible."
            if not failed
            else "Le script PowerShell échoue à l'analyse statique."
        ),
        "steps": steps,
        "failed_steps": [step["name"] for step in failed],
        "tests_executed": False,
        "isolation": {
            "execution": "static_only",
            "windows_disposable_vm": False,
        },
    }


def execute(
    code: str,
    language: str,
    *,
    test_code: str = "",
    integration_test_code: str = "",
    files: dict[str, str] | None = None,
    require_online: bool = False,
    timeout_seconds: int = 90,
) -> dict[str, Any]:
    language = str(language or "").strip().lower()
    online_forced_by_code = requires_online_integration(code, language)
    native_linux_required = requires_native_linux_runtime(code, language)
    require_online = bool(require_online or online_forced_by_code or native_linux_required)
    run_id = "test-forge-" + uuid.uuid4().hex[:12]
    try:
        safe_files = {
            deliverable_bundle.normalize_path(path): str(content)
            for path, content in dict(files or {}).items()
        }
    except deliverable_bundle.BundleError as exc:
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": language,
            "error": str(exc),
            "steps": [],
            "failed_steps": ["bundle_paths_safe"],
        }
    if language == "json":
        try:
            json.loads(code)
        except json.JSONDecodeError as exc:
            return {
                "success": False,
                "production_ready": False,
                "run_id": run_id,
                "language": language,
                "error": f"JSON invalide : {exc}",
                "steps": [],
            }
        checks = deliverable_bundle.reproducibility_checks(
            {"main.json": code, **safe_files}, language
        )
        return {
            "success": all(item["passed"] for item in checks),
            "production_ready": all(item["passed"] for item in checks),
            "run_id": run_id,
            "language": language,
            "steps": [
                {"name": "json_parse", "passed": True, "exit_code": 0},
                *checks,
            ],
            "isolation": {"network": "none", "execution": "parser_only"},
        }
    if language == "powershell":
        return _powershell_static(code, test_code, run_id, safe_files)
    if language not in FILE_NAMES:
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": language,
            "error": f"Langage non pris en charge par Test Forge : {language or 'inconnu'}.",
            "steps": [],
        }
    status = docker_status()
    if not status.get("available"):
        return {
            "success": False,
            "production_ready": False,
            "run_id": run_id,
            "language": language,
            "error": status.get("error"),
            "steps": [],
        }
    shape_error = _validate_test_shape(language, test_code)
    integration_shape_error = _validate_integration_shape(integration_test_code) if require_online else None
    if require_online and not integration_shape_error:
        integration_shape_error = _validate_integration_runtime_contract(
            language,
            integration_test_code,
        )
    main_name, test_name = FILE_NAMES[language]
    steps: list[dict[str, Any]] = []
    native_isolation: dict[str, Any] | None = None
    native_result_snapshot_available = False
    with tempfile.TemporaryDirectory(prefix="marvin-test-forge-") as temporary:
        directory = Path(temporary)
        reserved = {main_name.casefold(), test_name.casefold(), "integration.sh"}
        python_library_layout = bool(
            language == "python"
            and "pyproject.toml" in safe_files
            and any(
                path.startswith("src/") and path.endswith("/__init__.py")
                for path in safe_files
            )
        )
        for path, content in safe_files.items():
            if path.casefold() in reserved:
                continue
            destination = directory / Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        # Une bibliothèque Python en layout src/ n'a pas de main.py. En créer un
        # artificiellement fausse les tests de structure et déforme le livrable.
        if not python_library_layout:
            (directory / main_name).write_text(code, encoding="utf-8", newline="\n")
        if test_name and test_code.strip():
            (directory / test_name).write_text(test_code, encoding="utf-8", newline="\n")
        if integration_test_code.strip():
            (directory / "integration.sh").write_text(
                integration_test_code,
                encoding="utf-8",
                newline="\n",
            )
        executable = str(status["executable"])
        timeout = max(10, min(int(timeout_seconds), 180))
        if language == "bash":
            syntax = _run(
                executable, IMAGES["bats"], directory,
                ["-n", f"/workspace/{main_name}"],
                name="bash_syntax", timeout=timeout, entrypoint="/bin/bash",
            )
            steps.append(syntax)
            lint = _run(
                executable, IMAGES["shellcheck"], directory,
                ["--format=json", "--severity=warning", f"/workspace/{main_name}"],
                name="shellcheck", timeout=timeout,
            )
            lint["findings"] = _shellcheck_findings(lint)
            steps.append(lint)
            # Les tests Bats simulés sont utiles même lorsqu'une seconde phase en ligne
            # est requise. Ils évitent de perdre toute preuve si le runner natif manque.
            if not shape_error:
                steps.append(_run(
                    executable, IMAGES["bats"], directory,
                    ["--formatter", "tap", f"/workspace/{test_name}"],
                    name="bats", timeout=timeout,
                ))
        elif language == "python":
            steps.append(_run(
                executable, IMAGES["python"], directory,
                [
                    "python",
                    "-c",
                    (
                        "from pathlib import Path;"
                        "root=Path('/workspace');"
                        "[compile(p.read_text(encoding='utf-8'),str(p),'exec') "
                        "for p in root.rglob('*.py')]"
                    ),
                ],
                name="python_compile", timeout=timeout,
            ))
            if not shape_error and not require_online:
                steps.append(_run(
                    executable, IMAGES["python"], directory,
                    ["python", f"/workspace/{test_name}"],
                    name="python_unittest", timeout=timeout,
                ))
        elif language == "javascript":
            steps.append(_run(
                executable, IMAGES["node"], directory,
                [
                    "-c",
                    "find /workspace -type f \\( -name '*.js' -o -name '*.mjs' -o -name '*.cjs' \\) "
                    "-exec node --check '{}' \\;",
                ],
                name="node_check", timeout=timeout, entrypoint="/bin/sh",
            ))
            if not shape_error and not require_online:
                steps.append(_run(
                    executable, IMAGES["node"], directory,
                    ["node", "--test", f"/workspace/{test_name}"],
                    name="node_test", timeout=timeout,
                ))
        elif language == "go":
            steps.append(_run(
                executable, IMAGES["go"], directory,
                ["-c", "files=$(gofmt -l $(find /workspace -type f -name '*.go')); "
                 "if [ -n \"$files\" ]; then printf '%s\\n' \"$files\"; exit 1; fi"],
                name="gofmt", timeout=timeout, entrypoint="/bin/sh",
            ))
            if not shape_error and not require_online:
                steps.append(_run(
                    executable, IMAGES["go"], directory,
                    ["go", "vet", "./..."], name="go_vet", timeout=timeout,
                ))
                steps.append(_run(
                    executable, IMAGES["go"], directory,
                    ["go", "test", "./..."], name="go_test", timeout=timeout,
                ))
                steps.append(_run(
                    executable, IMAGES["go"], directory,
                    ["-c", "GOOS=windows GOARCH=amd64 go build -o /work/marvin-windows-amd64.exe ./..."],
                    name="go_build_windows", timeout=timeout, entrypoint="/bin/sh",
                ))
        if require_online:
            if native_linux_required:
                if integration_shape_error or shape_error:
                    steps.append({
                        "name": "native_linux_vm_required", "passed": False,
                        "exit_code": 2, "duration_ms": 0, "stdout": "",
                        "stderr": "; ".join(filter(None, (integration_shape_error, shape_error)))
                        or "La VM Debian exige integration.sh et une suite Bats valides.",
                        "image": None,
                    })
                else:
                    native_files = {
                        **safe_files, main_name: code, test_name: test_code,
                        "integration.sh": integration_test_code,
                    }
                    native = linux_test_runner.execute(
                        native_files, timeout_seconds=max(timeout, 1_800), capture_result=True,
                    )
                    native_isolation = native.get("isolation") if isinstance(native.get("isolation"), dict) else None
                    native_result_snapshot_available = bool(native.get("result_snapshot_available"))
                    if native.get("steps"):
                        steps.extend(native["steps"])
                    else:
                        steps.append({
                            "name": "native_linux_vm_required", "passed": False,
                            "exit_code": 2, "duration_ms": 0, "stdout": "",
                            "stderr": str(native.get("error") or "Runner Debian indisponible."),
                            "image": None,
                        })
            elif integration_shape_error:
                steps.append({
                    "name": "online_integration_required",
                    "passed": False,
                    "exit_code": 2,
                    "duration_ms": 0,
                    "stdout": "",
                    "stderr": integration_shape_error,
                    "image": IMAGES["debian13"],
                })
            else:
                steps.append(_run_online_integration(
                    executable,
                    directory,
                    language=language,
                    timeout=max(timeout, 600),
                ))
    reproducibility_files = dict(safe_files)
    if not python_library_layout:
        reproducibility_files[main_name] = code
    reproducibility = deliverable_bundle.reproducibility_checks(
        reproducibility_files,
        language,
    )
    steps.extend({
        "name": item["name"],
        "passed": item["passed"],
        "exit_code": 0 if item["passed"] else 2,
        "duration_ms": 0,
        "stdout": item["detail"] if item["passed"] else "",
        "stderr": "" if item["passed"] else item["detail"],
        "image": None,
    } for item in reproducibility)
    if shape_error:
        steps.append({
            "name": "test_suite_required",
            "passed": False,
            "exit_code": 2,
            "duration_ms": 0,
            "stdout": "",
            "stderr": shape_error,
            "image": None,
        })
    failed = [step for step in steps if not step.get("passed")]
    tests_executed = any(
            step["name"] in {"bats", "python_unittest", "node_test", "go_test", "native_debian_vm"}
        or (
            step["name"] == "online_integration"
            and step.get("test_completion_marker") is True
        )
        for step in steps
    )
    production_ready = not failed and tests_executed
    return {
        "success": production_ready,
        "production_ready": production_ready,
        "run_id": run_id,
        "language": language,
        "steps": steps,
        "failed_steps": [step["name"] for step in failed],
        "tests_executed": tests_executed,
        "online_required": bool(require_online),
        "online_requirement_reason": (
            "native_linux_runtime" if native_linux_required
            else "installer_detected" if online_forced_by_code
            else "requested" if require_online else None
        ),
        "online_executed": any(step["name"] in {"online_integration", "native_debian_vm"} for step in steps),
        "native_linux_required": native_linux_required,
        "result_snapshot_available": native_result_snapshot_available,
        "duration_ms": sum(int(step.get("duration_ms") or 0) for step in steps),
        "isolation": {
            "network": (
                "offline:none; native_vm:default_switch"
                if native_linux_required else
                "offline:none; integration:bridge" if require_online else "none"
            ),
            "host_mount": "read_only",
            "docker_socket_mounted": False,
            "online_container_has_host_secrets": False,
            "published_ports": False,
            "offline": {
                "read_only_rootfs": True,
                "cap_drop": "ALL",
                "no_new_privileges": True,
                "pids_limit": 128,
                "memory": "1g",
                "cpus": 1.0,
            },
            "online": (native_isolation if native_linux_required else {
                "disposable_writable_rootfs": True,
                "default_docker_capabilities": True,
                "privileged": False,
                "no_new_privileges": True,
                "pids_limit": 256,
                "memory": "1g",
                "cpus": 2.0,
            } if require_online else None),
        },
    }
