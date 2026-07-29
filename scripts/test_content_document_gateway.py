"""Contrats du gateway et des chemins pour les surfaces contenu/documents."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from api import content, documents


async def _check_gateway_calls() -> None:
    calls = []

    async def execute(name, arguments, **options):
        calls.append((name, arguments, options))
        return SimpleNamespace(
            result={"success": True, "events": [], "documents": []},
        )

    with (
        patch.object(content.tool_runtime, "execute", side_effect=execute),
        patch.object(documents.tool_runtime, "execute", side_effect=execute),
    ):
        await content.system_search_endpoint("rapport", "pdf", 12)
        await content.system_search_content_endpoint("contrat", "docx", 8)
        await content.unified_search_endpoint("Marvin", "files,memory", 4)
        await documents.list_documents()
        await documents.generate_document({"title": "Test"})
        await documents.index_document(documents.DocIndexBody(path="C:/tmp/test.pdf"))
        await documents.ask_documents(documents.DocAskBody(question="Résumé ?", k=3))
        await documents.refine_document(
            documents.DocRefineBody(file="x.docx", section="intro")
        )
        await documents.forget_document("doc-1")

    assert all(call[2]["source"] == "content_ui" for call in calls[:3])
    assert all(call[2]["source"] == "documents_ui" for call in calls[3:])
    assert calls[2][1]["scope"] == ["files", "memory"]
    assert calls[-1][2]["confirmed_by_ui"] is True


async def _check_download_containment() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-doc-path-") as temporary:
        root = Path(temporary)
        data = root / "data"
        allowed = data / "documents_generes"
        sibling = data / "documents_generes_evil"
        allowed.mkdir(parents=True)
        sibling.mkdir()
        inside = allowed / "inside.docx"
        outside = sibling / "outside.docx"
        inside.write_bytes(b"inside")
        outside.write_bytes(b"outside")

        with patch.object(documents, "_DATA_DIR", str(data)):
            response = await documents.download_document(str(inside))
            assert Path(response.path) == inside
            try:
                await documents.download_document(str(outside))
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("Un dossier voisin à préfixe commun doit être refusé.")


def main() -> int:
    asyncio.run(_check_gateway_calls())
    asyncio.run(_check_download_containment())
    print("Content/Document Gateway OK - 16 accès migrés et confinement de chemin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
