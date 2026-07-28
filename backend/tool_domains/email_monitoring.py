"""Surveillance et règles de classement e-mail avec dépendances injectées."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any


AsyncAction = Callable[[dict[str, Any]], Awaitable[Any]]
Generate = Callable[..., Awaitable[str]]

_get_setting: Callable[[str], Any] | None = None
_set_setting: Callable[[str, Any], None] | None = None
_list_accounts: Callable[[], list[dict[str, Any]]] | None = None
_fetch_inbox: Callable[..., list[dict[str, Any]]] | None = None
_move_email: Callable[..., Any] | None = None
_mark_email: Callable[..., Any] | None = None
_generate: Generate | None = None
_desktop_notify: AsyncAction | None = None
_telegram_notify: Callable[[str], Awaitable[Any]] | None = None
_clock: Callable[[], datetime] = datetime.now

_watch_lock = asyncio.Lock()
_rules_lock = asyncio.Lock()
_RULE_ACTIONS = {"move", "mark_read", "mark_unread"}


def configure(
    *,
    get_setting: Callable[[str], Any],
    set_setting: Callable[[str, Any], None],
    list_accounts: Callable[[], list[dict[str, Any]]],
    fetch_inbox: Callable[..., list[dict[str, Any]]],
    move_email: Callable[..., Any],
    mark_email: Callable[..., Any],
    generate: Generate,
    desktop_notify: AsyncAction,
    telegram_notify: Callable[[str], Awaitable[Any]],
    clock: Callable[[], datetime] = datetime.now,
) -> None:
    global _get_setting, _set_setting, _list_accounts, _fetch_inbox
    global _move_email, _mark_email, _generate, _desktop_notify, _telegram_notify, _clock
    _get_setting = get_setting
    _set_setting = set_setting
    _list_accounts = list_accounts
    _fetch_inbox = fetch_inbox
    _move_email = move_email
    _mark_email = mark_email
    _generate = generate
    _desktop_notify = desktop_notify
    _telegram_notify = telegram_notify
    _clock = clock


def _require_dependencies() -> None:
    if any(
        dependency is None
        for dependency in (
            _get_setting,
            _set_setting,
            _list_accounts,
            _fetch_inbox,
            _move_email,
            _mark_email,
            _generate,
            _desktop_notify,
            _telegram_notify,
        )
    ):
        raise RuntimeError("Le domaine de surveillance e-mail n'est pas configuré.")


def _coerce(value: Any, expected: type, default: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return value if isinstance(value, expected) else default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def _folder(value: Any) -> str:
    folder = _text(value, 255)
    if not folder or any(ord(character) < 32 or ord(character) == 127 for character in folder):
        raise ValueError("Dossier e-mail invalide.")
    return folder


def _configured_accounts(filter_values: Any = None) -> list[dict[str, Any]]:
    assert _list_accounts
    allowed = {
        _text(value, 320)
        for value in (filter_values if isinstance(filter_values, list) else [])
        if _text(value, 320)
    }
    accounts = []
    for account in _list_accounts()[:50]:
        if not isinstance(account, dict):
            continue
        username = _text(account.get("username"), 320)
        if not username or (allowed and username not in allowed):
            continue
        if not all(account.get(key) for key in ("imap_host", "password")):
            continue
        accounts.append(account)
    return accounts


def _important_indices(raw: Any, batch_size: int) -> set[int] | None:
    text = str(raw or "")
    decoder = json.JSONDecoder()
    payload = None
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if payload is None or not isinstance(payload.get("important"), list):
        return None
    indices = set()
    for value in payload["important"]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= parsed <= batch_size:
            indices.add(parsed)
    return indices


async def watch_check(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _get_setting and _set_setting and _fetch_inbox and _generate
    assert _desktop_notify and _telegram_notify
    if _watch_lock.locked():
        return {"error": "Une surveillance e-mail est déjà en cours."}
    async with _watch_lock:
        config = _coerce(_get_setting("email_watch"), dict, {})
        if not args.get("force") and not config.get("enabled"):
            return {
                "success": True,
                "checked": 0,
                "important": 0,
                "message": "Surveillance désactivée.",
            }
        max_notify = _bounded_int(config.get("max_notify"), 5, 1, 20)
        do_notify = not bool(args.get("dry_run", False))
        seen_order = [
            _text(value, 1_000)
            for value in _coerce(_get_setting("email_watch_seen"), list, [])
            if _text(value, 1_000)
        ][-1_000:]
        seen = set(seen_order)
        new_items: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []

        for account in _configured_accounts(config.get("accounts")):
            try:
                inbox = await asyncio.to_thread(
                    _fetch_inbox,
                    account["imap_host"],
                    int(account.get("imap_port", 993)),
                    account["username"],
                    account["password"],
                    folder="INBOX",
                    limit=15,
                    offset=0,
                )
            except Exception as error:
                errors.append(
                    {"account": account["username"], "phase": "fetch", "error": str(error)}
                )
                continue
            for message in inbox if isinstance(inbox, list) else []:
                uid = _text(message.get("id"), 500)
                key = f"{account['username']}:{uid}"
                if not uid or key in seen or message.get("read"):
                    continue
                new_items.append(
                    {
                        "account": account["username"],
                        "key": key,
                        "from": _text(message.get("from"), 2_000),
                        "subject": _text(message.get("subject"), 998),
                    }
                )
                if len(new_items) >= 100:
                    break
            if len(new_items) >= 100:
                break

        if not new_items:
            return {
                "success": True,
                "checked": 0,
                "important": 0,
                "errors": errors,
                "message": "Aucun nouvel email non lu.",
            }

        important_keys: set[str] = set()
        classified_keys: set[str] = set()
        for start in range(0, len(new_items), 20):
            batch = new_items[start : start + 20]
            listing = "\n".join(
                f"{index}. De: {item['from']} | Objet: {item['subject']}"
                for index, item in enumerate(batch, 1)
            )
            prompt = (
                "Parmi ces nouveaux emails non lus, lesquels sont VRAIMENT IMPORTANTS "
                "(action requise, urgent, vrai expéditeur attendant une réponse) — par "
                "opposition aux non importants (pub, newsletter, notification automatique, "
                "réseaux sociaux) ? Réponds UNIQUEMENT par un JSON : "
                '{"important": [numéros]}.\n\n'
                + listing
            )
            try:
                indices = _important_indices(
                    await _generate(prompt, model=args.get("model"), timeout=120),
                    len(batch),
                )
                if indices is None:
                    raise ValueError("Réponse IA sans objet JSON important valide.")
            except Exception as error:
                errors.append({"account": "*", "phase": "classification", "error": str(error)})
                continue
            classified_keys.update(item["key"] for item in batch)
            important_keys.update(
                item["key"] for index, item in enumerate(batch, 1) if index in indices
            )

        alerts = _coerce(_get_setting("email_watch_alerts"), list, [])
        alerts = [alert for alert in alerts if isinstance(alert, dict)][:50]
        reported = 0
        for item in new_items:
            if item["key"] not in classified_keys:
                continue
            if item["key"] not in seen:
                seen.add(item["key"])
                seen_order.append(item["key"])
            if item["key"] not in important_keys or reported >= max_notify:
                continue
            if do_notify:
                try:
                    await _desktop_notify(
                        {
                            "title": f"📧 Email important — {item['from'][:40]}",
                            "message": (item["subject"] or "(sans objet)")[:140],
                        }
                    )
                except Exception as error:
                    errors.append(
                        {
                            "account": item["account"],
                            "phase": "desktop_notification",
                            "error": str(error),
                        }
                    )
                try:
                    await _telegram_notify(
                        "🔴 <b>Mail important</b>\n"
                        f"De : {item['from'][:60]}\n"
                        f"{(item['subject'] or '(sans objet)')[:140]}"
                    )
                except Exception as error:
                    errors.append(
                        {
                            "account": item["account"],
                            "phase": "telegram_notification",
                            "error": str(error),
                        }
                    )
            alerts.insert(
                0,
                {
                    "account": item["account"],
                    "from": item["from"],
                    "subject": item["subject"],
                    "at": _clock().isoformat(timespec="seconds"),
                },
            )
            reported += 1

        _set_setting("email_watch_seen", seen_order[-1_000:])
        _set_setting("email_watch_alerts", alerts[:50])
        return {
            "success": True,
            "checked": len(new_items),
            "classified": len(classified_keys),
            "important": reported,
            "dry_run": not do_notify,
            "errors": errors[:50],
            "message": (
                f"{len(new_items)} nouvel(s) email(s) non lu(s), "
                f"{reported} important(s) signalé(s)."
            ),
        }


def _rules() -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    assert _get_setting
    raw_rules = _coerce(_get_setting("email_rules"), list, [])
    valid = []
    errors = []
    for index, raw in enumerate(raw_rules[:100]):
        if not isinstance(raw, dict) or not raw.get("enabled", True):
            continue
        sender = _text(raw.get("from_contains"), 500).casefold()
        subject = _text(raw.get("subject_contains"), 500).casefold()
        if not sender and not subject:
            continue
        action = _text(raw.get("action") or "move", 30)
        if action not in _RULE_ACTIONS:
            errors.append({"rule": str(index + 1), "error": f"Action inconnue : {action}"})
            continue
        folder = _text(raw.get("folder"), 255)
        if action == "move":
            try:
                folder = _folder(folder)
            except ValueError as error:
                errors.append({"rule": str(index + 1), "error": str(error)})
                continue
        valid.append(
            {
                "name": _text(raw.get("name") or action, 200),
                "account": _text(raw.get("account"), 320),
                "from_contains": sender,
                "subject_contains": subject,
                "action": action,
                "folder": folder,
            }
        )
    return valid, errors


async def apply_rules(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    assert _fetch_inbox and _move_email and _mark_email
    if _rules_lock.locked():
        return {"error": "Une application des règles e-mail est déjà en cours."}
    async with _rules_lock:
        rules, validation_errors = _rules()
        if not rules:
            return {
                "success": True,
                "applied": 0,
                "dry_run": bool(args.get("dry_run", False)),
                "results": validation_errors,
                "truncated": False,
                "message": "Aucune règle valide définie.",
            }
        dry_run = bool(args.get("dry_run", False))
        only_account = _text(args.get("account"), 320)
        limit = _bounded_int(args.get("limit"), 25, 1, 100)
        results: list[dict[str, Any]] = list(validation_errors)
        applied = 0

        for account in _configured_accounts(
            [only_account] if only_account else None
        ):
            try:
                inbox = await asyncio.to_thread(
                    _fetch_inbox,
                    account["imap_host"],
                    int(account.get("imap_port", 993)),
                    account["username"],
                    account["password"],
                    folder="INBOX",
                    limit=limit,
                    offset=0,
                )
            except Exception as error:
                results.append(
                    {
                        "account": account["username"],
                        "action": "erreur",
                        "reason": str(error),
                    }
                )
                continue
            for message in inbox if isinstance(inbox, list) else []:
                uid = _text(message.get("id"), 500)
                if not uid:
                    continue
                sender = _text(message.get("from"), 2_000).casefold()
                subject = _text(message.get("subject"), 998).casefold()
                for rule in rules:
                    if rule["account"] and rule["account"] != account["username"]:
                        continue
                    if rule["from_contains"] and rule["from_contains"] not in sender:
                        continue
                    if rule["subject_contains"] and rule["subject_contains"] not in subject:
                        continue
                    action = rule["action"]
                    target = rule["folder"]
                    label = (
                        f"{_text(message.get('subject') or '(sans objet)', 40)} "
                        f"→ règle « {rule['name']} »"
                    )
                    if not dry_run:
                        try:
                            if action == "move":
                                await asyncio.to_thread(
                                    _move_email,
                                    account["imap_host"],
                                    int(account.get("imap_port", 993)),
                                    account["username"],
                                    account["password"],
                                    uid=uid,
                                    dest_folder=target,
                                    folder="INBOX",
                                )
                            else:
                                await asyncio.to_thread(
                                    _mark_email,
                                    account["imap_host"],
                                    int(account.get("imap_port", 993)),
                                    account["username"],
                                    account["password"],
                                    uid=uid,
                                    folder="INBOX",
                                    seen=action == "mark_read",
                                )
                        except Exception as error:
                            results.append(
                                {
                                    "account": account["username"],
                                    "action": "échec",
                                    "detail": label,
                                    "reason": str(error),
                                }
                            )
                            break
                    results.append(
                        {
                            "account": account["username"],
                            "action": action + (" (simulation)" if dry_run else ""),
                            "detail": label,
                            "folder": target,
                        }
                    )
                    applied += 1
                    break
        return {
            "success": True,
            "applied": applied,
            "dry_run": dry_run,
            "results": results[:60],
            "truncated": len(results) > 60,
            "message": (
                f"{applied} email(s) classé(s) par règles"
                + (" (simulation)" if dry_run else "")
                + "."
            ),
        }
