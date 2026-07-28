"""Orchestration multiboîte des réponses e-mail et de la file différée."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any


GetSetting = Callable[[str], Any]
SetSetting = Callable[[str, Any], None]
ListAccounts = Callable[[], list[dict[str, Any]]]
FetchInbox = Callable[..., list[dict[str, Any]]]
FetchEmail = Callable[..., dict[str, Any]]
AsyncOperation = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

NEVER_FROM = (
    "noreply", "no-reply", "no_reply", "do-not-reply", "donotreply",
    "notification", "notifications", "newsletter", "mailer-daemon",
    "postmaster", "bounce", "automated", "automatique", "ne-pas-repondre",
)
SENSITIVE_KEYWORDS = (
    "banque", "bank", "mot de passe", "password", "sécurité", "securite",
    "security", "virement", "carte bancaire", "iban", "rib", "facture impayée",
    "code de vérification", "verification code", "2fa", "otp", "litige", "juridique",
)
VALID_MODES = frozenset({"manuel", "brouillon", "autonome", "differe"})

_get_setting: GetSetting | None = None
_set_setting: SetSetting | None = None
_list_accounts: ListAccounts | None = None
_fetch_inbox: FetchInbox | None = None
_fetch_email: FetchEmail | None = None
_draft_reply: AsyncOperation | None = None
_send_email: AsyncOperation | None = None
_clock: Callable[[], datetime] = datetime.now
_automation_lock = asyncio.Lock()
_outbox_lock = asyncio.Lock()


def configure(
    *,
    get_setting: GetSetting,
    set_setting: SetSetting,
    list_accounts: ListAccounts,
    fetch_inbox: FetchInbox,
    fetch_email: FetchEmail,
    draft_reply: AsyncOperation,
    send_email: AsyncOperation,
    clock: Callable[[], datetime] = datetime.now,
) -> None:
    global _get_setting, _set_setting, _list_accounts
    global _fetch_inbox, _fetch_email, _draft_reply, _send_email, _clock
    _get_setting = get_setting
    _set_setting = set_setting
    _list_accounts = list_accounts
    _fetch_inbox = fetch_inbox
    _fetch_email = fetch_email
    _draft_reply = draft_reply
    _send_email = send_email
    _clock = clock


def _require_dependencies() -> None:
    if any(
        dependency is None
        for dependency in (
            _get_setting, _set_setting, _list_accounts, _fetch_inbox,
            _fetch_email, _draft_reply, _send_email,
        )
    ):
        raise RuntimeError("Le domaine d'automatisation e-mail n'est pas configuré.")


def _json_value(value: Any, expected: type, default: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return default
    return value if isinstance(value, expected) else default


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _normalised_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item).lower().strip() for item in value if str(item).strip()
    ))


def get_config() -> dict[str, Any]:
    _require_dependencies()
    assert _get_setting is not None
    raw = _json_value(_get_setting("email_automation"), dict, {})
    mode = str(raw.get("mode") or "manuel").lower().strip()
    if mode not in VALID_MODES:
        mode = "manuel"
    return {
        "mode": mode,
        "accounts": _normalised_list(raw.get("accounts")),
        "instructions": str(raw.get("instructions") or "")[:10_000],
        "tone": str(raw.get("tone") or "professionnel, clair et courtois")[:500],
        "signature": str(raw.get("signature") or "")[:10_000],
        "only_from": _normalised_list(raw.get("only_from")),
        "never_from": _normalised_list(raw.get("never_from")),
        "skip_keywords": _normalised_list(raw.get("skip_keywords")),
        "max_per_run": _bounded_int(raw.get("max_per_run"), 5, 1, 100),
        "send_delay_min": _bounded_int(raw.get("send_delay_min"), 5, 1, 1_440),
        "scheduler_enabled": bool(raw.get("scheduler_enabled", False)),
        "interval_min": _bounded_int(raw.get("interval_min"), 5, 2, 1_440),
        "profiles": raw.get("profiles") if isinstance(raw.get("profiles"), dict) else {},
    }


def effective_profile(config: dict[str, Any], account: str) -> dict[str, Any]:
    override = config.get("profiles", {}).get(account, {})
    if not isinstance(override, dict):
        override = {}
    result = {
        key: config[key]
        for key in (
            "mode", "instructions", "tone", "signature", "only_from", "never_from",
            "skip_keywords", "max_per_run", "send_delay_min",
        )
    }
    for key in result:
        if key in override:
            result[key] = override[key]
    mode = str(result.get("mode") or "manuel").lower().strip()
    result["mode"] = mode if mode in VALID_MODES else "manuel"
    result["only_from"] = _normalised_list(result.get("only_from"))
    result["never_from"] = list(dict.fromkeys(
        _normalised_list(result.get("never_from")) + list(NEVER_FROM)
    ))
    result["skip_keywords"] = list(dict.fromkeys(
        _normalised_list(result.get("skip_keywords")) + list(SENSITIVE_KEYWORDS)
    ))
    result["max_per_run"] = _bounded_int(result.get("max_per_run"), 5, 1, 100)
    result["send_delay_min"] = _bounded_int(result.get("send_delay_min"), 5, 1, 1_440)
    return result


async def _headers_for(account: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    assert _fetch_inbox is not None
    if account.get("_auth_error"):
        return account, [], str(account["_auth_error"])
    try:
        messages = await asyncio.to_thread(
            _fetch_inbox,
            account["imap_host"],
            int(account.get("imap_port", 993)),
            account["username"],
            account["password"],
            folder="INBOX",
            limit=30,
            offset=0,
        )
        return account, messages if isinstance(messages, list) else [], None
    except Exception as error:
        return account, [], str(error)


def _skip_reason(header: dict[str, Any], profile: dict[str, Any]) -> str | None:
    sender_header = str(header.get("from") or "")
    sender = parseaddr(sender_header)[1].lower() or sender_header.lower()
    subject = str(header.get("subject") or "")
    auto_submitted = str(header.get("auto_submitted") or "").lower()
    precedence = str(header.get("precedence") or "").lower()
    mode = profile["mode"]
    if auto_submitted and auto_submitted != "no":
        return "message déjà automatique"
    if header.get("list_id") or precedence in {"bulk", "list", "junk"}:
        return "liste de diffusion ou message en masse"
    if any(item in sender for item in profile["never_from"]):
        return "expéditeur automatique/exclu"
    if any(item in f"{subject.lower()} {sender}" for item in profile["skip_keywords"]):
        return "sujet sensible"
    if mode in {"autonome", "differe"} and not profile["only_from"]:
        return "envoi automatique bloqué : liste d'expéditeurs autorisés vide"
    if profile["only_from"] and not any(item in sender for item in profile["only_from"]):
        return "hors liste d'expéditeurs autorisés"
    return None


async def run(args: dict[str, Any]) -> dict[str, Any]:
    _require_dependencies()
    if _automation_lock.locked():
        return {"error": "Une exécution des réponses automatiques est déjà en cours."}
    async with _automation_lock:
        return await _run_locked(args)


async def _run_locked(args: dict[str, Any]) -> dict[str, Any]:
    assert _get_setting and _set_setting and _list_accounts
    assert _fetch_email and _draft_reply and _send_email
    config = get_config()
    dry_run = bool(args.get("dry_run", False))
    forced_mode = str(args.get("mode") or "").lower().strip()
    if forced_mode and forced_mode not in VALID_MODES:
        return {"error": f"Mode e-mail invalide : {forced_mode}"}
    selected = set(config["accounts"])
    if not selected:
        return {"error": "Sélectionne explicitement au moins une boîte pour l'automatisation."}
    accounts = [
        account for account in _list_accounts()
        if str(account.get("username") or "").lower() in selected
    ]
    if not accounts:
        return {"error": "Aucune des boîtes sélectionnées n'est disponible."}

    fetched = await asyncio.gather(*(_headers_for(account) for account in accounts))
    results: list[dict[str, Any]] = []
    queues: dict[str, list[dict[str, Any]]] = {}
    profiles: dict[str, dict[str, Any]] = {}
    for account, messages, error in fetched:
        username = account["username"]
        profile = effective_profile(config, username)
        if forced_mode:
            profile["mode"] = forced_mode
        profiles[username] = profile
        if error:
            results.append({"account": username, "action": "erreur", "reason": error})
        queues[username] = [message for message in messages if not message.get("read")]

    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    per_account = {account["username"]: 0 for account in accounts}
    while any(queues.values()):
        progressed = False
        for account in accounts:
            username = account["username"]
            if queues[username] and per_account[username] < profiles[username]["max_per_run"]:
                candidates.append((account, queues[username].pop(0), profiles[username]))
                per_account[username] += 1
                progressed = True
        if not progressed:
            break

    seen_raw = _json_value(_get_setting("email_auto_seen") or [], list, [])
    seen = set(str(item) for item in seen_raw)
    new_seen: set[str] = set()
    pending_drafts: list[dict[str, Any]] = []
    pending_outbox: list[dict[str, Any]] = []
    sent = 0
    signatures = _json_value(_get_setting("email_signatures") or {}, dict, {})

    for account, header, profile in candidates:
        username = account["username"]
        mode = profile["mode"]
        if mode == "manuel":
            continue
        uid = str(header.get("id") or header.get("uid") or "")
        stable_id = str(header.get("message_id") or uid)
        key = f"{username.lower()}:{stable_id}"
        if not stable_id or key in seen:
            continue
        reason = _skip_reason(header, profile)
        sender_header = str(header.get("from") or "")
        subject = str(header.get("subject") or "")
        if reason:
            results.append({
                "account": username, "from": sender_header, "subject": subject,
                "action": "ignoré", "reason": reason,
            })
            new_seen.add(key)
            continue
        try:
            message = await asyncio.to_thread(
                _fetch_email,
                account["imap_host"],
                int(account.get("imap_port", 993)),
                account["username"],
                account["password"],
                uid=uid,
                folder="INBOX",
                mark_seen=not dry_run,
            )
        except Exception as error:
            results.append({
                "account": username, "subject": subject,
                "action": "erreur", "reason": str(error),
            })
            continue

        draft_result = await _draft_reply({
            "body": message.get("body", ""),
            "subject": subject,
            "from": message.get("reply_to") or sender_header,
            "instruction": profile.get("instructions", ""),
            "tone": profile.get("tone", ""),
            "signature": profile.get("signature") or signatures.get(username, ""),
            "account": username,
        })
        if draft_result.get("error"):
            results.append({
                "account": username, "subject": subject,
                "action": "erreur", "reason": draft_result["error"],
            })
            continue
        draft = str(draft_result.get("draft") or "").strip()
        to = parseaddr(str(draft_result.get("to") or sender_header))[1]
        reply_subject = str(draft_result.get("subject") or f"Re: {subject}")
        if not to or len(draft) < 15:
            results.append({
                "account": username, "subject": subject,
                "action": "ignoré", "reason": "réponse ou destinataire invalide",
            })
            new_seen.add(key)
            continue
        references = " ".join(filter(None, [
            message.get("references"), message.get("message_id"),
        ])).strip()
        if dry_run:
            action = "envoi simulé" if mode in {"autonome", "differe"} else "brouillon simulé"
            results.append({"account": username, "to": to, "subject": reply_subject, "action": action})
            continue
        now = _clock()
        common = {
            "account": username, "to": to, "subject": reply_subject, "body": draft,
            "from": sender_header, "original_subject": subject, "uid": uid,
            "message_id": message.get("message_id", ""), "references": references,
            "created_at": now.isoformat(timespec="seconds"),
        }
        if mode == "autonome":
            send_result = await _send_email({
                "to": to, "subject": reply_subject, "body": draft, "account": username,
                "confirmed": True, "in_reply_to": message.get("message_id", ""),
                "references": references, "auto_submitted": True,
            })
            if send_result.get("success"):
                sent += 1
                new_seen.add(key)
                results.append({"account": username, "to": to, "subject": reply_subject, "action": "envoyé"})
            else:
                results.append({
                    "account": username, "to": to, "subject": reply_subject,
                    "action": "échec envoi", "reason": send_result.get("error"),
                })
        elif mode == "differe":
            pending_outbox.append({
                **common,
                "id": uuid.uuid4().hex,
                "send_after": (now + timedelta(minutes=profile["send_delay_min"])).isoformat(timespec="seconds"),
                "status": "pending",
            })
            new_seen.add(key)
            results.append({
                "account": username, "to": to, "subject": reply_subject,
                "action": "envoi différé", "delay_min": profile["send_delay_min"],
            })
        else:
            pending_drafts.append(common)
            new_seen.add(key)
            results.append({"account": username, "to": to, "subject": reply_subject, "action": "brouillon préparé"})

    if not dry_run:
        _set_setting("email_auto_seen", list(seen | new_seen)[-2_000:])
        if pending_drafts:
            existing = _json_value(_get_setting("email_pending_drafts") or [], list, [])
            _set_setting("email_pending_drafts", (existing + pending_drafts)[-200:])
        if pending_outbox:
            existing = _json_value(_get_setting("email_scheduled_outbox") or [], list, [])
            _set_setting("email_scheduled_outbox", (existing + pending_outbox)[-200:])
        history = _json_value(_get_setting("email_automation_runs") or [], list, [])
        history.append({
            "at": _clock().isoformat(timespec="seconds"),
            "source": str(args.get("source") or "manual")[:100],
            "dry_run": False,
            "processed": len(results),
            "sent": sent,
            "drafted": len(pending_drafts),
            "queued": len(pending_outbox),
            "errors": sum(item["action"] in {"erreur", "échec envoi"} for item in results),
        })
        _set_setting("email_automation_runs", history[-100:])
    return {
        "success": True,
        "dry_run": dry_run,
        "processed": len(results),
        "sent": sent,
        "drafted": len(pending_drafts),
        "queued": len(pending_outbox),
        "results": results[:100],
        "message": (
            "Simulation terminée sans aucune modification."
            if dry_run
            else (
                f"{sent} réponse(s) envoyée(s), {len(pending_drafts)} brouillon(s), "
                f"{len(pending_outbox)} envoi(s) différé(s)."
            )
        ),
    }


async def flush_outbox() -> dict[str, Any]:
    _require_dependencies()
    assert _get_setting and _set_setting and _send_email
    if _outbox_lock.locked():
        return {"success": True, "sent": 0, "message": "File d'envoi déjà en cours."}
    async with _outbox_lock:
        outbox = _json_value(_get_setting("email_scheduled_outbox") or [], list, [])
        now = _clock()
        kept: list[dict[str, Any]] = []
        sent = failed = 0
        for raw_item in outbox[:200]:
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            if item.get("status", "pending") != "pending":
                kept.append(item)
                continue
            try:
                due = datetime.fromisoformat(str(item.get("send_after") or "")) <= now
            except (TypeError, ValueError):
                due = False
            if not due:
                kept.append(item)
                continue
            result = await _send_email({
                "to": item.get("to", ""),
                "subject": item.get("subject", ""),
                "body": item.get("body", ""),
                "account": item.get("account"),
                "confirmed": True,
                "in_reply_to": item.get("message_id", ""),
                "references": item.get("references", ""),
                "auto_submitted": True,
            })
            if result.get("success"):
                sent += 1
            else:
                failed += 1
                kept.append({
                    **item,
                    "last_error": str(result.get("error") or "Envoi impossible")[:1_000],
                    "last_attempt_at": now.isoformat(timespec="seconds"),
                    "send_after": (now + timedelta(minutes=5)).isoformat(timespec="seconds"),
                })
        _set_setting("email_scheduled_outbox", kept[-200:])
        return {"success": failed == 0, "sent": sent, "failed": failed, "pending": len(kept)}
