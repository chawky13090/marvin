"""API SSH : connexions, commandes, terminal interactif et transferts SFTP."""

import asyncio
import io
import json

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

import database as db
import security
import tools as tool_module

router = APIRouter()


class SSHConnectionCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""
    private_key: str = ""
    key_passphrase: str = ""
    connection_id: str = ""


class SSHConnectionUpdate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    password: str = ""
    private_key: str = ""
    key_passphrase: str = ""


class SSHCommandRequest(BaseModel):
    connection_id: str
    command: str
    timeout: int = 30


@router.get("/api/ssh")
async def list_ssh():
    return db.list_ssh_connections()


@router.post("/api/ssh")
async def create_ssh(body: SSHConnectionCreate):
    return db.save_ssh_connection(body.name, body.host, body.port, body.username,
                                  body.password, body.private_key, body.key_passphrase)


@router.put("/api/ssh/{sid}")
async def edit_ssh(sid: str, body: SSHConnectionUpdate):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return db.update_ssh_connection(sid, **body.model_dump())


@router.delete("/api/ssh/{sid}")
async def delete_ssh(sid: str):
    db.delete_ssh_connection(sid)
    return {"success": True}


@router.post("/api/ssh/test")
async def test_ssh(body: SSHConnectionCreate):
    password, private_key, key_passphrase = body.password, body.private_key, body.key_passphrase
    if body.connection_id and not password and not private_key:
        saved = db.get_ssh_connection(body.connection_id)
        if saved:
            password = saved.get("password") or ""
            private_key = saved.get("private_key") or ""
            key_passphrase = saved.get("key_passphrase") or ""

    def run():
        client = tool_module._ssh_connect({
            "host": body.host, "port": body.port, "username": body.username,
            "password": password, "private_key": private_key,
            "key_passphrase": key_passphrase,
        }, timeout=8)
        _, stdout, _ = client.exec_command("uname -a || ver", timeout=5)
        info = stdout.read().decode(errors="replace").strip()
        client.close()
        return info

    try:
        info = await asyncio.get_running_loop().run_in_executor(None, run)
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, True)
        return {"success": True, "info": info}
    except Exception as exc:
        if body.connection_id:
            db.set_ssh_test_result(body.connection_id, False)
        return {"success": False, "error": str(exc)}


@router.post("/api/ssh/exec")
async def exec_ssh(body: SSHCommandRequest):
    conn = db.get_ssh_connection(body.connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    blocked = security.guard_result(body.command)
    if blocked:
        return {"stdout": "", "stderr": blocked.get("error", "Commande bloquée."),
                "exit_code": -1, "command": body.command}

    def run():
        client = tool_module._ssh_connect(conn, timeout=body.timeout)
        _, stdout, stderr = client.exec_command(body.command, timeout=body.timeout)
        result = {"stdout": stdout.read().decode(errors="replace"),
                  "stderr": stderr.read().decode(errors="replace"),
                  "exit_code": stdout.channel.recv_exit_status(), "command": body.command}
        client.close()
        return result

    try:
        result = await asyncio.get_running_loop().run_in_executor(None, run)
        db.touch_ssh_connection(body.connection_id)
        try:
            db.log_execution("ssh_exec", {"connection_id": body.connection_id,
                             "command": body.command}, result, 0)
        except Exception:
            pass
        return result
    except Exception as exc:
        return {"stdout": "", "stderr": str(exc), "exit_code": -1, "command": body.command}


@router.get("/api/ssh/exec/stream")
async def exec_ssh_stream(connection_id: str, command: str):
    conn = db.get_ssh_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    blocked = security.guard_result(command)

    async def generate():
        if blocked:
            yield f"data: {json.dumps({'type': 'error', 'message': blocked.get('error', 'Commande bloquée.')})}\n\n"
            return
        try:
            client = await asyncio.get_running_loop().run_in_executor(None, tool_module._ssh_connect, conn, 30)
            _, stdout, stderr = client.exec_command(command, timeout=60)
            while True:
                line = await asyncio.get_running_loop().run_in_executor(None, stdout.readline)
                if not line:
                    break
                yield f"data: {json.dumps({'type': 'stdout', 'line': line.rstrip()})}\n\n"
            err = await asyncio.get_running_loop().run_in_executor(None, stderr.read)
            if err:
                yield f"data: {json.dumps({'type': 'stderr', 'line': err.decode(errors='replace').strip()})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'exit_code': stdout.channel.recv_exit_status()})}\n\n"
            db.touch_ssh_connection(connection_id)
            client.close()
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.websocket("/api/ssh/{sid}/shell")
async def ssh_shell_ws(websocket: WebSocket, sid: str):
    await websocket.accept()
    conn = db.get_ssh_connection(sid)
    if not conn:
        await websocket.send_json({"type": "error", "message": "Connexion introuvable."})
        await websocket.close()
        return
    loop = asyncio.get_running_loop()
    client = channel = None
    try:
        client = await loop.run_in_executor(None, tool_module._ssh_connect, conn, 15)
        channel = await loop.run_in_executor(
            None, lambda: client.invoke_shell(term="xterm-256color", width=80, height=24))
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
        await websocket.close()
        return
    db.touch_ssh_connection(sid)

    def blocking_recv():
        try:
            return channel.recv(4096)
        except Exception:
            return None

    async def pump_ssh_to_ws():
        try:
            while True:
                data = await loop.run_in_executor(None, blocking_recv)
                if not data:
                    break
                await websocket.send_json({"type": "data", "data": data.decode(errors="replace")})
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "closed"})
        except Exception:
            pass

    reader_task = asyncio.create_task(pump_ssh_to_ws())
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "input":
                channel.send(msg.get("data", "").encode("utf-8"))
            elif msg.get("type") == "resize":
                try:
                    channel.resize_pty(width=int(msg.get("cols", 80)), height=int(msg.get("rows", 24)))
                except Exception:
                    pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        reader_task.cancel()
        try:
            channel.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass


@router.get("/api/ssh/{sid}/browse")
async def browse_ssh(sid: str, path: str = "."):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_list_dir({"connection_id": sid, "remote_path": path})


@router.get("/api/ssh/{sid}/info")
async def ssh_server_info(sid: str):
    if not db.get_ssh_connection(sid):
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return await tool_module.execute_ssh_server_info({"connection_id": sid})


@router.get("/api/ssh/{sid}/download")
async def download_ssh_file(sid: str, path: str):
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")

    def run():
        client = tool_module._ssh_connect(conn, timeout=30)
        sftp = client.open_sftp()
        buf = io.BytesIO()
        sftp.getfo(path, buf)
        sftp.close()
        client.close()
        return buf.getvalue()

    try:
        data = await asyncio.get_running_loop().run_in_executor(None, run)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    filename = path.rstrip("/").rsplit("/", 1)[-1] or "download"
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/api/ssh/{sid}/upload")
async def upload_ssh_file(sid: str, remote_path: str = Form(...), file: UploadFile = File(...)):
    conn = db.get_ssh_connection(sid)
    if not conn:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    content = await file.read()

    def run():
        client = tool_module._ssh_connect(conn, timeout=60)
        sftp = client.open_sftp()
        sftp.putfo(io.BytesIO(content), remote_path)
        size = sftp.stat(remote_path).st_size
        sftp.close()
        client.close()
        return size

    try:
        size = await asyncio.get_running_loop().run_in_executor(None, run)
        db.touch_ssh_connection(sid)
        return {"success": True, "remote_path": remote_path, "size": size}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
