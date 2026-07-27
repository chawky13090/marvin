"""Régressions des utilitaires déterministes et de leurs façades."""

from __future__ import annotations

import asyncio
import string
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import tools
from tool_domains import deterministic_utilities as domain


async def main() -> None:
    calculated = await domain.calculator({"expression": "sqrt(81) + 3 * 4"})
    assert calculated["result"] == 21.0
    assert (await domain.calculator({"expression": "factorial(10)"}))["result"] == 3628800
    assert "error" in await domain.calculator({"expression": "__import__('os')"})
    assert "error" in await domain.calculator({"expression": "2 ** 10001"})
    assert "error" in await domain.calculator({"expression": "1" * 4097})

    generated = await domain.password_generate(
        {
            "length": 20,
            "count": 5,
            "include": ["letters", "digits", "symbols"],
        }
    )
    assert len(generated["passwords"]) == 5
    for password in generated["passwords"]:
        assert len(password) == 20
        assert any(char in string.ascii_letters for char in password)
        assert any(char in string.digits for char in password)
        assert any(char in domain._SYMBOLS for char in password)
    assert "error" in await domain.password_generate(
        {"length": 4, "exclude": string.digits, "pin": True}
    )

    with tempfile.TemporaryDirectory() as temporary:
        sample = Path(temporary) / "sample.bin"
        sample.write_bytes(b"marvin")
        hashed = await domain.hash_compute(
            {"file_path": str(sample), "algorithm": "sha256"},
            resolve_path=lambda value: value,
        )
        assert hashed["hash"] == (
            "d3f40079ab5385e2d3dfbcf07d4b088853feda1e6496c17c287a88ef02fecd68"
        )
    legacy = await domain.hash_compute(
        {"text": "marvin", "algorithm": "md5"}, resolve_path=lambda value: value
    )
    assert "collisions" in legacy["warning"]

    encoded = await domain.base64_tool({"action": "encode", "data": "é"})
    decoded = await domain.base64_tool(
        {"action": "decode", "data": encoded["result"]}
    )
    assert decoded["result"] == "é"
    assert "error" in await domain.base64_tool(
        {"action": "decode", "data": "%%%invalide"}
    )

    formatted = await domain.json_tool(
        {"action": "format", "data": '{"a":[{"b":2}]}'}
    )
    assert '"a"' in formatted["result"]
    queried = await domain.json_tool(
        {"action": "query", "data": '{"a":[{"b":2}]}', "path": "$.a[0].b"}
    )
    assert queried["result"] == 2
    assert (await domain.json_tool({"data": '{"v":NaN}'}))["valid"] is False

    stats = await domain.text_stats(
        {"text": "Marvin teste. Marvin valide.", "top_words": 3}
    )
    assert stats["words"] == 4
    assert stats["top_words"][0] == {"word": "marvin", "count": 2}
    assert "error" in await domain.text_stats({"text": "x", "top_words": 101})

    assert tools.execute_calculator is domain.calculator
    assert tools.execute_password_generate is domain.password_generate
    assert tools.execute_base64_tool is domain.base64_tool
    assert tools.execute_json_tool is domain.json_tool
    assert tools.execute_text_stats is domain.text_stats
    assert tools.TOOLS_REGISTRY["hash_compute"] is tools.execute_hash_compute


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - utilitaires déterministes")
