"""Jinja2 environment singleton used by all webui routes.

We register custom filters that templates rely on:
  - ``t(key)``      – i18n translation (i18n module)
  - ``etag(rv)``    – format a resourceVersion as a strong ETag
"""
from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from src.config import CONFIG
from src.console import i18n
from src.console.consistency import ConsistencyGate


_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Expose helpers as Jinja globals so templates can do `{{ t('key') }}`.
templates.env.globals["t"] = i18n.t
templates.env.globals["has_translation"] = i18n.has
templates.env.globals["config"] = CONFIG  # auth_provider check in dev banner
templates.env.filters["etag"] = ConsistencyGate.format_etag
