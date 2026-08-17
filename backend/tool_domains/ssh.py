"""Domaine des outils SSH : cibles, commandes, scripts et transferts SFTP."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import database as db
import security
import ssh_transport
from platform_paths import PATHS, expand_user_path


PathResolver = Callable[[str], str]
SizeFormatter = Callable[[int], str]
_resolve_path: PathResolver = expand_user_path
def _default_format_size(size: int) -> str:
    value = float(size)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} Po"


_format_size: SizeFormatter = _default_format_size
_home = str(PATHS["home"])


def configure(
    *, resolve_path: PathResolver, format_size: SizeFormatter, home: str
) -> None:
    global _resolve_path, _format_size, _home
    _resolve_path = resolve_path
    _format_size = format_size
    _home = home


def resolve_target(args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    connection_id = str(args.get("connection_id") or "").strip()
    if connection_id:
        connection = db.get_ssh_connection(connection_id)
        if not connection:
            return None, (
                f"Connexion SSH '{connection_id}' introuvable. "
                "Utilise ssh_list pour voir les connexions disponibles."
            )
        return dict(connection), None

    host = str(args.get("host") or "").strip()
    username = str(args.get("username") or "").strip()
    if not host:
        return None, (
            "Fournis 'connection_id' (voir ssh_list) ou l'hôte d'une connexion déjà "
            "enregistrée dans l'onglet SSH."
        )
    try:
        port = int(args.get("port") or 22)
    except (TypeError, ValueError):
        return None, "Port SSH invalide."
    if not 1 <= port <= 65535:
        return None, "Port SSH invalide."
    if args.get("password") or args.get("private_key") or args.get("key_passphrase"):
        return None, (
            "Un secret SSH ne doit pas transiter dans le chat. Enregistre cette cible et "
            "saisis toi-même le secret dans l'onglet SSH; Marvin pourra ensuite la piloter "
            "depuis le chat par son connection_id."
        )
    saved = db.find_ssh_connection(host, username, port)
    if saved:
        return saved, None
    return None, (
        "Aucune connexion SSH enregistrée ne correspond à cette cible. Ouvre l'onglet SSH, "
        "ajoute la connexion et son secret dans le formulaire protégé, puis relance la demande."
    )


def _target_error(error: str) -> dict[str, Any]:
    result: dict[str, Any] = {"error": error}
    if "onglet SSH" in error:
        result.update({
            "credentials_ui_required": True,
            "configuration_path": "/ssh",
            "configuration_action": "Configurer la connexion SSH",
        })
    return result


async def list_connections(args: dict[str, Any]) -> dict[str, Any]:
    try:
        safe = [
            {
                "id": connection["id"],
                "name": connection["name"],
                "host": connection["host"],
                "port": connection["port"],
                "username": connection["username"],
                "has_password": bool(connection.get("password")),
                "has_key": bool(str(connection.get("private_key", "")).strip()),
                "last_used": connection.get("last_used"),
            }
            for connection in db.list_ssh_connections()
        ]
        return {"success": True, "count": len(safe), "connections": safe}
    except Exception as exc:
        return {"error": str(exc)}


async def save_connection(args: dict[str, Any]) -> dict[str, Any]:
    name = str(args.get("name") or args.get("host") or "").strip()
    host = str(args.get("host") or "").strip()
    username = str(args.get("username") or "").strip()
    try:
        port = max(1, min(int(args.get("port") or 22), 65535))
    except (TypeError, ValueError):
        return {"error": "Port SSH invalide."}
    if not name or not host or not username:
        return {"error": "Les paramètres name, host et username sont requis."}
    if args.get("password") or args.get("private_key") or args.get("key_passphrase"):
        return {
            "error": "Les secrets SSH ne sont jamais enregistrés par le chat. Ajoute le mot de passe ou la clé toi-même dans l'onglet SSH.",
            "credentials_ui_required": True,
        }
    try:
        saved = db.save_ssh_connection(name, host, port, username)
        return {
            "success": True,
            "connection": saved,
            "message": "Cible SSH enregistrée sans secret. Complète l'authentification dans l'onglet SSH si nécessaire.",
        }
    except Exception as exc:
        return {"error": str(exc)}


def _read_command(client, command: str, timeout: int) -> dict[str, Any]:
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    return {"stdout": output, "stderr": error, "exit_code": exit_code}


async def execute(args: dict[str, Any]) -> dict[str, Any]:
    command = str(args.get("command") or "").strip()
    try:
        timeout = max(5, min(int(args.get("timeout", 30)), 120))
    except (TypeError, ValueError):
        return {"error": "Timeout SSH invalide."}
    if not command:
        return {"error": "Paramètre 'command' requis."}
    blocked = security.guard_result(command)
    if blocked:
        return blocked
    connection_id = str(args.get("connection_id") or "").strip()
    connection, error = resolve_target(args)
    if error:
        return _target_error(error)
    assert connection is not None
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Exécuter sur {connection['username']}@{connection['host']} : {command} ?",
        }

    def run():
        client = ssh_transport.connect(connection, timeout)
        try:
            return _read_command(client, command, timeout)
        finally:
            client.close()

    try:
        result = await asyncio.get_running_loop().run_in_executor(None, run)
        if connection_id:
            db.touch_ssh_connection(connection_id)
        result.update({
            "success": result["exit_code"] == 0,
            "command": command,
            "host": f"{connection['username']}@{connection['host']}",
        })
        if not connection_id and result["exit_code"] == 0:
            result["suggest_save_connection"] = {
                "host": connection["host"],
                "port": connection["port"],
                "username": connection["username"],
                "message": f"Connexion à {connection['username']}@{connection['host']} réussie — veux-tu que je l'enregistre pour la réutiliser sans retaper les identifiants ?",
            }
        return result
    except Exception as exc:
        message = str(exc)
        lowered = message.casefold()
        timed_out = "timed out" in lowered or "timeout" in lowered
        return {
            "success": False,
            "error": "Délai de connexion SSH dépassé." if timed_out else message,
            "error_type": "ssh_timeout" if timed_out else type(exc).__name__,
            "diagnosis": "indeterminate",
            "firewall_confirmed": False,
            "possible_causes": (
                ["service SSH arrêté", "port filtré", "route absente", "hôte indisponible"]
                if timed_out else []
            ),
            "command": command,
        }


async def execute_multi(args: dict[str, Any]) -> dict[str, Any]:
    connection_ids = args.get("connection_ids") or []
    command = str(args.get("command") or "").strip()
    try:
        timeout = max(5, min(int(args.get("timeout", 30)), 120))
    except (TypeError, ValueError):
        return {"error": "Timeout SSH invalide."}
    if not isinstance(connection_ids, list) or not connection_ids:
        return {"error": "Paramètre 'connection_ids' (liste) requis."}
    if not command:
        return {"error": "Paramètre 'command' requis."}
    blocked = security.guard_result(command)
    if blocked:
        return blocked
    connections = [(item, db.get_ssh_connection(item)) for item in connection_ids]
    missing = [item for item, connection in connections if not connection]
    if missing:
        return {"error": f"Connexions introuvables : {missing}"}
    if not args.get("confirmed"):
        hosts = ", ".join(
            f"{connection['username']}@{connection['host']}"
            for _, connection in connections
        )
        return {"requiresConfirmation": True, "message": f"Exécuter « {command} » sur : {hosts} ?"}

    def run_one(connection):
        try:
            client = ssh_transport.connect(connection, timeout)
            try:
                result = _read_command(client, command, timeout)
            finally:
                client.close()
            result["success"] = result["exit_code"] == 0
            return result
        except Exception as exc:
            return {"error": str(exc), "success": False}

    loop = asyncio.get_running_loop()
    results = await asyncio.gather(*[
        loop.run_in_executor(None, run_one, connection)
        for _, connection in connections
    ])
    output = []
    for (connection_id, connection), result in zip(connections, results):
        db.touch_ssh_connection(connection_id)
        output.append({
            "connection_id": connection_id,
            "host": f"{connection['username']}@{connection['host']}",
            **result,
        })
    succeeded = sum(1 for result in output if result.get("success"))
    return {
        "success": True,
        "command": command,
        "total": len(output),
        "succeeded": succeeded,
        "failed": len(output) - succeeded,
        "results": output,
    }


async def write_and_run(args: dict[str, Any]) -> dict[str, Any]:
    content = str(args.get("content") or "")
    remote_path = str(args.get("remote_path") or "").strip()
    if not content.strip():
        return {"error": "Paramètre 'content' requis (le script à écrire)."}
    if not remote_path:
        return {"error": "Paramètre 'remote_path' requis (ex. /tmp/install.sh)."}
    blocked = security.guard_result(content)
    if blocked:
        return blocked
    connection, error = resolve_target(args)
    if error:
        return _target_error(error)
    assert connection is not None
    connection_id = str(args.get("connection_id") or "").strip()
    run_command = str(args.get("run_command") or "").strip() or (
        f"chmod +x {remote_path} && {remote_path}"
    )
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Écrire « {remote_path} » ({len(content)} car.) sur {connection['username']}@{connection['host']} puis exécuter « {run_command} » ?",
        }

    def run():
        client = ssh_transport.connect(connection, 60)
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, "w") as remote_file:
                    remote_file.write(content)
            finally:
                sftp.close()
            timeout = max(5, min(int(args.get("timeout", 120)), 600))
            return _read_command(client, run_command, timeout)
        finally:
            client.close()

    try:
        result = await asyncio.get_running_loop().run_in_executor(None, run)
        if connection_id:
            db.touch_ssh_connection(connection_id)
        result.update({
            "success": result["exit_code"] == 0,
            "remote_path": remote_path,
            "run_command": run_command,
            "host": f"{connection['username']}@{connection['host']}",
        })
        if not connection_id and result["exit_code"] == 0:
            result["suggest_save_connection"] = {
                "host": connection["host"],
                "port": connection["port"],
                "username": connection["username"],
                "message": f"Connexion à {connection['username']}@{connection['host']} réussie — veux-tu que je l'enregistre pour la réutiliser ?",
            }
        return result
    except Exception as exc:
        return {"error": str(exc), "remote_path": remote_path}


async def upload(args: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(args.get("connection_id") or "").strip()
    local_path = _resolve_path(str(args.get("local_path") or ""))
    remote_path = str(args.get("remote_path") or "").strip()
    connection = db.get_ssh_connection(connection_id)
    if not connection:
        return {"error": "Connexion SSH introuvable."}
    if not os.path.isfile(local_path):
        return {"error": f"Fichier local introuvable : {local_path}"}
    if not remote_path:
        return {"error": "Paramètre 'remote_path' requis."}
    if not args.get("confirmed"):
        return {
            "requiresConfirmation": True,
            "message": f"Envoyer {os.path.basename(local_path)} → {connection['username']}@{connection['host']}:{remote_path} ?",
        }

    def run():
        client = ssh_transport.connect(connection, 60)
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(local_path, remote_path)
                return sftp.stat(remote_path).st_size
            finally:
                sftp.close()
        finally:
            client.close()

    try:
        size = await asyncio.get_running_loop().run_in_executor(None, run)
        db.touch_ssh_connection(connection_id)
        return {
            "success": True,
            "message": f"Envoyé : {remote_path} ({size} octets)",
            "remote_path": remote_path,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def download(args: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(args.get("connection_id") or "").strip()
    remote_path = str(args.get("remote_path") or "").strip()
    local_path = (
        _resolve_path(str(args["local_path"]))
        if args.get("local_path")
        else str(Path(_home) / "Downloads" / os.path.basename(remote_path or "download"))
    )
    connection = db.get_ssh_connection(connection_id)
    if not connection:
        return {"error": "Connexion SSH introuvable."}
    if not remote_path:
        return {"error": "Paramètre 'remote_path' requis."}

    def run():
        client = ssh_transport.connect(connection, 60)
        try:
            sftp = client.open_sftp()
            try:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                sftp.get(remote_path, local_path)
            finally:
                sftp.close()
        finally:
            client.close()
        return os.path.getsize(local_path)

    try:
        size = await asyncio.get_running_loop().run_in_executor(None, run)
        db.touch_ssh_connection(connection_id)
        return {
            "success": True,
            "message": f"Téléchargé : {local_path} ({size} octets)",
            "path": local_path,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def list_dir(args: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(args.get("connection_id") or "").strip()
    remote_path = str(args.get("remote_path") or ".").strip()
    connection = db.get_ssh_connection(connection_id)
    if not connection:
        return {"error": "Connexion SSH introuvable."}

    def run():
        client = ssh_transport.connect(connection, 30)
        try:
            sftp = client.open_sftp()
            try:
                entries = []
                for attribute in sftp.listdir_attr(remote_path):
                    is_directory = stat.S_ISDIR(attribute.st_mode)
                    entries.append({
                        "name": attribute.filename,
                        "is_dir": is_directory,
                        "size": attribute.st_size,
                        "size_human": "" if is_directory else _format_size(attribute.st_size),
                        "path": remote_path.rstrip("/") + "/" + attribute.filename,
                    })
            finally:
                sftp.close()
        finally:
            client.close()
        entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
        return entries

    try:
        entries = await asyncio.get_running_loop().run_in_executor(None, run)
        return {
            "success": True,
            "remote_path": remote_path,
            "count": len(entries),
            "entries": entries,
        }
    except Exception as exc:
        return {"error": str(exc)}


async def server_info(args: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(args.get("connection_id") or "").strip()
    connection = db.get_ssh_connection(connection_id)
    if not connection:
        return {"error": "Connexion SSH introuvable."}
    command = (
        "echo '###OS'; (cat /etc/os-release 2>/dev/null | grep PRETTY_NAME || uname -a); "
        "echo '###UP'; uptime; echo '###MEM'; free -h 2>/dev/null || vm_stat; "
        "echo '###DISK'; df -h / 2>/dev/null; echo '###LOAD'; cat /proc/loadavg 2>/dev/null; "
        "echo '###WHO'; who 2>/dev/null | head -5"
    )

    def run():
        client = ssh_transport.connect(connection, 30)
        try:
            _, stdout, _ = client.exec_command(command, timeout=30)
            return stdout.read().decode(errors="replace")
        finally:
            client.close()

    try:
        output = await asyncio.get_running_loop().run_in_executor(None, run)
        db.touch_ssh_connection(connection_id)
        sections: dict[str, list[str]] = {}
        current = None
        for line in output.splitlines():
            if line.startswith("###"):
                current = line[3:].lower()
                sections[current] = []
            elif current:
                sections[current].append(line)
        return {
            "success": True,
            "host": f"{connection['username']}@{connection['host']}",
            "info": {key: "\n".join(value).strip() for key, value in sections.items()},
            "raw": output,
        }
    except Exception as exc:
        return {"error": str(exc)}
