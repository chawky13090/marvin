"""Régressions de l'identité et du catalogue documentaires."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import document_profile
import tools


async def main() -> int:
    stored = {"author": "Ancien", "unknown": "conservé"}
    with (
        patch.object(document_profile.db, "get_setting", return_value=stored),
        patch.object(document_profile.db, "set_setting") as save,
    ):
        result = await document_profile.set_identity({
            "author": "  Chaouki  ", "email": "", "ignored": "non",
        })
    assert result["identity"]["author"] == "Chaouki"
    assert result["identity"]["email"] == ""
    assert result["identity"]["unknown"] == "conservé"
    assert "ignored" not in result["identity"]
    save.assert_called_once_with("document_identity", result["identity"])
    assert stored == {"author": "Ancien", "unknown": "conservé"}

    templates = document_profile.list_templates()
    assert len(templates) == 10
    assert any(item["key"] == "procedure" for item in templates)
    templates[0]["sections"].append("mutation locale")
    assert "mutation locale" not in document_profile.TEMPLATES["rapport_intervention"]["sections"]

    assert tools._document_identity is document_profile.get_identity
    assert tools.execute_document_identity_set is document_profile.set_identity
    assert tools._DOC_TEMPLATES is document_profile.TEMPLATES
    assert tools._doc_templates_list is document_profile.list_templates
    print("Document Profile OK - identité, liste blanche, copies et façade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
