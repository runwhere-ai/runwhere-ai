"""GPU prober —— 账本的「现实」侧(设计 #2 / job-queue-design.md §3.3、§3.4)。

在 GPU 节点上(form A: console 进程内,hostPID;form B: DaemonSet)周期性地:
  1. `nvidia-smi --query-gpu=...`         → 每张物理卡的 util/显存/UUID
  2. `nvidia-smi --query-compute-apps=...`→ 每卡上的进程(host PID + 显存 + 进程名)
  3. 读 `/proc/<pid>/cmdline` 展示完整命令；读 `/proc/<pid>/cgroup` 归因到 k8s/docker/host
→ 写入 STORE,供 GPU 大盘渲染；v1 不用它做自动准入。

本模块的**解析与分类是纯函数**(parse_gpu_query / parse_compute_apps / classify_cgroup),
不依赖 GPU,可用真实 nvidia-smi 样本单测(见 tests/console/test_gpu_prober.py)。
采集(collect)与背景循环(GpuProber)在有 nvidia-smi 的节点上才产出数据;无 GPU 环境降级为空。

机制已在 runw 实测验证(原生 Ubuntu,driver 595,见 docs/design/job-queue-design.md 附录 A)。
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# pod_uid -> (namespace, name);由调用方注入(接 informer pod 缓存)。返回 None=解析不出。
PodResolver = Callable[[str], Optional[tuple[str, str]]]

_SMI = "nvidia-smi"
_GPU_QUERY = "index,uuid,name,utilization.gpu,memory.used,memory.total"
_APPS_QUERY = "gpu_uuid,pid,used_gpu_memory,process_name"

# cgroup 形态识别
_RE_POD_UID = re.compile(
    r"pod([0-9a-f]{8}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{4}[-_][0-9a-f]{12})"
)
_RE_DOCKER = re.compile(r"docker[-/]([0-9a-f]{12,64})")
_RE_CONTAINERD = re.compile(r"(?:cri-containerd|containerd)[-:/]([0-9a-f]{12,64})")


# ── data model ─────────────────────────────────────────────────────────────────
@dataclass
class GpuProcess:
    pid: int
    name: str
    used_mem_mb: float
    kind: str            # "managed" | "unmanaged" | "docker" | "host"
    attrib: str          # 任务名 / 容器短 id / 进程名
    command: str = ""
    pod_namespace: Optional[str] = None
    pod_name: Optional[str] = None


@dataclass
class PhysicalGpu:
    node: str
    index: int
    uuid: str
    name: str
    util: float
    mem_used_mb: float
    mem_total_mb: float
    processes: list[GpuProcess] = field(default_factory=list)

    @property
    def state(self) -> str:
        if any(p.kind in ("docker", "host", "unmanaged") for p in self.processes):
            return "unmanaged"
        if self.processes:
            return "busy"
        return "free"


# ── pure parsers ────────────────────────────────────────────────────────────────
def parse_gpu_query(text: str) -> list[dict]:
    """解析 `--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total
    --format=csv,noheader,nounits`。"""
    out: list[dict] = []
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line or line.lower().startswith("index"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        try:
            out.append({
                "index": int(parts[0]),
                "uuid": parts[1],
                "name": parts[2],
                "util": float(parts[3]),
                "mem_used_mb": float(parts[4]),
                "mem_total_mb": float(parts[5]),
            })
        except ValueError:
            continue
    return out


def parse_compute_apps(text: str) -> list[dict]:
    """解析 `--query-compute-apps=gpu_uuid,pid,used_gpu_memory,process_name
    --format=csv,noheader,nounits`。process_name 可能含空格(不含逗号)。"""
    out: list[dict] = []
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line or line.lower().startswith("gpu_uuid"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            out.append({
                "uuid": parts[0],
                "pid": int(parts[1]),
                "used_mem_mb": float(parts[2]),
                "name": ",".join(parts[3:]).strip(),
            })
        except ValueError:
            # 显存可能是 "[N/A]" / "[Not Supported]" → 跳过该进程
            continue
    return out


def classify_cgroup(cgroup_text: str) -> tuple[str, Optional[str]]:
    """`/proc/<pid>/cgroup` → (类型, 标识)。
    类型: "k8s"(标识=pod uid) | "docker"(标识=容器 id) | "host"(标识=None)。
    先判 kubepods(k8s pod,内层也含 containerd id,不可先匹配容器)。"""
    t = cgroup_text or ""
    if "kubepods" in t:
        m = _RE_POD_UID.search(t)
        return ("k8s", m.group(1).replace("_", "-") if m else None)
    m = _RE_DOCKER.search(t)
    if m:
        return ("docker", m.group(1))
    m = _RE_CONTAINERD.search(t)
    if m:
        return ("docker", m.group(1))
    return ("host", None)


# ── /proc + nvidia-smi (guarded; 无 GPU 环境降级) ────────────────────────────────
def _run_smi(query_flag: str, query: str) -> str:
    try:
        r = subprocess.run(
            [_SMI, f"--{query_flag}={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout if r.returncode == 0 else ""
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        logger.debug("nvidia-smi unavailable (%s): %s", query_flag, exc)
        return ""


def _read_proc(pid: int, fname: str) -> str:
    try:
        with open(f"/proc/{pid}/{fname}", "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _cmdline_parts(raw: str) -> list[str]:
    raw = raw or ""
    return [p for p in raw.replace("\x00", "\n").splitlines() if p]


def _cmdline_text(raw: str, fallback: str) -> str:
    parts = _cmdline_parts(raw)
    return " ".join(parts) if parts else fallback


def _ppid_from_status(status: str) -> Optional[int]:
    for line in (status or "").splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _best_command(pid: int, fallback: str,
                  read_cmd: Callable[[int], str],
                  read_status: Callable[[int], str]) -> str:
    """Prefer the process cmdline, but follow short process-title workers to a parent.

    Some GPU workers (for example vLLM EngineCore) rewrite argv to a short title, so
    `/proc/<pid>/cmdline` contains only `VLLM::EngineCore`. The parent usually keeps
    the useful launch command (`vllm serve ...`), which is what operators need here.
    """
    raw = read_cmd(pid)
    parts = _cmdline_parts(raw)
    command = " ".join(parts) if parts else fallback
    if len(parts) > 1 or command != fallback:
        return command

    seen = {pid}
    current = pid
    for _ in range(3):
        ppid = _ppid_from_status(read_status(current))
        if not ppid or ppid <= 1 or ppid in seen:
            break
        seen.add(ppid)
        parent_parts = _cmdline_parts(read_cmd(ppid))
        if len(parent_parts) > 1:
            return " ".join(parent_parts)
        current = ppid
    return command


def collect(node: str, resolver: Optional[PodResolver] = None,
            smi_gpu: Optional[str] = None, smi_apps: Optional[str] = None,
            cgroup_reader: Optional[Callable[[int], str]] = None,
            cmdline_reader: Optional[Callable[[int], str]] = None,
            status_reader: Optional[Callable[[int], str]] = None) -> list[PhysicalGpu]:
    """采集一次,返回该节点的物理卡列表(含进程归因)。

    smi_gpu/smi_apps/cgroup_reader/cmdline_reader 可注入(测试用);
    默认实际 shell nvidia-smi + 读 /proc。
    """
    gpu_text = smi_gpu if smi_gpu is not None else _run_smi("query-gpu", _GPU_QUERY)
    apps_text = smi_apps if smi_apps is not None else _run_smi("query-compute-apps", _APPS_QUERY)
    read_cg = cgroup_reader or (lambda pid: _read_proc(pid, "cgroup"))
    read_cmd = cmdline_reader or (lambda pid: _read_proc(pid, "cmdline"))
    read_status = status_reader or (lambda pid: _read_proc(pid, "status"))

    procs_by_uuid: dict[str, list[GpuProcess]] = {}
    for p in parse_compute_apps(apps_text):
        kind, ident = classify_cgroup(read_cg(p["pid"]))
        gp = _attribute(p, kind, ident, resolver,
                        _best_command(p["pid"], p["name"], read_cmd, read_status))
        procs_by_uuid.setdefault(p["uuid"], []).append(gp)

    gpus: list[PhysicalGpu] = []
    for g in parse_gpu_query(gpu_text):
        gpus.append(PhysicalGpu(
            node=node, index=g["index"], uuid=g["uuid"], name=g["name"],
            util=g["util"], mem_used_mb=g["mem_used_mb"], mem_total_mb=g["mem_total_mb"],
            processes=procs_by_uuid.get(g["uuid"], []),
        ))
    return gpus


def _attribute(p: dict, kind: str, ident: Optional[str],
               resolver: Optional[PodResolver], command: str = "") -> GpuProcess:
    pid, name, mem = p["pid"], p["name"], p["used_mem_mb"]
    if kind == "k8s":
        resolved = resolver(ident) if (resolver and ident) else None
        if resolved:
            ns, pod = resolved
            return GpuProcess(pid, name, mem, "managed", pod, command, ns, pod)
        return GpuProcess(pid, name, mem, "unmanaged",
                          f"pod {ident[:8]}" if ident else "未知 pod", command)
    if kind == "docker":
        return GpuProcess(pid, name, mem, "docker",
                          f"docker {ident[:12]}" if ident else "docker 容器", command)
    return GpuProcess(pid, name, mem, "host", name or f"pid {pid}", command)


# ── reality store(现实侧:node -> 物理卡)───────────────────────────────────────
class RealityStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict] = {}   # node -> {"gpus": [...], "ts": float}

    def set_node(self, node: str, gpus: list[PhysicalGpu]) -> None:
        with self._lock:
            self._nodes[node] = {"gpus": gpus, "ts": time.time()}

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._nodes)

    def has_data(self) -> bool:
        with self._lock:
            return bool(self._nodes)


STORE = RealityStore()


# ── background prober(form A: console 进程内,hostPID)──────────────────────────
class GpuProber:
    """周期采集本节点 GPU → STORE。在 console 进程内随 lifespan 启停(参考 informer)。
    需要容器具备 hostPID + nvidia runtime(NVIDIA_VISIBLE_DEVICES=all)才看得见整机进程。"""

    def __init__(self, node: str, resolver: Optional[PodResolver] = None,
                 interval: float = 5.0) -> None:
        self.node = node
        self.resolver = resolver
        self.interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        # 先采一次确认有数据再起循环(无 GPU 则不启,日志提示)
        first = collect(self.node, self.resolver)
        if not first:
            logger.info("GpuProber: 本节点无 GPU 数据(nvidia-smi 不可用或无卡),prober 不启动")
            return
        STORE.set_node(self.node, first)
        self._thread = threading.Thread(target=self._loop, name="gpu-prober", daemon=True)
        self._thread.start()
        logger.info("GpuProber 已启动: 节点=%s 卡数=%d 间隔=%ss", self.node, len(first), self.interval)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                STORE.set_node(self.node, collect(self.node, self.resolver))
            except Exception as exc:  # noqa: BLE001 - 采集失败不该崩进程
                logger.warning("GpuProber 采集失败: %s", exc)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)


def make_k8s_pod_resolver(ttl: float = 10.0) -> PodResolver:
    """uid → (namespace, 任务名) 解析器:按 uid 索引集群全部 pod(TTL 缓存)。
    任务名取 job-name/app 标签(= 工作负载名,与列表/详情一致),否则用 pod 名。
    用于把 GPU 进程的 cgroup pod uid 反解成可读任务名。"""
    state: dict = {"idx": {}, "ts": 0.0, "cfg": False}
    lock = threading.Lock()

    def _refresh() -> None:
        from kubernetes import client, config
        if not state["cfg"]:
            try:
                config.load_incluster_config()
            except Exception:  # noqa: BLE001 — 非集群内则退回 kubeconfig
                try:
                    config.load_kube_config()
                except Exception:  # noqa: BLE001
                    pass
            state["cfg"] = True
        idx: dict[str, tuple[str, str]] = {}
        for p in client.CoreV1Api().list_pod_for_all_namespaces().items:
            uid = p.metadata.uid
            if not uid:
                continue
            labels = p.metadata.labels or {}
            name = labels.get("job-name") or labels.get("app") or p.metadata.name
            idx[uid] = (p.metadata.namespace, name)
        state["idx"], state["ts"] = idx, time.time()

    def resolver(uid: str) -> Optional[tuple[str, str]]:
        with lock:
            if time.time() - state["ts"] > ttl:
                try:
                    _refresh()
                except Exception as exc:  # noqa: BLE001 — 解析失败不该崩采集
                    logger.debug("pod resolver refresh failed: %s", exc)
            return state["idx"].get(uid)

    return resolver
