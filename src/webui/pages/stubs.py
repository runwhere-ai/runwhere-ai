"""Page handlers for sidebar routes — sourced from live gpuctl data.

Each list view fetches from the in-process gpuctl `/api/v1/*` route functions
(or the gpuctl sync clients directly) and maps the result into the cell format
that `pages/_listing.html` expects. Data sources mirror the JSON API one-to-one,
so the HTML pages and the API stay consistent.

(Previously this rendered hard-coded mock rows; that scaffolding is gone.)
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from src.console.models import User
from src.console.status_palette import StatusPalette
from src.webui.deps import get_current_user, require_admin
from src.webui.templating import templates


logger = logging.getLogger("src.webui.pages")
router = APIRouter(tags=["pages"])


# ── cell helpers ──────────────────────────────────────────────────────────────
def b(label: str, tone: str = "neutral", dot: str | None = None) -> dict:
    return {"badge": label, "tone": tone, "dot": dot}

def k(kind: str, label: str | None = None) -> dict:
    return {"kind": kind, "label": label}

def m(text: str) -> dict:
    return {"mono": text}

def mu(text: str) -> dict:
    return {"muted": text}

def t(title: str, sub: str | None = None) -> dict:
    return {"title": title, "sub": sub}

def link(title: str, href: str, sub: str | None = None) -> dict:
    return {"title": title, "href": href, "sub": sub}

def action(label: str, href: str, icon_name: str = "arrow-right") -> dict:
    return {"action": label, "href": href, "icon": icon_name}

def bar(pct: int, label: str | None = None) -> dict:
    return {"bar": pct, "label": label}


# ── status → badge ────────────────────────────────────────────────────────────
# StatusPalette keys are TitleCase k8s phases / reasons (Running, Pending, …).
# gpuctl clients also emit a few lowercase strings the palette doesn't know.
_EXTRA_STATUS = {
    "active":    ("running", "就绪"),
    "Active":    ("running", "Active"),
    "not_ready": ("danger", "未就绪"),
}

def status_badge(status: str) -> dict:
    if status in _EXTRA_STATUS:
        tone, label = _EXTRA_STATUS[status]
        return b(label, tone)
    return b(StatusPalette.explain(status), StatusPalette.color(status))

def _maybe_mono(value: Any) -> dict:
    """Mono cell, or a muted <none> for empty / N/A values."""
    if value in (None, "", "N/A", "<none>"):
        return mu("<none>")
    return m(str(value))

def _short_age(age: str) -> str:
    """Namespace age comes as a full datetime string — keep just the date."""
    return (age or "")[:10] or "—"


# Leading row-icon presets — shadcn-style chip colors per page kind.
_ICON_PINK   = "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400"
_ICON_PURPLE = "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"
_ICON_CYAN   = "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400"
_ICON_TEAL   = "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400"
_ICON_BLUE   = "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
_ICON_SLATE  = "bg-slate-100 text-slate-700 dark:bg-slate-900/40 dark:text-slate-300"
_ICON_AMBER  = "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
_ICON_INDIGO = "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400"


# ── column definitions ────────────────────────────────────────────────────────
# Pod-level job columns mirror the /api/v1/jobs JobItem shape exactly.
_JOB_COLUMNS = [
    {"label": "名称",     "key": "name"},
    {"label": "命名空间", "key": "namespace"},
    {"label": "状态",     "key": "status"},
    {"label": "READY",    "key": "ready"},
    {"label": "节点",     "key": "node"},
    {"label": "IP",       "key": "ip"},
    {"label": "AGE",      "key": "age", "align": "right"},
]
_POOL_COLUMNS = [
    {"label": "资源池名", "key": "name"},
    {"label": "状态",     "key": "status"},
    {"label": "GPU 总数", "key": "total", "align": "right"},
    {"label": "已用 GPU", "key": "used",  "align": "right"},
    {"label": "空闲 GPU", "key": "free",  "align": "right"},
    {"label": "节点数",   "key": "count", "align": "right"},
]
_NODE_COLUMNS = [
    {"label": "节点名",   "key": "name"},
    {"label": "状态",     "key": "status"},
    {"label": "GPU 总数", "key": "total", "align": "right"},
    {"label": "已用",     "key": "used",  "align": "right"},
    {"label": "空闲",     "key": "free",  "align": "right"},
    {"label": "GPU 类型", "key": "type"},
    {"label": "IP",       "key": "ip"},
    {"label": "资源池",   "key": "pool"},
]
_NS_COLUMNS = [
    {"label": "名称",     "key": "name"},
    {"label": "状态",     "key": "status"},
    {"label": "创建时间", "key": "age", "align": "right"},
    {"label": "配额",     "key": "quota"},
]
_QUOTA_COLUMNS = [
    {"label": "配额名",   "key": "name"},
    {"label": "命名空间", "key": "namespace"},
    {"label": "CPU",      "key": "cpu",    "align": "right"},
    {"label": "MEMORY",   "key": "memory", "align": "right"},
    {"label": "GPU",      "key": "gpu",    "align": "right"},
    {"label": "状态",     "key": "status"},
]


# ── row builders (live data) ──────────────────────────────────────────────────
async def _job_rows(kind: str) -> list[list[Any]]:
    """One row per pod for the given job kind, matching gpuctl get jobs."""
    from server.routes.jobs import get_jobs  # lazy: gpuctl `server` pkg

    resp = await get_jobs(kind=kind, pool=None, status=None, namespace=None, page=1, pageSize=200)
    return [
        [
            t(it.name),
            m(it.namespace),
            status_badge(it.status),
            it.ready,
            _maybe_mono(it.node),
            _maybe_mono(it.ip),
            it.age,
        ]
        for it in resp.items
    ]


async def _pool_rows() -> list[list[Any]]:
    from gpuctl.client.pool_client import PoolClient

    pools = PoolClient.get_instance().list_pools()
    return [
        [
            link(p["name"], f"/pools/{p['name']}/nodes"),
            status_badge(p.get("status", "active")),
            p.get("gpu_total", 0),
            p.get("gpu_used", 0),
            p.get("gpu_free", 0),
            len(p.get("nodes") or []),
        ]
        for p in pools
    ]


async def _namespace_rows() -> list[list[Any]]:
    from server.routes.namespaces import list_namespaces

    resp = await list_namespaces()
    return [
        [
            t(ns["name"]),
            status_badge(ns.get("status", "Active")),
            m(_short_age(ns.get("age", ""))),
            action("查看配额", f"/namespaces/{ns['name']}/quotas", "shield"),
        ]
        for ns in resp.get("items", [])
    ]


# ── page registry ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Page:
    path: str
    label: str
    title: str
    subtitle: str
    cta: dict | None
    columns: list[dict]
    rows_fn: Callable[[], Awaitable[list[list[Any]]]]
    row_icon: dict | None = None


_NOTEBOOKS = _Page(
    path="/notebooks", label="Notebook（开发调试）", title="Notebook",
    subtitle="3 分钟拉起 Jupyter，开箱即用的训练 / 数据探索环境。",
    cta={"label": "新建 Notebook", "href": "/notebooks?new=1", "icon": "plus"},
    row_icon={"name": "book-open", "classes": _ICON_PINK},
    columns=_JOB_COLUMNS, rows_fn=functools.partial(_job_rows, "notebook"),
)
_TRAININGS = _Page(
    path="/trainings", label="训练任务", title="训练任务",
    subtitle="表单 / YAML 双模式提交，实时日志与 dryRun 行号定位。",
    cta={"label": "新建训练", "href": "/trainings?new=1", "icon": "rocket"},
    row_icon={"name": "rocket", "classes": _ICON_PURPLE},
    columns=_JOB_COLUMNS, rows_fn=functools.partial(_job_rows, "training"),
)
_INFERENCES = _Page(
    path="/inferences", label="推理服务", title="推理服务",
    subtitle="HPA 自动扩缩，内置 Playground 调试与请求历史。",
    cta={"label": "发布推理", "href": "/inferences?new=1", "icon": "zap"},
    row_icon={"name": "zap", "classes": _ICON_CYAN},
    columns=_JOB_COLUMNS, rows_fn=functools.partial(_job_rows, "inference"),
)
_COMPUTES = _Page(
    path="/computes", label="计算服务", title="计算服务",
    subtitle="一次性 Job 或常驻 Deployment，通用容器作业入口。",
    cta={"label": "新建任务", "href": "/computes?new=1", "icon": "cpu"},
    row_icon={"name": "cpu", "classes": _ICON_TEAL},
    columns=_JOB_COLUMNS, rows_fn=functools.partial(_job_rows, "compute"),
)
_POOLS = _Page(
    path="/pools", label="资源池", title="资源管理",
    subtitle="资源池与节点统一管理，按机型 / 用途划池并绑定物理节点。",
    cta={"label": "新建池", "href": "/pools?new=1", "icon": "plus"},
    row_icon={"name": "database", "classes": _ICON_BLUE},
    columns=_POOL_COLUMNS, rows_fn=_pool_rows,
)
_NAMESPACES = _Page(
    path="/namespaces", label="命名空间", title="命名空间",
    subtitle="租户隔离单元，绑定资源池与配额。",
    cta={"label": "新建命名空间", "href": "/namespaces?new=1", "icon": "plus"},
    row_icon={"name": "folder", "classes": _ICON_INDIGO},
    columns=_NS_COLUMNS, rows_fn=_namespace_rows,
)

_USER_PAGES = (_NOTEBOOKS, _TRAININGS, _INFERENCES, _COMPUTES)
_ADMIN_PAGES = (_POOLS, _NAMESPACES)


async def _render(request: Request, user: User, page: _Page):
    try:
        rows = await page.rows_fn()
    except Exception as exc:  # never 500 a full page render; show empty + log
        logger.warning("page %s: failed to load live data (%s)", page.path, exc)
        rows = []
    return templates.TemplateResponse(
        request,
        "pages/_listing.html",
        {
            "user": user,
            "page_title": page.title,
            "page_subtitle": page.subtitle,
            "primary_cta": page.cta,
            "row_icon": page.row_icon,
            "columns": page.columns,
            "rows": rows,
        },
    )


def _user_handler(page: _Page):
    async def _h(request: Request, user: User = Depends(get_current_user)):
        return await _render(request, user, page)
    return _h


def _admin_handler(page: _Page):
    async def _h(request: Request, user: User = Depends(require_admin)):
        return await _render(request, user, page)
    return _h


for _page in _USER_PAGES:
    router.add_api_route(_page.path, _user_handler(_page), methods=["GET"],
                         name=f"page_{_page.path.lstrip('/')}")

for _page in _ADMIN_PAGES:
    router.add_api_route(_page.path, _admin_handler(_page), methods=["GET"],
                         name=f"page_admin_{_page.path.lstrip('/')}")


# ── detail pages ──────────────────────────────────────────────────────────────
@router.get("/pools/{pool_name}/nodes")
async def pool_nodes(pool_name: str, request: Request, user: User = Depends(require_admin)):
    rows: list[list[Any]] = []
    try:
        from gpuctl.client.pool_client import PoolClient
        from gpuctl.constants import Labels

        nodes = PoolClient.get_instance().list_nodes(filters={"pool": pool_name})
        for n in nodes:
            res = n.get("resources", {})
            gtypes = n.get("gpu_types") or []
            rows.append([
                t(n["name"]),
                status_badge(n.get("status", "active")),
                res.get("gpu_total", 0),
                res.get("gpu_used", 0),
                res.get("gpu_free", 0),
                m(gtypes[0]) if gtypes else mu("—"),
                _maybe_mono(n.get("ip")),
                m(n.get("labels", {}).get(Labels.POOL, "default")),
            ])
    except Exception as exc:
        logger.warning("pool_nodes %s: %s", pool_name, exc)
    return templates.TemplateResponse(
        request, "pages/_listing.html",
        {
            "user": user,
            "page_title": f"{pool_name} · 节点",
            "page_subtitle": "该资源池下的物理节点状态、GPU 利用率与标签管理。",
            "primary_cta": None,
            "row_icon": {"name": "server", "classes": _ICON_SLATE},
            "columns": _NODE_COLUMNS,
            "rows": rows,
        },
    )


@router.get("/namespaces/{namespace}/quotas")
async def namespace_quotas(namespace: str, request: Request, user: User = Depends(require_admin)):
    rows: list[list[Any]] = []
    try:
        from gpuctl.client.quota_client import QuotaClient

        q = QuotaClient().get_quota(namespace)
        if q:
            hard = q.get("hard", {})
            rows.append([
                t(q.get("name", namespace)),
                m(namespace),
                str(hard.get("cpu", "—")),
                str(hard.get("memory", "—")),
                str(hard.get("nvidia.com/gpu", "0")),
                status_badge(q.get("status", "Active")),
            ])
    except Exception as exc:
        logger.warning("namespace_quotas %s: %s", namespace, exc)
    return templates.TemplateResponse(
        request, "pages/_listing.html",
        {
            "user": user,
            "page_title": f"{namespace} · 配额",
            "page_subtitle": "该命名空间的 GPU / 内存 / Pod 用量与上限（未设置配额则为空）。",
            "primary_cta": None,
            "row_icon": {"name": "shield", "classes": _ICON_AMBER},
            "columns": _QUOTA_COLUMNS,
            "rows": rows,
        },
    )


@router.get("/nodes", include_in_schema=False)
async def nodes_redirect():
    return RedirectResponse("/pools", status_code=302)


@router.get("/quotas", include_in_schema=False)
async def quotas_redirect():
    return RedirectResponse("/namespaces", status_code=302)
