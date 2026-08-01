from __future__ import annotations

import hashlib
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_tool_step import prepare_tool_call
from agent_runner import RunnerState
from agent_turn_completion import _reconcile_pending_confirmation
from agent_tool_postprocess import postprocess_tool_result
from tool_domains import documents as documents_domain


class EmailAttachmentContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.desktop = self.root / "Desktop"
        self.desktop.mkdir()
        self.pdf = self.desktop / "document.pdf"
        self.pdf.write_bytes(b"%PDF-test-contract")
        self.paths = patch.dict("email_attachments.PATHS", {
            "desktop": str(self.desktop),
            "documents": str(self.root / "Documents"),
            "downloads": str(self.root / "Downloads"),
        })
        self.roots = patch("email_attachments.roots", return_value=(self.root / "machine", self.root / "exports"))
        self.paths.start()
        self.roots.start()

    def tearDown(self):
        self.roots.stop()
        self.paths.stop()
        self.temporary.cleanup()

    def test_single_path_is_normalized_and_hashed_before_policy(self):
        prepared = prepare_tool_call("email_send", {"attachments": str(self.pdf)})
        attachment = prepared.arguments["attachments"][0]
        self.assertEqual(attachment["path"], str(self.pdf.resolve()))
        self.assertEqual(attachment["sha256"], hashlib.sha256(self.pdf.read_bytes()).hexdigest())

    def test_item_object_from_cloud_model_is_normalized(self):
        prepared = prepare_tool_call("email_send", {"attachments": {"item": str(self.pdf)}})
        self.assertEqual(prepared.arguments["attachments"][0]["name"], self.pdf.name)

    def test_json_string_list_is_normalized(self):
        raw = '["' + str(self.pdf).replace('\\', '\\\\') + '"]'
        prepared = prepare_tool_call("email_send", {"attachments": raw})
        self.assertEqual(len(prepared.arguments["attachments"]), 1)
        self.assertEqual(len(prepared.arguments["attachments"][0]["sha256"]), 64)

    def test_pending_confirmation_cannot_be_reported_as_sent(self):
        state = RunnerState()
        state.record_tool(
            "email_send",
            {"to": "recipient@example.invalid"},
            {
                "requiresConfirmation": True,
                "message": "Confirmer l'envoi avec une pièce jointe.",
            },
            tooling_failure=True,
        )
        answer = _reconcile_pending_confirmation("E-mail envoyé avec succès.", state)
        self.assertIn("n'a pas encore été exécuté", answer)
        self.assertNotIn("envoyé avec succès", answer)

    def test_pdf_without_path_uses_marvin_document_tree(self):
        with (
            patch.object(documents_domain, "_generated_dir", self.root / "Marvin" / "documents"),
            patch.object(documents_domain, "_resolver", lambda value: str(Path(value).resolve())),
        ):
            result = asyncio.run(documents_domain.create_pdf({
                "title": "Rapport automatique",
                "content": "# Validation\n\nDocument classé.",
            }))
        self.assertNotIn("error", result)
        output = Path(result["path"])
        self.assertTrue(output.is_file())
        self.assertEqual(output.parent, self.root / "Marvin" / "documents")

    def test_explicit_pdf_path_has_priority(self):
        explicit = self.desktop / "destination-demandee.pdf"
        with (
            patch.object(documents_domain, "_generated_dir", self.root / "Marvin" / "documents"),
            patch.object(documents_domain, "_resolver", lambda value: str(Path(value).resolve())),
        ):
            result = asyncio.run(documents_domain.create_pdf({
                "path": str(explicit),
                "title": "Destination explicite",
                "content": "# Validation\n\nChemin utilisateur prioritaire.",
            }))
        self.assertNotIn("error", result)
        self.assertEqual(Path(result["path"]), explicit)
        self.assertTrue(explicit.is_file())

    def test_galactic_theme_is_applied_by_pdf_engine(self):
        explicit = self.desktop / "galactic.pdf"
        with patch.object(documents_domain, "_resolver", lambda value: str(Path(value).resolve())):
            result = asyncio.run(documents_domain.create_pdf({
                "path": str(explicit),
                "title": "Exploration galactique — Témoin",
                "subtitle": "Rapport visuel synthétique",
                "theme": "galactic",
                "content": "# Contexte\n\nContenu professionnel.\n\n| Axe | État |\n|---|---|\n| Design | Validé |",
            }))
        self.assertEqual(result.get("theme"), "galactic")
        self.assertGreater(result.get("size_bytes", 0), 5_000)
        from pypdf import PdfReader
        extracted = "\n".join(page.extract_text() or "" for page in PdfReader(explicit).pages)
        self.assertIn("Témoin", extracted)
        self.assertIn("synthétique", extracted)

    def test_galactic_theme_is_applied_by_docx_engine(self):
        explicit = self.desktop / "galactic.docx"
        with patch.object(documents_domain, "_resolver", lambda value: str(Path(value).resolve())):
            result = asyncio.run(documents_domain.create_docx({
                "path": str(explicit),
                "title": "Exploration galactique",
                "subtitle": "Rapport professionnel",
                "theme": "galactic",
                "logo_position": "right",
                "content": "# Synthèse\n\nDocument structuré et lisible.",
            }))
        self.assertEqual(result.get("theme"), "galactic")
        self.assertGreater(result.get("size_bytes", 0), 10_000)
        from docx import Document
        rendered = Document(explicit)
        self.assertIn("Exploration galactique", "\n".join(p.text for p in rendered.paragraphs))

    def test_confirmation_does_not_wait_for_llm_critique(self):
        calls = []

        async def critique(*args, **kwargs):
            calls.append((args, kwargs))
            return "ne doit pas être appelé"

        result = asyncio.run(postprocess_tool_result(
            tool_name="email_send",
            arguments={"to": "recipient@example.invalid"},
            result={"requiresConfirmation": True, "message": "Confirmer"},
            duration_ms=1,
            user_query="envoie le document",
            active_model="cloud-model",
            dangerous_tools={"email_send"},
            critique_action=critique,
            scan_document=lambda *args, **kwargs: [],
        ))
        self.assertTrue(result["requiresConfirmation"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
