from __future__ import annotations

import argparse
import importlib.abc
import importlib.machinery
import inspect
import json
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


def install_runtime_guard() -> None:
    sys.meta_path.insert(0, AllowListFinder())

    # sys.addaudithook est irréversible dans ce processus. Cette garde doit rester
    # confinée au sous-processus du harnais et ne doit jamais être installée dans
    # le backend Marvin, même pour éviter le coût de création du sous-processus.
    def audit(event: str, args) -> None:
        if event not in {"compile", "exec"} or not _caller_is_fixture():
            return
        filename = ""
        if event == "compile" and len(args) > 1:
            filename = str(args[1])
        elif event == "exec" and args:
            filename = str(getattr(args[0], "co_filename", ""))
        try:
            source_path = Path(filename).resolve()
            is_static_fixture_module = (
                source_path.suffix == ".py"
                and source_path.exists()
                and (PACKAGE_ROOT in source_path.parents or STDLIB_ROOT in source_path.parents)
            )
        except (OSError, RuntimeError, ValueError):
            is_static_fixture_module = False
        if not is_static_fixture_module:
            raise RuntimeError(f"fixture_dynamic_code_denied:{event}")

    sys.addaudithook(audit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("allowed", "forbidden-import", "forbidden-dynamic-code"))
    args = parser.parse_args()
    install_runtime_guard()
    if args.mode == "allowed":
        from e7_fixture_harness import build_pilot_plans
        plans = build_pilot_plans()
        print(json.dumps({"accepted": True, "plans": len(plans)}))
        return 0
    if args.mode == "forbidden-import":
        __import__("backend.tools")
        return 2
    source = "result = 1"
    exec(compile(source, "<fixture-canary>", "exec"), {})
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
