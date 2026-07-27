"""Régressions déterministes du domaine documentation d'intervention."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import intervention_docs


async def _run() -> None:
    exports: list[tuple[str, dict]] = []

    async def fake_docx(args: dict) -> dict:
        exports.append(("docx", args))
        return {"success": True, "path": args["path"], "size": 12}

    async def fake_pdf(args: dict) -> dict:
        exports.append(("pdf", args))
        return {"success": True, "path": args["path"], "size": 24}

    async def fake_extract(_args: dict) -> dict:
        return {"success": True, "commands": []}

    def fake_risk(command: str) -> dict:
        return {
            "risk_level": "safe",
            "command": command,
            "risk_explanation": "",
            "safer_alternative": "",
        }

    intervention_docs.configure(
        file_create_docx=fake_docx,
        file_create_pdf=fake_pdf,
        cmd_extract=fake_extract,
        analyze_risk=fake_risk,
    )

    assert intervention_docs._render_template(
        "Client {{name}} / {{missing}}", {"name": "KOIOS"}
    ).startswith("Client KOIOS")
    assert "non renseign" in intervention_docs._render_template(
        "{{missing}}", {}
    )

    assert "raw_text" in (
        await intervention_docs.execute_doc_analyze_input({"raw_text": 42})
    )["error"]
    analysis = await intervention_docs.execute_doc_analyze_input(
        {"raw_text": "Incident DNS\n> nslookup example.org\nServeur 192.0.2.10"}
    )
    assert analysis["success"] is True
    assert "nslookup example.org" in analysis["extracted_commands"]
    assert "192.0.2.10" in analysis["ip_addresses"]

    assert "limit" in (
        await intervention_docs.execute_doc_intervention_list({"limit": 0})
    )["error"]
    assert "limit" in (
        await intervention_docs.execute_doc_intervention_list({"limit": 501})
    )["error"]
    assert "query" in (
        await intervention_docs.execute_doc_knowledge_search({"query": []})
    )["error"]

    assert "Formats acceptés" in (
        await intervention_docs._doc_export_md(
            "# Test", "Test", "report", "html", None
        )
    )["error"]
    exported = await intervention_docs._doc_export_md(
        "# Test", "Test", "report", "docx", None
    )
    assert exported["success"] is True
    assert exported["path"].endswith(".docx")
    assert exports[-1][0] == "docx"

    public_names = [
        name.removeprefix("execute_")
        for name in dir(intervention_docs)
        if name.startswith("execute_doc_")
    ]
    assert len(public_names) == 18
    for public_name in public_names:
        implementation = getattr(intervention_docs, f"execute_{public_name}")
        assert getattr(tools, f"execute_{public_name}") is implementation
        assert tools.TOOLS_REGISTRY[public_name] is implementation


if __name__ == "__main__":
    asyncio.run(_run())
    print("Domaine documentation d'intervention OK")
