"""Régressions du contexte prompt d'une compétence."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_skill_context import build_skill_prompt_context


def main() -> int:
    context = build_skill_prompt_context(
        "base",
        {
            "name": "diagnostic",
            "description": "Diagnostiquer",
            "body": "Commence par observer.",
            "related": ["réseau", None, ""],
            "tools": ["pc_info"],
        },
        get_golden_trace=lambda _name: {
            "calls": [
                {"tool": "pc_info", "args": {"detail": True}},
                {"args": {}},
            ]
        },
        resources_prompt_block=lambda _name: "\nRESSOURCE",
    )
    assert context.valid is True
    assert context.requires_agent_profile is True
    assert "Compétence activée : diagnostic" in context.prompt
    assert "réseau" in context.prompt
    assert "`pc_info`" in context.prompt
    assert "RESSOURCE" in context.prompt

    invalid = build_skill_prompt_context(
        "base",
        {"name": "incomplète", "tools": ["pc_info"]},
        get_golden_trace=lambda _name: None,
        resources_prompt_block=lambda _name: "",
    )
    assert invalid.prompt == "base"
    assert invalid.valid is False
    assert invalid.requires_agent_profile is False

    resilient = build_skill_prompt_context(
        "base",
        {"name": "simple", "description": "Description", "body": "Méthode"},
        get_golden_trace=lambda _name: (_ for _ in ()).throw(RuntimeError("golden")),
        resources_prompt_block=lambda _name: (_ for _ in ()).throw(RuntimeError("resource")),
    )
    assert resilient.valid is True
    assert resilient.requires_agent_profile is False
    print("Agent Skill Context OK - méthode, golden path, ressources et repli invalide.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
