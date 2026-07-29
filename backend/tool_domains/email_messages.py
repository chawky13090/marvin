"""Outils de consultation, envoi et assistance IA pour les e-mails."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any


GetAccount = Callable[[str | None], dict[str, Any] | None]
ListAccounts = Callable[[], list[dict[str, Any]]]
Generate = Callable[..., Awaitable[Any]]
NetworkError = Callable[[Exception, str], dict[str, Any]]

_get_account: GetAccount | None = None
_list_accounts: ListAccounts | None = None
_list_public_accounts: ListAccounts | None = None
_fetch_inbox: Callable[..., list[dict[str, Any]]] | None = None
_fetch_email: Callable[..., dict[str, Any]] | None = None
_search_emails: Callable[..., list[dict[str, Any]]] | None = None
_send_email: Callable[..., dict[str, Any]] | None = None
_generate: Generate | None = None
_network_error: NetworkError | None = None


def configure(
    *,
    get_account: GetAccount,
    list_accounts: ListAccounts,
    list_public_accounts: ListAccounts,
    fetch_inbox: Callable[..., list[dict[str, Any]]],
    fetch_email: Callable[..., dict[str, Any]],
    search_emails: Callable[..., list[dict[str, Any]]],
    send_email: Callable[..., dict[str, Any]],
    generate: Generate,
    network_error: NetworkError,
) -> None:
    global _get_account, _list_accounts, _list_public_accounts
    global _fetch_inbox, _fetch_email, _search_emails, _send_email
    global _generate, _network_error
    _get_account = get_account
    _list_accounts = list_accounts
    _list_public_accounts = list_public_accounts
    _fetch_inbox = fetch_inbox
    _fetch_email = fetch_email
    _search_emails = search_emails
    _send_email = send_email
    _generate = generate
    _network_error = network_error


def _require_dependencies() -> None:
    if any(
        dependency is None
        for dependency in (
            _get_account, _list_accounts, _list_public_accounts, _fetch_inbox,
            _fetch_email, _search_emails, _send_email, _generate, _network_error,
        )
    ):
        raise RuntimeError("Le domaine des messages e-mail n'est pas configuré.")


async def _generate_with_provenance(prompt: str, **kwargs) -> tuple[str, dict[str, Any]]:
    assert _generate is not None
    generated = await _generate(prompt, return_metadata=True, **kwargs)
    if isinstance(generated, dict):
        provenance = {
            key: generated[key]
            for key in (
                "model",
                "provider",
                "privacy_preset",
                "cloud_only",
            )
            if key in generated
        }
        return _text(generated.get("text"), 100_000), provenance
    return _text(generated, 100_000), {}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _folder(value: Any) -> str:
    folder = _text(value or "INBOX", 255)
    if not folder or re.search(r"[\x00-\x1f\x7f]", folder):
        raise ValueError("Dossier e-mail invalide.")
    return folder


def _account_error(long: bool = False) -> dict[str, Any]:
    message = "Email non configuré."
    if long:
        message += " Allez dans Paramètres > Email pour configurer votre boîte."
    return {"error": message}


async def accounts(_args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _list_public_accounts is not None
    connected = _list_public_accounts()
    if not connected:
        return {
            "success": True,
            "count": 0,
            "accounts": [],
            "message": "Aucune boîte mail configurée. Allez dans Paramètres > Email.",
        }
    return {
        "success": True,
        "count": len(connected),
        "accounts": connected,
        "default": connected[0]["username"],
        "message": (
            f"{len(connected)} boîte(s) connectée(s) : "
            + ", ".join(str(account["username"]) for account in connected)
        ),
    }


async def list_messages(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _fetch_inbox
    config = _get_account(args.get("account"))
    if not config:
        return _account_error(long=True)
    try:
        folder = _folder(args.get("folder"))
        limit = _bounded_int(args.get("limit"), 20, 1, 50)
        offset = _bounded_int(args.get("offset"), 0, 0, 100_000)
        messages = await asyncio.to_thread(
            _fetch_inbox,
            config["imap_host"],
            int(config.get("imap_port", 993)),
            config["username"],
            config["password"],
            folder=folder,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "folder": folder,
            "count": len(messages),
            "emails": messages,
        }
    except Exception as error:
        return {"error": str(error)}


async def read(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _fetch_email
    config = _get_account(args.get("account"))
    if not config:
        return _account_error()
    uid = _text(args.get("uid"), 500)
    if not uid:
        return {"error": "Paramètre 'uid' requis."}
    try:
        message = await asyncio.to_thread(
            _fetch_email,
            config["imap_host"],
            int(config.get("imap_port", 993)),
            config["username"],
            config["password"],
            uid=uid,
            folder=_folder(args.get("folder")),
        )
        return {"success": True, "email": message}
    except Exception as error:
        return {"error": str(error)}


async def search(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _search_emails
    config = _get_account(args.get("account"))
    if not config:
        return _account_error()
    query = _text(args.get("query"), 1_000)
    if not query:
        return {"error": "Paramètre 'query' requis."}
    try:
        messages = await asyncio.to_thread(
            _search_emails,
            config["imap_host"],
            int(config.get("imap_port", 993)),
            config["username"],
            config["password"],
            query=query,
            folder=_folder(args.get("folder")),
            limit=_bounded_int(args.get("limit"), 20, 1, 50),
        )
        return {
            "success": True,
            "query": query,
            "count": len(messages),
            "emails": messages,
        }
    except Exception as error:
        return {"error": str(error)}


async def send(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _send_email
    config = _get_account(args.get("account"))
    if not config:
        return _account_error()
    to = _text(args.get("to"), 2_000)
    subject = _text(args.get("subject"), 998)
    body = _text(args.get("body"), 2_000_000)
    if not to:
        return {"needsClarification": True, "message": "Il me manque le destinataire. À qui dois-je envoyer ce mail ?"}
    if not subject:
        return {"needsClarification": True, "message": "Quel doit être l'objet de ce mail ?"}
    if not body:
        return {"needsClarification": True, "message": "Que dois-je écrire dans le corps du mail ?"}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Envoyer l'email à {to} — Objet : {subject} ?\n\n{body[:300]}",
        }
    try:
        result = await asyncio.to_thread(
            _send_email,
            config.get("smtp_host", config["imap_host"].replace("imap.", "smtp.")),
            int(config.get("smtp_port", 587)),
            config["username"],
            config["password"],
            to=to,
            subject=subject,
            body=body,
            cc=_text(args.get("cc"), 2_000),
            reply_to=_text(args.get("reply_to"), 500),
            in_reply_to=_text(args.get("in_reply_to"), 1_000),
            references=_text(args.get("references"), 4_000),
            auto_submitted=bool(args.get("auto_submitted", False)),
        )
        return {"success": True, "message": f"Email envoyé à {to}", "detail": result}
    except Exception as error:
        return {"error": str(error)}


async def _message_content(args: dict[str, Any]) -> tuple[str, str, str] | dict[str, Any]:
    assert _get_account and _fetch_email
    original = _text(args.get("body"), 100_000)
    subject = _text(args.get("subject"), 998)
    sender = _text(args.get("from") or args.get("from_addr"), 2_000)
    uid = _text(args.get("uid"), 500)
    if uid and not original:
        config = _get_account(args.get("account"))
        if not config:
            return _account_error()
        try:
            message = await asyncio.to_thread(
                _fetch_email,
                config["imap_host"],
                int(config.get("imap_port", 993)),
                config["username"],
                config["password"],
                uid=uid,
                folder=_folder(args.get("folder")),
            )
        except Exception as error:
            return {"error": f"Lecture de l'email impossible : {error}"}
        original = _text(message.get("body") or message.get("text"), 100_000)
        subject = subject or _text(message.get("subject"), 998)
        sender = sender or _text(message.get("from") or message.get("from_addr"), 2_000)
    return original, subject, sender


async def draft_reply(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _generate and _network_error
    content = await _message_content(args)
    if isinstance(content, dict):
        return content
    original, subject, sender = content
    if not original:
        return {"error": "Aucun contenu à traiter : fournir 'uid' (email à lire) ou 'body'."}
    instruction = _text(args.get("instruction") or args.get("intent"), 10_000)
    tone = _text(args.get("tone") or "professionnel, clair et courtois", 500)
    language = _text(args.get("language") or "français", 100)
    signature = _text(args.get("signature"), 10_000)
    prompt = (
        "Tu es un assistant expert en rédaction d'emails. Rédige LA meilleure réponse à "
        f"l'email ci-dessous, en {language}, dans un style {tone}, avec une orthographe et "
        "une grammaire IRRÉPROCHABLES (zéro faute). Structure : formule d'appel adaptée, "
        "corps clair et bien tourné, formule de politesse finale. Réponds UNIQUEMENT avec "
        "le corps de l'email (pas d'objet, pas d'explication, pas de balises).\n\n"
        f"=== EMAIL REÇU ===\nDe : {sender or '(inconnu)'}\n"
        f"Objet : {subject or '(sans objet)'}\n\n{original[:5_000]}\n\n"
    )
    if instruction:
        prompt += f"=== CONSIGNE pour ta réponse ===\n{instruction}\n\n"
    if signature:
        prompt += f"Termine par cette signature :\n{signature}\n\n"
    prompt += "=== TA RÉPONSE (corps de l'email uniquement) ==="
    try:
        draft, provenance = await _generate_with_provenance(
            prompt, model=args.get("model"), timeout=180
        )
        if not draft:
            return {"error": "L'IA n'a pas produit de réponse. Réessayez."}
        reply_subject = subject if subject.lower().startswith("re:") else (f"Re: {subject}" if subject else "Re:")
        return {
            "success": True,
            "draft": draft,
            "to": sender,
            "subject": reply_subject,
            "account": args.get("account"),
            "message": "Brouillon de réponse généré.",
            "generation": provenance,
        }
    except Exception as error:
        return _network_error(error, "rédaction IA")


async def summarize(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _generate and _network_error
    content = await _message_content(args)
    if isinstance(content, dict):
        return content
    original, subject, sender = content
    if not original:
        return {"error": "Aucun contenu à résumer : fournir 'uid' ou 'body'."}
    prompt = (
        "Résume cet email en français, de manière concise et claire. Donne exactement :\n"
        "**Résumé** : 2-3 phrases.\n**Points clés** : 2 à 4 puces.\n"
        "**Action attendue** : ce que je dois faire (ou « Aucune action requise »).\n"
        "N'invente rien, base-toi uniquement sur le contenu.\n\n"
        f"De : {sender or '(inconnu)'}\nObjet : {subject or '(sans objet)'}\n\n{original[:6_000]}"
    )
    try:
        summary, provenance = await _generate_with_provenance(
            prompt, model=args.get("model"), timeout=180
        )
        return {
            "success": True,
            "summary": summary,
            "subject": subject,
            "from": sender,
            "message": "Résumé généré.",
            "generation": provenance,
        }
    except Exception as error:
        return _network_error(error, "résumé IA")


async def digest(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _list_accounts and _fetch_inbox
    assert _generate and _network_error
    account = args.get("account")
    limit = _bounded_int(args.get("limit"), 15, 3, 25)
    try:
        folder = _folder(args.get("folder"))

        async def fetch_one(config: dict[str, Any]) -> list[dict[str, Any]]:
            messages = await asyncio.to_thread(
                _fetch_inbox,
                config["imap_host"],
                int(config.get("imap_port", 993)),
                config["username"],
                config["password"],
                folder=folder,
                limit=limit,
                offset=0,
            )
            return [{**message, "_account": config["username"]} for message in messages]

        if account == "__all__":
            batches = await asyncio.gather(
                *(fetch_one(config) for config in _list_accounts()),
                return_exceptions=True,
            )
            messages = [
                message
                for batch in batches
                if isinstance(batch, list)
                for message in batch
            ]
        else:
            config = _get_account(account)
            if not config:
                return _account_error()
            messages = await fetch_one(config)
        if not messages:
            return {"success": True, "digest": "Aucun email récent à analyser.", "count": 0}
        messages.sort(key=lambda message: message.get("date") or "", reverse=True)
        messages = messages[:limit]
        lines = []
        for index, message in enumerate(messages, 1):
            box = f" [{message.get('_account')}]" if account == "__all__" else ""
            lines.append(
                f"{index}. De : {message.get('from', '?')} | "
                f"Objet : {message.get('subject', '(sans objet)')}{box}"
            )
        prompt = (
            "Tu es mon assistant. Voici la liste de mes emails récents. Fais-moi un BRIEFING "
            "en français :\n- Classe-les par priorité avec une pastille : "
            "🔴 (urgent / à traiter vite), 🟡 (à traiter), ⚪ (info / promo / newsletter).\n"
            "- Pour chaque email important, UNE ligne très courte : qui, de quoi, "
            "et l'action suggérée.\n"
            "- Regroupe les ⚪ peu importants en une seule ligne à la fin.\n"
            "- Termine par : « 👉 À TRAITER EN PRIORITÉ : … ».\n"
            "Sois synthétique et concret.\n\n=== EMAILS ===\n" + "\n".join(lines)
        )
        result, provenance = await _generate_with_provenance(
            prompt, model=args.get("model"), timeout=180
        )
        return {
            "success": True,
            "digest": result,
            "count": len(messages),
            "message": f"Briefing de {len(messages)} email(s) généré.",
            "generation": provenance,
        }
    except Exception as error:
        return _network_error(error, "briefing IA")
