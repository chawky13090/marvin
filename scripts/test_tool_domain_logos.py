"""Contrats Logos avec faux générateur et vrais fichiers temporaires."""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import logos


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marvin-logos-") as temp:
        root = Path(temp).resolve()
        records: list[dict] = []
        calls: list[dict] = []

        def availability():
            return {"ok": True, "device": "fake-gpu"}

        def generate_image(prompt, path, size, seed):
            calls.append({"prompt": prompt, "path": path, "size": size, "seed": seed})
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return {
                "success": True,
                "path": path,
                "generation_seconds": 0.1,
                "device": "fake-gpu",
            }

        def create_record(name, prompt, path):
            records.append(
                {
                    "id": len(records) + 1,
                    "name": name,
                    "prompt": prompt,
                    "path": path,
                    "created_at": "2026-07-28",
                }
            )

        def list_records(*, limit):
            return records[:limit] + ["invalid"]

        logos.configure(
            availability=availability,
            generate_image=generate_image,
            create_record=create_record,
            list_records=list_records,
            output_root=root,
            token_factory=lambda: "fixed",
        )
        assert "error" in await logos.generate({"prompt": ""})
        invalid_size = await logos.generate({"prompt": "mark", "size": "huge"})
        assert "entier" in invalid_size["error"]
        unsupported = await logos.generate({"prompt": "mark", "size": 513})
        assert 512 in unsupported["allowed_sizes"]
        invalid_seed = await logos.generate({"prompt": "mark", "seed": -1})
        assert "graine" in invalid_seed["error"]

        result = await logos.generate(
            {
                "name": "../../ Client",
                "prompt": "blue geometric mark",
                "size": 512,
                "seed": 42,
            }
        )
        assert result["success"] is True
        path = Path(result["path"])
        assert path.parent == root
        assert path.read_bytes().startswith(b"\x89PNG")
        assert calls[0]["seed"] == 42
        assert not list(root.glob("*.tmp.png"))
        assert len(records) == 1

        listing = await logos.list_logos({"limit": 9999})
        assert listing["count"] == 1
        assert listing["logos"][0]["name"] == "../../ Client"

        logos.configure(
            availability=lambda: {"ok": False, "reason": "dependencies missing"},
            generate_image=generate_image,
            create_record=create_record,
            list_records=list_records,
            output_root=root,
            token_factory=lambda: "unavailable",
        )
        unavailable = await logos.generate({"prompt": "mark"})
        assert unavailable["error"] == "dependencies missing"

        def failed_record(_name, _prompt, _path):
            raise RuntimeError("db unavailable")

        logos.configure(
            availability=availability,
            generate_image=generate_image,
            create_record=failed_record,
            list_records=list_records,
            output_root=root,
            token_factory=lambda: "db-failure",
        )
        failed = await logos.generate({"prompt": "mark"})
        assert "catalogue" in failed["error"]
        assert not (root / "logo-db-failure.png").exists()

    import local_image

    logos.configure(
        availability=local_image.is_available,
        generate_image=local_image.generate_logo_image,
        create_record=tools.db.create_logo,
        list_records=tools.db.list_logos,
        output_root=ROOT / "data" / "logos",
    )
    assert tools.execute_logo_generate is logos.generate
    assert tools.execute_logo_list is logos.list_logos
    assert tools.TOOLS_REGISTRY["logo_generate"] is logos.generate
    assert tools.TOOLS_REGISTRY["logo_list"] is logos.list_logos
    logo_spec = next(
        item["function"]["parameters"]["properties"]
        for item in tools.TOOLS_SPEC
        if item["function"]["name"] == "logo_generate"
    )
    assert logo_spec["size"]["enum"] == [256, 384, 512, 640, 768, 1024]
    assert logo_spec["seed"]["maximum"] == 4294967295
    print(
        "Logos Domain OK - bornes, seed, fichier, catalogue, nettoyage, "
        "indisponibilité et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
