# syntax=docker/dockerfile:1
#
# runwhere-ai 一体化控制台镜像。
#
# 重要：构建上下文必须是 *父目录*（包含 runwhere-ai/ 与 gpuctl/ 两个子目录），
# 因为本项目通过本地 path 依赖引用同仓库的 gpuctl（pyproject 里的
# `gpuctl = { path = "../gpuctl" }`）。构建命令：
#
#   docker build -f runwhere-ai/Dockerfile -t runwhere-ai:latest ..
#
# 或直接用 runwhere-ai/docker-compose.yml（已把 context 设为 `..`）。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── 1) gpuctl：以可编辑方式安装 ────────────────────────────────────────────────
# 可编辑安装会在 site-packages 写入 .pth，把 gpuctl 仓库根目录加入 sys.path，
# 这样 `import gpuctl` 与 `import server`（gpuctl 仓库里的 FastAPI 路由模块）
# 都能解析 —— 与本地 .venv 的行为完全一致。同时自动拉取 gpuctl 的依赖。
COPY gpuctl/ /app/gpuctl/
RUN pip install -e /app/gpuctl

# ── 2) runwhere-ai 自身的额外依赖 ─────────────────────────────────────────────
# 不安装本项目为包（直接以源码运行），仅补齐 gpuctl 未覆盖的运行期依赖。
RUN pip install \
        "uvicorn[standard]>=0.25.0,<1.0.0" \
        "jinja2>=3.1.0" \
        "python-multipart>=0.0.6" \
        "kubernetes-asyncio>=29.0.0"

# ── 3) 应用源码（含预构建的 static/css/tailwind.css）────────────────────────────
COPY runwhere-ai/ /app/runwhere-ai/

# 让 `import src.*` 可解析；static/templates 由 main.py 基于该目录定位。
ENV PYTHONPATH=/app/runwhere-ai
WORKDIR /app/runwhere-ai

EXPOSE 8000

# 平台控制台模式：服务端用 kubeconfig/in-cluster 访问 K8s，浏览器无需登录。
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
