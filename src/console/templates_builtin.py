"""内置任务模板(随代码发布,只读)。

目录以 SkyPilot docs/source/examples 为蓝本(全量对照见 docs/templates-design.md
§3.1)。gpuctl 无 setup 阶段,两个替代:现成官方镜像,或「运行时 pip install
前缀」充当穷人版 setup。

模板 YAML 内嵌覆盖令牌(__NAME__/__NAMESPACE__/__POOL__/__GPU__/__CPU__/
__MEMORY__/__IMAGE__),启动页据表单值实时替换。

模板命名规则:启动页会给任务名追加 4 位 hex 后缀;gpuctl 列表的名字简化
启发式会把"第三段 ≥5 位字母数字"当作 pod hash 截断,因此模板名的第三段
必须 <5 字符(或只用两段)。

自定义模板的文件存储见 template_store.py。
"""
from __future__ import annotations

from dataclasses import dataclass


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
        image="quay.io/jupyter/pytorch-notebook:latest",
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
        tags=("需 GPU", "单机"), gpu=1, cpu=8, memory="24Gi",
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
        description="多机多卡 torchrun DDP;改 distributed.workers 调整节点数,平台注入 MASTER_ADDR / RANK / WORLD_SIZE,checkpoint 写 /home/jovyan 自动共享。",
        tags=("需 GPU", "分布式"), gpu=2, cpu=8, memory="24Gi",
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
resources:
  pool: __POOL__
  nodes: 2               # 节点数;>1 启用多机(Indexed Job + Headless + DDP env 注入)
  gpu: __GPU__           # 每节点 GPU 数(总卡 = nodes × gpu)
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="training-llamafactory", display="LLaMA-Factory 微调(SFT)", kind="training",
        description="零代码 LLM 微调:支持 LoRA/QLoRA/全参,改 model/dataset 即用。",
        tags=("需 GPU", "LLM 微调"), gpu=1, cpu=8, memory="24Gi",
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
        tags=("需 GPU", "LLM 微调"), gpu=1, cpu=8, memory="24Gi",
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
        description="nvidia-smi 一次性自检,验证节点 GPU/驱动在容器内可用,跑完即 Succeeded。兼容新架构(Blackwell 等)。",
        tags=("需 GPU", "自检"), gpu=1, cpu=1, memory="1Gi",
        image="nvidia/cuda:12.8.0-base-ubuntu22.04",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "GPU 环境自检(nvidia-smi)"
environment:
  image: __IMAGE__
  command: ["nvidia-smi"]
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    # ── Inference ─────────────────────────────────────────────────────────────
    Template(
        name="inference-vllm-multinode", display="vLLM 多机推理(模型并行)", kind="inference",
        description="一个模型跨节点切分 serving:resources.nodes>1 → StatefulSet + Ray;rank0=head 对外,其余 worker 入群。改 --model 换大模型、nodes 调节点数。",
        tags=("需 GPU", "多机", "OpenAI API"), gpu=2, cpu=8, memory="32Gi",
        image="vllm/vllm-openai:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: high
  description: "vLLM 多机模型并行 serving(Ray)"
environment:
  image: __IMAGE__
  command:
    - bash
    - -c
    - |
      # rank 0 = head(起 Ray 头 + 对外 vLLM 服务);其余 = worker,加入 head 的 Ray 集群。
      # 平台注入:RUNWHERE_NODE_RANK / RUNWHERE_NUM_NODES / RUNWHERE_GPUS_PER_NODE / RUNWHERE_HEAD_ADDR
      if [ "$RUNWHERE_NODE_RANK" = "0" ]; then
        ray start --head --port=6379
        python3 -m vllm.entrypoints.openai.api_server \\
          --model=Qwen/Qwen2.5-0.5B-Instruct \\
          --tensor-parallel-size=$RUNWHERE_GPUS_PER_NODE \\
          --pipeline-parallel-size=$RUNWHERE_NUM_NODES \\
          --host=0.0.0.0 --port=8000
      else
        until ray start --address="$RUNWHERE_HEAD_ADDR:6379" --block; do echo "waiting for head..."; sleep 5; done
      fi
service:
  replicas: 1            # 多机时固定 1(StatefulSet 副本数取 resources.nodes)
  port: 8000             # 只在 head(pod-0)上暴露
resources:
  pool: __POOL__
  nodes: 2               # 节点数;>1 启用多机(与 gpu/cpu/memory 并列;总卡 = nodes × gpu)
  gpu: __GPU__           # 每节点 GPU 数
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
    - python3
    - -m
    - vllm.entrypoints.openai.api_server
    - --model=Qwen/Qwen2.5-0.5B-Instruct
    - --host=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
  healthCheck: /
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
  command:
    - /bin/sh
    - -c
    - |
      [ -f /usr/share/nginx/html/index.html ] || echo '<h1>runwhere-ai · nginx</h1><p>把你的静态文件放到 /usr/share/nginx/html 覆盖此页。</p>' > /usr/share/nginx/html/index.html
      exec nginx -g 'daemon off;'
service:
  replicas: 1
  port: 80
  healthCheck: tcp     # nginx「端口在听」即健康,不看 / 返回什么(网站根目录由用户决定,空根会 403)
  startupTimeout: 5m   # 服务启动到就绪最多等这么久;超时才判失败重启。compute 服务通常起得快,慢的(如装依赖)可调大。
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
  healthCheck: tcp     # redis 是 TCP 服务,没 HTTP 健康端点 → 只探端口能否连上
  startupTimeout: 5m
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
    # ── 第二批(SkyPilot examples 全量对照后收编;运行时 pip install 充当 setup)──
    Template(
        name="notebook-marimo", display="Marimo Notebook", kind="notebook",
        description="新一代响应式 Python notebook(纯 .py 文件,git 友好)。运行时安装,CPU 即可。",
        tags=("CPU 可跑", "交互开发"), cpu=2, memory="2Gi",
        image="python:3.11-slim",
        yaml="""kind: notebook
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Marimo 响应式 notebook"
environment:
  image: __IMAGE__
  command:
    - /bin/sh
    - -c
    - |
      pip install -q marimo
      marimo edit --host 0.0.0.0 --port 8888 --no-token --base-url=/nb/__NAMESPACE__/__NAME__
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /notebooks
""",
    ),
    Template(
        name="training-unsloth", display="Unsloth 微调", kind="training",
        description="2-5x 提速、省显存的 LLM 微调(LoRA/QLoRA),单卡即可调 7B。",
        tags=("需 GPU", "LLM 微调"), gpu=1, cpu=8, memory="24Gi",
        image="unsloth/unsloth:latest",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Unsloth 高效微调"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      # TODO: 替换为你的 unsloth 微调脚本
      python -c "import unsloth; print('unsloth ready')"
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
        name="training-nemo", display="NVIDIA NeMo 训练", kind="training",
        description="NVIDIA 官方大模型训练框架(预训练/SFT/对齐),适合多卡大任务。",
        tags=("需 GPU", "大模型"), gpu=2, cpu=16, memory="64Gi",
        image="nvcr.io/nvidia/nemo:24.07",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "NeMo 大模型训练"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      # TODO: 替换为你的 NeMo 训练脚本
      python -c "import nemo; print('NeMo', nemo.__version__)"
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
        name="training-deepspeed", display="DeepSpeed 训练", kind="training",
        description="ZeRO 显存优化训练。运行时安装 deepspeed,替换启动命令即用。",
        tags=("需 GPU", "分布式"), gpu=1, cpu=8, memory="24Gi",
        image="pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "DeepSpeed 训练"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      pip install -q deepspeed
      ds_report
      # TODO: deepspeed --num_gpus=$GPUCTL_NPROC_PER_NODE train.py --deepspeed ds_config.json
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="training-ray", display="Ray 任务(单节点)", kind="training",
        description="Ray 并行计算/调参(tune)。单 Pod 内起本地 Ray,适合中小规模并行。",
        tags=("CPU 可跑", "并行计算"), cpu=4, memory="8Gi",
        image="rayproject/ray:latest",
        yaml="""kind: training
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Ray 单节点并行任务"
environment:
  image: __IMAGE__
  command:
    - /bin/bash
    - -c
    - |
      # TODO: 替换为你的 Ray 脚本(ray.init() 本地模式)
      python -c "import ray; ray.init(); print(ray.cluster_resources())"
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
    Template(
        name="inference-lorax", display="LoRAX 多适配器推理", kind="inference",
        description="一个基座模型动态加载上百个 LoRA 适配器(Predibase),多租户微调服务。",
        tags=("需 GPU", "LoRA"), gpu=1, cpu=4, memory="16Gi",
        image="ghcr.io/predibase/lorax:main",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "LoRAX 多适配器推理"
environment:
  image: __IMAGE__
  command:
    - lorax-launcher
    - --model-id=Qwen/Qwen2.5-0.5B-Instruct
    - --hostname=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
        name="inference-tabby", display="Tabby 代码补全", kind="inference",
        description="自托管 AI 编程助手(Copilot 替代),IDE 插件直连。CPU 也能跑小模型。",
        tags=("CPU 可跑", "编程助手"), cpu=4, memory="8Gi",
        image="tabbyml/tabby:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Tabby 代码补全服务"
environment:
  image: __IMAGE__
  command:
    - /opt/tabby/bin/tabby
    - serve
    - --model=TabbyML/StarCoder-1B
    - --device=cpu
service:
  replicas: 1
  port: 8080
  healthCheck: /
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
        name="inference-deepseek", display="DeepSeek-R1 蒸馏版", kind="inference",
        description="DeepSeek-R1-Distill-Qwen-1.5B 推理(vLLM),单卡可跑的推理小钢炮。",
        tags=("需 GPU", "模型预设"), gpu=1, cpu=4, memory="16Gi",
        image="vllm/vllm-openai:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "DeepSeek-R1 蒸馏版推理"
environment:
  image: __IMAGE__
  command:
    - python3
    - -m
    - vllm.entrypoints.openai.api_server
    - --model=deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B
    - --host=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
        name="inference-qwen", display="Qwen2.5-7B-Instruct", kind="inference",
        description="Qwen2.5-7B 指令模型推理(vLLM),建议 ≥24G 显存。",
        tags=("需大显存", "模型预设"), gpu=1, cpu=8, memory="24Gi",
        image="vllm/vllm-openai:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "Qwen2.5-7B-Instruct 推理"
environment:
  image: __IMAGE__
  command:
    - python3
    - -m
    - vllm.entrypoints.openai.api_server
    - --model=Qwen/Qwen2.5-7B-Instruct
    - --host=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
        name="inference-gptoss", display="GPT-OSS-20B", kind="inference",
        description="OpenAI 开源 GPT-OSS-20B 推理(vLLM),建议 ≥24G 显存。",
        tags=("需大显存", "模型预设"), gpu=1, cpu=8, memory="48Gi",
        image="vllm/vllm-openai:latest",
        yaml="""kind: inference
version: v0.1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  priority: medium
  description: "GPT-OSS-20B 推理"
environment:
  image: __IMAGE__
  command:
    - python3
    - -m
    - vllm.entrypoints.openai.api_server
    - --model=openai/gpt-oss-20b
    - --host=0.0.0.0
    - --port=8000
service:
  replicas: 1
  port: 8000
  healthCheck: /health
  startupTimeout: 15m   # 启动(拉取+加载模型)最多等这么久,期间不被探针杀;超时才判失败重启。大模型/慢网络可调大。
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
        name="compute-qdrant", display="Qdrant 向量数据库", kind="compute",
        description="RAG 标配向量库,REST/gRPC 双协议。CPU 即可运行,配合 Embeddings 服务使用。",
        tags=("CPU 可跑", "RAG"), cpu=2, memory="2Gi",
        image="qdrant/qdrant:latest",
        yaml="""kind: compute
version: v1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  description: "Qdrant 向量数据库"
environment:
  image: __IMAGE__
  command: ["/qdrant/entrypoint.sh"]
service:
  replicas: 1
  port: 6333
  healthCheck: /healthz
  startupTimeout: 5m
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
storage:
  workdirs:
    - path: /qdrant/storage
""",
    ),
    Template(
        name="compute-streamlit", display="Streamlit 应用", kind="compute",
        description="数据应用快速搭建。默认跑官方 hello 演示,替换为你的 app.py 即上线。",
        tags=("CPU 可跑", "Web 应用"), cpu=1, memory="1Gi",
        image="python:3.11-slim",
        yaml="""kind: compute
version: v1
job:
  name: __NAME__
  namespace: __NAMESPACE__
  description: "Streamlit 数据应用"
environment:
  image: __IMAGE__
  command:
    - /bin/sh
    - -c
    - |
      pip install -q streamlit
      # TODO: 换成 streamlit run your_app.py
      streamlit hello --server.address 0.0.0.0 --server.port 8000 --server.headless true
service:
  replicas: 1
  port: 8000
  healthCheck: /_stcore/health
  startupTimeout: 5m
resources:
  pool: __POOL__
  gpu: __GPU__
  cpu: __CPU__
  memory: __MEMORY__
""",
    ),
]
