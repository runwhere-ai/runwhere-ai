"""Shared pytest fixtures for runwhere-ai.

Provides:
  - app fixture: a fresh FastAPI app per test (no side effects between tests)
  - client fixture: httpx AsyncClient against the app
  - uvicorn_server fixture (session scope, opt-in): spawns a real uvicorn
    subprocess on a random port for E2E tests
"""
from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
import sys
import time
from typing import AsyncIterator, Iterator

import httpx
import pytest


@pytest.fixture
def app():
    """Fresh FastAPI app per test (no shared singletons leak)."""
    from src.main import create_app

    return create_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    """httpx async client bound to the in-process ASGI app."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def uvicorn_server() -> Iterator[str]:
    """Spawn a real uvicorn subprocess for E2E (Playwright) tests.

    Yields the base URL (e.g. http://127.0.0.1:54321).
    """
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    # Wait up to 10s for /health to respond.
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=0.5)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("uvicorn did not become ready within 10s")
    try:
        yield base_url
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)
