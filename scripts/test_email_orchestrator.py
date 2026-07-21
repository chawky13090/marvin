"""Régressions déterministes du moteur e-mail, sans réseau ni envoi réel."""

from __future__ import annotations

import asyncio
import email
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import email_accounts  # noqa: E402
import email_manager  # noqa: E402
import tools  # noqa: E402


class FakeImap:
    def __init__(self, *_args, **_kwargs):
        self.auth = None
        self.readonly = None
        self.stores = []

    def authenticate(self, mechanism, callback):
        self.auth = (mechanism, callback(b""))
        return "OK", []

    def login(self, *_args):
        raise AssertionError("LOGIN ne doit pas être utilisé avec OAuth2")

    def select(self, _folder, readonly=False):
        self.readonly = readonly
        return "OK", []

    def store(self, *args):
        self.stores.append(args)

    def fetch(self, _uid, _parts):
        raw = (b"From: Client <client@example.com>\r\nTo: me@example.com\r\n"
               b"Subject: Test\r\nMessage-ID: <original@example.com>\r\n\r\nBonjour")
        return "OK", [(b"1 (RFC822 {1})", raw)]

    def logout(self):
        return "BYE", []


class FakeSmtp:
    last = None

    def __init__(self, *_args, **_kwargs):
        FakeSmtp.last = self
        self.auth_data = None
        self.raw_message = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        pass

    def starttls(self, **_kwargs):
        pass

    def auth(self, mechanism, callback):
        self.auth_data = (mechanism, callback())

    def login(self, *_args):
        raise AssertionError("LOGIN ne doit pas être utilisé avec OAuth2")

    def sendmail(self, _from, _recipients, raw):
        self.raw_message = raw


def test_oauth_and_reply_headers() -> None:
    fake = FakeImap()
    with patch.object(email_manager.imaplib, "IMAP4_SSL", return_value=fake):
        message = email_manager.fetch_email(
            "imap.gmail.com", 993, "me@example.com",
            email_manager._OAUTH_PREFIX + "jeton-test", "1", mark_seen=False,
        )
    assert fake.auth == ("XOAUTH2", b"user=me@example.com\x01auth=Bearer jeton-test\x01\x01")
    assert fake.readonly is True and not fake.stores
    assert message["message_id"] == "<original@example.com>"

    with patch.object(email_manager.smtplib, "SMTP", FakeSmtp):
        result = email_manager.send_email(
            "smtp.gmail.com", 587, "me@example.com",
            email_manager._OAUTH_PREFIX + "jeton-test", "client@example.com", "Re: Test", "Réponse",
            in_reply_to="<original@example.com>", references="<older@example.com> <original@example.com>",
            auto_submitted=True,
        )
    assert result["success"] is True
    assert FakeSmtp.last.auth_data[0] == "XOAUTH2"
    parsed = email.message_from_string(FakeSmtp.last.raw_message)
    assert parsed["In-Reply-To"] == "<original@example.com>"
    assert parsed["References"] == "<older@example.com> <original@example.com>"
    assert parsed["Auto-Submitted"] == "auto-replied"
    assert parsed["X-Auto-Response-Suppress"] == "All"


async def test_dry_run_has_no_side_effect() -> None:
    settings = {
        "email_automation": {
            "mode": "brouillon", "accounts": ["me@example.com"],
            "only_from": ["client@example.com"], "never_from": [], "skip_keywords": [],
            "instructions": "", "tone": "courtois", "signature": "", "max_per_run": 5,
            "profiles": {},
        },
        "email_auto_seen": [], "email_signatures": {},
    }
    writes = []
    marks = []

    def fake_get(key, default=None):
        return settings.get(key, default)

    def fake_set(key, value):
        writes.append((key, value))

    def fake_inbox(*_args, **_kwargs):
        return [{"id": "1", "message_id": "<m1@example.com>", "from": "Client <client@example.com>",
                 "subject": "Question", "read": False, "auto_submitted": "", "precedence": "", "list_id": ""}]

    def fake_email(*_args, **kwargs):
        marks.append(kwargs.get("mark_seen"))
        return {"body": "Peux-tu me répondre ?", "message_id": "<m1@example.com>",
                "references": "", "reply_to": "client@example.com"}

    async def fake_draft(_args):
        return {"draft": "Oui, voici une réponse suffisamment longue.", "to": "client@example.com", "subject": "Re: Question"}

    account = {"username": "me@example.com", "imap_host": "imap.test", "imap_port": 993, "password": "secret"}
    with patch.object(tools.db, "get_setting", side_effect=fake_get), \
         patch.object(tools.db, "set_setting", side_effect=fake_set), \
         patch.object(tools, "_all_email_cfgs", return_value=[account]), \
         patch.object(email_manager, "fetch_inbox", side_effect=fake_inbox), \
         patch.object(email_manager, "fetch_email", side_effect=fake_email), \
         patch.object(tools, "execute_email_draft_reply", side_effect=fake_draft):
        result = await tools.execute_email_orchestrator_run({"dry_run": True, "source": "test"})
    assert result["success"] is True and result["dry_run"] is True
    assert result["drafted"] == 0 and result["sent"] == 0
    assert marks == [False]
    assert writes == [], f"La simulation a écrit dans la base : {writes}"


def test_public_account_masks_secrets() -> None:
    public = email_accounts.public({
        "username": "me@example.com", "provider": "gmail", "auth_type": "oauth2",
        "refresh_token": "secret", "access_token": "secret", "oauth_client_secret": "secret",
    })
    assert public["oauth_connected"] is True
    assert not ({"refresh_token", "access_token", "oauth_client_secret", "password"} & public.keys())


def main() -> int:
    test_oauth_and_reply_headers()
    asyncio.run(test_dry_run_has_no_side_effect())
    test_public_account_masks_secrets()
    print("Orchestrateur email OK - OAuth2, entetes RFC, secrets masques, simulation sans effet de bord.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
