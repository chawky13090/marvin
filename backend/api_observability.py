"""Corrélation HTTP et métriques API bornées, sans contenu utilisateur."""
from __future__ import annotations

import re
import threading
import time
import uuid
from collections import Counter, deque
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from config import DATA_DIR
from structured_logging import StructuredJsonlStore


_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_UUID_OR_NUMBER = re.compile(
    r"/(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{24,64}|\d+)(?=/|$)",
    re.IGNORECASE,
)
_LATENCY_BUCKETS_MS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_MAX_ROUTES = 256
_SLOW_MS = 2000
_SLO_WINDOW_SECONDS = 60 * 60
_SLO_MAX_SAMPLES = 20_000
_SLO_MIN_SAMPLES = 20
_SLO_AVAILABILITY_TARGET = 0.99
_SLO_LATENCY_TARGET = 0.95
_SLO_LATENCY_THRESHOLD_MS = 2000.0
_SLO_EXCLUDED_ROUTES = frozenset({"/api/health"})
_current_request_id: ContextVar[str | None] = ContextVar(
    "marvin_request_id",
    default=None,
)

_lock = threading.Lock()
_started_at = time.time()
_requests = 0
_status_classes: Counter[str] = Counter()
_latency_buckets: Counter[str] = Counter()
_routes: Counter[str] = Counter()
_errors = 0
_slow = 0
_total_duration_ms = 0.0
_max_duration_ms = 0.0
_slo_samples: deque[tuple[float, int, float]] = deque(maxlen=_SLO_MAX_SAMPLES)

_store = StructuredJsonlStore.from_environment(
    Path(DATA_DIR) / "logs" / "api_requests.jsonl",
    component="http_api",
    prefix="API_REQUESTS",
    default_retention_days=30,
)


def normalize_request_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    return candidate if _REQUEST_ID.fullmatch(candidate) else uuid.uuid4().hex


def current_request_id() -> str | None:
    return _current_request_id.get()


def normalize_route(path: str) -> str:
    normalized = _UUID_OR_NUMBER.sub("/{id}", str(path or "/")[:500])
    return normalized if normalized.startswith("/") else "/"


def is_slo_eligible(method: str, route: str) -> bool:
    normalized_method = str(method or "").upper()
    normalized_route = str(route or "")
    return (
        normalized_method != "OPTIONS"
        and normalized_route not in _SLO_EXCLUDED_ROUTES
        and normalized_route != "/api/chat"
        and not normalized_route.endswith("/stream")
    )


def _record(method: str, route: str, status: int, duration_ms: float, request_id: str) -> None:
    global _requests, _errors, _slow, _total_duration_ms, _max_duration_ms
    status_class = f"{max(1, min(status // 100, 5))}xx"
    bucket = next((str(value) for value in _LATENCY_BUCKETS_MS if duration_ms <= value), "inf")
    with _lock:
        _requests += 1
        _status_classes[status_class] += 1
        _latency_buckets[bucket] += 1
        _total_duration_ms += duration_ms
        _max_duration_ms = max(_max_duration_ms, duration_ms)
        if status >= 500:
            _errors += 1
        if duration_ms >= _SLOW_MS:
            _slow += 1
        route_key = f"{method} {route}"
        if route_key in _routes or len(_routes) < _MAX_ROUTES:
            _routes[route_key] += 1
        else:
            _routes["other"] += 1
        if is_slo_eligible(method, route):
            _slo_samples.append((time.time(), status, duration_ms))
    if status >= 500 or duration_ms >= _SLOW_MS:
        _store.write(
            "http_request",
            severity="ERROR" if status >= 500 else "WARNING",
            outcome="error" if status >= 500 else "slow",
            trace_id=request_id,
            attributes={
                "method": method,
                "route": route,
                "status_code": status,
                "duration_ms": round(duration_ms, 2),
            },
        )


def snapshot() -> dict[str, Any]:
    with _lock:
        requests = _requests
        return {
            "started_at_epoch": _started_at,
            "requests": requests,
            "errors_5xx": _errors,
            "slow_requests": _slow,
            "average_duration_ms": round(_total_duration_ms / requests, 2) if requests else 0.0,
            "max_duration_ms": round(_max_duration_ms, 2),
            "status_classes": dict(sorted(_status_classes.items())),
            "latency_buckets_ms": dict(_latency_buckets),
            "top_routes": [
                {"route": route, "requests": count}
                for route, count in _routes.most_common(20)
            ],
            "route_cardinality": len(_routes),
            "slow_threshold_ms": _SLOW_MS,
            "slo": _slo_snapshot_locked(time.time()),
        }


def _slo_snapshot_locked(now: float) -> dict[str, Any]:
    cutoff = now - _SLO_WINDOW_SECONDS
    while _slo_samples and _slo_samples[0][0] < cutoff:
        _slo_samples.popleft()
    total = len(_slo_samples)
    errors = sum(1 for _, status, _ in _slo_samples if status >= 500)
    slow = sum(
        1 for _, _, duration_ms in _slo_samples
        if duration_ms > _SLO_LATENCY_THRESHOLD_MS
    )
    availability = (total - errors) / total if total else None
    latency_compliance = (total - slow) / total if total else None
    budget_fraction = 1.0 - _SLO_AVAILABILITY_TARGET
    error_fraction = errors / total if total else 0.0
    burn_rate = error_fraction / budget_fraction if budget_fraction > 0 else 0.0
    if total < _SLO_MIN_SAMPLES:
        state = "insufficient"
    elif (
        availability is not None
        and availability >= _SLO_AVAILABILITY_TARGET
        and latency_compliance is not None
        and latency_compliance >= _SLO_LATENCY_TARGET
    ):
        state = "met"
    else:
        state = "missed"
    return {
        "state": state,
        "window_seconds": _SLO_WINDOW_SECONDS,
        "samples": total,
        "minimum_samples": _SLO_MIN_SAMPLES,
        "availability": round(availability, 6) if availability is not None else None,
        "availability_target": _SLO_AVAILABILITY_TARGET,
        "latency_compliance": (
            round(latency_compliance, 6) if latency_compliance is not None else None
        ),
        "latency_target": _SLO_LATENCY_TARGET,
        "latency_threshold_ms": _SLO_LATENCY_THRESHOLD_MS,
        "errors": errors,
        "slow": slow,
        "error_budget_remaining": (
            round(max(0.0, 1.0 - burn_rate), 6) if total else None
        ),
        "burn_rate": round(burn_rate, 6) if total else None,
    }


def slo_snapshot(now: float | None = None) -> dict[str, Any]:
    with _lock:
        return _slo_snapshot_locked(time.time() if now is None else float(now))


def reset_for_tests() -> None:
    global _requests, _errors, _slow, _total_duration_ms, _max_duration_ms
    with _lock:
        _requests = _errors = _slow = 0
        _total_duration_ms = _max_duration_ms = 0.0
        _status_classes.clear()
        _latency_buckets.clear()
        _routes.clear()
        _slo_samples.clear()


class ApiObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        request_id = normalize_request_id(headers.get("x-request-id"))
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = _current_request_id.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_headers = [
                    item for item in message.get("headers", [])
                    if item[0].lower() not in {b"x-request-id", b"server-timing"}
                ]
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                elapsed_ms = (time.perf_counter() - started) * 1000
                response_headers.append(
                    (b"server-timing", f"app;dur={elapsed_ms:.2f}".encode("ascii"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        finally:
            try:
                _record(
                    str(scope.get("method") or "GET")[:16],
                    normalize_route(str(scope.get("path") or "/")),
                    status_code,
                    (time.perf_counter() - started) * 1000,
                    request_id,
                )
            finally:
                _current_request_id.reset(context_token)
