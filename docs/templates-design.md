# 任务模板库 / 快速开始(Templates & Quickstart)产品设计

> 状态:**原型评审中**(分支 `feat/templates-prototype`)。
> 灵感来源:SkyPilot Recipes(`skypilot/docs/source/reference/recipes.rst`,v0.12),完整调研见 workspace 的 `docs/BORROW-skypilot.md`。

## 1. 问题与目标

**问题**:「新建 Notebook/训练/推理/计算」按钮此前是死链,Web 端没有提交任务的入口;提交任务唯一途径是手写 gpuctl YAML 走 CLI。新人冷启动成本高,团队同类任务的 YAML 无沉淀、无标准化。

**目标**
1. 新用户 **3 分钟内**从模板提交第一个任务,不需要会写 YAML。
2. 团队配置**标准化**:好的 YAML 沉淀为模板,全员复用。
3. 补齐「新建任务」的 Web 提交链路:模板 → 表单覆盖 → 校验 → 提交 → 跳详情看日志。

**非目标**(本期):多用户权限隔离、模板版本历史、`${VAR}` 参数占位符语言、跨集群分发。

## 2. 信息架构:「快速开始」菜单

侧边栏新增一级入口 **「快速开始」**(置于控制面板之下、我的工作台之上,带 New 徽章):

```
runwhere.ai
├─ 控制面板
├─ ✨ 快速开始        ← 新增(模板陈列馆)
├─ 我的工作台
│   ├─ Notebook / 训练任务 / 推理服务 / 计算服务
└─ 平台管理(admin)
```

- `/quickstart` —— 模板陈列馆:按任务类型分组的模板卡片,筛选 chips + 搜索。
- `/quickstart/{name}` —— 启动页:左表单(常用覆盖)+ 右 YAML(同步生成),校验 + 提交。
- 四个任务列表页的「新建 XX」CTA 改为跳 `/quickstart?kind=<kind>`(死链复活)。

## 3. 概念模型

**模板 = 一份带元数据的 gpuctl YAML**:

| 字段 | 说明 |
|---|---|
| name | k8s 合法 slug,唯一(`training-pytorch-ddp`) |
| displayName / description | 展示名 + 用途/适用人/前置要求(评审最佳实践:写明"需要什么、花多少") |
| kind | notebook / training / inference / compute |
| yaml | gpuctl YAML 正文,内含覆盖令牌(见 §5) |
| builtin | 内置(随版本发布,只读,可复制)/ 自定义 |
| tags | 如「CPU 可跑」「需 GPU」「分布式」 |

**内置模板首批 7 个**:`notebook-jupyter`(CPU)、`notebook-jupyter-gpu`、`training-pytorch`(单机)、`training-pytorch-ddp`(多节点)、`inference-vllm`、`compute-web`(nginx)、`compute-batch`(数据处理)。无 GPU 集群给 `gpu:0` 变体可直接跑通 demo。

## 4. 存储设计(目标态;原型阶段先硬编码)

每个模板 = 一个 **ConfigMap**(命名空间 `runwhere-system`):

```yaml
metadata:
  name: tpl-training-pytorch-ddp
  labels:
    runwhere.ai/template: "true"
    runwhere.ai/template-kind: training
  annotations:
    runwhere.ai/display-name: "PyTorch 分布式训练"
    runwhere.ai/description: "..."
    runwhere.ai/builtin: "false"
data:
  template.yaml: |
    kind: training
    ...
```

理由:与 gpuctl 一切皆 k8s 资源的哲学一致、kubectl 可管可备份、resourceVersion 天然防并发冲突、无需引入 DB。内置模板由 `deploy/k8s/` 清单随版本 apply,API 层对 `builtin` 强制只读(改/删 → 403,只能「复制为新模板」)。

> **原型阶段**:模板硬编码在 `src/webui/pages/quickstart.py` 的 `TEMPLATES` 列表,评审通过后迁移 ConfigMap + CRUD。

## 5. 启动流(核心交互)

```
┌ 从模板启动:PyTorch 分布式训练 ──────────────────────────────┐
│ 左:常用覆盖                  │ 右:YAML(深色代码块,可编辑) │
│  任务名   [training-ddp-x7k2] │  kind: training              │
│  命名空间 [default]           │  job:                        │
│  资源池   [default]           │    name: training-ddp-x7k2   │
│  GPU [2]  CPU [8]  内存[32Gi] │    ...                       │
│  镜像 [pytorch/pytorch:2.1…]  │                              │
│        [校验 YAML]  [🚀 提交]                                 │
└──────────────────────────────────────────────────────────────┘
```

- **单向同步**(评审决策:先单向,联动放 Phase 2):模板 YAML 内嵌覆盖令牌(`__NAME__` `__NAMESPACE__` `__POOL__` `__GPU__` `__CPU__` `__MEMORY__` `__IMAGE__`),Alpine 监听表单字段实时替换生成右侧 YAML;**用户一旦手改 YAML 即进入"手动模式"**(表单停止同步并显示提示徽章),以 YAML 为准。
- **任务名自动建议** `<模板名>-<4位随机>` 防撞名;前端按 k8s 命名规则(`[a-z0-9-]`,63 字)即时校验。
- **校验**:`POST /quickstart/validate` → webui 层调 gpuctl `BaseParser.parse_yaml` 纯解析,返回 `{ok, error}`(解析错误原样回显)。
- **提交**:浏览器直接 `POST /api/v1/jobs {yamlContent}`(**与 CLI 完全同一条代码路径**,符合 CLI↔UI 一致性宪章)→ 201 后跳转对应任务详情页(实时日志接管)。

## 6. 模板管理(MVP 完整功能;原型只读)

- 模板详情:元数据 + YAML 只读视图 + `从此模板启动`/`复制为新模板`;自定义模板另有 `编辑`/`删除`(删除二次确认,提示"已启动任务不受影响")。
- **任务详情页「另存为模板」**:detail 端点已有 `yaml_content`(`map_k8s_to_gpuctl` 重建),一键把跑得好的任务沉淀为模板——成本最低、最能形成"用得好→沉淀→复用"飞轮(评审已确认进 MVP)。
- 敏感值展示打码:env 名匹配 `TOKEN|KEY|SECRET|PASSWORD` 的值渲染为 `••••`(仅展示层)。

## 7. API(目标态)

```
GET    /api/v1/templates?kind=        列表
GET    /api/v1/templates/{name}       详情(含 yaml)
POST   /api/v1/templates              创建
PUT    /api/v1/templates/{name}       更新(builtin → 403)
DELETE /api/v1/templates/{name}       删除(builtin → 403)
POST   /quickstart/validate           dryRun 纯解析(webui 层)
POST   /api/v1/jobs                   提交(gpuctl 现有端点,复用)
```

先落 webui 层,稳定后下沉 gpuctl `server/routes/templates.py`,同时给 CLI 加 `gpuctl create --template <name>`(Phase 2)。

## 8. 调研中发现的后端缺口(独立修复项,不阻塞原型)

1. **`POST /api/v1/jobs` 忽略 `dryRun` 字段**(`server/routes/jobs.py:43`):请求模型里有 `dryRun: bool` 但 handler 不读,传 true 也会真创建。应支持 dryRun=解析+构建但不下发,并返回行号级错误。
2. **强制 `namespace=DEFAULT_NAMESPACE`**(`jobs.py:56` 等):忽略 YAML `job.namespace`。多租户语义下应尊重 YAML 或显式参数。
3. 解析错误(`ParserError`)只有字符串消息,无行号——「dryRun 行号定位」(spec 承诺)需要 parser 暴露行号。

## 9. 分期

| 期 | 内容 |
|---|---|
| **原型**(本分支) | 快速开始菜单 + 模板陈列馆 + 启动页(表单→YAML 单向同步、真校验、真提交)+ 7 个硬编码内置模板 + 列表页 CTA 接活 |
| **MVP** | ConfigMap 存储 + 模板 CRUD + 「复制为新模板」+ 任务详情「另存为模板」+ 空状态引导 + Monaco 替换 textarea |
| Phase 2 | CLI `--template`;`${VAR}` 占位符;secrets 段;表单↔YAML 双向联动;使用统计 |
| Phase 3 | RBAC、版本历史、跨集群分发 |

## 10. 评审记录

- 2026-06-11:表单↔YAML 先做**单向**(联动 Phase 2);「另存为模板」进 MVP;API 先放 webui 层;新增「快速开始」一级菜单(本文档 §2),先出 UI 原型评审。
