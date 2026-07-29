"""Tests déterministes du contrat, des sources et du gate Research Forge v3."""
from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from research_contract import build_contract, initial_query_portfolio
from research_forge import (
    conservative_cited_report,
    evaluate_report,
    extract_citations,
    link_citations,
)
from research_sources import SourceIndex, canonical_url
import research_engine_v3
import research_export
import research_swarm


def expect_value_error(callback) -> None:
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("ValueError attendu.")


def main() -> int:
    contract = build_contract(
        "Effectue une recherche approfondie sur les moteurs agentiques.",
        {
            "source_policy": "primary_first",
            "preferred_domains": ["docs.searxng.org"],
            "excluded_domains": ["example.invalid"],
            "freshness": "year",
        },
    )
    assert contract.depth == "deep"
    assert contract.budget.max_rounds == 20
    assert contract.preferred_domains == ("docs.searxng.org",)
    portfolio = initial_query_portfolio(contract)
    assert len(portfolio) >= 24
    assert {item["axis"] for item in portfolio} >= {"primary", "counterevidence", "verification"}
    assert portfolio[1]["query"].startswith("site:docs.searxng.org")

    exhaustive = build_contract("Étude exhaustive", {"max_pages": 80})
    assert exhaustive.depth == "exhaustive"
    assert exhaustive.budget.max_pages == 80
    expect_value_error(lambda: build_contract("x", {"depth": "unknown"}))
    expect_value_error(lambda: build_contract("x", {
        "preferred_domains": ["docs.example.org"],
        "excluded_domains": ["docs.example.org"],
    }))
    expect_value_error(lambda: build_contract("x", {"max_pages": 151}))

    assert canonical_url(
        "HTTPS://Example.COM:443/docs//guide/?utm_source=test&a=2&a=1#part"
    ) == "https://example.com/docs/guide?a=1&a=2"
    index = SourceIndex(max_sources_per_domain=2)
    first, created = index.add(
        url="https://docs.example.org/guide?utm_source=x",
        title="Official documentation",
        text="A" * 300,
        query_id="query-1",
    )
    assert created is True and first.source_type == "primary"
    same_url, created = index.add(
        url="https://docs.example.org/guide",
        title="Duplicate URL",
        text="Different",
        query_id="query-2",
    )
    assert created is False and same_url.id == first.id
    same_content, created = index.add(
        url="https://mirror.example.net/page",
        title="Mirror",
        text="A" * 300,
        query_id="query-3",
    )
    assert created is False and same_content.id == first.id
    second, created = index.add(
        url="https://example.net/analysis",
        title="Analysis",
        text="B" * 300,
        query_id="query-4",
    )
    assert created is True and second.id == "source-2"
    assert index.metrics()["unique_domains"] == 2

    report = (
        "Le système est documenté par la source officielle [1]. "
        "Il permet également une analyse secondaire indépendante [2]."
    )
    sources = [first.as_dict(include_text=False), second.as_dict(include_text=False)]
    metrics = evaluate_report(report, sources)
    assert metrics["gate_passed"] is True
    assert metrics["citation_validity"] == 1.0
    assert metrics["factual_citation_coverage"] == 1.0
    assert extract_citations("Test [source-2] et [1].") == [2, 1]
    failed = evaluate_report("Le système est documenté [3].", sources)
    assert failed["gate_passed"] is False
    assert failed["invalid_citations"] == [3]
    linked = link_citations(report, sources)
    assert "[source-1](https://docs.example.org/guide)" in linked
    conservative = conservative_cited_report(
        "Le système est documenté [source-1]. Une affirmation est sans preuve.",
        sources,
    )
    assert "documenté [source-1]" in conservative
    assert "sans preuve" not in conservative
    export_run = {
        "id": "swarm-123456789abc",
        "answer": report,
        "sources": sources,
        "forge": metrics,
    }
    markdown, markdown_type, markdown_name = research_export.export_run(export_run, "md")
    assert markdown.startswith(b"# Rapport")
    assert markdown_type.startswith("text/markdown")
    assert markdown_name.endswith(".md")
    docx, docx_type, _ = research_export.export_run(export_run, "docx")
    assert docx.startswith(b"PK") and "wordprocessingml" in docx_type
    pdf, pdf_type, _ = research_export.export_run(export_run, "pdf")
    assert pdf.startswith(b"%PDF") and pdf_type == "application/pdf"
    expect_value_error(lambda: research_export.export_run(export_run, "exe"))

    async def exercise_adaptive_engine() -> None:
        counter = {"search": 0}
        behavior = {"bad_synthesis": False}

        async def fake_search(args):
            counter["search"] += 1
            base = counter["search"] * 10
            primary = "documentation officielle" in args["query"]
            return {
                "success": True,
                "provider": "SearXNG",
                "results": [
                    {
                        "title": f"Source {base + offset}",
                        "url": (
                            f"https://docs.domain{base + offset}.example.org/page"
                            if primary
                            else f"https://domain{base + offset}.example.org/page"
                        ),
                        "snippet": "Résumé",
                    }
                    for offset in range(4)
                ],
            }

        async def fake_fetch(url, *, max_chars=3500):
            marker = url.split("domain", 1)[1].split(".", 1)[0]
            return {
                "title": f"Source {marker}",
                "url": url,
                "text": (
                    f"preuve{marker} méthode{marker} résultat{marker} "
                    f"contexte{marker} analyse{marker} limite{marker}. "
                ) * 80,
            }

        async def fake_model(client, model, prompt, phase, need):
            if phase == "v3_synthesis":
                if behavior["bad_synthesis"]:
                    return {
                        "ok": True,
                        "model": model,
                        "family": "test",
                        "answer": "Le système est nécessairement parfait et sans aucune limite.",
                        "duration_ms": 1,
                    }
                return {
                    "ok": True,
                    "model": model,
                    "family": "test",
                    "answer": (
                        "Le premier constat est confirmé par les preuves [source-1]. "
                        "Le second constat est confirmé indépendamment [source-2]."
                    ),
                    "duration_ms": 1,
                }
            if phase.startswith("v3_citation_repair") and behavior["bad_synthesis"]:
                answer = "Le système est nécessairement parfait et sans aucune limite."
            elif phase.startswith("adaptive_gap"):
                answer = "[]"
            elif phase == "v3_query_plan":
                answer = "[]"
            else:
                answer = "Fait vérifié [source-1]. Limite documentée [source-2]."
            return {
                "ok": True,
                "model": model,
                "family": "test",
                "answer": answer,
                "duration_ms": 1,
            }

        market = [
            {"model": f"model-{index}:cloud", "family": f"family-{index}", "score": 90}
            for index in range(1, 6)
        ]
        progress_events = []
        async def collect_progress(value):
            progress_events.append(value)

        with (
            patch.object(research_engine_v3, "execute_web_search", new=fake_search),
            patch.object(research_engine_v3.evidence_fabric, "scan_untrusted_content", return_value={}),
            patch.object(research_engine_v3.model_market, "recommend", return_value=market),
            patch.object(research_swarm, "_fetch_public_source", new=fake_fetch),
            patch.object(research_swarm, "_model_call", new=fake_model),
            patch.object(research_swarm, "validate_runtime", return_value=(None, market)),
            patch.object(research_swarm, "_record_run", side_effect=lambda run: {**run, "evidence_persisted": True}),
            patch.object(research_engine_v3.tool_activity, "emit", new=AsyncMock()),
        ):
            result = await research_engine_v3.execute(
                "Recherche approfondie sur un système public",
                max_duration_seconds=600,
                progress=collect_progress,
            )
            checkpoint = next(
                event["checkpoint"]
                for event in reversed(progress_events)
                if event.get("checkpoint")
            )
            resumed = await research_engine_v3.execute(
                "Recherche approfondie sur un système public",
                max_duration_seconds=600,
                options={"depth": "deep", "_resume_checkpoint": checkpoint},
            )
            behavior["bad_synthesis"] = True
            refused = await research_engine_v3.execute(
                "Recherche approfondie sur un système public",
                max_duration_seconds=600,
            )
        assert result["success"] is True
        assert result["engine_version"] == "v3"
        assert result["forge"]["gate_passed"] is True
        assert "[source-1](https://" in result["answer"]
        assert result["source_coverage"]["unique_sources"] >= 8
        assert result["source_coverage"]["axis_coverage"] == 1.0
        assert len(result["queries"]) >= 24
        assert resumed["success"] is True
        assert len(resumed["queries"]) >= 24
        assert refused["draft_withheld"] is True
        assert "refusé" in refused["error"]

    asyncio.run(exercise_adaptive_engine())
    print("Research Engine v3 OK - contrat, déduplication et gate déterministes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
