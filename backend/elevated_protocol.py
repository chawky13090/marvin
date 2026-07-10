"""
elevated_protocol.py — Protocole IPC partagé entre le backend Marvin (non-admin) et le
démon élevé (backend/elevated_daemon.py, admin). Named Pipe local Windows + jeton partagé.

Piège Windows connu (Mandatory Integrity Control) : un named pipe créé par un process
ÉLEVÉ (High integrity) hérite par défaut d'une étiquette High + « No-Write-Up » → un
process NON élevé (Medium integrity, cas normal) ne peut PAS y écrire, même si le DACL
l'autorise. `build_pipe_security_attributes()` fixe explicitement l'étiquette du pipe à
Medium pour que le backend (Medium) et le démon (High) puissent communiquer, tout en
restreignant le DACL au seul compte de l'utilisateur courant (aucun autre utilisateur/
process du système ne peut se connecter).

Format des messages : préfixe de longueur (4 octets big-endian) + JSON UTF-8. Simple et
robuste, indépendant du mode octet/message du pipe.
"""
import json
import os
import struct

PIPE_NAME = r"\\.\pipe\MarvinElevatedV1"
_TOKEN_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "elevated_token.json")
_MAX_MSG = 8 * 1024 * 1024   # 8 Mo — garde-fou anti-DoS sur la taille d'un message


def build_pipe_security_attributes():
    """SECURITY_ATTRIBUTES pour CreateNamedPipe : DACL = utilisateur courant uniquement
    (lecture/écriture) ; SACL = étiquette d'intégrité MEDIUM explicite (sinon un pipe créé
    par un process élevé bloque l'écriture depuis un process non élevé — cf. docstring)."""
    import win32api
    import win32security

    user = win32api.GetUserName()
    user_sid, _domain, _typ = win32security.LookupAccountName(None, user)
    sid_str = win32security.ConvertSidToStringSid(user_sid)

    # D: DACL — l'utilisateur courant a un contrôle total du pipe (GA). Personne d'autre.
    # S: SACL — étiquette obligatoire Medium (ME), sans restriction write-up : un process
    #    Medium (le backend, non élevé) peut donc écrire vers ce pipe créé par un process High.
    sddl = f"D:(A;;GA;;;{sid_str})S:(ML;;;;;ME)"
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, win32security.SDDL_REVISION_1)

    import pywintypes
    sa = pywintypes.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    sa.bInheritHandle = False
    return sa


def generate_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def save_token(token: str):
    os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
    with open(_TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"token": token}, f)


def load_token() -> str | None:
    try:
        with open(_TOKEN_PATH, encoding="utf-8") as f:
            return json.load(f).get("token")
    except Exception:
        return None


def clear_token():
    try:
        os.remove(_TOKEN_PATH)
    except Exception:
        pass


def encode_message(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(body)) + body


def read_exact(read_fn, n: int) -> bytes:
    """Lit exactement n octets via read_fn(size)->bytes (ex. win32file.ReadFile wrapper)."""
    buf = b""
    while len(buf) < n:
        chunk = read_fn(n - len(buf))
        if not chunk:
            raise ConnectionError("Connexion IPC fermée prématurément.")
        buf += chunk
    return buf


def decode_length(prefix: bytes) -> int:
    n = struct.unpack(">I", prefix)[0]
    if n > _MAX_MSG:
        raise ValueError(f"Message IPC trop volumineux ({n} octets).")
    return n
