"""Exécution Python en processus séparé, bornée et honnête sur son isolation."""

from __future__ import annotations

import ast
import asyncio
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil


_output_root: Path | None = None
_python_executable = sys.executable
_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex[:12]
_MAX_CODE_CHARS = 100_000
_MAX_STDOUT_BYTES = 64_000
_MAX_STDERR_BYTES = 32_000
_MAX_ARTIFACTS = 100
_SAFE_IMPORTS = {
    "collections",
    "datetime",
    "decimal",
    "fractions",
    "functools",
    "itertools",
    "json",
    "math",
    "matplotlib",
    "numpy",
    "pandas",
    "random",
    "re",
    "statistics",
    "string",
}
_SENSITIVE_MODULES = {
    "builtins",
    "ctypes",
    "ftplib",
    "http",
    "importlib",
    "io",
    "multiprocessing",
    "os",
    "pathlib",
    "pickle",
    "psutil",
    "resource",
    "shutil",
    "smtplib",
    "socket",
    "subprocess",
    "sys",
    "threading",
    "urllib",
    "winreg",
}
_SENSITIVE_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}
_SENSITIVE_ATTRIBUTES = {
    "chmod",
    "connect",
    "exec",
    "mkdir",
    "open",
    "popen",
    "read_csv",
    "read_excel",
    "read_bytes",
    "read_text",
    "remove",
    "rename",
    "replace",
    "request",
    "rmdir",
    "run",
    "send",
    "save",
    "savefig",
    "spawn",
    "start",
    "system",
    "touch",
    "to_csv",
    "to_excel",
    "unlink",
    "write_bytes",
    "write_text",
}


def configure(
    *,
    output_root: str | os.PathLike[str],
    python_executable: str = sys.executable,
    id_factory: Callable[[], str] | None = None,
) -> None:
    global _output_root, _python_executable, _id_factory
    _output_root = Path(output_root).resolve()
    _python_executable = str(python_executable)
    if id_factory is not None:
        _id_factory = id_factory


def scan_code(code: str) -> list[str]:
    """Signale les capacités qui nécessitent une confirmation d'accès hôte."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Erreur de syntaxe : {exc.msg} (ligne {exc.lineno})"]
    risks: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root not in _SAFE_IMPORTS:
                    label = (
                        "module sensible"
                        if root in _SENSITIVE_MODULES
                        else "module non autorisé par défaut"
                    )
                    risks.add(f"{label} : {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root not in _SAFE_IMPORTS:
                label = (
                    "module sensible"
                    if root in _SENSITIVE_MODULES
                    else "module non autorisé par défaut"
                )
                risks.add(f"{label} : {node.module or '?'}")
        elif isinstance(node, ast.Call):
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name in _SENSITIVE_CALLS:
                risks.add(f"appel sensible : {name}(...)")
            if isinstance(function, ast.Attribute) and name in _SENSITIVE_ATTRIBUTES:
                risks.add(f"méthode sensible : .{name}(...)")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            risks.add(f"introspection spéciale : .{node.attr}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            risks.add(f"nom spécial : {node.id}")
    return sorted(risks)


def _minimal_environment(workdir: Path) -> dict[str, str]:
    allowed = (
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
    )
    environment = {
        key: os.environ[key]
        for key in allowed
        if key in os.environ
    }
    environment.update(
        {
            "HOME": str(workdir),
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(workdir / ".matplotlib"),
            "PYTHONIOENCODING": "utf-8",
            "TEMP": str(workdir),
            "TMP": str(workdir),
        }
    )
    return environment


def _terminate_process_tree(pid: int) -> None:
    try:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.Error:
                pass
        _, alive = psutil.wait_procs(children, timeout=1)
        for child in alive:
            try:
                child.kill()
            except psutil.Error:
                pass
        try:
            process.kill()
        except psutil.Error:
            pass
    except psutil.Error:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass


def _read_bounded(file_object: Any, limit: int) -> tuple[bytes, bool]:
    file_object.seek(0)
    content = file_object.read(limit + 1)
    return content[:limit], len(content) > limit


async def execute(args: dict) -> dict:
    if _output_root is None:
        return {"error": "L'exécuteur Python n'est pas configuré."}
    code = str(args.get("code") or "").strip()
    if not code:
        return {"error": "Paramètre 'code' requis."}
    if len(code) > _MAX_CODE_CHARS:
        return {"error": f"Le code dépasse {_MAX_CODE_CHARS} caractères."}
    try:
        timeout = int(args.get("timeout", 15))
    except (TypeError, ValueError):
        return {"error": "'timeout' doit être un entier entre 1 et 60."}
    if not 1 <= timeout <= 60:
        return {"error": "'timeout' doit être compris entre 1 et 60."}
    confirmed = bool(args.get("confirmed", False))
    risks = scan_code(code)
    syntax_errors = [risk for risk in risks if risk.startswith("Erreur de syntaxe")]
    if syntax_errors:
        return {"error": syntax_errors[0]}
    if risks and not confirmed:
        return {
            "requiresConfirmation": True,
            "message": (
                "Ce code demande un accès non confiné à l'hôte "
                f"({', '.join(risks[:4])}). Confirmer l'exécution ?"
            ),
            "risks": risks,
            "isolation": "process_only",
            "sandboxed": False,
        }

    run_id = _id_factory()
    output_dir = (_output_root / run_id).resolve()
    try:
        output_dir.relative_to(_output_root)
    except ValueError:
        return {"error": "Identifiant d'exécution invalide."}
    output_dir.mkdir(parents=True, exist_ok=False)
    script_path = output_dir / "_script.py"
    marker = f"___MARVIN_RESULT_{uuid.uuid4().hex}___"
    script_path.write_text(
        code
        + "\ntry:\n"
        + "    _mv_r = locals().get('result', locals().get('output'))\n"
        + "    if _mv_r is not None:\n"
        + f"        print({marker!r} + repr(_mv_r)[:2000])\n"
        + "except Exception:\n"
        + "    pass\n",
        encoding="utf-8",
    )
    creation_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creation_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creation_kwargs["start_new_session"] = True

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            process = await asyncio.create_subprocess_exec(
                _python_executable,
                "-I",
                str(script_path),
                cwd=str(output_dir),
                env=_minimal_environment(output_dir),
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                **creation_kwargs,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await asyncio.to_thread(_terminate_process_tree, process.pid)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                return {
                    "error": f"Timeout dépassé ({timeout}s).",
                    "timed_out": True,
                    "isolation": "process_only",
                    "sandboxed": False,
                }
        except (OSError, RuntimeError) as exc:
            return {
                "error": f"Échec de lancement du processus Python : {str(exc)[:300]}"
            }
        stdout_bytes, stdout_truncated = _read_bounded(
            stdout_file,
            _MAX_STDOUT_BYTES,
        )
        stderr_bytes, stderr_truncated = _read_bounded(
            stderr_file,
            _MAX_STDERR_BYTES,
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    result_value = None
    clean_lines = []
    for line in stdout.splitlines():
        if line.startswith(marker):
            result_value = line[len(marker):][:2000]
        else:
            clean_lines.append(line)
    generated = []
    artifact_truncated = False
    for path in sorted(output_dir.iterdir(), key=lambda item: item.name.lower()):
        if path.name in {"_script.py", ".matplotlib"} or not path.is_file():
            continue
        if len(generated) >= _MAX_ARTIFACTS:
            artifact_truncated = True
            break
        try:
            size = path.stat().st_size
        except OSError:
            continue
        generated.append({"path": str(path), "size_bytes": size})

    response = {
        "success": process.returncode == 0,
        "stdout": "\n".join(clean_lines) or "(aucune sortie)",
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "result": result_value,
        "returncode": process.returncode,
        "isolation": "process_only",
        "sandboxed": False,
        "network_isolated": False,
        "environment_inherited": False,
        "run_id": run_id,
        "artifacts_truncated": artifact_truncated,
    }
    if generated:
        response["artifacts"] = generated
        response["files"] = [item["path"] for item in generated]
        if len(generated) == 1:
            response["path"] = generated[0]["path"]
            response["message"] = f"Fichier généré : {Path(generated[0]['path']).name}"
    if process.returncode != 0 and not stderr:
        response["error"] = (
            "Le script a échoué avec un code de retour non nul sans message d'erreur."
        )
    if confirmed:
        response["warning"] = (
            "Exécution confirmée avec accès hôte : utilisez Test Forge/VM pour "
            "un confinement système et réseau réel."
        )
    return response
