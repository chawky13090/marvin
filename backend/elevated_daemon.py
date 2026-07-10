"""
elevated_daemon.py — Démon élevé de Marvin (pattern sidecar / séparation de privilèges).

RÔLE : seul ce petit process tourne en ADMINISTRATEUR. Le backend principal (FastAPI,
agent, les 282 outils) peut tourner en utilisateur NORMAL et lui déléguer, via ce canal
IPC local authentifié, les quelques actions qui exigent réellement des droits élevés.

Volontairement MINIMAL et AUDITABLE : ce fichier n'importe PAS tools.py (282 outils,
dépendances lourdes) — juste `security.py` (garde anti-catastrophe) et `audit.py`
(journal). Moins de code élevé = moins de surface d'attaque. N'accepte qu'une ALLOWLIST
stricte d'actions ; toute commande passe par `security.screen_command()` AVANT exécution,
même ici, même en admin — défense en profondeur.

Lancement : `python elevated_daemon.py` DOIT s'exécuter avec élévation (UAC). Le script
refuse de démarrer sinon. Voir `launch_elevated_daemon.ps1` pour un lancement guidé.
"""
import ctypes
import json
import os
import subprocess
import sys
import time

import elevated_protocol as proto
import security

_ALLOWED_ACTIONS = {"run_command", "run_powershell", "ping"}


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _run_command(command: str, timeout: int) -> dict:
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    r = subprocess.run(command, shell=True, capture_output=True, text=True,
                       timeout=timeout, encoding="utf-8", errors="replace", creationflags=flags)
    return {"success": r.returncode == 0, "returncode": r.returncode,
            "stdout": r.stdout.strip() or "(aucune sortie)", "stderr": (r.stderr or "").strip()}


def _run_powershell(script: str, timeout: int) -> dict:
    import base64
    script = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
              "$OutputEncoding=[System.Text.Encoding]::UTF8;" + script)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    ps_candidates = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Windows\SysWow64\WindowsPowerShell\v1.0\powershell.exe",
        "powershell.exe",
    ]
    ps_exe = next((p for p in ps_candidates if "\\" in p and os.path.exists(p)), "powershell.exe")
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    r = subprocess.run([ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-EncodedCommand", encoded],
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace", creationflags=flags)
    stderr = r.stderr.strip()
    if stderr.startswith("#< CLIXML"):
        stderr = ""
    return {"success": r.returncode == 0, "returncode": r.returncode,
            "stdout": r.stdout.strip() or "(aucune sortie)", "stderr": stderr}


def _handle_request(req: dict, token: str) -> dict:
    if req.get("token") != token:
        return {"error": "Jeton invalide.", "auth_failed": True}
    action = req.get("action")
    if action == "ping":
        return {"success": True, "pong": True, "admin": True, "pid": os.getpid()}
    if action not in _ALLOWED_ACTIONS:
        return {"error": f"Action non autorisée : {action!r}."}

    payload = req.get("command") if action == "run_command" else req.get("script")
    if not payload:
        return {"error": "Paramètre de commande manquant."}

    # 🛡️ Défense en profondeur : la garde s'applique aussi DANS le démon élevé —
    # un contexte admin est justement celui où une commande catastrophique ferait
    # le plus de dégâts, donc c'est ICI qu'elle doit être vérifiée en dernier ressort.
    blocked = security.guard_result(payload)
    if blocked:
        try:
            import audit
            audit.log_action(f"elevated:{action}", {"command": payload[:200]}, blocked, source="elevated")
        except Exception:
            pass
        return blocked

    timeout = max(5, min(int(req.get("timeout", 30)), 300))
    try:
        result = _run_command(payload, timeout) if action == "run_command" else _run_powershell(payload, timeout)
    except subprocess.TimeoutExpired:
        result = {"error": f"Délai dépassé ({timeout}s)."}
    except Exception as e:
        result = {"error": str(e)[:300]}

    try:
        import audit
        audit.log_action(f"elevated:{action}", {"command": payload[:200]}, result, source="elevated")
    except Exception:
        pass
    return result


def _serve_one_connection(pipe_handle, token: str):
    import win32file
    import pywintypes

    def _read(n):
        _hr, data = win32file.ReadFile(pipe_handle, n)
        return data

    try:
        length = proto.decode_length(proto.read_exact(_read, 4))
        body = proto.read_exact(_read, length)
        req = json.loads(body.decode("utf-8"))
    except Exception as e:
        resp = {"error": f"Requête IPC malformée : {str(e)[:150]}"}
    else:
        resp = _handle_request(req, token)

    try:
        win32file.WriteFile(pipe_handle, proto.encode_message(resp))
    except pywintypes.error:
        pass  # le client a peut-être déjà fermé sa connexion


def main():
    if not _is_admin():
        print("[elevated_daemon] ERREUR : ce process doit être lancé EN ADMINISTRATEUR. Arrêt.",
              file=sys.stderr)
        sys.exit(1)

    import win32pipe
    import win32file
    import pywintypes

    token = proto.generate_token()
    proto.save_token(token)
    print(f"[elevated_daemon] Démarré — PID={os.getpid()} — admin=True — pipe={proto.PIPE_NAME}")
    print("[elevated_daemon] Jeton généré, en attente de connexions… (Ctrl+C pour arrêter)")

    try:
        while True:
            sa = proto.build_pipe_security_attributes()
            handle = win32pipe.CreateNamedPipe(
                proto.PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                4,          # instances max
                65536, 65536,
                5000,       # timeout par défaut (ms)
                sa,
            )
            try:
                win32pipe.ConnectNamedPipe(handle, None)
                _serve_one_connection(handle, token)
            except pywintypes.error as e:
                print(f"[elevated_daemon] Erreur de connexion : {e}", file=sys.stderr)
            finally:
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass
    except KeyboardInterrupt:
        print("\n[elevated_daemon] Arrêt demandé (Ctrl+C).")
    finally:
        proto.clear_token()
        print("[elevated_daemon] Jeton révoqué. Arrêté proprement.")


if __name__ == "__main__":
    main()
