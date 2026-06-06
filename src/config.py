"""Runtime configuration for runwhere-ai.

All knobs live here so that operators can tweak via env vars without
touching code. Tasks T008 (Phase 1 Setup).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Config:
    # ── Authentication (FR-001 + clarify Q1) ─────────────────────────────────
    # "kubeconfig" = platform-console mode: no browser login; the server uses
    # in-cluster config or the operator's kubeconfig to access all resources.
    # "bypass" = DEV ONLY: fake admin user, no K8s client setup.
    auth_provider: Literal["kubeconfig", "bearer", "oidc", "bypass"] = field(
        default_factory=lambda: os.getenv("RWAI_AUTH_PROVIDER", "kubeconfig")
    )
    session_cookie_name: str = "rw_token"
    csrf_cookie_name: str = "csrf"
    cookie_secure: bool = field(default_factory=lambda: _env_bool("RWAI_COOKIE_SECURE", True))
    token_review_cache_seconds: int = field(default_factory=lambda: _env_int("RWAI_TOKEN_REVIEW_CACHE_S", 300))

    # ── Informer (FR-101 / R-01) ──────────────────────────────────────────────
    informer_resync_seconds: int = field(default_factory=lambda: _env_int("RWAI_INFORMER_RESYNC_S", 300))
    informer_cache_max_objects: int = field(default_factory=lambda: _env_int("RWAI_INFORMER_CACHE_MAX", 50_000))

    # ── PubSub (FR-101a / R-02) ───────────────────────────────────────────────
    pubsub_queue_max: int = field(default_factory=lambda: _env_int("RWAI_PUBSUB_QUEUE_MAX", 1000))
    pubsub_max_topics_per_conn: int = field(default_factory=lambda: _env_int("RWAI_PUBSUB_MAX_TOPICS", 6))

    # ── WebSocket (R-02) ──────────────────────────────────────────────────────
    ws_heartbeat_seconds: int = field(default_factory=lambda: _env_int("RWAI_WS_HEARTBEAT_S", 25))
    ws_max_connections: int = field(default_factory=lambda: _env_int("RWAI_WS_MAX_CONN", 1000))
    ws_frames_per_sec_per_subscriber: int = field(
        default_factory=lambda: _env_int("RWAI_WS_FPS_PER_SUB", 50)
    )

    # ── Consistency (FR-103 / R-04) ───────────────────────────────────────────
    ryw_wait_timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("RWAI_RYW_TIMEOUT_S", "2.0"))
    )

    # ── Idle Watcher (FR-042 / R-08) ──────────────────────────────────────────
    idle_watcher_poll_seconds: int = field(default_factory=lambda: _env_int("RWAI_IDLE_POLL_S", 60))
    idle_warning_minutes: int = field(default_factory=lambda: _env_int("RWAI_IDLE_WARN_M", 10))

    # ── Compute (FR-072) ──────────────────────────────────────────────────────
    compute_default_ttl_seconds: int = field(
        default_factory=lambda: _env_int("RWAI_COMPUTE_TTL_S", 2_592_000)  # 30 days
    )

    # ── Playground (FR-061a) ──────────────────────────────────────────────────
    playground_history_max: int = field(default_factory=lambda: _env_int("RWAI_PLAYGROUND_HIST_MAX", 50))
    playground_rate_limit_per_sec: int = field(
        default_factory=lambda: _env_int("RWAI_PLAYGROUND_RATE_LIMIT", 30)
    )

    # ── YAML (Assumptions) ────────────────────────────────────────────────────
    yaml_max_bytes: int = field(default_factory=lambda: _env_int("RWAI_YAML_MAX_BYTES", 256 * 1024))

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = field(default_factory=lambda: os.getenv("RWAI_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("RWAI_PORT", 8000))
    log_level: str = field(default_factory=lambda: os.getenv("RWAI_LOG_LEVEL", "INFO"))

    # ── Paths (resolved at import time) ───────────────────────────────────────
    # Relative to src package; concrete absolute paths derived in main.py.
    templates_dir: str = "templates"
    static_dir: str = "static"


CONFIG = Config()
