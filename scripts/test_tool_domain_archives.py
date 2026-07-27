"""Régressions déterministes du domaine d'archives."""

from __future__ import annotations

import asyncio
import io
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import archives
import tools


def _resolve(raw: str) -> str:
    return str(Path(raw).resolve())


async def _run() -> None:
    archives.configure(resolve_path=_resolve)
    with tempfile.TemporaryDirectory(prefix="marvin-archives-") as temp:
        root = Path(temp)
        source = root / "source"
        source.mkdir()
        (source / "hello.txt").write_text("Bonjour Marvin", encoding="utf-8")
        nested = source / "nested"
        nested.mkdir()
        (nested / "data.json").write_text('{"ok": true}', encoding="utf-8")

        output = root / "bundle.zip"
        compressed = await archives.compress(
            {"sources": [str(source)], "output_path": str(output)}
        )
        assert compressed.get("success") is True, compressed
        assert output.is_file()
        with zipfile.ZipFile(output) as handle:
            names = set(handle.namelist())
        assert "source/hello.txt" in names
        assert "source/nested/data.json" in names
        assert output.name not in names

        destination = root / "zip-output"
        extracted = await archives.extract(
            {"archive_path": str(output), "dest_path": str(destination)}
        )
        assert extracted.get("success") is True, extracted
        assert (destination / "source" / "hello.txt").read_text(
            encoding="utf-8"
        ) == "Bonjour Marvin"

        tar_path = root / "bundle.tar.gz"
        payload = b"tar payload"
        with tarfile.open(tar_path, "w:gz") as handle:
            info = tarfile.TarInfo("folder/payload.txt")
            info.size = len(payload)
            handle.addfile(info, io.BytesIO(payload))
        tar_destination = root / "tar-output"
        tar_result = await archives.extract(
            {"archive_path": str(tar_path), "dest_path": str(tar_destination)}
        )
        assert tar_result.get("success") is True, tar_result
        assert (tar_destination / "folder" / "payload.txt").read_bytes() == payload

        malicious_zip = root / "traversal.zip"
        with zipfile.ZipFile(malicious_zip, "w") as handle:
            handle.writestr("../outside.txt", "blocked")
        blocked_zip = await archives.extract(
            {
                "archive_path": str(malicious_zip),
                "dest_path": str(root / "bad-zip-output"),
            }
        )
        assert "error" in blocked_zip, blocked_zip
        assert not (root / "outside.txt").exists()

        malicious_tar = root / "link.tar"
        with tarfile.open(malicious_tar, "w") as handle:
            link = tarfile.TarInfo("unsafe-link")
            link.type = tarfile.SYMTYPE
            link.linkname = "../outside.txt"
            handle.addfile(link)
        blocked_tar = await archives.extract(
            {
                "archive_path": str(malicious_tar),
                "dest_path": str(root / "bad-tar-output"),
            }
        )
        assert "error" in blocked_tar, blocked_tar
        assert not (root / "bad-tar-output" / "unsafe-link").exists()

        unsupported = root / "archive.rar"
        unsupported.write_bytes(b"not-rar")
        unsupported_result = await archives.extract({"archive_path": str(unsupported)})
        assert "non supporté" in unsupported_result.get("error", "")

    archives.configure(resolve_path=tools._resolve_path)
    assert tools.execute_file_compress is archives.compress
    assert tools.execute_file_extract is archives.extract


if __name__ == "__main__":
    asyncio.run(_run())
    print("Archive tool domain tests passed.")
