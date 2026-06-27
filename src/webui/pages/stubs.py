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
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse

# 全局命名空间筛选的 cookie 名(命名空间 = 用户:选中后全局只看该 ns 资源)
NS_COOKIE = "rwai_ns"


def selected_namespace(request: Request) -> Optional[str]:
    """读取全局选中的命名空间;空/未选 → None(= 全部)。"""
    ns = (request.cookies.get(NS_COOKIE) or "").strip()
    return ns or None

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


def del_action(name: str, namespace: str, pod: str) -> dict:
    """删除按钮单元格(列表「操作」列)。前端确认后 fetch DELETE /api/v1/jobs,
    进入「删除中」并轮询 pod 是否从列表消失(真正删完)再移除该行。

    key 用 delbtn 而非 del——del 是 Jinja 关键字,模板里 cell.del 会被解析成
    Undefined 导致按钮渲染不出来(踩过)。
    """
    return {"delbtn": {"name": name, "namespace": namespace, "pod": pod}}

def pool_del_action(name: str) -> dict:
    """删除资源池按钮(列表「操作」列)。确认后 DELETE /api/v1/pools/{name}:摘掉该池所有节点的
    runwhere.ai/pool 标签(节点回落 default 池,不动节点与运行中的任务);池内有关联任务时 gpuctl
    拒绝(→ 409,前端提示先删任务)。default 是隐式兜底池,不给删除按钮。"""
    return {"pooldel": {"name": name}}

def bar(pct: int, label: str | None = None) -> dict:
    return {"bar": pct, "label": label}

def gpu_cell(namespace: str, pod: str, metric: str) -> dict:
    """实时 GPU 进度条单元格。前端按 (ns, pod) 轮询 /api/v1/telemetry 填充。
    metric: "util"(利用率) | "mem"(显存占用率)。数据来自任务 sidecar。"""
    return {"gpu": {"ns": namespace, "pod": pod, "metric": metric}}


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
    {"label": "任务ID",   "key": "jobId"},
    {"label": "任务名称", "key": "name"},
    {"label": "命名空间", "key": "namespace"},
    {"label": "状态",     "key": "status"},
    {"label": "就绪",     "key": "ready"},
    {"label": "节点",     "key": "node"},
    {"label": "IP",       "key": "ip"},
    {"label": "AGE",      "key": "age", "align": "right"},
    {"label": "操作",     "key": "ops", "align": "right"},
]
# GPU 列集:notebook / training / inference 用(compute 是 CPU,不展示)。
# 两列插在「状态」之后(_JOB_COLUMNS 索引 3=状态)。
_JOB_COLUMNS_GPU = _JOB_COLUMNS[:4] + [
    {"label": "GPU 利用率", "key": "gpu_util"},
    {"label": "GPU 占用率", "key": "gpu_mem"},
] + _JOB_COLUMNS[4:]
_POOL_COLUMNS = [
    {"label": "资源池名", "key": "name"},
    {"label": "状态",     "key": "status"},
    {"label": "GPU 总数", "key": "total", "align": "right"},
    {"label": "已用 GPU", "key": "used",  "align": "right"},
    {"label": "空闲 GPU", "key": "free",  "align": "right"},
    {"label": "节点数",   "key": "count", "align": "right"},
    {"label": "操作",     "key": "ops",   "align": "right"},
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
    {"label": "操作",     "key": "ops",    "align": "right"},
]


# ── row builders (live data) ──────────────────────────────────────────────────
async def _job_rows(kind: str, namespace: Optional[str] = None) -> list[list[Any]]:
    """One row per JOB for the given kind.

    gpuctl /api/v1/jobs 返回 Pod 级数据;同一个作业的多个 Pod(失败重试 backoff / 多机训练)
    在此折叠成一行,各 Pod 明细在详情页展示。

    namespace=None → 全部命名空间;否则按全局选中的命名空间过滤(命名空间=用户)。
    """
    from server.routes.jobs import get_jobs  # lazy: gpuctl `server` pkg

    resp = await get_jobs(kind=kind, pool=None, status=None, namespace=namespace, page=1, pageSize=200)
    # compute 是 CPU 任务,不加 GPU 列(列数须与所选 columns 对齐)。
    want_gpu = kind != "compute"
    # 按作业(控制器)归并:gpuctl /api/v1/jobs 是 Pod 级(一个失败重试/多机作业有多个 Pod)。
    # 列表要「一行一个作业」,故在 UI 层按 (namespace, name) 折叠,每个作业取一个代表 Pod——
    # 状态优先级最高的那个(Running > Succeeded > Pending/其它 > Failed)。pod 维度的列
    # (pod 名 / GPU util-mem)显示该代表 Pod;全部 Pod 明细在详情页展示。归并是 UI 展示决策,
    # 不动 gpuctl 的 /api/v1/jobs(对外契约保持 Pod 级、与 CLI 一致)。
    def _status_rank(s: str) -> int:
        s = (s or "").lower()
        if s == "running":
            return 0
        if s in ("succeeded", "completed"):
            return 1
        if s in ("failed", "error", "oomkilled", "crashloopbackoff", "imagepullbackoff"):
            return 3
        return 2  # pending / containercreating / 其它

    reps: dict = {}
    order: list = []
    for it in resp.items:
        key = (it.namespace, it.name)
        if key not in reps:
            reps[key] = it
            order.append(key)
        elif _status_rank(it.status) < _status_rank(reps[key].status):
            reps[key] = it

    rows: list[list[Any]] = []
    for key in order:
        it = reps[key]
        # it.name = 真实作业名(gpuctl 路由从 pod 标签 app/job-name 读,= YAML job.name =
        # 工作负载名):任务名称列显示它、详情页链接用它、删除按它删。
        wl = it.name
        # 行 + 状态格挂 OOB id,供 /_events WebSocket 定点替换:DELETED→删该行、
        # MODIFIED→只换状态格(不动 GPU 格/删除按钮)。详情页用同样的 id 约定。
        id_cell = m(it.jobId)
        id_cell["row_id"] = f"row-{it.namespace}-{kind}-{wl}"
        status_cell = status_badge(it.status)
        status_cell["oob_id"] = f"status-{it.namespace}-{kind}-{wl}"
        row = [
            id_cell,
            link(wl, f"/{kind}s/{wl}?namespace={it.namespace}"),
            m(it.namespace),
            status_cell,
            it.ready,
            _maybe_mono(it.node),
            _maybe_mono(it.ip),
            it.age,
        ]
        if want_gpu:
            # it.jobId 即真实 pod 名(gpuctl: jobId=pod_name),遥测按 pod 存储。
            # 两列插在「状态」(索引 3)之后,与列定义一致。
            row = row[:4] + [
                gpu_cell(it.namespace, it.jobId, "util"),
                gpu_cell(it.namespace, it.jobId, "mem"),
            ] + row[4:]
        # 末尾「操作」列:删除按钮(工作负载名 wl 删,pod=it.jobId 用于轮询是否删完)。
        row.append(del_action(wl, it.namespace, it.jobId))
        rows.append(row)
    return rows


async def _pool_rows(namespace: Optional[str] = None) -> list[list[Any]]:
    # 资源池 / 节点是集群级,不随命名空间过滤(忽略 namespace)。
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
            # default 是隐式兜底池(节点无 pool 标签即归它),不可删 → 占位破折号保持列对齐
            mu("—") if p["name"] == "default" else pool_del_action(p["name"]),
        ]
        for p in pools
    ]


async def _namespace_rows(namespace: Optional[str] = None) -> list[list[Any]]:
    # 命名空间管理页本身列出全部命名空间(不自我过滤)。
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
    rows_fn: Callable[[Optional[str]], Awaitable[list[list[Any]]]]
    row_icon: dict | None = None


_NOTEBOOKS = _Page(
    path="/notebooks", label="Notebook（开发调试）", title="Notebook",
    subtitle="3 分钟拉起 Jupyter，开箱即用的训练 / 数据探索环境。",
    cta={"label": "新建 Notebook", "href": "/quickstart?kind=notebook", "icon": "plus"},
    row_icon={"name": "book-open", "classes": _ICON_PINK},
    columns=_JOB_COLUMNS_GPU, rows_fn=functools.partial(_job_rows, "notebook"),
)
_TRAININGS = _Page(
    path="/trainings", label="训练任务", title="训练任务",
    subtitle="表单 / YAML 双模式提交，实时日志与 dryRun 行号定位。",
    cta={"label": "新建训练", "href": "/quickstart?kind=training", "icon": "rocket"},
    row_icon={"name": "rocket", "classes": _ICON_PURPLE},
    columns=_JOB_COLUMNS_GPU, rows_fn=functools.partial(_job_rows, "training"),
)
_INFERENCES = _Page(
    path="/inferences", label="推理服务", title="推理服务",
    subtitle="HPA 自动扩缩，内置 Playground 调试与请求历史。",
    cta={"label": "发布推理", "href": "/quickstart?kind=inference", "icon": "zap"},
    row_icon={"name": "zap", "classes": _ICON_CYAN},
    columns=_JOB_COLUMNS_GPU, rows_fn=functools.partial(_job_rows, "inference"),
)
_COMPUTES = _Page(
    path="/computes", label="计算服务", title="计算服务",
    subtitle="一次性 Job 或常驻 Deployment，通用容器作业入口。",
    cta={"label": "新建任务", "href": "/quickstart?kind=compute", "icon": "cpu"},
    row_icon={"name": "cpu", "classes": _ICON_TEAL},
    columns=_JOB_COLUMNS, rows_fn=functools.partial(_job_rows, "compute"),
)
_POOLS = _Page(
    path="/pools", label="资源池", title="资源管理",
    subtitle="资源池与节点统一管理，按机型 / 用途划池并绑定物理节点。",
    cta={"label": "新建池", "href": "/pools/new", "icon": "plus"},
    row_icon={"name": "database", "classes": _ICON_BLUE},
    columns=_POOL_COLUMNS, rows_fn=_pool_rows,
)
_NAMESPACES = _Page(
    path="/namespaces", label="命名空间", title="命名空间",
    subtitle="租户隔离单元，绑定资源池与配额。",
    cta={"label": "新建命名空间", "href": "/namespaces/new", "icon": "plus"},
    row_icon={"name": "folder", "classes": _ICON_INDIGO},
    columns=_NS_COLUMNS, rows_fn=_namespace_rows,
)

_USER_PAGES = (_NOTEBOOKS, _TRAININGS, _INFERENCES, _COMPUTES)
_ADMIN_PAGES = (_POOLS, _NAMESPACES)


async def _render(request: Request, user: User, page: _Page):
    ns = selected_namespace(request)
    try:
        rows = await page.rows_fn(ns)
    except Exception as exc:  # never 500 a full page render; show empty + log
        logger.warning("page %s: failed to load live data (%s)", page.path, exc)
        rows = []
    # 任务列表(用户页)订阅 /_events WebSocket → 行的状态/删除经定点 OOB 实时更新(无轮询)。
    # ws_kind 由路径推导(/trainings→training);ws_ns 用选中命名空间,空=全部(用通配 *)。
    is_job_list = page in _USER_PAGES
    ws_kind = page.path.lstrip("/").rstrip("s") if is_job_list else None
    ws_ns = (ns or "*") if is_job_list else None
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
            "current_ns": ns,
            "ws_kind": ws_kind,
            "ws_ns": ws_ns,
        },
    )


@router.get("/set-namespace", include_in_schema=False)
async def set_namespace(request: Request, ns: str = "", next: str = "/dashboard",
                        user: User = Depends(get_current_user)):
    """设置全局命名空间筛选(写 cookie),跳回来源页。ns 为空 = 全部命名空间。"""
    # next 只接受站内相对路径,避免开放重定向
    target = next if next.startswith("/") and not next.startswith("//") else "/dashboard"
    resp = RedirectResponse(target, status_code=303)
    ns = (ns or "").strip()
    if ns:
        resp.set_cookie(NS_COOKIE, ns, max_age=31536000, samesite="lax", path="/")
    else:
        resp.delete_cookie(NS_COOKIE, path="/")
    return resp


@router.get("/api/namespaces", include_in_schema=False)
async def api_namespaces(request: Request, user: User = Depends(get_current_user)):
    """命名空间列表 + 当前选中,供顶栏选择器拉取。"""
    names: list[str] = []
    try:
        from server.routes.namespaces import list_namespaces
        resp = await list_namespaces()
        names = [it["name"] for it in resp.get("items", []) if it.get("name")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("api/namespaces failed: %s", exc)
    return JSONResponse({"namespaces": names, "current": selected_namespace(request) or ""})


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


# ── 任务详情 + 日志 + notebook 访问（功能 1/2/3）──────────────────────────────
_KIND_LABEL = {"compute": "计算服务", "notebook": "Notebook",
               "inference": "推理服务", "training": "训练任务"}


def _pod_selector(kind: str, name: str) -> dict:
    # training 底层是 Job(job-name=)，其余是 Deployment/StatefulSet(app=)
    return {"job-name": name} if kind == "training" else {"app": name}


async def _job_detail_ctx(kind: str, name: str, namespace: str, public_host: Optional[str] = None,
                          base_url: Optional[str] = None) -> dict:
    import os
    import re

    list_url = f"/{kind}s"
    ctx: dict[str, Any] = {
        "kind": kind, "kind_label": _KIND_LABEL.get(kind, kind), "name": name,
        "namespace": namespace, "list_url": list_url,
        "logs_url": f"{list_url}/{name}/logs/fragment?namespace={namespace}",
        "logs_ws_path": f"{list_url}/{name}/logs/ws?namespace={namespace}",
        "not_found": False, "status": "Unknown", "status_tone": "neutral",
        "age": "—", "pool": "default", "priority": "medium", "resource_type": "—",
        "image": None, "command": None, "resources": {}, "pods": [], "events": [],
        "access": None, "ssh_cmd": None,
    }
    try:
        from server.routes.jobs import get_job_detail
        d = await get_job_detail(jobId=name, namespace=namespace)
    except Exception as exc:  # 404 / 500 → 渲染“未找到”而非崩
        logger.warning("job detail %s/%s: %s", kind, name, exc)
        ctx["not_found"] = True
        return ctx

    sb = status_badge(d.status)
    ctx.update(status=sb["badge"], status_tone=sb["tone"], age=d.age, pool=d.pool,
               priority=d.priority, resource_type=d.resource_type, events=d.events or [])

    # 镜像 / 命令 / 资源 来自重建的 gpuctl 规格(yaml_content)
    # gpuctl mapper 对缺失字段会填字面量 "N/A",归一成 None 以便走 Pod spec 兜底
    def _na(v):
        return None if v in (None, "", "N/A") else v

    yc = d.yaml_content if isinstance(d.yaml_content, dict) else {}
    env = yc.get("environment") or {}
    res = yc.get("resources") or {}
    ctx["image"] = _na(env.get("image"))
    cmd = env.get("command")
    ctx["command"] = _na(cmd if isinstance(cmd, str) else (" ".join(map(str, cmd)) if isinstance(cmd, list) else None))
    ctx["resources"] = {"gpu": res.get("gpu", 0), "cpu": res.get("cpu", "—"),
                        "memory": res.get("memory", "—"), "pool": res.get("pool", d.pool)}

    # Pod 列表(+ 控制器规格缺字段时的兜底来源)
    raw_pods: list = []
    try:
        from gpuctl.client.job_client import JobClient
        raw_pods = JobClient().list_pods(d.namespace, labels=_pod_selector(kind, name))
        for p in raw_pods:
            ctx["pods"].append({
                "name": p.get("name"),
                "phase": (p.get("status") or {}).get("phase", "Unknown"),
                "node": (p.get("spec") or {}).get("node_name") or "—",
                "ip": (p.get("status") or {}).get("pod_ip") or "—",
            })
    except Exception as exc:
        logger.warning("list pods %s: %s", name, exc)

    # 兜底:StatefulSet(notebook)等控制器的重建规格不含 containers
    # (gpuctl _statefulset_to_dict 缺字段),镜像/命令/资源改从 Pod spec 取。
    if raw_pods and (not ctx["image"] or not ctx["command"] or ctx["resources"].get("memory") in (None, "—")):
        c0 = ((raw_pods[0].get("spec") or {}).get("containers") or [{}])[0]
        if not ctx["image"]:
            ctx["image"] = c0.get("image")
        if not ctx["command"]:
            cmd = list(c0.get("command") or []) + list(c0.get("args") or [])
            ctx["command"] = " ".join(str(x) for x in cmd) if cmd else None
        limits = ((c0.get("resources") or {}).get("limits") or {})
        if limits and ctx["resources"].get("memory") in (None, "—"):
            ctx["resources"] = {
                "gpu": limits.get("nvidia.com/gpu", ctx["resources"].get("gpu", 0)),
                "cpu": limits.get("cpu", ctx["resources"].get("cpu", "—")),
                "memory": limits.get("memory", "—"),
                "pool": ctx["resources"].get("pool", d.pool),
            }

    # 访问方式(inference/compute/notebook 统一:对外 / 节点 / 集群内;notebook 另带 token)。
    # gpuctl access_methods 给两条:node_port_access(节点内网 IP:NodePort,节点/局域网级)
    # + pod_ip_access(Pod IP:端口,真·集群内,Pod 重启会变)。两条都展示——别再把节点地址错当"集群内"。
    am = d.access_methods or {}
    npa = am.get("node_port_access") or {}
    pia = am.get("pod_ip_access") or {}
    node_url = npa.get("url")     # http://<节点内网IP>:<NodePort>
    pod_url = pia.get("url")      # http://<PodIP>:<端口>
    if kind == "notebook":
        # notebook 走 console 反向代理(/nb/<ns>/<name>/),不依赖 NodePort/portproxy。
        # token 多源提取:命令行 / NOTEBOOK_ARGS / JUPYTER_TOKEN。
        env_map = {}
        for ev in (env.get("env") or []):
            if isinstance(ev, dict):
                if "name" in ev and "value" in ev:   # k8s 风格 {name,value}
                    env_map[ev["name"]] = ev["value"]
                else:                                  # gpuctl 风格 {key: value}
                    env_map.update(ev)
        search = " ".join(filter(None, [ctx["command"], env_map.get("NOTEBOOK_ARGS")]))
        mt = re.search(r"--(?:Notebook|Server)App\.token=(\S+)", search)
        token = mt.group(1) if mt else env_map.get("JUPYTER_TOKEN")
        # 落地路径按工具区分:Jupyter 的 UI 在 /lab;marimo / code-server 的 UI 在 base-url 根。
        _landing = "/" if re.search(r"marimo|code-server", ctx["command"] or "") else "/lab"
        proxy_path = f"/nb/{d.namespace}/{name}{_landing}" + (f"?token={token}" if token else "")
        ctx["access"] = {
            "public_url": (base_url.rstrip("/") + proxy_path) if base_url else proxy_path,
            "public_via": "console",
            "node_url": node_url,
            "pod_url": pod_url,
            "token": token,
        }
    else:
        # inference/compute:对外用「你访问控制台用的 Host」+ NodePort(适配任意域名/IP/ingress);
        #   RWAI_PUBLIC_NODE_HOST > 该 Host > localhost。无 NodePort 时仅展示集群内 / 节点地址。
        host = os.getenv("RWAI_PUBLIC_NODE_HOST") or public_host or "localhost"
        public_url = f"http://{host}:{npa['node_port']}/" if npa.get("node_port") else None
        if public_url or node_url or pod_url:
            ctx["access"] = {
                "public_url": public_url,
                "public_via": "nodeport",
                "node_url": node_url,
                "pod_url": pod_url,
                "token": None,
            }

    # SSH / 进入容器(notebook 无原生 sshd → 给 kubectl exec 等价命令)
    pod_name = ctx["pods"][0]["name"] if ctx["pods"] else (f"{name}-0" if kind == "notebook" else name)
    ctx["ssh_cmd"] = f"kubectl exec -it -n {d.namespace} {pod_name} -- /bin/sh"

    # 存储挂载:集群级 NFS 已注册(kube-system/gpuctl-config)时,所有任务自动挂载
    # /home/jovyan(读写,按命名空间隔离)+ /datasets(只读)。未配置则不展示。
    try:
        from gpuctl.builder.base_builder import BaseBuilder
        _nfs = BaseBuilder.read_nfs_config()
    except Exception as exc:
        _nfs = None
        logger.debug("read nfs config %s: %s", name, exc)
    if _nfs:
        _server, _path = _nfs
        ctx["nfs"] = {
            "server": _server,
            "home": f"{_server}:{_path}/home/{d.namespace}",
            "datasets": f"{_server}:{_path}/datasets",
        }

    # 分布式训练:从实时 Job spec 推导(重建的 yaml_content 不含 distributed,
    # 且 _job_to_dict 不带 spec)。Indexed 完成模式 + completions>1 即多机多卡;
    # 各 worker pod(<name>-0…<name>-N)已在 ctx["pods"] 中。
    if kind == "training":
        try:
            from kubernetes import client as _k8s
            _spec = _k8s.BatchV1Api().read_namespaced_job(name, d.namespace).spec
            if getattr(_spec, "completion_mode", None) == "Indexed" and (_spec.completions or 1) > 1:
                ctx["distributed"] = {
                    "mode": "multi-node",
                    "workers": _spec.completions,
                    "headless": f"{name}-headless.{d.namespace}.svc.cluster.local",
                }
        except Exception as exc:
            logger.debug("distributed probe %s: %s", name, exc)

    return ctx


def _detail_handler(kind: str):
    async def _h(name: str, request: Request, namespace: str = "default",
                 user: User = Depends(get_current_user)):
        host = (request.headers.get("host") or "").split(":")[0] or None
        ctx = await _job_detail_ctx(kind, name, namespace, public_host=host, base_url=str(request.base_url))
        return templates.TemplateResponse(request, "pages/_job_detail.html", {"user": user, **ctx})
    return _h


def _logs_handler(kind: str):
    async def _h(name: str, request: Request, namespace: str = "default", tail: int = 200,
                 user: User = Depends(get_current_user)):
        logs: list = []
        try:
            from server.routes.jobs import get_job_logs
            resp = await get_job_logs(jobId=name, follow=False, tail=tail, pod=None)
            logs = resp.logs or []
        except Exception as exc:
            logger.warning("job logs %s: %s", name, exc)
        return templates.TemplateResponse(request, "pages/_log_fragment.html", {"logs": logs})
    return _h


def _logs_ws_handler(kind: str):
    """真·实时日志:后台线程跑同步 follow 生成器 → asyncio.Queue → WebSocket。"""
    async def _h(websocket: WebSocket, name: str, namespace: str = "default"):
        import asyncio
        import threading

        await websocket.accept()
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        stop = threading.Event()

        def _push(item):
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass

        def _producer():
            try:
                from gpuctl.client.log_client import LogClient
                for line in LogClient().stream_job_logs(name, namespace):
                    if stop.is_set():
                        break
                    loop.call_soon_threadsafe(_push, line)
            except Exception as exc:  # noqa: BLE001
                loop.call_soon_threadsafe(_push, f"[stream error] {exc}")
            finally:
                loop.call_soon_threadsafe(_push, None)  # 哨兵 = 流结束

        threading.Thread(target=_producer, daemon=True).start()
        try:
            while True:
                line = await q.get()
                if line is None:
                    break
                await websocket.send_text(line)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("logs ws %s: %s", name, exc)
        finally:
            stop.set()
            try:
                await websocket.close()
            except Exception:
                pass
    return _h


for _jp in _USER_PAGES:
    _k = _jp.path.lstrip("/").rstrip("s")          # /notebooks -> notebook
    router.add_api_route(_jp.path + "/{name}", _detail_handler(_k),
                         methods=["GET"], name=f"detail_{_k}")
    router.add_api_route(_jp.path + "/{name}/logs/fragment", _logs_handler(_k),
                         methods=["GET"], name=f"logs_{_k}")
    router.add_api_websocket_route(_jp.path + "/{name}/logs/ws", _logs_ws_handler(_k),
                                   name=f"logsws_{_k}")


# ── detail pages ──────────────────────────────────────────────────────────────
@router.get("/pools/new")
async def pool_new(request: Request, user: User = Depends(require_admin)):
    """新建资源池表单页。

    资源池 = 一组打了 runwhere.ai/pool=<name> 标签的节点(gpuctl 没有独立的池对象,list_pools
    按节点标签聚合)——故必须选中至少一个节点,空池无法持久化。提交走与 CLI apply 相同的
    POST /api/v1/pools(→ PoolClient.create_pool)。

    必须注册在 /pools/{pool_name}/nodes 之前(literal 路径优先,避免 new 被当成 pool_name)。"""
    nodes: list[dict[str, Any]] = []
    existing_pools: list[str] = []
    try:
        from gpuctl.client.pool_client import PoolClient
        from gpuctl.constants import Labels

        pc = PoolClient.get_instance()
        for n in pc.list_nodes():
            res = n.get("resources", {})
            gtypes = n.get("gpu_types") or []
            nodes.append({
                "name": n["name"],
                "status": n.get("status", "active"),
                "gpuTotal": res.get("gpu_total", 0),
                "gpuFree": res.get("gpu_free", 0),
                "gpuType": gtypes[0] if gtypes else "",
                # 节点当前所属池(单值标签);选入新池即从原池迁出,前端据此给迁移提示。
                "pool": (n.get("labels") or {}).get(Labels.POOL, "default"),
            })
        existing_pools = [p["name"] for p in pc.list_pools()]
    except Exception as exc:  # 取不到节点也照常渲染(空态),不 500 整页
        logger.warning("pool_new: failed to load nodes (%s)", exc)
    return templates.TemplateResponse(
        request, "pages/pool_new.html",
        {"user": user, "nodes": nodes, "existing_pools": existing_pools},
    )


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


@router.get("/namespaces/new")
async def namespace_new(request: Request, user: User = Depends(require_admin)):
    """新建命名空间表单页。提交走 gpuctl 的 POST /api/v1/quotas——「建配额即建命名空间」
    (QuotaClient.create_quota → _ensure_namespace_exists 自动建 ns + 挂 NFS Home)。
    必须注册在 /namespaces/{namespace}/quotas 之前(literal 路径,避免被参数路由吞掉)。"""
    return templates.TemplateResponse(request, "pages/namespace_new.html", {"user": user})


@router.get("/namespaces/{namespace}/quotas")
async def namespace_quotas(namespace: str, request: Request, user: User = Depends(require_admin)):
    rows: list[list[Any]] = []
    has_quota = False
    try:
        from gpuctl.client.quota_client import QuotaClient

        q = QuotaClient().get_quota(namespace)
        if q:
            has_quota = True
            hard = q.get("hard", {})
            rows.append([
                t(q.get("name", namespace)),
                m(namespace),
                str(hard.get("cpu", "—")),
                str(hard.get("memory", "—")),
                str(hard.get("nvidia.com/gpu", "0")),
                status_badge(q.get("status", "Active")),
                # 编辑动作放在「行内操作」列——对应到这一行(=该命名空间)的配额,语义明确。
                action("编辑配额", f"/namespaces/{namespace}/quotas/edit", "settings"),
            ])
    except Exception as exc:
        logger.warning("namespace_quotas %s: %s", namespace, exc)
    # 有配额→编辑入口在行内操作列(见上);页头不再放「编辑」(右上角是「新建」语义,且无法对应到具体行)。
    # 无配额→表里没有行可承载行内动作,此时页头给「设置配额」作为该命名空间的创建入口。
    cta = None if has_quota else {
        "label": "设置配额",
        "href": f"/namespaces/{namespace}/quotas/edit",
        "icon": "settings",
    }
    return templates.TemplateResponse(
        request, "pages/_listing.html",
        {
            "user": user,
            "page_title": f"{namespace} · 配额",
            "page_subtitle": "该命名空间的 GPU / 内存 / Pod 用量与上限（未设置配额则为空）。",
            "primary_cta": cta,
            "row_icon": {"name": "shield", "classes": _ICON_AMBER},
            "columns": _QUOTA_COLUMNS,
            "rows": rows,
        },
    )


@router.get("/namespaces/{namespace}/quotas/edit")
async def namespace_quota_edit(namespace: str, request: Request, user: User = Depends(require_admin)):
    """编辑/设置某命名空间的配额。预填当前上限,提交走 PUT /api/v1/quotas(幂等 upsert)。
    必须注册在 /namespaces/{namespace}/quotas 之后亦可(路径多一段 /edit,不冲突)。"""
    quota_name = f"{namespace}-quota"
    cpu = memory = gpu = ""
    try:
        from gpuctl.client.quota_client import QuotaClient

        q = QuotaClient().get_quota(namespace)
        if q:
            quota_name = q.get("name", quota_name)
            hard = q.get("hard", {})
            # gpuctl 对未设上限填 "unlimited" 字面量 → 归一成空串(表单留空 = 不限制)。
            def _val(v: Any) -> str:
                return "" if v in (None, "", "unlimited", "—") else str(v)
            cpu = _val(hard.get("cpu"))
            memory = _val(hard.get("memory"))
            gpu = _val(hard.get("nvidia.com/gpu"))
    except Exception as exc:
        logger.warning("namespace_quota_edit %s: %s", namespace, exc)
    return templates.TemplateResponse(
        request, "pages/quota_edit.html",
        {
            "user": user,
            "namespace": namespace,
            "is_default": namespace == "default",
            "quota_name": quota_name,
            "cpu": cpu,
            "memory": memory,
            "gpu": gpu,
        },
    )


@router.get("/nodes", include_in_schema=False)
async def nodes_redirect():
    return RedirectResponse("/pools", status_code=302)


@router.get("/quotas", include_in_schema=False)
async def quotas_redirect():
    return RedirectResponse("/namespaces", status_code=302)
