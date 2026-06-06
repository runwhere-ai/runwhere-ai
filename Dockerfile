# runwhere-ai 一体化控制台镜像。
#
# 重要：构建上下文必须是 *父目录*（包含 runwhere-ai/ 与 gpuctl/ 两个子目录），
# 因为本项目通过本地 path 依赖引用同仓库的 gpuctl（pyproject 里的
# `gpuctl = { path = "../gpuctl" }`）。构建命令：
#
#   docker build -f runwhere-ai/Dockerfile -t runwhere-ai:latest ..
#
# 或直接用 runwhere-ai/docker-compose.yml（已把 context 设为 `..`）。
#
# 注：未使用 `# syntax=` 前端指令，避免离线/受限网络下拉取 docker.io frontend；
# 基础镜像用 3.11-slim（目标机已缓存），项目要求 Python >=3.10。
FROM python:3.11-slim

# pip 走可达的镜像源（受限网络下 pypi.org 不可达）。
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com

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

# ── 3) 应用源码 ───────────────────────────────────────────────────────────────
# vendored JS（htmx / alpine）已随 git 提交；仅生成的 tailwind.css 未入库。
COPY runwhere-ai/ /app/runwhere-ai/
WORKDIR /app/runwhere-ai

# ── 4) Tailwind CSS ────────────────────────────────────────────────────────────
# tailwind.css 是生成物（被 .gitignore，不入 git）。两种来源：
#   a) 构建上下文里已存在预构建的 static/css/tailwind.css → 直接用（受限网络推荐）；
#   b) 否则从 github releases 拉取 Tailwind Standalone CLI（linux-x64，带重试）现编。
RUN set -e; \
    if [ -s static/css/tailwind.css ]; then \
      echo "✓ 使用上下文中已存在的 tailwind.css"; \
    else \
      echo "… 下载 Tailwind CLI 现场编译"; \
      mkdir -p tools; \
      for i in 1 2 3 4 5; do \
        python -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.13/tailwindcss-linux-x64','tools/tailwindcss')" && break \
          || { echo "下载失败，重试 $i/5…"; sleep 6; }; \
      done; \
      chmod +x tools/tailwindcss; \
      ./tools/tailwindcss -i static/css/runwhere.in.css -o static/css/tailwind.css --minify; \
      rm -f tools/tailwindcss; \
    fi

# 让 `import src.*` 可解析；static/templates 由 main.py 基于该目录定位。
ENV PYTHONPATH=/app/runwhere-ai

EXPOSE 8000

# 平台控制台模式：服务端用 kubeconfig/in-cluster 访问 K8s，浏览器无需登录。
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
