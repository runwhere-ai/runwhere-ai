"""Lightweight middlewares used by the webui layer.

  - RequestIdMiddleware: attach `request.state.request_id` for logging /
    error correlation (spec FR-111, task T151).
"""
from __future__ import annotations

import time
import uuid
import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger("src.request")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_id=%s method=%s path=%s status=500 latency_ms=%.1f",
                rid, request.method, request.url.path,
                (time.perf_counter() - start) * 1000,
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-Id"] = rid
        logger.info(
            "request_id=%s method=%s path=%s status=%d latency_ms=%.1f",
            rid, request.method, request.url.path, response.status_code, latency_ms,
        )
        return response
