"""Regressions des validations deterministes de la boucle agentique."""

from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from agent_safety import scan_dangerous_script_patterns, validator_for


def main() -> int:
    validator = validator_for(({
        "function": {
            "name": "file_read",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "mode": {"type": "string", "enum": ["text", "binary"]},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["path"],
            },
        }
    },))
    assert validator("file_read", {"path": "C:/test.txt"}) is None
    assert "path" in (validator("file_read", {"path": "  "}) or "")
    assert "objet JSON" in (validator("file_read", []) or "")
    assert "integer" in (validator("file_read", {"path": "x", "limit": "2"}) or "")
    assert "inférieur ou égal" in (
        validator("file_read", {"path": "x", "limit": 501}) or ""
    )
    assert "valeurs" in (
        validator("file_read", {"path": "x", "mode": "other"}) or ""
    )
    assert "tags[0]" in (
        validator("file_read", {"path": "x", "tags": [42]}) or ""
    )
    assert validator("unknown", {}) is None

    assert scan_dangerous_script_patterns("chmod -R 777 /srv") == []
    warnings = scan_dangerous_script_patterns("```bash\nchmod -R 777 /srv\nufw disable\n```")
    assert len(warnings) == 2
    assert any("777" in warning for warning in warnings)
    assert any("pare-feu" in warning for warning in warnings)
    assert scan_dangerous_script_patterns("$(date)", require_code_fence=False) == []
    assert len(scan_dangerous_script_patterns(
        "Rapport $(date)", require_code_fence=False, document_mode=True
    )) == 1

    tree = ast.parse((BACKEND / "agent.py").read_text(encoding="utf-8-sig"))
    definitions = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_validate_tool_args" not in definitions
    assert "_scan_dangerous_script_patterns" not in definitions
    print("Agent Safety OK - arguments, scripts, documents et facade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
