"""快速开始(Quickstart)— 任务模板陈列馆 + 从模板启动。

原型阶段:内置模板硬编码于 TEMPLATES;评审通过后迁移 ConfigMap 存储 + CRUD
(见 docs/templates-design.md §4)。提交复用 gpuctl 的 POST /api/v1/jobs,
与 CLI 同一条代码路径;校验在本层用 BaseParser 纯解析(gpuctl 的 dryRun
字段当前被忽略,不能用于校验 — design doc §8)。

模板 YAML 内嵌覆盖令牌(__NAME__/__NAMESPACE__/__POOL__/__GPU__/__CPU__/
__MEMORY__/__IMAGE__),启动页 Alpine 据表单值实时替换(单向同步;手改
YAML 即进入手动模式)。
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.console.models import User
from src.webui.deps import get_current_user
from src.webui.templating import templates


router = APIRouter(tags=["quickstart"])

_KIND_LABEL = {"compute": "计算服务", "notebook": "Notebook",
               "inference": "推理服务", "training": "训练任务"}

# 与 stubs.py 的行图标风格一致(字符串字面量保留以便 Tailwind 扫描)
_KIND_ICON = {
    "notebook":  ("book-open", "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-400"),
    "training":  ("rocket",    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400"),
    "inference": ("zap",       "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400"),
    "compute":   ("cpu",       "bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-400"),
}


@dataclass(frozen=True)
class Template:
    name: str
    display: str
    description: str
    kind: str
    tags: tuple = ()
    builtin: bool = True
    # 表单默认值(令牌替换的初值)
    gpu: int = 0
    cpu: int = 1
    memory: str = "1Gi"
    image: str = ""
    yaml: str = ""


TEMPLATES: list[Template] = [
    Template(
        name="notebook-jupyter", display="Jupyter Notebook", kind="notebook",
        description="3 分钟拉起 JupyterLab,数据探索 / 轻量开发。CPU 即可运行。",
        tags=("CPU 可跑", "交互开发"), cpu=2, memory="2Gi",
        image="jupyter/minimal-notebook:latest",
        yaml="""kind: notebook
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "JupyterLab 开发环境"
environment:
  image: __IMAGE__
  command: ["start-notebook.sh", "--NotebookApp.token=notebook-token"]
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /home/jovyan/work
""",
    ),
    Template(
        name="notebook-jupyter-gpu", display="Jupyter Notebook(GPU)", kind="notebook",
        description="带 1 张 GPU 的 JupyterLab,模型调试 / 小规模微调。",
        tags=("需 GPU", "交互开发"), gpu=1, cpu=4, memory="16Gi",
        image="jupyter/pytorch-notebook:latest",
        yaml="""kind: notebook
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "GPU JupyterLab 开发环境"
environment:
  image: __IMAGE__
  command: ["start-notebook.sh", "--NotebookApp.token=notebook-token"]
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /home/jovyan/work
""",
    ),
    Template(
        name="training-pytorch", display="PyTorch 单机训练", kind="training",
        description="单节点 PyTorch 训练。把 run 段替换成你的训练命令。",
        tags=("需 GPU", "单机"), gpu=1, cpu=8, memory="32Gi",
        image="pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "PyTorch 单机训练"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      # TODO: 替换为你的训练命令
      python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="training-pytorch-ddp", display="PyTorch 分布式训练(DDP)", kind="training",
        description="2 节点 torchrun DDP;平台注入 MASTER_ADDR / RANK / WORLD_SIZE。",
        tags=("需 GPU", "分布式"), gpu=2, cpu=8, memory="32Gi",
        image="pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "PyTorch DDP 多节点训练"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      torchrun \\
        --nnodes=$WORLD_SIZE --node_rank=$RANK \\
        --nproc_per_node=$GPUCTL_NPROC_PER_NODE \\
        --master_addr=$MASTER_ADDR --master_port=$MASTER_PORT \\
        train.py
distributed:
  mode: multi-node
  workers: 2
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="inference-vllm", display="vLLM 推理服务", kind="inference",
        description="vLLM OpenAI 兼容 API,默认 Qwen2.5-0.5B;改 --model 换模型。",
        tags=("需 GPU", "OpenAI API"), gpu=1, cpu=4, memory="16Gi",
        image="vllm/vllm-openai:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "vLLM OpenAI 兼容推理服务"
environment:
  image: __IMAGE__
  command:
    - python
    - -m
    - vllm.entrypoints.openai.api_server
    - --model=Qwen/Qwen2.5-0.5B-Instruct
    - --host=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /models
""",
    ),
    Template(
        name="compute-web", display="Web 服务(nginx)", kind="compute",
        description="常驻 Web 服务示例,NodePort 对外。CPU 即可运行,适合冒烟验证。",
        tags=("CPU 可跑", "常驻服务"), cpu=1, memory="256Mi",
        image="nginx:alpine",
        yaml="""kind: compute
version: v1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  description: "nginx Web 服务"
environment:
  image: __IMAGE__
  command: ["nginx", "-g", "daemon off;"]
service:
  replicas: 1
  port: 80
  healthCheck: /
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /usr/share/nginx/html
""",
    ),
    Template(
        name="compute-batch", display="批处理任务(Python)", kind="compute",
        description="通用容器批处理:数据预处理 / 评估 / 特征工程。CPU 即可运行。",
        tags=("CPU 可跑", "批处理"), cpu=2, memory="2Gi",
        image="python:3.11-slim",
        yaml="""kind: compute
version: v1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  description: "Python 批处理任务"
environment:
  image: __IMAGE__
  command:
    - python
    - -c
    - |
      import time
      # TODO: 替换为你的处理逻辑
      for i in range(1, 101):
          print(f"[batch] processing chunk {i}/100", flush=True)
          time.sleep(3)
      print("[batch] done")
service:
  replicas: 1
  port: 8000
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
]

_BY_NAME = {t.name: t for t in TEMPLATES}


def _card(t: Template) -> dict:
    icon_name, icon_cls = _KIND_ICON[t.kind]
    return {
        "name": t.name, "display": t.display, "description": t.description,
        "kind": t.kind, "kind_label": _KIND_LABEL[t.kind], "tags": t.tags,
        "builtin": t.builtin, "icon": icon_name, "icon_cls": icon_cls,
    }


@router.get("/quickstart")
async def quickstart(request: Request, kind: str | None = None,
                     user: User = Depends(get_current_user)):
    kinds = [("", "全部")] + [(k, _KIND_LABEL[k]) for k in ("notebook", "training", "inference", "compute")]
    items = [_card(t) for t in TEMPLATES if (not kind or t.kind == kind)]
    return templates.TemplateResponse(
        request, "pages/quickstart.html",
        {"user": user, "cards": items, "kinds": kinds, "active_kind": kind or ""},
    )


@router.get("/quickstart/{name}")
async def quickstart_launch(name: str, request: Request,
                            user: User = Depends(get_current_user)):
    t = _BY_NAME.get(name)
    if not t:
        return RedirectResponse("/quickstart", status_code=302)
    suggested = f"{t.name}-{secrets.token_hex(2)}"
    return templates.TemplateResponse(
        request, "pages/quickstart_launch.html",
        {
            "user": user, "tpl": _card(t), "tpl_yaml": t.yaml,
            "defaults": {
                "name": suggested, "namespace": "default", "pool": "default",
                "gpu": t.gpu, "cpu": t.cpu, "memory": t.memory, "image": t.image,
            },
        },
    )


@router.post("/quickstart/validate")
async def quickstart_validate(request: Request,
                              user: User = Depends(get_current_user)):
    """纯解析校验(不创建任何资源)。"""
    body = await request.json()
    yaml_content = body.get("yamlContent", "")
    try:
        from gpuctl.parser.base_parser import BaseParser
        parsed = BaseParser.parse_yaml(yaml_content)
        return JSONResponse({"ok": True, "kind": parsed.kind,
                             "name": parsed.job.name})
    except Exception as exc:  # ParserError / yaml error → 原样回显
        return JSONResponse({"ok": False, "error": str(exc)})
