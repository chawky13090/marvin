"""Contrats du domaine des messages e-mail, sans réseau ni envoi réel."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import tools
from tool_domains import email_messages


ACCOUNTS = [
    {
        "username": "a@example.com",
        "provider": "oauth",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "password": "secret-a",
    },
    {
        "username": "b@example.com",
        "provider": "password",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "password": "secret-b",
    },
]


async def main() -> None:
    inbox_calls: list[dict] = []
    read_calls: list[dict] = []
    search_calls: list[dict] = []
    send_calls: list[dict] = []
    prompts: list[str] = []

    def get_account(account=None):
        if account is None:
            return ACCOUNTS[0]
        return next((item for item in ACCOUNTS if item["username"] == account), None)

    def fetch_inbox(_host, _port, username, _password, **kwargs):
        inbox_calls.append({"username": username, **kwargs})
        if username == "b@example.com" and kwargs["folder"] == "FAIL":
            raise OSError("IMAP indisponible")
        return [
            {
                "uid": f"{username}-1",
                "from": "Client <client@example.com>",
                "subject": f"Question pour {username}",
                "date": "2026-07-28T12:00:00",
            }
        ]

    def fetch_email(_host, _port, username, _password, **kwargs):
        read_calls.append({"username": username, **kwargs})
        return {
            "uid": kwargs["uid"],
            "from": "Client <client@example.com>",
            "subject": "Demande",
            "body": "Pouvez-vous confirmer la date ?",
        }

    def search_emails(_host, _port, username, _password, **kwargs):
        search_calls.append({"username": username, **kwargs})
        return [{"uid": "s1", "subject": kwargs["query"]}]

    def send_email(_host, _port, username, _password, **kwargs):
        send_calls.append({"username": username, **kwargs})
        return {"message_id": "<sent@example.com>"}

    async def generate(prompt, **_kwargs):
        prompts.append(prompt)
        return "Résultat IA"

    def network_error(error, resource):
        return {"error": f"{resource}: {error}"}

    def configure(*, failing_second_box: bool = False):
        def selected_fetch(*args, **kwargs):
            if failing_second_box and args[2] == "b@example.com":
                raise OSError("IMAP indisponible")
            return fetch_inbox(*args, **kwargs)

        email_messages.configure(
            get_account=get_account,
            list_accounts=lambda: ACCOUNTS,
            list_public_accounts=lambda: [
                {"username": item["username"], "provider": item["provider"]}
                for item in ACCOUNTS
            ],
            fetch_inbox=selected_fetch,
            fetch_email=fetch_email,
            search_emails=search_emails,
            send_email=send_email,
            generate=generate,
            network_error=network_error,
        )

    configure()

    accounts = await email_messages.accounts({})
    assert accounts["count"] == 2 and accounts["default"] == "a@example.com"
    assert all("password" not in account for account in accounts["accounts"])

    listed = await email_messages.list_messages(
        {"account": "a@example.com", "folder": "INBOX", "limit": 999, "offset": -5}
    )
    assert listed["success"] and inbox_calls[-1]["limit"] == 50
    assert inbox_calls[-1]["offset"] == 0
    invalid_folder = await email_messages.list_messages({"folder": "INBOX\nDELETED"})
    assert "invalide" in invalid_folder["error"]

    assert (await email_messages.read({}))["error"] == "Paramètre 'uid' requis."
    read = await email_messages.read({"uid": "42", "account": "b@example.com"})
    assert read["email"]["uid"] == "42" and read_calls[-1]["username"] == "b@example.com"

    assert (await email_messages.search({}))["error"] == "Paramètre 'query' requis."
    searched = await email_messages.search({"query": "contrat", "limit": "invalid"})
    assert searched["count"] == 1 and search_calls[-1]["limit"] == 20

    missing_recipient = await email_messages.send({"subject": "Objet", "body": "Corps"})
    assert missing_recipient["needsClarification"]
    confirmation = await email_messages.send(
        {"to": "client@example.com", "subject": "Objet", "body": "Corps"}
    )
    assert confirmation["requiresConfirmation"] and send_calls == []
    sent = await email_messages.send(
        {
            "account": "b@example.com",
            "to": "client@example.com",
            "subject": "Objet",
            "body": "Corps",
            "confirmed": True,
            "auto_submitted": True,
        }
    )
    assert sent["success"] and send_calls[-1]["username"] == "b@example.com"
    assert send_calls[-1]["auto_submitted"] is True

    draft = await email_messages.draft_reply(
        {"uid": "42", "instruction": "Accepter", "signature": "Chaouki"}
    )
    assert draft["success"] and draft["subject"] == "Re: Demande"
    assert "Accepter" in prompts[-1] and "Chaouki" in prompts[-1]
    direct_summary = await email_messages.summarize(
        {"body": "Information importante.", "subject": "Info", "from": "Client"}
    )
    assert direct_summary["success"] and direct_summary["summary"] == "Résultat IA"
    assert (await email_messages.summarize({}))["error"].startswith("Aucun contenu")

    digest = await email_messages.digest({"account": "__all__", "limit": 25})
    assert digest["success"] and digest["count"] == 2
    assert "a@example.com" in prompts[-1] and "b@example.com" in prompts[-1]
    assert "🔴" in prompts[-1] and "👉 À TRAITER EN PRIORITÉ" in prompts[-1]

    configure(failing_second_box=True)
    partial_digest = await email_messages.digest({"account": "__all__"})
    assert partial_digest["success"] and partial_digest["count"] == 1

    assert tools.execute_email_accounts is email_messages.accounts
    assert tools.execute_email_list is email_messages.list_messages
    assert tools.execute_email_read is email_messages.read
    assert tools.execute_email_search is email_messages.search
    assert tools.execute_email_send is email_messages.send
    assert tools.execute_email_draft_reply is email_messages.draft_reply
    assert tools.execute_email_summarize is email_messages.summarize
    assert tools.execute_email_digest is email_messages.digest
    for name, function in {
        "email_accounts": email_messages.accounts,
        "email_list": email_messages.list_messages,
        "email_read": email_messages.read,
        "email_search": email_messages.search,
        "email_send": email_messages.send,
        "email_draft_reply": email_messages.draft_reply,
        "email_summarize": email_messages.summarize,
        "email_digest": email_messages.digest,
    }.items():
        assert tools.TOOLS_REGISTRY[name] is function

    tools_source = (BACKEND / "tools.py").read_text(encoding="utf-8")
    assert "async def execute_email_accounts" not in tools_source
    assert "async def execute_email_digest" not in tools_source

    print(
        "Email Messages Domain OK - comptes, bornes, lecture, recherche, "
        "confirmation, IA, multi-comptes et façades."
    )


if __name__ == "__main__":
    asyncio.run(main())
