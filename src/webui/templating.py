"""Jinja2 environment singleton used by all webui routes.

We register custom filters that templates rely on:
  - ``t(key)``      – i18n translation (i18n module)
  - ``etag(rv)``    – format a resourceVersion as a strong ETag
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from fastapi.templating import Jinja2Templates

from src.config import CONFIG
from src.console import i18n
from src.console.consistency import ConsistencyGate


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_STATIC_DIR = _TEMPLATES_DIR.parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _asset_version() -> str:
    """Short content hash of the built CSS, used to cache-bust static URLs.

    Browsers cache /static/css/tailwind.css by URL; without a version query a
    redeploy keeps serving the stale CSS. Hashing the file content means the
    URL changes exactly when the CSS changes — no manual hard-refresh needed.
    Computed once at startup (every deploy is a fresh process → fresh hash).
    """
    h = hashlib.md5()
    for rel in ("css/tailwind.css", "css/tokens.css"):
        try:
            h.update((_STATIC_DIR / rel).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:8] or "dev"


# gpuctl 管理的命名空间名(30s 缓存),供顶栏全局命名空间选择器【服务端】渲染。
_ns_cache = {"ts": 0.0, "names": []}


def _available_namespaces() -> list:
    now = time.time()
    if _ns_cache["names"] and now - _ns_cache["ts"] < 30:
        return _ns_cache["names"]
    try:
        from gpuctl.client.quota_client import QuotaClient
        from gpuctl.constants import NS_LABEL_SELECTOR
        res = QuotaClient().core_v1.list_namespace(label_selector=NS_LABEL_SELECTOR)
        _ns_cache["names"] = sorted(ns.metadata.name for ns in res.items)
        _ns_cache["ts"] = now
    except Exception:  # noqa: BLE001 - 顶栏不能因列命名空间失败而崩
        pass
    return _ns_cache["names"]


# Expose helpers as Jinja globals so templates can do `{{ t('key') }}`.
templates.env.globals["t"] = i18n.t
templates.env.globals["has_translation"] = i18n.has
templates.env.globals["config"] = CONFIG  # auth_provider check in dev banner
templates.env.globals["asset_v"] = _asset_version()
templates.env.globals["available_namespaces"] = _available_namespaces
templates.env.filters["etag"] = ConsistencyGate.format_etag
