from __future__ import annotations

import argparse
import importlib.abc
import importlib.machinery
import inspect
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "e7_fixture_harness"
STDLIB_ROOT = Path(sysconfig.get_paths()["stdlib"]).resolve()
if str(PACKAGE_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT.parent))


def _caller_is_fixture() -> bool:
    for frame in inspect.stack()[2:]:
        try:
            path = Path(frame.filename).resolve()
        except (OSError, RuntimeError):
            continue
        if path == PACKAGE_ROOT or PACKAGE_ROOT in path.parents:
            return True
    return False


class AllowListFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path=None, target=None):
        root = fullname.split(".", 1)[0]
        if fullname == PACKAGE_NAME or fullname.startswith(PACKAGE_NAME + "."):
            return None
        if root in sys.stdlib_module_names:
            return None
        raise ImportError(f"fixture_import_denied:{fullname}")


def _normalize_path(value: object) -> Path:
    return Path(os.fspath(value)).resolve()


def _guarded_child_command() -> list[str]:
    return [sys.executable, "-I", str(Path(__file__).resolve()), "child-probe"]


def _command_key(argv: object) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        return ("raw", os.fsdecode(argv))
    values = tuple(str(item) for item in argv)
    if not values:
        raise RuntimeError("fixture_spawn_denied:empty_arguments")
    return ("argv", str(_normalize_path(values[0])).casefold(), *values[1:])


def _permitted_command_keys(argv: tuple[str, ...]) -> set[tuple[str, ...]]:
    return {_command_key(argv), ("raw", subprocess.list2cmdline(list(argv)))}


def install_runtime_guard(*, permitted_commands: tuple[tuple[str, ...], ...] = ()) -> None:
    sys.meta_path.insert(0, AllowListFinder())

    # sys.addaudithook est irréversible dans ce processus. Cette garde doit rester
    # confinée au sous-processus du harnais et ne doit jamais être installée dans
    # le backend Marvin, même pour éviter le coût de création du sous-processus.
    def audit(event: str, args) -> None:
        watched = {"compile", "exec", "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"}
        if event not in watched or not _caller_is_fixture():
            return
        if event in {"compile", "exec"}:
            filename = ""
            if event == "compile" and len(args) > 1:
                filename = str(args[1])
            elif event == "exec" and args:
                filename = str(getattr(args[0], "co_filename", ""))
            try:
                source_path = Path(filename).resolve()
                static_module = (
                    source_path.suffix == ".py" and source_path.exists()
                    and (PACKAGE_ROOT in source_path.parents or STDLIB_ROOT in source_path.parents)
                )
            except (OSError, RuntimeError, ValueError):
                static_module = False
            if not static_module:
                raise RuntimeError(f"fixture_dynamic_code_denied:{event}")
            return
        if event == "subprocess.Popen":
            executable, argv, cwd, env = args
            command = _command_key(argv)
            if executable is not None:
                resolved_executable = executable
            elif command[0] == "argv":
                resolved_executable = command[1]
            else:
                resolved_executable = sys.executable
            executable_matches = _normalize_path(resolved_executable) == Path(sys.executable).resolve()
            permitted_keys = set().union(*(_permitted_command_keys(item) for item in permitted_commands)) if permitted_commands else set()
            if not executable_matches or command not in permitted_keys:
                raise RuntimeError("fixture_spawn_denied:subprocess.Popen")
            if cwd is not None and _normalize_path(cwd) != PACKAGE_ROOT.parent.resolve():
                raise RuntimeError("fixture_spawn_denied:cwd")
            if env is not None and set(env) - {"PYTHONIOENCODING", "SYSTEMROOT", "WINDIR"}:
                raise RuntimeError("fixture_spawn_denied:environment")
            return
        if event in {"os.system", "os.exec", "os.posix_spawn", "os.spawn"}:
            raise RuntimeError(f"fixture_spawn_denied:{event}")

    sys.addaudithook(audit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=(
        "allowed", "forbidden-import", "forbidden-dynamic-code",
        "recursive-child", "child-probe", "forbidden-spawn",
    ))
    args = parser.parse_args()
    permitted = (tuple(_guarded_child_command()),) if args.mode == "recursive-child" else ()
    install_runtime_guard(permitted_commands=permitted)
    if args.mode == "allowed":
        from e7_fixture_harness import build_pilot_plans
        plans = build_pilot_plans()
        print(json.dumps({"accepted": True, "plans": len(plans)}))
        return 0
    if args.mode == "forbidden-import":
        __import__("backend.tools")
        return 2
    if args.mode == "child-probe":
        try:
            __import__("backend.tools")
        except ImportError as exc:
            print(json.dumps({"child_guard_active": True, "denied": str(exc)}))
            return 0
        return 4
    if args.mode == "recursive-child":
        child_env = {"PYTHONIOENCODING": "utf-8"}
        if os.name == "nt":
            child_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
            child_env["WINDIR"] = os.environ.get("WINDIR", "")
        completed = subprocess.run(
            _guarded_child_command(), cwd=PACKAGE_ROOT.parent, env=child_env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        print(completed.stdout.strip())
        return 0
    if args.mode == "forbidden-spawn":
        subprocess.run([sys.executable, "-c", "print('denied')"], check=False)
        return 5
    source = "result = 1"
    exec(compile(source, "<fixture-canary>", "exec"), {})
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
