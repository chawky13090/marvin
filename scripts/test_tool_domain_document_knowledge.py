"""Régressions déterministes du domaine de connaissance documentaire."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from tool_domains import document_knowledge
import database as db
import tools
import vector_store


class FakeVectorStore:
    def __init__(self) -> None:
        self.indexed: dict[str, list[str]] = {}
        self.deleted: list[str] = []
        self.queries: list[str] = []

    async def index_chunks(
        self, doc_id: str, name: str, path: str, chunks: list[str]
    ) -> int:
        self.indexed[doc_id] = chunks
        return len(chunks)

    async def search(
        self, query: str, *, collections: list[str], limit: int
    ) -> list[dict]:
        assert collections == ["documents"]
        self.queries.append(query)
        if len(self.queries) == 1:
            return [
                {
                    "text": "La procédure Alpha configure le service.",
                    "metadata": {"name": "alpha.txt"},
                    "score": 0.91,
                }
            ]
        return [
            {
                "text": "Le contrôle complémentaire utilise systemctl status.",
                "metadata": {"name": "tableau.xlsx"},
                "score": 0.83,
            }
        ]

    def delete_doc_chunks(self, doc_id: str) -> None:
        self.deleted.append(doc_id)
        self.indexed.pop(doc_id, None)


async def _run() -> None:
    settings: dict[str, object] = {"task_concurrency": 2, "rag_k": 4}
    vectors = FakeVectorStore()
    generated_calls: list[str] = []
    rendered: list[dict] = []

    def get_setting(key: str) -> object:
        return settings.get(key)

    def set_setting(key: str, value: object) -> None:
        settings[key] = value

    async def generate_text(prompt: str, **kwargs) -> str:
        generated_calls.append(prompt)
        if "Réponds uniquement SUFFISANT" in prompt:
            return "systemctl contrôle service"
        if "Réécris uniquement la section" in prompt:
            return "## Diagnostic\n\nDiagnostic expert enrichi."
        return "Réponse sourcée depuis alpha.txt et tableau.xlsx."

    async def create_docx(args: dict) -> dict:
        rendered.append(args)
        Path(args["path"]).write_bytes(b"updated-docx")
        return {"success": True, "path": args["path"]}

    with tempfile.TemporaryDirectory(prefix="marvin-doc-knowledge-") as temp:
        root = Path(temp)
        generated_dir = root / "generated"
        generated_dir.mkdir()
        document_knowledge.configure(
            resolve_path=lambda raw: str(Path(raw).resolve()),
            get_setting=get_setting,
            set_setting=set_setting,
            text_generator=generate_text,
            create_docx=create_docx,
            vector_store=vectors,
            generated_dir=generated_dir,
        )

        source_dir = root / "sources"
        source_dir.mkdir()
        (source_dir / "alpha.txt").write_text(
            "Procédure Alpha " * 150, encoding="utf-8"
        )
        workbook_path = source_dir / "tableau.xlsx"
        workbook = openpyxl.Workbook()
        workbook.active.append(["Service", "État"])
        workbook.active.append(["Marvin", "Actif"])
        workbook.save(workbook_path)
        workbook.close()
        (source_dir / "ignored.exe").write_bytes(b"MZ")

        indexed = await document_knowledge.index({"path": str(source_dir)})
        assert indexed.get("success") is True, indexed
        assert indexed["documents"] == 2
        assert indexed["failed_count"] == 0
        assert indexed["chunks"] >= 2
        stored = settings["indexed_documents"]
        assert isinstance(stored, list) and len(stored) == 2

        listed = await document_knowledge.list_documents({})
        assert listed["count"] == 2
        asked = await document_knowledge.ask(
            {"question": "Comment contrôler le service ?"}
        )
        assert asked.get("success") is True, asked
        assert len(asked["sources"]) == 2
        assert "2 passes" in asked["message"]
        assert vectors.queries == [
            "Comment contrôler le service ?",
            "systemctl contrôle service",
        ]

        first_id = stored[0]["id"]
        forgotten = await document_knowledge.forget({"id": first_id})
        assert forgotten.get("success") is True, forgotten
        assert first_id in vectors.deleted
        assert len(settings["indexed_documents"]) == 1

        docx_path = generated_dir / "rapport.docx"
        docx_path.write_bytes(b"old-docx")
        metadata_path = Path(f"{docx_path}.meta.json")
        metadata = {
            "title": "Rapport",
            "subtitle": "Infrastructure",
            "author": "Marvin",
            "sections": ["Contexte", "Diagnostic", "Solution"],
            "markdown": (
                "## Contexte\n\nTexte.\n\n"
                "## Diagnostic\n\nAncien diagnostic.\n\n"
                "## Solution\n\nSolution."
            ),
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
        )
        refined = await document_knowledge.refine_section(
            {
                "file": str(docx_path),
                "section": "Diagnostic",
                "instruction": "enrichis",
            }
        )
        assert refined.get("success") is True, refined
        assert "Diagnostic expert enrichi" in refined["markdown"]
        assert rendered[-1]["path"] == str(docx_path)
        persisted = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert "Diagnostic expert enrichi" in persisted["markdown"]
        assert not list(generated_dir.glob(".*.tmp"))

        evil_dir = root / "generated_evil"
        evil_dir.mkdir()
        evil_doc = evil_dir / "evil.docx"
        evil_doc.write_bytes(b"evil")
        Path(f"{evil_doc}.meta.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        rejected = await document_knowledge.refine_section(
            {"file": str(evil_doc), "section": "Diagnostic"}
        )
        assert "non affinable" in rejected.get("error", "")

    document_knowledge.configure(
        resolve_path=tools._resolve_path,
        get_setting=db.get_setting,
        set_setting=db.set_setting,
        text_generator=tools._ollama_generate,
        create_docx=tools.execute_file_create_docx,
        vector_store=vector_store,
        generated_dir=ROOT / "data" / "documents_generes",
    )
    assert tools.execute_document_index is document_knowledge.index
    assert tools.execute_document_ask is document_knowledge.ask
    assert tools.execute_document_list is document_knowledge.list_documents
    assert tools.execute_document_forget is document_knowledge.forget
    assert tools.execute_document_refine_section is document_knowledge.refine_section


if __name__ == "__main__":
    asyncio.run(_run())
    print("Document knowledge domain tests passed.")
