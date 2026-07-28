"""Transformation contrôlée des e-mails en tâches et résumés de pièces jointes."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any


GetAccount = Callable[[str | None], dict[str, Any] | None]
AsyncTool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
Generate = Callable[..., Awaitable[str]]
NetworkError = Callable[[Exception, str], dict[str, Any]]

_MAX_BODY = 100_000
_MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
_TEXT_EXTENSIONS = {".txt", ".csv", ".md", ".log", ".json"}

_get_account: GetAccount | None = None
_fetch_email: Callable[..., dict[str, Any]] | None = None
_fetch_attachment: Callable[..., dict[str, Any] | None] | None = None
_generate: Generate | None = None
_create_task: AsyncTool | None = None
_read_pdf: AsyncTool | None = None
_read_docx: AsyncTool | None = None
_network_error: NetworkError | None = None
_today: Callable[[], date] = date.today


def configure(
    *,
    get_account: GetAccount,
    fetch_email: Callable[..., dict[str, Any]],
    fetch_attachment: Callable[..., dict[str, Any] | None],
    generate: Generate,
    create_task: AsyncTool,
    read_pdf: AsyncTool,
    read_docx: AsyncTool,
    network_error: NetworkError,
    today: Callable[[], date] = date.today,
) -> None:
    global _get_account, _fetch_email, _fetch_attachment, _generate, _create_task
    global _read_pdf, _read_docx, _network_error, _today
    _get_account = get_account
    _fetch_email = fetch_email
    _fetch_attachment = fetch_attachment
    _generate = generate
    _create_task = create_task
    _read_pdf = read_pdf
    _read_docx = read_docx
    _network_error = network_error
    _today = today


def _require_dependencies() -> None:
    if any(
        dependency is None
        for dependency in (
            _get_account,
            _fetch_email,
            _fetch_attachment,
            _generate,
            _create_task,
            _read_pdf,
            _read_docx,
            _network_error,
        )
    ):
        raise RuntimeError("Le domaine de productivité e-mail n'est pas configuré.")


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _folder(value: Any) -> str:
    folder = _text(value or "INBOX", 255)
    if not folder or any(ord(character) < 32 or ord(character) == 127 for character in folder):
        raise ValueError("Dossier e-mail invalide.")
    return folder


async def _load_message(args: dict[str, Any]) -> tuple[str, str, str] | dict[str, Any]:
    assert _get_account and _fetch_email
    body = _text(args.get("body"), _MAX_BODY)
    subject = _text(args.get("subject"), 998)
    sender = _text(args.get("from") or args.get("from_addr"), 2_000)
    uid = _text(args.get("uid"), 500)
    if uid and not body:
        account = _get_account(args.get("account"))
        if not account:
            return {"error": "Email non configuré."}
        try:
            message = await asyncio.to_thread(
                _fetch_email,
                account["imap_host"],
                int(account.get("imap_port", 993)),
                account["username"],
                account["password"],
                uid=uid,
                folder=_folder(args.get("folder")),
            )
        except Exception as error:
            return {"error": f"Lecture de l'email impossible : {error}"}
        body = _text(message.get("body") or message.get("text"), _MAX_BODY)
        subject = subject or _text(message.get("subject"), 998)
        sender = sender or _text(message.get("from") or message.get("from_addr"), 2_000)
    return body, subject, sender


def _first_json_object(raw: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, character in enumerate(raw):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _due_date(value: Any) -> str | None:
    candidate = _text(value, 32)
    if not candidate or candidate.casefold() in {"null", "none", "aucune", "n/a"}:
        return None
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return None


async def to_task(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _generate and _create_task and _network_error
    content = await _load_message(args)
    if isinstance(content, dict):
        return content
    body, subject, sender = content
    if not body and not subject:
        return {"error": "Aucun contenu : fournir 'uid' ou 'body'."}

    current_day = _today().isoformat()
    prompt = (
        "À partir de cet email, définis UNE tâche à faire. Réponds UNIQUEMENT par un objet "
        "JSON valide (aucun texte autour), au format exact :\n"
        '{"title": "...", "description": "...", "priority": "low|medium|high", '
        '"due_date": "YYYY-MM-DD ou null"}\n'
        "- title : court, actionnable, commence par un verbe (français).\n"
        f"- due_date : déduis l'échéance si l'email en mentionne une "
        f"(aujourd'hui = {current_day}), sinon null.\n"
        "- priority : selon l'urgence/importance.\n\n"
        f"De : {sender}\nObjet : {subject}\n\n{body[:4_000]}"
    )
    try:
        raw = await _generate(prompt, model=args.get("model"), timeout=180)
    except Exception as error:
        return _network_error(error, "extraction tâche IA")
    parsed = _first_json_object(str(raw or "")) or {}
    title = _text(parsed.get("title") or subject or raw or "Tâche depuis email", 200)
    if not title:
        title = "Tâche depuis email"
    priority = _text(parsed.get("priority") or "medium", 20).casefold()
    if priority not in {"low", "medium", "high"}:
        priority = "medium"
    due = _due_date(parsed.get("due_date"))
    description = _text(parsed.get("description"), 10_000)
    if subject:
        provenance = f"— Issu de l'email « {subject} »"
        if sender:
            provenance += f" de {sender}"
        description = _text(f"{description}\n\n{provenance}", 10_000)

    result = await _create_task(
        {
            "title": title,
            "description": description,
            "priority": priority,
            "due_date": due,
            "tags": ["email"],
        }
    )
    if result.get("error") or not result.get("success"):
        return result
    return {
        "success": True,
        "task": result.get("task"),
        "title": title,
        "priority": priority,
        "due_date": due,
        "message": (
            f"Tâche créée : « {title} »"
            + (f" (échéance {due})" if due else "")
        ),
    }


def _write_bytes(path: str, content: bytes) -> None:
    with open(path, "wb") as stream:
        stream.write(content)


async def attachment_summary(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_account and _fetch_attachment and _generate
    assert _read_pdf and _read_docx and _network_error
    uid = _text(args.get("uid"), 500)
    if not uid:
        return {"error": "Paramètre 'uid' requis."}
    account = _get_account(args.get("account"))
    if not account:
        return {"error": "Email non configuré."}
    try:
        attachment = await asyncio.to_thread(
            _fetch_attachment,
            account["imap_host"],
            int(account.get("imap_port", 993)),
            account["username"],
            account["password"],
            uid=uid,
            name=_text(args.get("name"), 255),
            folder=_folder(args.get("folder")),
        )
    except Exception as error:
        return {
            "error": (
                "Pièce jointe introuvable (uid invalide ou email inaccessible) : "
                f"{error}"
            )
        }
    if not attachment or not attachment.get("data"):
        return {"error": "Pièce jointe introuvable."}
    content = attachment["data"]
    if not isinstance(content, bytes):
        return {"error": "Contenu de pièce jointe invalide."}
    if len(content) > _MAX_ATTACHMENT_BYTES:
        return {"error": "Pièce jointe trop volumineuse (maximum 25 Mio)."}

    filename = Path(_text(attachment.get("name") or "piece_jointe", 255)).name
    extension = Path(filename).suffix.casefold()
    if extension not in ({".pdf", ".docx"} | _TEXT_EXTENSIONS):
        return {
            "error": (
                f"Type non pris en charge pour le résumé : {extension or filename}. "
                "(PDF, Word .docx, texte supportés)"
            )
        }

    temporary_path = ""
    try:
        if extension in _TEXT_EXTENSIONS:
            extracted = content.decode("utf-8", errors="replace")[:20_000]
        else:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix="marvin_att_",
                suffix=extension,
            )
            os.close(descriptor)
            await asyncio.to_thread(_write_bytes, temporary_path, content)
            if extension == ".pdf":
                result = await _read_pdf({"path": temporary_path, "max_chars": 14_000})
                extracted = _text(result.get("text") or result.get("content"), 14_000)
            else:
                result = await _read_docx({"path": temporary_path, "format": "text"})
                extracted = _text(result.get("text"), 20_000)
            if result.get("error"):
                return result
        if not extracted.strip():
            return {
                "error": (
                    f"Impossible d'extraire du texte de « {filename} » "
                    "(document vide ou scanné)."
                )
            }
        prompt = (
            f"Résume en français cette pièce jointe nommée « {filename} ». "
            "Donne : **Résumé** (2-4 phrases), **Points clés** (puces), et "
            "**À retenir / action** s'il y a lieu. Base-toi uniquement sur le contenu.\n\n"
            f"{extracted[:13_000]}"
        )
        summary = _text(
            await _generate(prompt, model=args.get("model"), timeout=180),
            100_000,
        )
        if not summary:
            return {"error": "L'IA n'a pas produit de résumé. Réessayez."}
        return {
            "success": True,
            "name": filename,
            "size": len(content),
            "summary": summary,
            "message": f"Résumé de « {filename} » généré.",
        }
    except Exception as error:
        return _network_error(error, "résumé pièce jointe")
    finally:
        if temporary_path:
            try:
                await asyncio.to_thread(os.remove, temporary_path)
            except OSError:
                pass
