"""GPU prober 解析/归因单测 —— 用 runw 实测的真实 nvidia-smi / cgroup 样本。

样本来自 docs/design/job-queue-design.md 附录 A(原生 Ubuntu,driver 595,RTX 5060 Ti)。
纯函数,不依赖 GPU。
"""
from src.console.gpu_prober import (
    GpuProcess,
    classify_cgroup,
    collect,
    parse_compute_apps,
    parse_gpu_query,
)

# ── 真实样本(--format=csv,noheader,nounits)────────────────────────────────────
SMI_GPU = "0, GPU-de8093d2-016c-6f19-66e7-0e219acbfc86, NVIDIA GeForce RTX 5060 Ti, 0, 8314, 16311"
SMI_APPS = "GPU-de8093d2-016c-6f19-66e7-0e219acbfc86, 298017, 8234, VLLM::EngineCore"

CG_DOCKER = "0::/system.slice/docker-7a5072b08f25a9b38ad54d872db30a007a33f5d870108a46f1c41e48a4de9a38.scope"
CG_K8S = ("0::/kubepods.slice/kubepods-besteffort.slice/"
          "kubepods-besteffort-pod1234abcd_5678_90ef_1234_567890abcdef.slice/"
          "cri-containerd-aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666aaaa7777bbbb8888.scope")
CG_HOST = "0::/init.scope"


def test_parse_gpu_query():
    gpus = parse_gpu_query(SMI_GPU)
    assert len(gpus) == 1
    g = gpus[0]
    assert g["index"] == 0
    assert g["uuid"] == "GPU-de8093d2-016c-6f19-66e7-0e219acbfc86"
    assert g["name"] == "NVIDIA GeForce RTX 5060 Ti"
    assert g["util"] == 0.0
    assert g["mem_used_mb"] == 8314.0
    assert g["mem_total_mb"] == 16311.0


def test_parse_compute_apps():
    procs = parse_compute_apps(SMI_APPS)
    assert len(procs) == 1
    p = procs[0]
    assert p["pid"] == 298017
    assert p["used_mem_mb"] == 8234.0
    assert p["name"] == "VLLM::EngineCore"
    assert p["uuid"] == "GPU-de8093d2-016c-6f19-66e7-0e219acbfc86"


def test_parse_compute_apps_skips_header_and_na():
    text = "gpu_uuid, pid, used_gpu_memory, process_name\nGPU-x, 12, [N/A], foo\nGPU-x, 13, 100, bar"
    procs = parse_compute_apps(text)
    assert [p["pid"] for p in procs] == [13]  # header skipped, [N/A] skipped


def test_classify_cgroup_docker():
    kind, ident = classify_cgroup(CG_DOCKER)
    assert kind == "docker"
    assert ident.startswith("7a5072b0")


def test_classify_cgroup_k8s_normalizes_underscores():
    kind, uid = classify_cgroup(CG_K8S)
    assert kind == "k8s"
    # systemd cgroup 把 uid 的 '-' 转成 '_';归因前要还原成标准 uid
    assert uid == "1234abcd-5678-90ef-1234-567890abcdef"


def test_classify_cgroup_host():
    assert classify_cgroup(CG_HOST) == ("host", None)


def test_collect_attributes_docker_process():
    """整链路:nvidia-smi + cgroup(docker)→ 一张卡,卡上一个 docker 进程,卡态=非托管。"""
    gpus = collect(
        node="runw",
        smi_gpu=SMI_GPU, smi_apps=SMI_APPS,
        cgroup_reader=lambda pid: CG_DOCKER,
        cmdline_reader=lambda pid: "python\x00-m\x00vllm.entrypoints.openai.api_server\x00--model\x00qwen\x00",
    )
    assert len(gpus) == 1
    g = gpus[0]
    assert g.uuid.startswith("GPU-de8093d2")
    assert len(g.processes) == 1
    proc = g.processes[0]
    assert proc.kind == "docker"
    assert proc.pid == 298017
    assert proc.used_mem_mb == 8234.0
    assert proc.command == "python -m vllm.entrypoints.openai.api_server --model qwen"
    assert g.state == "unmanaged"   # docker 占用 → 非托管


def test_collect_attributes_managed_pod_via_resolver():
    """k8s pod + resolver 能反解 → 归为托管任务,带 ns/name。"""
    gpus = collect(
        node="runw",
        smi_gpu=SMI_GPU, smi_apps=SMI_APPS,
        cgroup_reader=lambda pid: CG_K8S,
        resolver=lambda uid: ("ml-team", "alice-sft"),
    )
    proc = gpus[0].processes[0]
    assert proc.kind == "managed"
    assert proc.pod_namespace == "ml-team"
    assert proc.pod_name == "alice-sft"
    assert gpus[0].state == "busy"   # 全是托管 → 运行中(非非托管)


def test_collect_unmanaged_pod_when_resolver_fails():
    """k8s pod 但 resolver 解析不出 → 标非托管,不假装托管。"""
    gpus = collect(
        node="runw", smi_gpu=SMI_GPU, smi_apps=SMI_APPS,
        cgroup_reader=lambda pid: CG_K8S, resolver=lambda uid: None,
    )
    proc = gpus[0].processes[0]
    assert proc.kind == "unmanaged"


def test_free_card_has_no_processes():
    gpus = collect(node="n", smi_gpu=SMI_GPU, smi_apps="", cgroup_reader=lambda pid: "")
    assert gpus[0].state == "free"
    assert gpus[0].processes == []


def test_collect_command_falls_back_to_process_name_when_cmdline_unreadable():
    gpus = collect(
        node="runw",
        smi_gpu=SMI_GPU,
        smi_apps=SMI_APPS,
        cgroup_reader=lambda pid: CG_HOST,
        cmdline_reader=lambda pid: "",
    )
    assert gpus[0].processes[0].command == "VLLM::EngineCore"


def test_collect_uses_parent_command_for_short_gpu_worker_title():
    def cmdline(pid: int) -> str:
        if pid == 298017:
            return "VLLM::EngineCore\x00\x00\x00"
        if pid == 298000:
            return "/usr/bin/python3\x00/usr/local/bin/vllm\x00serve\x00/models/qwen\x00--port\x008001\x00"
        return ""

    def status(pid: int) -> str:
        if pid == 298017:
            return "Name:\tVLLM::EngineCor\nPPid:\t298000\n"
        return "Name:\tpython3\nPPid:\t1\n"

    gpus = collect(
        node="runw",
        smi_gpu=SMI_GPU,
        smi_apps=SMI_APPS,
        cgroup_reader=lambda pid: CG_DOCKER,
        cmdline_reader=cmdline,
        status_reader=status,
    )
    assert gpus[0].processes[0].command == "/usr/bin/python3 /usr/local/bin/vllm serve /models/qwen --port 8001"
