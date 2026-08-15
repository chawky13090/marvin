"""Smoke live sans outil métier du pilotage d'un tour Marvin."""

from __future__ import annotations

import json
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8005"


def post_json(path: str, payload: dict, *, timeout: float = 10.0):
    request = Request(
        BASE_URL + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Marvin-CSRF": "1"},
        method="POST",
    )
    return urlopen(request, timeout=timeout)


def get_json(path: str, *, timeout: float = 10.0) -> dict:
    with urlopen(BASE_URL + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    request_id = str(uuid.uuid4())
    conversation_key = str(uuid.uuid4())
    events: list[dict] = []
    failure: list[str] = []

    def consume() -> None:
        try:
            payload = {
                "messages": [{
                    "role": "user",
                    "content": "Réponds seulement par une courte phrase, sans appeler aucun outil.",
                }],
                "conversationId": None,
                "conversationKey": conversation_key,
                "requestId": request_id,
                "rootRequestId": request_id,
                "model": "qwen3:4b",
            }
            with post_json("/api/chat", payload, timeout=180.0) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        events.append(event)
                        if event.get("type") in {"done", "error"}:
                            break
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            failure.append(f"{type(exc).__name__}:{getattr(exc, 'code', '')}")

    worker = threading.Thread(target=consume, name="marvin-steering-live-smoke", daemon=True)
    worker.start()

    directive = None
    client_directive_id = str(uuid.uuid4())
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and directive is None and not failure:
        try:
            with post_json(
                f"/api/chat/turns/{request_id}/directives",
                {
                    "clientDirectiveId": client_directive_id,
                    "kind": "append",
                    "text": "Ajoute le mot test-validé à la fin de ta réponse.",
                },
                timeout=15.0,
            ) as response:
                directive = json.loads(response.read().decode("utf-8"))["directive"]
        except HTTPError as exc:
            if exc.code not in {404, 409}:
                failure.append(f"HTTPError:{exc.code}")
                break
            time.sleep(0.05)
        except (URLError, TimeoutError, ValueError):
            # Une rupture après POST est ambiguë : ne jamais créer une seconde
            # directive. Lire le reçu durable, puis seulement réémettre la même
            # clé idempotente si le reçu n'existe pas encore.
            try:
                listed = get_json(
                    f"/api/chat/turns/{request_id}/directives", timeout=15.0
                ).get("directives", [])
                directive = next(
                    (item for item in listed if item.get("clientDirectiveId") == client_directive_id),
                    None,
                )
            except (HTTPError, URLError, TimeoutError, ValueError):
                time.sleep(0.1)

    worker.join(timeout=190.0)
    assert not worker.is_alive(), "Le tour live n'a pas respecté sa borne."
    assert not failure, failure
    assert directive is not None and directive["status"] == "received", directive
    kinds = [event.get("type") for event in events]
    assert "directive_applied" in kinds or "directive_ready" in kinds, kinds
    assert kinds[-1] == "done", kinds
    assert not any(event.get("type") == "tool_start" for event in events), kinds
    if "directive_applied" in kinds:
        text = "".join(str(event.get("text") or "") for event in events if event.get("type") == "text")
        assert "test-valid" in text.lower(), text[-500:]
    else:
        ready = next(event["directive"] for event in events if event.get("type") == "directive_ready")
        assert ready["reasonCode"] == "root_turn_terminal_followup", ready
    print("Chat Turn Steering Live OK - directive reçue puis appliquée ou reprise sans perte, sans outil métier.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
