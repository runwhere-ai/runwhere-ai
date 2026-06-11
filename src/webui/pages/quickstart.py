"""快速开始(Quickstart)— 任务模板陈列馆 + 从模板启动。

原型阶段:内置模板硬编码于 TEMPLATES;评审通过后迁移 ConfigMap 存储 + CRUD
(见 docs/templates-design.md §4)。提交复用 gpuctl 的 POST /api/v1/jobs,
与 CLI 同一条代码路径;校验在本层用 BaseParser 纯解析(gpuctl 的 dryRun
字段当前被忽略,不能用于校验 — design doc §8)。

模板 YAML 内嵌覆盖令牌(__NAME__/__NAMESPACE__/__POOL__/__GPU__/__CPU__/
__MEMORY__/__IMAGE__),启动页 Alpine 据表单值实时替换(单向同步;手改
YAML 即进入手动模式)。

模板目录以 SkyPilot examples/llm 库为蓝本(详见 workspace docs/BORROW-skypilot.md),
但 gpuctl 无 setup 阶段,故全部选用现成公开镜像。

模板命名规则:启动页会给任务名追加 4 位 hex 后缀;gpuctl 列表的名字简化
启发式会把"第三段 ≥5 位字母数字"当作 pod hash 截断(design doc §8),
因此模板名的第三段必须 <5 字符(或只用两段)。
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

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
    # ── Notebook ──────────────────────────────────────────────────────────────
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
        description="带 1 张 GPU 的 PyTorch JupyterLab,模型调试 / 小规模微调。",
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
        name="notebook-codeserver", display="VS Code(浏览器版)", kind="notebook",
        description="code-server:浏览器里的完整 VS Code,远程开发无需本地 IDE。CPU 即可运行。",
        tags=("CPU 可跑", "交互开发"), cpu=2, memory="2Gi",
        image="codercom/code-server:latest",
        yaml="""kind: notebook
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "code-server 浏览器 IDE"
environment:
  image: __IMAGE__
  command: ["code-server", "--bind-addr", "0.0.0.0:8888", "--auth", "none"]
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /home/coder/project
""",
    ),
    # ── Training ──────────────────────────────────────────────────────────────
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
        name="training-llamafactory", display="LLaMA-Factory 微调(SFT)", kind="training",
        description="零代码 LLM 微调:支持 LoRA/QLoRA/全参,改 model/dataset 即用。",
        tags=("需 GPU", "LLM 微调"), gpu=1, cpu=8, memory="32Gi",
        image="hiyouga/llamafactory:0.9.4",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "LLaMA-Factory SFT 微调"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      llamafactory-cli train \\
        --stage sft --do_train \\
        --model_name_or_path Qwen/Qwen2.5-0.5B-Instruct \\
        --dataset alpaca_zh_demo --template qwen \\
        --finetuning_type lora \\
        --output_dir /output/sft
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /output
""",
    ),
    Template(
        name="training-axolotl", display="Axolotl 微调", kind="training",
        description="配置驱动的 LLM 微调框架(内置 DeepSpeed/FSDP)。挂载你的 config.yaml 即跑。",
        tags=("需 GPU", "LLM 微调"), gpu=1, cpu=8, memory="32Gi",
        image="axolotlai/axolotl:main-latest",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Axolotl 微调"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      # TODO: 把 config.yaml 放到工作目录(NFS)后改这里
      axolotl train /workspace/config.yaml
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /workspace
""",
    ),
    Template(
        name="training-demo-cpu", display="训练冒烟 Demo(CPU)", kind="training",
        description="合成数据训练一个小模型,loss 实时下降。无 GPU 也能完整体验提交→日志→完成。",
        tags=("CPU 可跑", "Demo"), cpu=1, memory="1Gi",
        image="pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "CPU 训练冒烟 Demo(合成数据)"
environment:
  image: __IMAGE__
  command:
    - python
    - -c
    - |
      import torch, torch.nn as nn
      torch.manual_seed(0)
      X = torch.randn(512, 16); y = X @ torch.randn(16, 1) + 0.1 * torch.randn(512, 1)
      model = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, 1))
      opt = torch.optim.Adam(model.parameters(), lr=1e-2)
      for step in range(1, 201):
          loss = nn.functional.mse_loss(model(X), y)
          opt.zero_grad(); loss.backward(); opt.step()
          if step % 10 == 0:
              print(f"[train] step {step}/200 loss={loss.item():.4f}", flush=True)
      print("[train] done")
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="training-gpucheck", display="GPU 环境自检", kind="training",
        description="CUDA vectorAdd 一次性自检任务,验证节点 GPU/驱动可用,跑完即 Succeeded。",
        tags=("需 GPU", "自检"), gpu=1, cpu=1, memory="1Gi",
        image="nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "GPU 环境自检(CUDA vectorAdd)"
environment:
  image: __IMAGE__
  command: ["/cuda-samples/vectorAdd"]
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    # ── Inference ─────────────────────────────────────────────────────────────
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
        name="inference-sglang", display="SGLang 推理服务", kind="inference",
        description="SGLang 高吞吐推理(RadixAttention),OpenAI 兼容;默认 Qwen2.5-0.5B。",
        tags=("需 GPU", "OpenAI API"), gpu=1, cpu=4, memory="16Gi",
        image="lmsysorg/sglang:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "SGLang 推理服务"
environment:
  image: __IMAGE__
  command:
    - python3
    - -m
    - sglang.launch_server
    - --model-path=Qwen/Qwen2.5-0.5B-Instruct
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
        name="inference-tgi", display="TGI 推理服务", kind="inference",
        description="HuggingFace Text Generation Inference;默认 Qwen2.5-0.5B,改 --model-id 换模型。",
        tags=("需 GPU", "HuggingFace"), gpu=1, cpu=4, memory="16Gi",
        image="ghcr.io/huggingface/text-generation-inference:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "TGI 推理服务"
environment:
  image: __IMAGE__
  command:
    - text-generation-launcher
    - --model-id=Qwen/Qwen2.5-0.5B-Instruct
    - --hostname=0.0.0.0
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
    - path: /data
""",
    ),
    Template(
        name="inference-ollama", display="Ollama 推理服务", kind="inference",
        description="本地大模型一键跑:启动即拉取 qwen2.5:0.5b,CPU 也能服务小模型。",
        tags=("CPU 可跑", "本地模型"), cpu=4, memory="8Gi",
        image="ollama/ollama:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Ollama 推理服务"
environment:
  image: __IMAGE__
  command:
    - /bin/sh
    - -c
    - |
      ollama serve &
      sleep 8 && ollama pull qwen2.5:0.5b
      wait
service:
  replicas: 1
  port: 11434
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /root/.ollama
""",
    ),
    Template(
        name="inference-embeddings", display="Embeddings 服务(TEI)", kind="inference",
        description="HuggingFace TEI 向量化服务,默认 bge-small-zh;RAG 标配,CPU 即可运行。",
        tags=("CPU 可跑", "RAG"), cpu=2, memory="4Gi",
        image="ghcr.io/huggingface/text-embeddings-inference:cpu-latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "TEI 向量化服务"
environment:
  image: __IMAGE__
  command:
    - text-embeddings-router
    - --model-id=BAAI/bge-small-zh-v1.5
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
    - path: /data
""",
    ),
    # ── Compute ───────────────────────────────────────────────────────────────
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
    Template(
        name="compute-redis", display="Redis 缓存", kind="compute",
        description="集群内 Redis,给训练/推理任务做特征缓存或消息队列。CPU 即可运行。",
        tags=("CPU 可跑", "中间件"), cpu=1, memory="512Mi",
        image="redis:alpine",
        yaml="""kind: compute
version: v1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  description: "Redis 缓存服务"
environment:
  image: __IMAGE__
  command: ["redis-server", "--appendonly", "no"]
service:
  replicas: 1
  port: 6379
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /data
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
