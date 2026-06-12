# 工作负载 Sidecar Agent 设计(Per-task Sidecar Agent)

> 状态:**评审稿**(尚未实现;待评审通过后再拉分支动手)
> 缘起:从"无 DCGM 下如何统计每个任务的 GPU 利用率"这个问题延展而来
> 关联:[templates-design.md](templates-design.md)、`docs/BORROW-skypilot.md`(SkyPilot 借鉴,spot 恢复部分)

---

## 1. 背景与问题

平台调度四类任务:Notebook / 训练 / 推理 / 计算。最初的诉求是**给每个任务采集 GPU 利用率**。但调研后发现:

- GPU 利用率**不是 cgroup 计量资源**(不像 CPU/内存),现有 metrics-server / cAdvisor 永远给不出 GPU%,必须直接问 GPU(NVML)。
- DCGM 只是 NVIDIA 把"问 GPU"打包成的重组件,**不是唯一途径**;且在 WSL2 dev 机上 DCGM 本身也跑不起来。

由此引出两种采集形态:**节点 DaemonSet** vs **每任务 Sidecar**。本文论证:**纯采集 GPU 利用率应交给 DaemonSet;Sidecar 的长期价值在于一切"必须在 pod 内部才能做"的事**,GPU 利用率反而是它最弱的理由。

---

## 2. 核心判断(本文结论先行)

> **GPU 利用率是 Sidecar 最弱的论据**(DaemonSet 干得更好、还不侵入)。真正值得为 Sidecar 买单的,是 **in-pod 上下文**带来的能力。

一个 per-task Sidecar 的本质 = **平台塞进每个工作负载里的"贴身 agent"**。它独有、节点级 agent 拿不到的四样东西:

1. `localhost` 网络命名空间 —— 能直接抓任务自身暴露的 `:port/metrics`、能挡在任务端点前做代理。
2. 共享 PID(`shareProcessNamespace`)—— 能看见任务主进程、截信号、判断"在跑还是死了"。
3. 共享 volume —— 能搬运 checkpoint / 产物 / 缓存。
4. 任务生命周期 —— 与任务同生共死,能在任务被杀前抢救(checkpoint)。

**围绕这四样的能力,DaemonSet 做不了;围绕 GPU 整卡遥测的能力,DaemonSet 做得更好。** 这就是分工的依据。

---

## 3. 可行性验证记录(2026-06-12 于 runw 实测)

为确认 Sidecar 能否在**不申请 `nvidia.com/gpu`、非特权**的前提下看到 GPU,在 runw(RTX 5060 Ti + WSL2 + k3s)起了一个双容器 pod 实测:

- pod 设 `runtimeClassName: nvidia`;collector 容器**无 `nvidia.com/gpu` 资源请求、无 `privileged`**,仅 `NVIDIA_VISIBLE_DEVICES=all` + `NVIDIA_DRIVER_CAPABILITIES=utility`。

| 验证项 | 结果 |
|---|---|
| Sidecar 能否拿到 GPU(无资源请求) | ✅ `/dev/dxg` 与 `nvidia-smi` 被注入,`nvidia-smi -L` 看到卡 |
| 能否读设备级利用率 | ✅ `25%, 8478MiB/16311MiB` |
| 能否做 per-process 归因 | ❌ 进程表 `[Not Found] / [N/A]`(WSL2 GPU-PV 老天花板) |
| runtime 是否放行 env 路径 | ✅ `accept-nvidia-visible-devices-envvar-when-unprivileged` 取默认 `true` |
| 节点可分配 GPU | `nvidia.com/gpu = 0`(WSL2 device-plugin 未广播)→ env 路径在 runw 上本就是**唯一正门** |

**结论**:Sidecar 拿 GPU 这件事在本套 runtime 上**不需要额外占卡、不需要特权**——之前担心的"GPU 可见性硬伤"不成立。归因能力则受限于 GPU 圈定范围(见 §6)。

---

## 4. 能力分层

### Tier A — 传感器(DaemonSet 也能做,Sidecar 无优势 → **不交给 Sidecar**)
GPU 整卡 util/显存/温度/功耗/throttle/XID 错误、节点级 CPU/内存/IO。统一交给**节点 DaemonSet**。

### Tier B — 执行器(只有 Sidecar 能做 → **这才是建 Sidecar 的理由**)

| 能力 | 为何必须 in-pod | 对本平台的价值 |
|---|---|---|
| 抓任务自身 `localhost:port/metrics` | vLLM/SGLang/TGI 均暴露 Prometheus;训练的 loss/吞吐/step 时间 | 把异构负载**统一成一套 console 仪表盘**:推理 QPS/p99、训练 tokens/s |
| 空闲检测 → notebook 自动挂起/缩容到零 | 要看内核活动 + GPU 是否真在动 | GPU 平台**头号浪费**(notebook 占卡空转)的直接回收,省钱 |
| GPU hang / 0%-util 看门狗 | 要贴着任务判断"卡死还是在跑" | 训练 dataloader 死锁、XID 掉卡 → 自动告警/重启;杀僵尸任务 |
| 优雅抢占:截 SIGTERM → 通知 trainer checkpoint | 必须在进程旁截信号、卡死前存盘 | 支撑 **spot/竞价卡**(SkyPilot 借鉴点);抢占前抢救进度 |
| 端点鉴权代理 + SSH/exec 网关 | 要在 pod 网络命名空间挡在 jupyter/vLLM 前 | 统一 token/TLS/访问控制(现 notebook 是裸 token);收口"SSH 信息可复制" |
| 产物/checkpoint 上传 MinIO | 任务结束前从本地盘搬走 | 栈内已有 MinIO;训练完自动归档权重/日志 |
| per-task 计量 → 计费 | 带 pod 身份采集 GPU-hours、实际 vs 申请 | 直接喂 **runwhere/pricing**;输出 right-sizing 建议("申请 4 卡只用 1.2 卡 → 降配") |

---

## 5. 架构:混合(DaemonSet + Sidecar 分工)

```
节点 DaemonSet(每节点 1 个)         Sidecar(按任务类型 opt-in)
  ─ GPU 整卡 util/显存/温度/XID         ─ 抓任务 localhost /metrics
  ─ fleet 级视图、节点健康              ─ 空闲回收 / hang 看门狗
  ─ 设备→pod 粗归因(可选)            ─ 抢占 checkpoint / 端点代理 / 产物上传
        │                                      │
        └──────────────┬───────────────────────┘
                       ▼
                console(聚合 + 仪表盘 + 计费)
```

两者**不重叠**:DaemonSet 拿"卡/节点"维度,Sidecar 拿"任务内部"维度。

---

## 6. GPU 可见性与归因(关键设计)

Sidecar 能否给出**单任务**利用率,取决于 `NVIDIA_VISIBLE_DEVICES` 圈定的范围:

- **生产 / 多卡 / 每任务独占一张卡**:Sidecar 的 `NVIDIA_VISIBLE_DEVICES = 本任务那张卡的 UUID` → **设备级 util = 本任务 util**,无需 per-process、无需 PID 映射、不占额外卡。**最干净。**
- **runw(1 卡且与 Windows 桌面共享)**:`=all` 看到的数混着主机占用,圈不出单任务;per-process 又 N/A。→ 本机只能给"整卡忙不忙",给不了"本任务用多少"(如实标注即可)。

Sidecar 怎么知道本任务的 UUID:

| 模式 | UUID 来源 |
|---|---|
| env 模式(如 runw,无 device-plugin) | gpuctl 建 pod 时自选 UUID,给主容器与 Sidecar **设同一个** `NVIDIA_VISIBLE_DEVICES` → 天然只圈本任务卡 |
| device-plugin 模式(生产装 GPU-Operator) | UUID 调度时分配,建 pod 时未知 → `shareProcessNamespace` 让 Sidecar 读主进程 `/proc/<pid>/environ` 取 UUID,或退回 DaemonSet 的设备→pod 映射 |

---

## 7. Sidecar 形态与技术约束

为不背叛"轻量、一条 docker 命令、别侵入客户 K8s"的平台哲学:

1. **一个小的静态二进制(Go)**,无外部依赖;镜像极小(scratch/distroless)。
2. **能力按任务类型 opt-in**,不需要的不塞:
   - notebook:空闲回收 + 端点代理
   - training:hang 看门狗 + 抢占 checkpoint
   - inference:metrics 抓取 + 端点代理
   - compute:仅基础遥测(或不注入)
3. **注入方式 = gpuctl builder**:平台自建 pod,builder 里加这个容器即可,**无需 mutating webhook**(对比社区方案的关键优势)。
4. **身份来自 downward API**:pod label(`runwhere.ai/job-type`、namespace、task name)注入为 env → 上报数据天然带任务身份。
5. **上报通道**:暴露 `/metrics`(被 DaemonSet/Prometheus 抓)或直接 push 给 console;复用现有 WebSocket/console 聚合层。
6. **资源占用**:requests 极小(如 10m CPU / 32Mi),不抢任务资源;不申请 GPU(见 §3 验证)。

---

## 8. 与现有系统的关系

- **gpuctl**:builder 增加 Sidecar 注入逻辑(按 kind 决定能力集);注入主容器与 Sidecar 一致的 `NVIDIA_VISIBLE_DEVICES`(env 模式)。
- **console**:新增"任务遥测/效率"视图;复用任务详情页;空闲回收/hang 告警进入任务状态流。
- **runwhere/pricing**:消费 per-task GPU-hours → 计费 / showback。
- **MinIO**:作为 checkpoint/产物归档后端。

---

## 9. 风险与张力(必须直面)

| 风险 | 说明 | 缓解 |
|---|---|---|
| 增重每个 pod | Sidecar 每加功能,所有任务 pod 变重 | 保持瘦 + 按类型 opt-in;Tier A 交给 DaemonSet |
| 生命周期绑死 | Sidecar 随任务死,末尾数据可能丢 | 关键数据(计费、最终利用率)死前主动 flush/push |
| 密度/启动税 | 多一个容器影响调度密度与冷启动 | 二进制小、启动快;compute 类可不注入 |
| 安全面 | 贴身 agent 拥有 in-pod 访问权 | 最小权限;不加 `privileged`(§3 已验证不需要);能力白名单 |
| WSL2 天花板 | dev 机给不出单任务真实值 | 标注"设备级";真实单任务值留生产(UUID 圈定) |

---

## 10. 建议路线(分期)

1. **P0 — 遥测 Sidecar 原型**:gpuctl 注入 collector,采设备级 util + 经 downward API 打任务标签 → console 展示。runw 上验证"注入→采集→带标签上报"全链路(数值为整卡级,标注清楚)。
2. **P1 — 空闲回收**(notebook):最高性价比的省钱功能;空闲检测 → 挂起/缩容到零。
3. **P1 — inference metrics 抓取**:Sidecar 抓 vLLM/TGI `localhost/metrics` → 统一推理仪表盘。
4. **P2 — hang 看门狗 + 抢占 checkpoint**:支撑竞价卡与僵尸治理。
5. **P2 — 端点代理 / 计费打通**:统一鉴权;喂 pricing。

> 用 Tier B 的功能去论证 Sidecar,而非 GPU 利用率;后者交给 DaemonSet。

---

## 11. 评审记录

- 2026-06-12 创建评审稿。先验证可行性(§3 runw 实测通过:无资源请求、非特权即可读设备级 util;per-process 受 WSL2 限制),再形成"DaemonSet 管卡/节点、Sidecar 管任务内部"的混合判断。待评审决定是否进入 P0 原型。
