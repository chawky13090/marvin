"""
elevated_client.py — Client du démon élevé, utilisé par le backend principal (non-admin).

Se connecte au Named Pipe local exposé par `elevated_daemon.py`, s'authentifie avec le
jeton partagé (lu dans data/elevated_token.json, régénéré à chaque démarrage du démon),
et transmet une action de l'ALLOWLIST. Échoue proprement (message clair) si le démon
n'est pas lancé — jamais d'exception qui remonterait crue à l'utilisateur.
"""
import asyncio
import json

import elevated_protocol as proto

_NOT_RUNNING = (
    "Le démon élevé de Marvin n'est pas lancé. Cette action nécessite des droits "
    "administrateur. Lance `backend/launch_elevated_daemon.ps1` (une seule fenêtre "
    "UAC à accepter), puis réessaie."
)


def is_daemon_available() -> bool:
    """Vérification rapide et non bloquante (best-effort) : le fichier jeton existe-t-il ?
    (Ne prouve pas que le pipe répond, mais évite une tentative de connexion coûteuse
    quand le démon n'a manifestement jamais été lancé.)"""
    return proto.load_token() is not None


def _call_sync(action: str, timeout: int, **params) -> dict:
    import win32file
    import pywintypes

    token = proto.load_token()
    if not token:
        return {"error": _NOT_RUNNING, "daemon_unavailable": True}

    try:
        handle = win32file.CreateFile(
            proto.PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None, win32file.OPEN_EXISTING, 0, None,
        )
    except pywintypes.error as e:
        if e.winerror == 2:      # ERROR_FILE_NOT_FOUND — le démon n'écoute pas
            return {"error": _NOT_RUNNING, "daemon_unavailable": True}
        return {"error": f"Connexion au démon élevé impossible : {e.strerror}"}

    try:
        req = {"action": action, "token": token, "timeout": timeout, **params}
        win32file.WriteFile(handle, proto.encode_message(req))

        def _read(n):
            _hr, data = win32file.ReadFile(handle, n)
            return data

        length = proto.decode_length(proto.read_exact(_read, 4))
        body = proto.read_exact(_read, length)
        return json.loads(body.decode("utf-8"))
    except Exception as e:
        return {"error": f"Erreur de communication avec le démon élevé : {str(e)[:200]}"}
    finally:
        try:
            win32file.CloseHandle(handle)
        except Exception:
            pass


async def call_elevated(action: str, timeout: int = 30, **params) -> dict:
    """Appelle une action élevée en arrière-plan (l'I/O pipe est bloquante côté OS)."""
    return await asyncio.to_thread(_call_sync, action, timeout, **params)


async def ping() -> dict:
    return await call_elevated("ping", timeout=5)
