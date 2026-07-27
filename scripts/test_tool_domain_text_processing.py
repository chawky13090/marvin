"""Régressions du domaine de traitement textuel déterministe."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from agent_safety import validator_for
from tool_domains import text_processing as domain


async def run_domain() -> None:
    extracted = await domain.text_extract(
        {
            "text": (
                "Écrire à test@example.org, voir https://example.org/a "
                "ou appeler le 01 23 45 67 89. test@example.org"
            ),
            "extract": "all",
        }
    )
    assert extracted["emails"] == ["test@example.org"]
    assert extracted["urls"] == ["https://example.org/a"]
    assert extracted["phones"] == ["01 23 45 67 89"]
    assert extracted["truncated"] is False
    assert "extract" in (await domain.text_extract({"text": "x", "extract": "other"}))["error"]
    assert "limité" in (await domain.text_extract({"text": "x" * 1_000_001}))["error"]

    unified = await domain.diff_text(
        {"text_a": "a\nb\n", "text_b": "a\nc\n", "mode": "unified"}
    )
    assert unified["lines_added"] == 1
    assert unified["lines_removed"] == 1
    assert unified["identical"] is False
    ratio = await domain.diff_text({"text_a": "abc", "text_b": "abc", "mode": "ratio"})
    assert ratio["similarity"] == 100.0
    assert "mode" in (await domain.diff_text({"text_a": "a", "text_b": "b", "mode": "x"}))["error"]
    assert "context_lines" in (
        await domain.diff_text({"text_a": "a", "text_b": "b", "context_lines": 101})
    )["error"]

    markdown = await domain.markdown_convert(
        {
            "text": (
                "# Titre\n\n**gras** <script>alert(1)</script>\n\n"
                "[sûr](https://example.org) [hostile](javascript:alert(1))\n\n"
                "```python\nprint('<ok>')\n```"
            ),
            "to": "html",
        }
    )
    rendered = markdown["result"]
    assert "<h1>Titre</h1>" in rendered
    assert "<strong>gras</strong>" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert 'href="https://example.org"' in rendered
    assert 'href="javascript:' not in rendered
    assert "&lt;ok&gt;" in rendered
    plain = await domain.markdown_convert({"text": "# Titre\n**gras**", "to": "plain"})
    assert plain["result"] == "Titre\ngras"
    stats = await domain.markdown_convert(
        {"text": "# T\n[site](https://example.org)\n![alt](https://example.org/a.png)\n```\nx\n```", "to": "stats"}
    )
    assert stats == {
        "success": True,
        "headings": 1,
        "links": 1,
        "images": 1,
        "code_blocks": 1,
    }

    found = await domain.regex_tool(
        {"pattern": r"(\w+)@(\w+\.\w+)", "text": "a@example.org b@example.net", "max_results": 1}
    )
    assert found["matches"] == [["a", "example.org"]]
    assert found["truncated"] is True
    single_group = await domain.regex_tool(
        {"pattern": r"(\d+)", "text": "a1 b22", "max_results": 10}
    )
    assert single_group["matches"] == ["1", "22"]
    replaced = await domain.regex_tool(
        {"pattern": "a", "text": "aaaa", "action": "replace", "replace": "b", "max_results": 2}
    )
    assert replaced["result"] == "bbaa"
    assert replaced["replacements"] == 2
    assert "flags" in (
        await domain.regex_tool({"pattern": ".", "text": "x", "flags": "X"})
    )["error"]
    pathological = await domain.regex_tool(
        {"pattern": r"(a+)+$", "text": ("a" * 750_000) + "!", "action": "test"}
    )
    assert "interrompue" in pathological["error"]

    joined = await domain.text_join(
        {
            "texts": ["a", "a", "b"],
            "separator": ",",
            "prefix": "[",
            "suffix": "]",
            "dedupe": True,
        }
    )
    assert joined == {
        "success": True,
        "result": "[a],[b]",
        "items": 2,
        "total_chars": 7,
    }
    assert "chaîne" in (await domain.text_join({"texts": ["a", 2]}))["error"]
    assert "limité" in (
        await domain.text_join({"texts": ["x" * 1_000_000] * 6})
    )["error"]


def main() -> int:
    assert tools.execute_text_extract is domain.text_extract
    assert tools.execute_diff_text is domain.diff_text
    assert tools.execute_markdown_convert is domain.markdown_convert
    assert tools.execute_regex_tool is domain.regex_tool
    assert tools.execute_text_join is domain.text_join
    for name, function in {
        "text_extract": domain.text_extract,
        "diff_text": domain.diff_text,
        "markdown_convert": domain.markdown_convert,
        "regex_tool": domain.regex_tool,
        "text_join": domain.text_join,
    }.items():
        assert tools.TOOLS_REGISTRY[name] is function

    validator = validator_for(tools.TOOLS_SPEC)
    assert validator("regex_tool", {"pattern": ".", "text": "x", "max_results": 1001})
    assert validator("diff_text", {"text_a": "a", "text_b": "b", "context_lines": -1})
    assert validator("text_join", {"texts": []})
    asyncio.run(run_domain())
    print("Text Processing Domain OK - limites, HTML sûr, timeout regex et façades.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
