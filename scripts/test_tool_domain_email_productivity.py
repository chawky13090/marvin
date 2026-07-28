"""Contrats du domaine de productivité e-mail, sans réseau ni données réelles."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import email_productivity


ACCOUNT = {
    "username": "user@example.test",
    "imap_host": "imap.example.test",
    "imap_port": 993,
    "password": "test-credential",
}


async def main() -> None:
    fetched_messages: list[dict] = []
    fetched_attachments: list[dict] = []
    created_tasks: list[dict] = []
    generated_prompts: list[str] = []
    temporary_paths: list[str] = []
    attachment = {
        "name": "../rapport.txt",
        "data": b"Contenu important.",
        "size": 999,
    }
    generated = (
        'Préambule invalide {pas du json} puis '
        '{"title":"Confirmer la date","description":"Répondre au client",'
        '"priority":"high","due_date":"2026-08-01"}'
    )

    def get_account(account=None):
        return ACCOUNT if account in (None, ACCOUNT["username"]) else None

    def fetch_email(_host, _port, username, _password, **kwargs):
        fetched_messages.append({"username": username, **kwargs})
        return {
            "subject": "Planification",
            "from": "Client <client@example.test>",
            "body": "Merci de confirmer avant vendredi.",
        }

    def fetch_attachment(_host, _port, username, _password, **kwargs):
        fetched_attachments.append({"username": username, **kwargs})
        return attachment

    async def generate(prompt, **_kwargs):
        generated_prompts.append(prompt)
        if "UNE tâche" in prompt:
            return generated
        return "Résumé contrôlé"

    async def create_task(args):
        created_tasks.append(args)
        return {"success": True, "task": {"id": "task-1", **args}}

    async def read_pdf(args):
        temporary_paths.append(args["path"])
        assert os.path.isfile(args["path"])
        return {"success": True, "text": "Texte PDF"}

    async def read_docx(args):
        temporary_paths.append(args["path"])
        assert os.path.isfile(args["path"])
        return {"success": True, "text": "Texte DOCX"}

    def network_error(error, resource):
        return {"error": f"{resource}: {error}"}

    def configure(*, task_creator=create_task, generator=generate):
        email_productivity.configure(
            get_account=get_account,
            fetch_email=fetch_email,
            fetch_attachment=fetch_attachment,
            generate=generator,
            create_task=task_creator,
            read_pdf=read_pdf,
            read_docx=read_docx,
            network_error=network_error,
            today=lambda: date(2026, 7, 28),
        )

    configure()

    assert (await email_productivity.to_task({}))["error"].startswith("Aucun contenu")
    task = await email_productivity.to_task({"uid": "42"})
    assert task["success"] and task["title"] == "Confirmer la date"
    assert task["priority"] == "high" and task["due_date"] == "2026-08-01"
    assert fetched_messages[-1]["uid"] == "42"
    assert created_tasks[-1]["tags"] == ["email"]
    assert "aujourd'hui = 2026-07-28" in generated_prompts[-1]
    assert "Issu de l'email" in created_tasks[-1]["description"]

    generated = '{"title":"Relancer","priority":"invalide","due_date":"demain"}'
    fallback = await email_productivity.to_task({"body": "Relancer le fournisseur"})
    assert fallback["priority"] == "medium" and fallback["due_date"] is None

    async def failed_task(_args):
        return {"error": "SQLite indisponible"}

    configure(task_creator=failed_task)
    failed = await email_productivity.to_task({"body": "Créer une tâche"})
    assert failed == {"error": "SQLite indisponible"}
    configure()

    assert (await email_productivity.attachment_summary({}))["error"] == "Paramètre 'uid' requis."
    assert "non configuré" in (
        await email_productivity.attachment_summary(
            {"uid": "1", "account": "absent@example.test"}
        )
    )["error"]

    text_summary = await email_productivity.attachment_summary({"uid": "1"})
    assert text_summary["success"] and text_summary["name"] == "rapport.txt"
    assert text_summary["size"] == len(attachment["data"])
    assert "Contenu important." in generated_prompts[-1]

    attachment.update({"name": "rapport.pdf", "data": b"%PDF-test"})
    pdf_summary = await email_productivity.attachment_summary({"uid": "2"})
    assert pdf_summary["success"] and temporary_paths
    assert all(not os.path.exists(path) for path in temporary_paths)

    attachment.update({"name": "archive.exe", "data": b"MZ"})
    unsupported = await email_productivity.attachment_summary({"uid": "3"})
    assert "non pris en charge" in unsupported["error"]

    attachment.update({"name": "rapport.txt", "data": "pas des octets"})
    invalid = await email_productivity.attachment_summary({"uid": "4"})
    assert "invalide" in invalid["error"]

    original_limit = email_productivity._MAX_ATTACHMENT_BYTES
    try:
        email_productivity._MAX_ATTACHMENT_BYTES = 4
        attachment.update({"name": "rapport.txt", "data": b"12345"})
        oversized = await email_productivity.attachment_summary({"uid": "5"})
        assert "25 Mio" in oversized["error"]
    finally:
        email_productivity._MAX_ATTACHMENT_BYTES = original_limit

    async def failed_generate(_prompt, **_kwargs):
        raise TimeoutError("modèle indisponible")

    attachment.update({"name": "rapport.txt", "data": b"Texte"})
    configure(generator=failed_generate)
    generation_failure = await email_productivity.attachment_summary({"uid": "6"})
    assert generation_failure["error"].startswith("résumé pièce jointe:")

    assert tools.execute_email_to_task is email_productivity.to_task
    assert tools.execute_email_attachment_summary is email_productivity.attachment_summary
    assert tools.TOOLS_REGISTRY["email_to_task"] is email_productivity.to_task
    assert (
        tools.TOOLS_REGISTRY["email_attachment_summary"]
        is email_productivity.attachment_summary
    )
    tools_source = (BACKEND / "tools.py").read_text(encoding="utf-8")
    assert "async def execute_email_to_task" not in tools_source
    assert "async def execute_email_attachment_summary" not in tools_source

    print(
        "Email Productivity Domain OK - tâche, JSON, date, pièce jointe, "
        "taille, nettoyage et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
