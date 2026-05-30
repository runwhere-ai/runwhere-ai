# runwhere-ai

> 一体化 Web 控制台：Notebook · Training · Inference · Compute · 资源治理 · 实时同步
>
> 基于 gpuctl 的可视化 AI 训练平台

---

## 与 gpuctl 的关系

runwhere-ai 是 **gpuctl 的 UI 层**，但作为**独立 Python 包**存在于 `../gpuctl` 同级。
通过 Poetry path dependency（`develop = true`）引用，**gpuctl 主仓库的任何改动立即在 runwhere-ai 内生效**——不需要 publish 新版本或重新安装。

```
runwhere-org/
├── gpuctl/                # 既有 · 不动 · 持续迭代
│   ├── gpuctl/            # gpuctl 业务库
│   └── server/            # gpuctl /api/v1/* JSON API
└── runwhere-ai/           # 本目录
    ├── src/
    │   ├── console/       # runwhere-ai 业务库（Informer / PubSub / 一致性 / 鉴权 / ViewModel）
    │   ├── webui/         # HTML 路由（Jinja2 / HTMX）
    │   └── main.py        # FastAPI 启动入口（mount gpuctl /api/v1/* + runwhere-ai 路由）
    ├── templates/
    ├── static/
    └── tests/
```

## 一体进程架构

启动 `runwhere-ai` 时，FastAPI app **在同一进程同一端口**同时挂载两套路由：

```
                 ┌───────────────────────────────┐
                 │     FastAPI App (uvicorn)     │
                 │                               │
                 │  /api/v1/*   ← from gpuctl    │  ← CLI / 三方
                 │  /, /notebooks, /trainings... │  ← UI 浏览器
                 │  /_events    ← WS 推送        │
                 │                               │
                 │  共享 Service 层 (gpuctl/console/) │
                 └─────────────────┬─────────────┘
                                   │
                                   ▼
                            Kubernetes API
```

浏览器**永不直连 K8s**；UI 与 `/api/v1/*` 是同一进程内的平级兄弟路由，共享 Service 层（FR-115~119）。

## 本地起 dev

```bash
# 一次性安装（自动以 develop 模式安装 gpuctl）
poetry install

# 安装 Playwright Chromium（E2E 测试）
poetry run playwright install chromium

# 下载 Tailwind Standalone CLI 二进制
./scripts/install-tailwind.sh

# 一键编译资产 + 启动开发服务器
make dev
```

打开 http://localhost:8000 → 进入登录页（用 gpuctl Bearer Token 登录）。

## 测试

```bash
poetry run pytest tests/console -v          # 业务库单元测试
poetry run pytest tests/webui -v            # 路由契约测试
poetry run pytest tests/e2e -v              # Playwright E2E
poetry run pytest --cov=src         # 覆盖率（宪法 §III ≥80%）
```

## 进一步阅读

- [spec](../specs/003-runwhere-ai-console/spec.md) · feature 合同
- [plan](../specs/003-runwhere-ai-console/plan.md) · 工程计划
- [contracts](../specs/003-runwhere-ai-console/contracts/) · 路由 / Service / WS / 鉴权契约
- [tasks](../specs/003-runwhere-ai-console/tasks.md) · 173 任务清单
- [PRD](../docs/AI训练平台%20PRD.md) · 早期设计说明
