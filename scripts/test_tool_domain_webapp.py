"""Contrats Webapp sur fichiers réels dans un répertoire temporaire."""

from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import webapp


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-webapp-") as temp:
        root = Path(temp).resolve()
        webapp.configure(output_root=root, token_factory=lambda: "fixed-token")
        empty = await webapp.create({"content": ""})
        assert "error" in empty
        null = await webapp.create({"content": "hello\x00world"})
        assert "nul" in null["error"]

        result = await webapp.create(
            {
                "title": "../ Tableau <client>",
                "content": "<h1>Test</h1><script>window.ok=true</script>",
            }
        )
        assert result["success"] is True
        path = Path(result["path"])
        assert path.parent.parent == root
        assert path.name == "index.html"
        content = path.read_text(encoding="utf-8")
        assert "Content-Security-Policy" in content
        assert "connect-src 'none'" in content
        assert "<title>../ Tableau &lt;client&gt;</title>" in content
        assert result["sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert not list(path.parent.glob("*.tmp"))

        webapp.configure(output_root=root, token_factory=lambda: "second")
        existing_policy = await webapp.create(
            {
                "title": "Existing",
                "content": (
                    '<html><head><meta http-equiv="Content-Security-Policy" '
                    'content="default-src *; connect-src *"></head><body>OK</body></html>'
                ),
            }
        )
        existing_text = Path(existing_policy["path"]).read_text(encoding="utf-8")
        assert existing_text.count("Content-Security-Policy") == 1
        assert "connect-src 'none'" in existing_text
        assert "default-src *" not in existing_text

        webapp.configure(output_root=root, token_factory=lambda: "large")
        too_large = await webapp.create({"content": "x" * (2 * 1024 * 1024 + 1)})
        assert too_large["max_bytes"] == 2 * 1024 * 1024
        assert not (root / "webapp_large").exists()

    webapp.configure(output_root=ROOT / "data" / "webapps")
    assert tools.execute_webapp_create is webapp.create
    assert tools.TOOLS_REGISTRY["webapp_create"] is webapp.create
    print(
        "Webapp Domain OK - HTML, CSP offline, bornes, chemin, atomicité, "
        "empreinte et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
