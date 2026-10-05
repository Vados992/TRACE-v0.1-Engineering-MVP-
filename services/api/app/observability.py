"""Dependency-free request metrics and structured operational telemetry."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter, defaultdict

logger = logging.getLogger("trace.access")
_LOCK = threading.Lock()
_REQUESTS = Counter()
_ERRORS = Counter()
_LATENCY_SUM = defaultdict(float)
_LATENCY_COUNT = Counter()
_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_LATENCY_BUCKETS = Counter()


def _route_key(path: str) -> str:
    if path.startswith("/api/internal/"):
        return "/".join(path.split("/")[:4])
    if path.startswith("/api/v1/"):
        return "/".join(path.split("/")[:4])
    if path.startswith("/api/public/"):
        return "/".join(path.split("/")[:4])
    return path


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        method = scope["method"]
        route = _route_key(scope["path"])
        status_code = 500

        async def observed_send(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        finally:
            elapsed = time.perf_counter() - started
            key = (method, route, str(status_code))
            with _LOCK:
                _REQUESTS[key] += 1
                if status_code >= 500:
                    _ERRORS[(method, route)] += 1
                _LATENCY_SUM[(method, route)] += elapsed
                _LATENCY_COUNT[(method, route)] += 1
                for bucket in _BUCKETS:
                    if elapsed <= bucket:
                        _LATENCY_BUCKETS[(method, route, bucket)] += 1
            state = scope.get("state", {})
            logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": state.get("request_id"),
                        "method": method,
                        "route_group": route,
                        "status": status_code,
                        "duration_ms": round(elapsed * 1000, 3),
                    },
                    separators=(",", ":"),
                )
            )


def prometheus_text() -> str:
    lines = [
        "# HELP trace_http_requests_total HTTP requests handled by TRACE.",
        "# TYPE trace_http_requests_total counter",
    ]
    with _LOCK:
        for (method, route, status), value in sorted(_REQUESTS.items()):
            lines.append(
                f'trace_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {value}'
            )
        lines += [
            "# HELP trace_http_request_duration_seconds HTTP request latency.",
            "# TYPE trace_http_request_duration_seconds histogram",
        ]
        for (method, route), count in sorted(_LATENCY_COUNT.items()):
            for bucket in _BUCKETS:
                cumulative = _LATENCY_BUCKETS[(method, route, bucket)]
                lines.append(
                    f'trace_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="{bucket}"}} {cumulative}'
                )
            lines.append(
                f'trace_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="+Inf"}} {count}'
            )
            lines.append(
                f'trace_http_request_duration_seconds_sum{{method="{method}",route="{route}"}} {_LATENCY_SUM[(method, route)]:.9f}'
            )
            lines.append(
                f'trace_http_request_duration_seconds_count{{method="{method}",route="{route}"}} {count}'
            )
        lines += [
            "# HELP trace_http_server_errors_total HTTP 5xx responses.",
            "# TYPE trace_http_server_errors_total counter",
        ]
        for (method, route), value in sorted(_ERRORS.items()):
            lines.append(
                f'trace_http_server_errors_total{{method="{method}",route="{route}"}} {value}'
            )
    return "\n".join(lines) + "\n"
