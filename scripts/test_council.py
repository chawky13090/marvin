"""Régressions déterministes du routage Cloud et de Council v2, sans appel payant."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cloud_routing as routing  # noqa: E402
import agent  # noqa: E402
import tools  # noqa: E402


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def main() -> int:
    installed = [
        "deepseek-v4-pro:cloud", "deepseek-v4-flash:cloud", "qwen3.5:397b-cloud",
        "glm-5.2:cloud", "kimi-k2.7-code:cloud", "nemotron-3-super:cloud",
        "mistral-large-3:675b-cloud", "minimax-m3:cloud",
    ]
    with patch.object(routing, "list_installed_cloud_models", return_value=installed):
        panel = routing.list_distinct_cloud_models("general")
        check(len(panel) >= 5, "cinq familles disponibles")
        check(len({routing.model_family(model) for model in panel[:5]}) == 5,
              "familles Council réellement distinctes")
        code_panel = routing.list_distinct_cloud_models("code")
        check(code_panel[0].startswith("kimi"), "spécialiste code reconnu")

    with (
        patch.object(routing, "get_cloud_config", return_value=(True, {"agent": "retire:cloud"})),
        patch.object(routing, "list_installed_cloud_models", return_value=["deepseek-v4-pro:cloud"]),
        patch.object(routing, "pick_best_cloud_model", return_value="deepseek-v4-pro:cloud"),
        patch.object(routing, "is_local_only_lockdown", return_value=False),
        patch.object(routing, "is_ultra_unrestricted", return_value=True),
    ):
        selected = routing.resolve_model(None, profile="agent", text_for_sensitivity="question publique")
        check(selected == "deepseek-v4-pro:cloud", "override cloud périmé remplacé")

    registry = set(tools.TOOLS_REGISTRY)
    specs = {item["function"]["name"] for item in tools.TOOLS_SPEC}
    check(registry == specs, "registre Council/SSH synchronisé")
    check("ssh_connection_save" in registry, "enregistrement SSH disponible")
    check("email_send" in agent._ALWAYS_CONFIRM_TOOLS, "email toujours confirmé en Expert")
    check("ssh_exec" in agent._ALWAYS_CONFIRM_TOOLS, "SSH sortant toujours confirmé en Expert")

    print("Council v2 OK - 8 régressions déterministes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
