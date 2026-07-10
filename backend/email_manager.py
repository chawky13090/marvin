"""
email_manager.py — Lecture (IMAP) et envoi (SMTP) d'emails.
Pas de dépendances externes : imaplib + smtplib + email (stdlib).
"""
import imaplib
import smtplib
import email
import email.header
import email.utils
import email.mime.text
import email.mime.multipart
import ssl
import asyncio
import html
import re
from datetime import datetime
from typing import Optional

# ── Presets fournisseurs populaires ─────────────────────────────────────────

PROVIDERS = {
    "gmail": {
        "name": "Gmail",
        "imap_host": "imap.gmail.com", "imap_port": 993,
        "smtp_host": "smtp.gmail.com", "smtp_port": 587,
        "note": "Utilisez un mot de passe d'application Google (pas votre vrai mot de passe).",
    },
    "outlook": {
        "name": "Outlook / Hotmail",
        "imap_host": "outlook.office365.com", "imap_port": 993,
        "smtp_host": "smtp.office365.com",    "smtp_port": 587,
        "note": "Activez IMAP dans les paramètres Outlook.",
    },
    "yahoo": {
        "name": "Yahoo Mail",
        "imap_host": "imap.mail.yahoo.com", "imap_port": 993,
        "smtp_host": "smtp.mail.yahoo.com",  "smtp_port": 587,
        "note": "Créez un mot de passe d'application dans la sécurité Yahoo.",
    },
    "orange": {
        "name": "Orange / Wanadoo",
        "imap_host": "imap.orange.fr", "imap_port": 993,
        "smtp_host": "smtp.orange.fr",  "smtp_port": 465,
        "note": "",
    },
    "sfr": {
        "name": "SFR",
        "imap_host": "imap.sfr.fr", "imap_port": 993,
        "smtp_host": "smtp.sfr.fr",  "smtp_port": 587,
        "note": "",
    },
    "custom": {
        "name": "Personnalisé",
        "imap_host": "", "imap_port": 993,
        "smtp_host": "", "smtp_port": 587,
        "note": "Entrez manuellement les serveurs IMAP et SMTP.",
    },
}


# ── Helpers décodage ─────────────────────────────────────────────────────────

def _decode_header(raw: str) -> str:
    """Décode les en-têtes email encodés (RFC 2047)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                out.append(part.decode(charset or "utf-8", errors="replace"))
            except Exception:
                out.append(part.decode("latin-1", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def _html_to_text(html_content: str) -> str:
    """Conversion HTML → texte brut simplifiée."""
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _get_body(msg) -> tuple[str, str]:
    """Extrait le corps text/plain et text/html d'un message."""
    plain, html_body = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                continue
            charset = part.get_content_charset() or "utf-8"
            if ct == "text/plain" and not plain:
                try:
                    plain = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    plain = ""
            elif ct == "text/html" and not html_body:
                try:
                    html_body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    html_body = ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            payload = ""
        if msg.get_content_type() == "text/html":
            html_body = payload
        else:
            plain = payload

    # Si pas de plain, convertir l'HTML
    if not plain and html_body:
        plain = _html_to_text(html_body)

    return plain, html_body


def _get_attachments(msg) -> list[dict]:
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                fname = _decode_header(part.get_filename() or "")
                size = len(part.get_payload(decode=True) or b"")
                attachments.append({"name": fname, "size": size, "content_type": part.get_content_type()})
    return attachments


# ── Connexion IMAP ───────────────────────────────────────────────────────────

def _imap_connect(imap_host: str, imap_port: int, username: str, password: str):
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=ctx)
    conn.login(username, password)
    return conn


def fetch_inbox(imap_host: str, imap_port: int, username: str, password: str,
                folder: str = "INBOX", limit: int = 30, offset: int = 0) -> list[dict]:
    """Lit les N derniers emails d'une boîte IMAP."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder, readonly=True)
        _, data = conn.search(None, "ALL")
        ids = data[0].split()
        # Plus récents en premier
        ids = list(reversed(ids))
        page = ids[offset: offset + limit]

        emails = []
        for uid in page:
            try:
                _, raw = conn.fetch(uid, "(RFC822.HEADER FLAGS)")
                msg = email.message_from_bytes(raw[0][1])
                flags = str(raw[0][0])
                emails.append({
                    "id": uid.decode(),
                    "subject": _decode_header(msg.get("Subject", "(Sans objet)")),
                    "from": _decode_header(msg.get("From", "")),
                    "to": _decode_header(msg.get("To", "")),
                    "date": _decode_header(msg.get("Date", "")),
                    "read": "\\Seen" in flags,
                    "preview": "",
                })
            except Exception:
                continue
        return emails
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_attachment(imap_host: str, imap_port: int, username: str, password: str,
                     uid: str, name: str = "", folder: str = "INBOX") -> dict | None:
    """Récupère le contenu binaire d'une pièce jointe d'un email (par nom, ou la 1ère)."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder, readonly=True)  # lecture seule : ne modifie pas l'état "lu"
        _, raw = conn.fetch(uid.encode(), "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        if msg.is_multipart():
            for part in msg.walk():
                cd = str(part.get("Content-Disposition", ""))
                if "attachment" in cd:
                    fname = _decode_header(part.get_filename() or "")
                    if not name or fname == name:
                        data = part.get_payload(decode=True) or b""
                        return {"name": fname or "piece_jointe", "content_type": part.get_content_type(),
                                "data": data, "size": len(data)}
        return None
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_email(imap_host: str, imap_port: int, username: str, password: str,
                uid: str, folder: str = "INBOX") -> dict:
    """Lit le contenu complet d'un email par son UID."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder, readonly=False)
        # Marquer comme lu
        conn.store(uid.encode(), "+FLAGS", "\\Seen")
        _, raw = conn.fetch(uid.encode(), "(RFC822)")
        msg = email.message_from_bytes(raw[0][1])
        plain, html_body = _get_body(msg)
        return {
            "id": uid,
            "subject": _decode_header(msg.get("Subject", "(Sans objet)")),
            "from": _decode_header(msg.get("From", "")),
            "to": _decode_header(msg.get("To", "")),
            "cc": _decode_header(msg.get("Cc", "")),
            "date": _decode_header(msg.get("Date", "")),
            "body": plain,
            "html": html_body,
            "attachments": _get_attachments(msg),
            "read": True,
        }
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def search_emails(imap_host: str, imap_port: int, username: str, password: str,
                  query: str, folder: str = "INBOX", limit: int = 20) -> list[dict]:
    """Recherche dans les emails IMAP (SUBJECT + FROM)."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder, readonly=True)
        # Recherche SUBJECT
        _, data1 = conn.search(None, f'SUBJECT "{query}"')
        _, data2 = conn.search(None, f'FROM "{query}"')
        ids = list(set((data1[0] or b"").split() + (data2[0] or b"").split()))
        ids = list(reversed(ids))[:limit]

        results = []
        for uid in ids:
            try:
                _, raw = conn.fetch(uid, "(RFC822.HEADER)")
                msg = email.message_from_bytes(raw[0][1])
                results.append({
                    "id": uid.decode(),
                    "subject": _decode_header(msg.get("Subject", "")),
                    "from": _decode_header(msg.get("From", "")),
                    "date": _decode_header(msg.get("Date", "")),
                    "read": True,
                    "preview": "",
                })
            except Exception:
                continue
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def list_folders(imap_host: str, imap_port: int, username: str, password: str) -> list[str]:
    """Liste les dossiers IMAP disponibles."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        _, folders = conn.list()
        result = []
        for f in folders:
            parts = f.decode().split('"')
            name = parts[-1].strip() if parts else ""
            if name:
                result.append(name)
        return result
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def delete_email(imap_host: str, imap_port: int, username: str, password: str,
                 uid: str, folder: str = "INBOX"):
    """Déplace un email vers la corbeille (ou le supprime)."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder)
        conn.store(uid.encode(), "+FLAGS", "\\Deleted")
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def mark_email(imap_host: str, imap_port: int, username: str, password: str,
               uid: str, folder: str = "INBOX", seen: bool = True):
    """Marque un email comme lu (seen=True) ou NON lu (seen=False)."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder)
        conn.store(uid.encode(), "+FLAGS" if seen else "-FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def move_email(imap_host: str, imap_port: int, username: str, password: str,
               uid: str, dest_folder: str, folder: str = "INBOX"):
    """Déplace un email vers un autre dossier (copie puis suppression de l'original)."""
    conn = _imap_connect(imap_host, imap_port, username, password)
    try:
        conn.select(folder)
        typ, _ = conn.copy(uid.encode(), dest_folder)
        if typ != "OK":
            raise RuntimeError(f"Copie vers « {dest_folder} » impossible")
        conn.store(uid.encode(), "+FLAGS", "\\Deleted")
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ── Envoi SMTP ───────────────────────────────────────────────────────────────

def send_email(smtp_host: str, smtp_port: int, username: str, password: str,
               to: str, subject: str, body: str,
               cc: str = "", reply_to: str = "",
               html_body: str = "") -> dict:
    """Envoie un email via SMTP (STARTTLS)."""
    msg = email.mime.multipart.MIMEMultipart("alternative")
    msg["From"] = username
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if reply_to:
        msg["Reply-To"] = reply_to

    msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))

    recipients = [to] + ([cc] if cc else [])

    # Port 465 = SSL direct, autre = STARTTLS
    if smtp_port == 465:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
            server.login(username, password)
            server.sendmail(username, recipients, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.login(username, password)
            server.sendmail(username, recipients, msg.as_string())

    return {"success": True, "to": to, "subject": subject}


def test_connection(imap_host: str, imap_port: int, smtp_host: str, smtp_port: int,
                    username: str, password: str) -> dict:
    """Teste IMAP et SMTP sans envoyer ni lire."""
    errors = []

    # Test IMAP
    try:
        conn = _imap_connect(imap_host, imap_port, username, password)
        conn.logout()
        imap_ok = True
    except Exception as e:
        imap_ok = False
        errors.append(f"IMAP: {e}")

    # Test SMTP
    try:
        if smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=8) as s:
                s.login(username, password)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=8) as s:
                s.ehlo()
                s.starttls(context=ssl.create_default_context())
                s.login(username, password)
        smtp_ok = True
    except Exception as e:
        smtp_ok = False
        errors.append(f"SMTP: {e}")

    return {
        "imap_ok": imap_ok,
        "smtp_ok": smtp_ok,
        "success": imap_ok and smtp_ok,
        "errors": errors,
    }
