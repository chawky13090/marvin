"""Deterministic regression tests for multi-file Code Forge deliverables."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import deliverable_bundle


def main() -> int:
    parsed = deliverable_bundle.parse(
        """```python file=main.py
from src.service import value
print(value())
```
```python file=src/service.py
def value(): return 42
```
```toml file=pyproject.toml
[project]
name = "marvin-sample"
dependencies = ["httpx==0.28.1"]
```
```text file=requirements.lock
httpx==0.28.1
```
""",
        default_language="python",
    )
    assert parsed["errors"] == []
    assert parsed["primary"] == "main.py"
    assert parsed["file_count"] == 4
    assert "src/service.py" in deliverable_bundle.supporting_files(parsed)
    checks = deliverable_bundle.reproducibility_checks(parsed["files"], "python")
    assert all(item["passed"] for item in checks)

    python_library = deliverable_bundle.parse(
        "```toml file=pyproject.toml\n[project]\nname='slugify-safe'\nversion='0.1.0'\n```\n"
        "```python file=src/slugify_safe/__init__.py\ndef slugify(text: str) -> str: return text\n```\n"
        "```python file=tests/test_slugify.py\nimport unittest\n```",
        default_language="python",
    )
    assert python_library["errors"] == []
    assert python_library["primary"] == "src/slugify_safe/__init__.py"
    assert "main.py" not in python_library["files"]
    scripted_library = deliverable_bundle.parse(
        "```toml file=pyproject.toml\n"
        "[project]\nname='probe'\nversion='0.1.0'\n"
        "[project.scripts]\nprobe='probe.cli:main'\n```\n"
        "```python file=src/probe/__init__.py\nfrom .cli import main\n```\n"
        "```python file=src/probe/__main__.py\nfrom .cli import main\nmain()\n```\n"
        "```python file=src/probe/cli.py\ndef main() -> int: return 0\n```\n",
        default_language="python",
    )
    assert scripted_library["errors"] == []
    assert scripted_library["primary"] == "src/probe/cli.py"

    escaped_metadata = deliverable_bundle.parse(
        '```python file=\\"src/pkg/__init__.py\\"\ndef value(): return 1\n```\n'
        '```toml file=pyproject.toml\n[project]\nname="pkg"\nversion="0.1.0"\n```',
        default_language="python",
    )
    assert escaped_metadata["errors"] == []
    assert escaped_metadata["primary"] == "src/pkg/__init__.py"

    javascript = deliverable_bundle.parse(
        """```javascript file=main.mjs
import leftPad from 'left-pad';
console.log(leftPad('x', 2));
```
```json file=package.json
{"dependencies":{"left-pad":"1.3.0"}}
```
""",
        default_language="javascript",
    )
    js_checks = deliverable_bundle.reproducibility_checks(javascript["files"], "javascript")
    assert any(item["name"] == "javascript_dependencies_locked" and not item["passed"] for item in js_checks)

    go_bundle = deliverable_bundle.parse(
        "```go file=main.go\npackage main\nfunc main() {}\n```\n"
        "```text file=go.mod\nmodule example.com/marvin/sample\n\ngo 1.26\n```",
        default_language="go",
    )
    assert go_bundle["primary"] == "main.go"
    assert all(item["passed"] for item in deliverable_bundle.reproducibility_checks(go_bundle["files"], "go"))
    missing_go_mod = deliverable_bundle.reproducibility_checks({"main.go": "package main"}, "go")
    assert any(item["name"] == "go_module_valid" and not item["passed"] for item in missing_go_mod)

    traversal = deliverable_bundle.parse(
        "```python file=../escape.py\nprint('no')\n```",
        default_language="python",
    )
    assert traversal["errors"]
    ambiguous = deliverable_bundle.parse(
        "```python\nprint('one')\n```\n```python\nprint('two')\n```",
        default_language="python",
    )
    assert ambiguous["errors"]
    collision = deliverable_bundle.parse(
        "```python file=main.py\nprint('ok')\n```\n```python file=MAIN.PY\nprint('bad')\n```",
        default_language="python",
    )
    assert collision["errors"]
    try:
        deliverable_bundle.normalize_path(r"C:\Windows\system32\bad.ps1")
    except deliverable_bundle.BundleError:
        pass
    else:
        raise AssertionError("Un chemin absolu Windows doit être refusé.")
    for unsafe in ("NUL.txt", "src/name:stream.py", "trailing./file.py"):
        try:
            deliverable_bundle.normalize_path(unsafe)
        except deliverable_bundle.BundleError:
            pass
        else:
            raise AssertionError(f"Le chemin Windows dangereux doit être refusé : {unsafe}")

    print("Deliverable Bundle OK - multi-fichiers, chemins sûrs et verrous reproductibles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
