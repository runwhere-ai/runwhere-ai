"""Page handlers for sidebar routes.

Renders polished list views with mock data so the navigation feels complete
end-to-end before the real US1~US7 slices wire in live data. When those land,
the per-page handlers below should be replaced with real list-controllers
that source from gpuctl + Informer caches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request

from src.console.models import User
from src.webui.deps import get_current_user, require_admin
from src.webui.templating import templates


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

def bar(pct: int, label: str | None = None) -> dict:
    return {"bar": pct, "label": label}


# Leading row-icon presets — shadcn-style chip colors per page kind.
# String literals are kept here (not in CSS) so Tailwind's content scanner
# (which already scans `src/**/*.py`) generates the utility classes.
_ICON_PINK   = "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400"
_ICON_PURPLE = "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"
_ICON_CYAN   = "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400"
_ICON_TEAL   = "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400"
_ICON_BLUE   = "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"
_ICON_SLATE  = "bg-slate-100 text-slate-700 dark:bg-slate-900/40 dark:text-slate-300"
_ICON_AMBER  = "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
_ICON_INDIGO = "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400"


@dataclass(frozen=True)
class _Page:
    path: str
    label: str
    title: str
    subtitle: str
    cta: dict | None
    columns: list[dict]
    rows: list[list[Any]]
    row_icon: dict | None = None


# ── User pages ────────────────────────────────────────────────────────────────

_NOTEBOOKS = _Page(
    path="/notebooks",
    label="Notebook（开发调试）",
    title="Notebook",
    subtitle="3 分钟拉起 Jupyter，开箱即用的训练 / 数据探索环境。",
    cta={"label": "新建 Notebook", "href": "/notebooks?new=1", "icon": "plus"},
    row_icon={"name": "book-open", "classes": _ICON_PINK},
    columns=[
        {"label": "名称",     "key": "name"},
        {"label": "命名空间", "key": "namespace"},
        {"label": "状态",     "key": "status"},
        {"label": "READY",    "key": "ready"},
        {"label": "节点",     "key": "node"},
        {"label": "IP",       "key": "ip"},
        {"label": "AGE",      "key": "age", "align": "right"},
    ],
    rows=[
        [t("jupyter-llm-eval"),  m("team-llm"),    b("Running",   "running",   "online"),  "1/1", m("gpu-h100-01"), m("10.244.5.32"), "12m"],
        [t("jupyter-rag"),       m("team-rag"),    b("Running",   "running",   "online"),  "1/1", m("gpu-a10-02"),  m("10.244.7.18"), "5h"],
        [t("jupyter-vision-ft"), m("team-vision"), b("Pending",   "pending"),                "0/1", mu("<none>"),     mu("<none>"),     "2m"],
        [t("jupyter-explore"),   m("team-llm"),    b("Succeeded", "succeeded"),              "0/1", m("gpu-a100-04"), mu("<none>"),     "2d"],
    ],
)

_TRAININGS = _Page(
    path="/trainings",
    label="训练任务",
    title="训练任务",
    subtitle="表单 / YAML 双模式提交，实时日志与 dryRun 行号定位。",
    cta={"label": "新建训练", "href": "/trainings?new=1", "icon": "rocket"},
    row_icon={"name": "rocket", "classes": _ICON_PURPLE},
    columns=[
        {"label": "名称",     "key": "name"},
        {"label": "命名空间", "key": "namespace"},
        {"label": "状态",     "key": "status"},
        {"label": "READY",    "key": "ready"},
        {"label": "GPU",      "key": "gpu"},
        {"label": "节点",     "key": "node"},
        {"label": "AGE",      "key": "age", "align": "right"},
    ],
    rows=[
        [t("llama3-8b-sft-r3"),  m("team-llm"),      b("Running",   "running",   "online"),  "8/8",   "8 × h100-80g",  m("gpu-h100-01..08"),       "2h14m"],
        [t("baichuan-pretrain"), m("team-base"),     b("Running",   "running",   "online"),  "32/32", "32 × h100-80g", m("gpu-h100-09..40 (4)"),   "1d4h"],
        [t("qwen2-vl-finetune"), m("team-vision"),   b("Running",   "running",   "online"),  "16/16", "16 × h100-80g", m("gpu-h100-41..56 (2)"),   "38m"],
        [t("qwen2-14b-dpo"),     m("team-llm"),      b("Pending",   "pending"),                "0/16",  "16 × h100-80g", mu("<none>"),               "2m"],
        [t("yolov8-finetune"),   m("team-vision"),   b("Succeeded", "succeeded"),              "0/4",   "4 × l40-48g",   m("gpu-l40-02"),            "3h"],
        [t("mamba-ablation"),    m("team-research"), b("OOMKilled", "danger",    "offline"),   "0/2",   "2 × a100-80g",  m("gpu-a100-05"),           "23m"],
    ],
)

_INFERENCES = _Page(
    path="/inferences",
    label="推理服务",
    title="推理服务",
    subtitle="HPA 自动扩缩，内置 Playground 调试与请求历史。",
    cta={"label": "发布推理", "href": "/inferences?new=1", "icon": "zap"},
    row_icon={"name": "zap", "classes": _ICON_CYAN},
    columns=[
        {"label": "名称",     "key": "name"},
        {"label": "命名空间", "key": "namespace"},
        {"label": "状态",     "key": "status"},
        {"label": "READY",    "key": "ready"},
        {"label": "模型",     "key": "model"},
        {"label": "GPU",      "key": "gpu"},
        {"label": "AGE",      "key": "age", "align": "right"},
    ],
    rows=[
        [t("llama3-8b-chat"),      m("team-llm"),      b("Running", "running", "online"), "3/3", m("Llama-3-8B-Instruct"),  "1 × h100-80g", "2d"],
        [t("qwen2-vl-7b"),         m("team-vision"),   b("Running", "running", "online"), "2/2", m("Qwen2-VL-7B-Instruct"), "1 × a100-80g", "5h"],
        [t("embedding-bge-large"), m("team-platform"), b("Running", "running", "online"), "4/4", m("bge-large-zh-v1.5"),    "0",            "7d"],
        [t("rerank-bge-v2"),       m("team-platform"), b("Pending", "pending"),            "0/1", m("bge-reranker-v2"),      "0",            "1m"],
    ],
)

_COMPUTES = _Page(
    path="/computes",
    label="计算服务",
    title="计算服务",
    subtitle="一次性 Job 或常驻 Deployment，通用容器作业入口。",
    cta={"label": "新建任务", "href": "/computes?new=1", "icon": "cpu"},
    row_icon={"name": "cpu", "classes": _ICON_TEAL},
    columns=[
        {"label": "名称",     "key": "name"},
        {"label": "命名空间", "key": "namespace"},
        {"label": "状态",     "key": "status"},
        {"label": "READY",    "key": "ready"},
        {"label": "镜像",     "key": "image"},
        {"label": "GPU",      "key": "gpu"},
        {"label": "AGE",      "key": "age", "align": "right"},
    ],
    rows=[
        [t("data-prep-shuffle"),    m("team-data"),     b("Running",   "running",   "online"),  "1/1",   m("datatools:v3.2"),      "0",             "8m"],
        [t("nccl-allreduce-bench"), m("team-platform"), b("Running",   "running",   "online"),  "32/32", m("nccl-tests:2.21"),     "32 × h100-80g", "22m"],
        [t("nightly-eval"),         m("team-llm"),      b("Succeeded", "succeeded"),              "0/1",   m("evalkit:0.9"),         "2 × a100-80g",  "3h"],
        [t("jupyter-shared"),       m("team-shared"),   b("Running",   "running",   "online"),  "3/3",   m("jupyter:lab-2024.11"), "0",             "5d"],
    ],
)


# ── Admin pages ───────────────────────────────────────────────────────────────

_POOLS = _Page(
    path="/pools",
    label="资源池",
    title="资源池",
    subtitle="按机型 / 用途划池，绑定节点与命名空间。",
    cta={"label": "新建池", "href": "/pools?new=1", "icon": "plus"},
    row_icon={"name": "database", "classes": _ICON_BLUE},
    # gpuctl pool list → POOL NAME / STATUS / GPU TOTAL / GPU USED / GPU FREE / NODE COUNT
    columns=[
        {"label": "资源池名",   "key": "name"},
        {"label": "状态",       "key": "status"},
        {"label": "GPU 总数",   "key": "total", "align": "right"},
        {"label": "已用 GPU",   "key": "used",  "align": "right"},
        {"label": "空闲 GPU",   "key": "free",  "align": "right"},
        {"label": "节点数",     "key": "count", "align": "right"},
    ],
    rows=[
        [t("pool-h100"), b("Active", "running", "online"), "64", "48", "16", "8"],
        [t("pool-a100"), b("Active", "running", "online"), "96", "71", "25", "12"],
        [t("pool-l40"),  b("Active", "running", "online"), "48", "12", "36", "6"],
        [t("pool-cpu"),  b("Active", "running", "online"), "0",  "0",  "0",  "24"],
    ],
)

_NODES = _Page(
    path="/nodes",
    label="节点",
    title="节点",
    subtitle="物理节点状态、GPU 利用率与标签管理。",
    cta=None,
    row_icon={"name": "server", "classes": _ICON_SLATE},
    # gpuctl node list → NODE NAME / STATUS / GPU TOTAL / GPU USED / GPU FREE / GPU TYPE / IP / POOL
    columns=[
        {"label": "节点名",    "key": "name"},
        {"label": "状态",      "key": "status"},
        {"label": "GPU 总数",  "key": "total", "align": "right"},
        {"label": "已用",      "key": "used",  "align": "right"},
        {"label": "空闲",      "key": "free",  "align": "right"},
        {"label": "GPU 类型",  "key": "type"},
        {"label": "IP",        "key": "ip"},
        {"label": "资源池",    "key": "pool"},
    ],
    rows=[
        [t("gpu-h100-01"), b("Ready",    "running", "online"),   "8", "8", "0", m("h100-80g"), m("10.0.1.11"), m("pool-h100")],
        [t("gpu-h100-02"), b("Ready",    "running", "online"),   "8", "7", "1", m("h100-80g"), m("10.0.1.12"), m("pool-h100")],
        [t("gpu-h100-03"), b("Cordoned", "warning", "degraded"), "8", "0", "0", m("h100-80g"), m("10.0.1.13"), m("pool-h100")],
        [t("gpu-a100-04"), b("Ready",    "running", "online"),   "8", "6", "2", m("a100-80g"), m("10.0.2.14"), m("pool-a100")],
        [t("gpu-a100-05"), b("Ready",    "running", "online"),   "8", "5", "3", m("a100-80g"), m("10.0.2.15"), m("pool-a100")],
        [t("gpu-l40-02"),  b("Ready",    "running", "online"),   "8", "3", "5", m("l40-48g"),  m("10.0.3.22"), m("pool-l40")],
        [t("gpu-h100-07"), b("NotReady", "danger",  "offline"),  "8", "0", "0", m("h100-80g"), m("10.0.1.17"), m("pool-h100")],
        [t("cpu-256-12"),  b("Ready",    "running", "online"),   "0", "0", "0", mu("—"),        m("10.0.4.12"), m("pool-cpu")],
    ],
)

_QUOTAS = _Page(
    path="/quotas",
    label="配额",
    title="配额",
    subtitle="命名空间维度的 GPU / 内存 / Pod 用量与上限。",
    cta=None,
    row_icon={"name": "shield", "classes": _ICON_AMBER},
    # gpuctl quota list → QUOTA NAME / NAMESPACE / CPU / MEMORY / GPU / STATUS
    columns=[
        {"label": "配额名",   "key": "name"},
        {"label": "命名空间", "key": "namespace"},
        {"label": "CPU",      "key": "cpu",    "align": "right"},
        {"label": "MEMORY",   "key": "memory", "align": "right"},
        {"label": "GPU",      "key": "gpu",    "align": "right"},
        {"label": "状态",     "key": "status"},
    ],
    rows=[
        [t("team-llm-quota"),      m("team-llm"),      "512", "2Ti",   "64", b("Active", "running", "online")],
        [t("team-vision-quota"),   m("team-vision"),   "256", "512Gi", "32", b("Active", "running", "online")],
        [t("team-platform-quota"), m("team-platform"), "128", "512Gi", "16", b("Active", "running", "online")],
        [t("team-research-quota"), m("team-research"), "128", "768Gi", "16", b("Active", "running", "online")],
        [t("team-data-quota"),     m("team-data"),     "256", "384Gi", "8",  b("Active", "running", "online")],
    ],
)

_NAMESPACES = _Page(
    path="/namespaces",
    label="命名空间",
    title="命名空间",
    subtitle="租户隔离单元，绑定资源池与配额。",
    cta={"label": "新建命名空间", "href": "/namespaces?new=1", "icon": "plus"},
    row_icon={"name": "folder", "classes": _ICON_INDIGO},
    # gpuctl quota namespace list → NAME / STATUS / AGE
    columns=[
        {"label": "名称",       "key": "name"},
        {"label": "状态",       "key": "status"},
        {"label": "创建时间",   "key": "age", "align": "right"},
    ],
    rows=[
        [t("team-llm"),      b("Active", "running", "online"), "87d"],
        [t("team-vision"),   b("Active", "running", "online"), "54d"],
        [t("team-platform"), b("Active", "running", "online"), "102d"],
        [t("team-research"), b("Active", "running", "online"), "41d"],
        [t("team-data"),     b("Active", "running", "online"), "18d"],
        [t("default"),       b("Active", "running", "online"), "187d"],
    ],
)


_USER_PAGES = (_NOTEBOOKS, _TRAININGS, _INFERENCES, _COMPUTES)
_ADMIN_PAGES = (_POOLS, _NODES, _QUOTAS, _NAMESPACES)


def _render(page: _Page):
    async def _handler(request: Request, user: User):
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
                "rows": page.rows,
            },
        )
    return _handler


def _user_handler(page: _Page):
    handler = _render(page)
    async def _h(request: Request, user: User = Depends(get_current_user)):
        return await handler(request, user)
    return _h


def _admin_handler(page: _Page):
    handler = _render(page)
    async def _h(request: Request, user: User = Depends(require_admin)):
        return await handler(request, user)
    return _h


for page in _USER_PAGES:
    router.add_api_route(page.path, _user_handler(page), methods=["GET"],
                         name=f"page_{page.path.lstrip('/')}")

for page in _ADMIN_PAGES:
    router.add_api_route(page.path, _admin_handler(page), methods=["GET"],
                         name=f"page_admin_{page.path.lstrip('/')}")
