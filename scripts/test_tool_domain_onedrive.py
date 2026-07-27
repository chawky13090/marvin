"""Régressions déterministes du domaine OneDrive."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import onedrive


class Response:
    def __init__(self, payload=None, *, content=b"", content_type="application/json"):
        self._payload = payload or {}
        self.content = content
        self.headers = {"content-type": content_type}
        self.encoding = "utf-8"

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


async def main() -> None:
    calls: list[tuple[str, str, dict]] = []

    async def token():
        return "test-token"

    async def requester(method: str, url: str, **kwargs):
        calls.append((method, url, kwargs))
        if method == "PUT":
            uploaded = b""
            async for chunk in kwargs["content"]:
                uploaded += chunk
            assert uploaded == b"contenu"
            return Response({"id": "new", "webUrl": "https://onedrive.test/new"})
        if url.endswith("/content"):
            return Response(content=b"texte", content_type="text/plain")
        return Response(
            {
                "value": [
                    {
                        "id": "one",
                        "name": "Dossier",
                        "folder": {},
                        "size": -1,
                    }
                ]
            }
        )

    listed = await onedrive.list_files(
        {"query": "l'été", "max_results": 5000},
        token_getter=token,
        requester=requester,
    )
    assert listed["files"][0]["type"] == "dossier"
    assert listed["files"][0]["size"] == 0
    assert calls[-1][2]["params"]["$top"] == 999
    assert "q='l''%C3%A9t%C3%A9'" in calls[-1][1]

    read = await onedrive.read_file(
        {"file_id": "abc"}, token_getter=token, requester=requester
    )
    assert read["content"] == "texte"
    assert calls[-1][2]["headers"]["Range"] == "bytes=0-49999"

    invalid = await onedrive.upload_file(
        {"local_path": "x", "dest_path": "../secret"},
        resolve_path=lambda path: path,
        token_getter=token,
        requester=requester,
    )
    assert "error" in invalid

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "rapport.txt"
        source.write_bytes(b"contenu")
        uploaded = await onedrive.upload_file(
            {"local_path": str(source), "dest_path": "Documents/rapport final.txt"},
            resolve_path=lambda path: path,
            token_getter=token,
            requester=requester,
        )
        assert uploaded["file_id"] == "new"
        assert "Documents/rapport%20final.txt" in calls[-1][1]

    assert tools.TOOLS_REGISTRY["onedrive_list"] is tools.execute_onedrive_list
    assert tools.TOOLS_REGISTRY["onedrive_read"] is tools.execute_onedrive_read
    assert tools.TOOLS_REGISTRY["onedrive_upload"] is tools.execute_onedrive_upload


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - domaine OneDrive")
