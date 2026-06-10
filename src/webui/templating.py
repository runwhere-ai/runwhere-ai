"""Jinja2 environment singleton used by all webui routes.

We register custom filters that templates rely on:
  - ``t(key)``      – i18n translation (i18n module)
  - ``etag(rv)``    – format a resourceVersion as a strong ETag
"""
from __future__ import annotations

import hashlib
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


# Expose helpers as Jinja globals so templates can do `{{ t('key') }}`.
templates.env.globals["t"] = i18n.t
templates.env.globals["has_translation"] = i18n.has
templates.env.globals["config"] = CONFIG  # auth_provider check in dev banner
templates.env.globals["asset_v"] = _asset_version()
templates.env.filters["etag"] = ConsistencyGate.format_etag
