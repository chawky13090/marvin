"""Régressions du formatage Markdown partagé DOCX/PDF."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import document_formatting
import tools


def main() -> int:
    blocks = list(document_formatting.parse_markdown_blocks(
        "# Titre\n\n- Élément\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        "```python\nprint('ok')\n```\n![preuve](C:/tmp/a.png)"
    ))
    assert [kind for kind, _ in blocks] == [
        "h1", "space", "bullet", "space", "table", "code", "image"
    ]
    inline = document_formatting.markdown_inline_to_reportlab(
        "🤖 **fort** *italique* `code` [site](https://example.com) <x>"
    )
    assert "🤖" not in inline
    assert "<b>fort</b>" in inline and "<i>italique</i>" in inline
    assert "&lt;x&gt;" in inline and 'href="https://example.com"' in inline
    quoted_url = document_formatting.markdown_inline_to_reportlab(
        '[site](https://example.com/"bad")'
    )
    assert 'href="https://example.com/&quot;bad&quot;"' in quoted_url
    assert tools._parse_md_blocks is document_formatting.parse_markdown_blocks
    assert tools._md_inline_to_rl is document_formatting.markdown_inline_to_reportlab
    print("Document Formatting OK - blocs, échappement et façade historique.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
