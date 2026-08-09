"""Régressions de la matérialisation des outils obligatoires."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agent_required_tools import (
    RequiredToolContext,
    inject_required_tool_calls,
)


def main() -> int:
    context = RequiredToolContext(
        user_query="reprends ce script",
        workspace_normalized_query="reprends ce script",
        workspace_mission_id="mission-1",
        workspace_action="resume",
        messages=[
            {"role": "user", "content": "écris un script"},
            {"role": "assistant", "content": "ancien livrable"},
            {"role": "user", "content": "reprends ce script"},
        ],
    )
    ids = iter(["required-a", "required-b"])
    injected = inject_required_tool_calls(
        required_names={"code_workspace_start", "ai_model_council"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=context,
        call_id_factory=lambda: next(ids),
    )
    assert injected.injected_names == (
        "ai_model_council",
        "code_workspace_start",
    )
    calls = {item["function"]["name"]: item for item in injected.tool_calls}
    assert calls["ai_model_council"]["function"]["arguments"] == {
        "question": "reprends ce script"
    }
    workspace_request = calls["code_workspace_start"]["function"]["arguments"][
        "request"
    ]
    assert "ancien livrable" in workspace_request

    deferred = inject_required_tool_calls(
        required_names={"ai_model_council"},
        executed_names=set(),
        tool_calls=[
            {
                "id": "web-1",
                "function": {"name": "web_research", "arguments": {}},
            }
        ],
        step=2,
        max_steps=10,
        context=context,
    )
    assert not deferred.injected and len(deferred.tool_calls) == 1

    near_budget = inject_required_tool_calls(
        required_names={"code_workspace_control", "web_deep_research"},
        executed_names=set(),
        tool_calls=[
            {
                "id": "other-1",
                "function": {"name": "calculator", "arguments": {}},
            }
        ],
        step=8,
        max_steps=10,
        context=context,
        call_id_factory=lambda: "required-fixed",
    )
    arguments = {
        call["function"]["name"]: call["function"]["arguments"]
        for call in near_budget.tool_calls
    }
    assert arguments["code_workspace_control"] == {
        "mission_id": "mission-1",
        "action": "resume",
    }
    assert arguments["web_deep_research"] == {"query": "reprends ce script"}

    crawl = inject_required_tool_calls(
        required_names={"web_site_crawl"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=RequiredToolContext(user_query="aspire le site France Travail"),
        call_id_factory=lambda: "required-crawl",
    )
    assert crawl.injected_names == ("web_site_crawl",)
    assert crawl.tool_calls[0]["function"]["arguments"] == {
        "site": "aspire le site France Travail"
    }

    calculator = inject_required_tool_calls(
        required_names={"calculator"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=RequiredToolContext(
            user_query=(
                "Le mot de passe fictif est DEMO-NON-SECRET. Utilise exactement "
                "l'outil calculator avec l'expression 37*229."
            )
        ),
        call_id_factory=lambda: "required-calculator",
    )
    assert calculator.injected_names == ("calculator",)
    assert calculator.tool_calls[0]["function"]["arguments"] == {
        "expression": "37*229"
    }

    satisfied = inject_required_tool_calls(
        required_names={"ai_model_council", "long_task_start"},
        executed_names={"ai_model_council"},
        tool_calls=[
            {
                "id": "long-1",
                "function": {"name": "long_task_start", "arguments": {}},
            }
        ],
        step=9,
        max_steps=10,
        context=context,
    )
    assert not satisfied.injected

    delivery_waits_for_forge = inject_required_tool_calls(
        required_names={"file_write"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=RequiredToolContext(
            user_query="mets le script dans install-c.sh sur mon bureau",
        ),
    )
    assert not delivery_waits_for_forge.injected

    delivery_ready = inject_required_tool_calls(
        required_names={"file_write"},
        executed_names=set(),
        tool_calls=[],
        step=1,
        max_steps=10,
        context=RequiredToolContext(
            user_query="mets le script dans install-c.sh sur mon bureau",
            successful_results=[{
                "tool": "ai_code_forge",
                "code": "#!/usr/bin/env bash\nset -Eeuo pipefail\n",
                "language": "bash",
            }],
        ),
        call_id_factory=lambda: "required-file",
    )
    assert delivery_ready.injected_names == ("file_write",)
    assert delivery_ready.tool_calls[0]["function"]["arguments"] == {
        "path": "Bureau/install-c.sh",
        "content": "#!/usr/bin/env bash\nset -Eeuo pipefail\n",
        "overwrite": False,
    }

    pptx = inject_required_tool_calls(
        required_names={"pptx_create"},
        executed_names=set(),
        tool_calls=[],
        step=0,
        max_steps=10,
        context=RequiredToolContext(
            user_query="je veux une présentation KOIOS en koios-final.pptx",
            messages=[
                {"role": "user", "content": "analyse KOIOS"},
                {
                    "role": "assistant",
                    "content": (
                        "# KOIOS\n## Services\n- Assistance informatique\n"
                        "- Sauvegarde\n## Contact\n| Téléphone | 04 89 81 06 59 |"
                    ),
                },
                {"role": "user", "content": "je veux une présentation KOIOS en koios-final.pptx"},
            ],
        ),
        call_id_factory=lambda: "required-pptx",
    )
    assert pptx.injected_names == ("pptx_create",)
    pptx_args = pptx.tool_calls[0]["function"]["arguments"]
    assert pptx_args["title"] == "KOIOS"
    assert pptx_args["output_path"] == "Bureau/koios-final.pptx"
    assert pptx_args["slides"] == [
        {"title": "Services", "bullets": ["Assistance informatique", "Sauvegarde"]},
        {"title": "Contact", "bullets": ["Téléphone — 04 89 81 06 59"]},
    ]

    hallucinated = inject_required_tool_calls(
        required_names={"pptx_create"},
        executed_names=set(),
        tool_calls=[{
            "id": "model-pptx",
            "function": {
                "name": "pptx_create",
                "arguments": {
                    "title": "KOIOS Lyon",
                    "slides": [{"title": "Implantation", "bullets": ["Lyon"]}],
                },
            },
        }],
        step=0,
        max_steps=10,
        context=RequiredToolContext(
            user_query="je veux une présentation KOIOS en koios-final.pptx",
            messages=[
                {"role": "user", "content": "analyse KOIOS"},
                {
                    "role": "assistant",
                    "content": "# KOIOS\n## Localisation\n- Aix-en-Provence",
                },
                {"role": "user", "content": "je veux une présentation KOIOS en koios-final.pptx"},
            ],
        ),
    )
    assert not hallucinated.injected
    clean_args = hallucinated.tool_calls[0]["function"]["arguments"]
    assert "Lyon" not in str(clean_args)
    assert clean_args["slides"] == [
        {"title": "Localisation", "bullets": ["Aix-en-Provence"]}
    ]

    grounded_model = inject_required_tool_calls(
        required_names={"pptx_create"},
        executed_names=set(),
        tool_calls=[{
            "id": "grounded-pptx",
            "function": {
                "name": "pptx_create",
                "arguments": {
                    "title": "Ville d'Aix-en-Provence",
                    "slides": [
                        {"title": "Actualités", "bullets": ["Les Nuits d'Aix 2026"]},
                        {"title": "Culture", "bullets": ["Musée Granet"]},
                    ],
                    "output_path": "Bureau/aix.pptx",
                },
            },
        }],
        step=1,
        max_steps=10,
        context=RequiredToolContext(
            user_query="crée le powerpoint depuis le crawl",
            successful_results=[{
                "tool": "web_site_crawl",
                "job_id": "crawl-aix-1234",
                "seed_url": "https://www.aixenprovence.fr/",
                "pages": [{
                    "title": "Mairie d'Aix-en-Provence",
                    "url": "https://www.aixenprovence.fr/",
                    "content": "Les Nuits d'Aix 2026\nMusée Granet",
                }],
            }],
        ),
    )
    assert grounded_model.tool_calls[0]["function"]["arguments"]["title"] == "Ville d'Aix-en-Provence"
    assert len(grounded_model.tool_calls[0]["function"]["arguments"]["slides"]) == 2

    duplicate_after_success = inject_required_tool_calls(
        required_names={"pptx_create"},
        executed_names={"pptx_create"},
        tool_calls=grounded_model.tool_calls,
        step=2,
        max_steps=10,
        context=RequiredToolContext(user_query="crée le powerpoint"),
    )
    assert duplicate_after_success.tool_calls == []

    media_fallback = inject_required_tool_calls(
        required_names={"pptx_create"},
        executed_names=set(),
        tool_calls=[],
        step=9,
        max_steps=10,
        context=RequiredToolContext(
            user_query="crée un powerpoint",
            messages=[
                {"role": "assistant", "content": "# Aix\n## Culture\n- Musée Granet\n## Sport\n- Ronde d'Aix"},
                {"role": "user", "content": "crée un powerpoint"},
            ],
            successful_results=[{
                "tool": "web_media_extract",
                "images": [
                    {"path": "C:/media/culture.jpg", "alt": "Culture", "page_url": "https://example.test/culture"},
                    {"path": "C:/media/sport.jpg", "alt": "Sport", "page_url": "https://example.test/sport"},
                ],
            }],
        ),
    )
    media_slides = media_fallback.tool_calls[0]["function"]["arguments"]["slides"]
    assert media_slides[0]["image_path"] == "C:/media/culture.jpg"
    assert media_slides[1]["source_url"] == "https://example.test/sport"
    print(
        "Agent Required Tools OK - contrats, autonomie, budget, Workspace et dédoublonnage."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
