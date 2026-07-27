"""Régressions déterministes du domaine Google Drive."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import google_drive


class Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class Files:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return Request(
            {
                "files": [
                    {
                        "id": "folder",
                        "name": "Dossier",
                        "mimeType": "application/vnd.google-apps.folder",
                    }
                ]
            }
        )

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return Request(
            {
                "name": "Document",
                "mimeType": "application/vnd.google-apps.document",
            }
        )

    def export(self, **kwargs):
        self.calls.append(("export", kwargs))
        return Request(b"contenu")

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return Request({"id": "new", "webViewLink": "https://drive.test/new"})


class Service:
    def __init__(self):
        self.resource = Files()

    def files(self):
        return self.resource


async def main() -> None:
    service = Service()
    factory = lambda: service
    listed = await google_drive.list_files(
        {"folder_id": "root", "query": "l'été", "max_results": 5000},
        service_factory=factory,
    )
    assert listed["files"][0]["type"] == "dossier"
    list_call = service.resource.calls[-1][1]
    assert list_call["pageSize"] == 1000
    assert "l\\'été" in list_call["q"]

    read = await google_drive.read_file({"file_id": "abc"}, service_factory=factory)
    assert read["content"] == "contenu"
    assert service.resource.calls[-1][1]["mimeType"] == "text/plain"

    invalid_name = await google_drive.upload_file(
        {"local_path": "x", "file_name": "../x"},
        resolve_path=lambda path: path,
        service_factory=factory,
    )
    assert "error" in invalid_name

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "rapport.txt"
        source.write_text("test", encoding="utf-8")
        uploaded = await google_drive.upload_file(
            {"local_path": str(source), "file_name": "final.txt"},
            resolve_path=lambda path: path,
            service_factory=factory,
        )
        assert uploaded["file_id"] == "new"
        create_call = service.resource.calls[-1][1]
        assert create_call["body"]["name"] == "final.txt"

    assert tools.TOOLS_REGISTRY["google_drive_list"] is tools.execute_google_drive_list
    assert tools.TOOLS_REGISTRY["google_drive_read"] is tools.execute_google_drive_read
    assert tools.TOOLS_REGISTRY["google_drive_upload"] is tools.execute_google_drive_upload


if __name__ == "__main__":
    asyncio.run(main())
    print("OK - domaine Google Drive")
