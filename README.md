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

打开 http://localhost:8000 → 直接进入控制台。默认 `RWAI_AUTH_PROVIDER=kubeconfig`：

- 本地开发：读取当前 `KUBECONFIG` / `~/.kube/config`
- 集群部署：读取 Pod 的 in-cluster ServiceAccount
- 浏览器侧：不需要登录，不需要粘贴 token

K8s 配置读取规则与 `gpuctl` CLI 保持一致：

- 进程环境里有 `KUBERNETES_SERVICE_HOST`：读取 in-cluster ServiceAccount
- 否则读取 Kubernetes 标准 kubeconfig：`KUBECONFIG` 或 `~/.kube/config`

如果自动读取不符合预期，请通过 `gpuctl` 配置入口设置，这样 CLI 和 UI 才会同步：

```bash
gpuctl config set-kubeconfig --file /path/to/admin.conf --context prod
make dev
```

也可以查看或清除配置：

```bash
gpuctl config view
gpuctl config unset-kubeconfig
```

如需兼容按 Kubernetes Bearer Token 登录的旧模式，可设置
`RWAI_AUTH_PROVIDER=bearer` 后重启服务。

## Docker 部署

容器化部署同样依赖同级的 `gpuctl/`，因此**构建上下文是父目录**。已在 `docker-compose.yml` 中配好，直接用即可：

```bash
# 在 runwhere-ai/ 目录下
docker compose up -d --build      # 构建镜像并后台启动
docker compose logs -f            # 跟踪日志
docker compose down               # 停止并移除容器
```

打开 http://<宿主机IP>:8000 即进入控制台。要点：

- **网络**：使用 `network_mode: host`，既直接暴露 `:8000`，又让容器内能访问 k3s 的 `127.0.0.1:6443`。
- **集群凭据**：只读挂载宿主机 `~/.kube/config` 到容器 `/root/.kube/config`，并设 `KUBECONFIG` 指向它。
- **认证**：`RWAI_AUTH_PROVIDER=kubeconfig`（平台控制台模式，浏览器无需登录）；经 http 访问时 `RWAI_COOKIE_SECURE=false`。
- **资产**：vendored JS（htmx / alpine）已随 git 入库；`tailwind.css` 为生成物（被 .gitignore），故镜像构建阶段会自动下载 Tailwind CLI 并编译，无需本地预构建。

不用 compose 直接构建：

```bash
docker build -f runwhere-ai/Dockerfile -t runwhere-ai:latest ..      # 注意结尾的 ..
docker run -d --name runwhere-ai --network host \
  -e RWAI_AUTH_PROVIDER=kubeconfig -e RWAI_COOKIE_SECURE=false \
  -e KUBECONFIG=/root/.kube/config \
  -v "$HOME/.kube/config:/root/.kube/config:ro" \
  runwhere-ai:latest
```

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
