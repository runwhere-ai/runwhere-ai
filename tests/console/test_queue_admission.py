"""队列自动准入单测(job-queue-design.md 最后一环)。

三条要断言到位:
  1. 空闲判定只信 prober(state=='free'),不信 k8s allocation。
  2. 有一个在途任务未落地时,不评估/不放行下一个候选。
  3. prober 没数据 / 拿不到节点列表时,当"不知道",不放行。
"""
from __future__ import annotations

import time

import pytest

from src.console.gpu_prober import GpuProcess, PhysicalGpu
from src.console.job_queue import QueuedJob
from src.console import queue_admission as qa


def _gpu(node="runw", index=0, uuid="GPU-0", processes=None):
    return PhysicalGpu(
        node=node, index=index, uuid=uuid, name="RTX 5060 Ti",
        util=0.0, mem_used_mb=0.0, mem_total_mb=16311.0,
        processes=processes or [],
    )


def _managed_proc(namespace="ml", name="train-a"):
    return GpuProcess(pid=123, name="python", used_mem_mb=8000.0,
                      kind="managed", attrib=name,
                      pod_namespace=namespace, pod_name=name)


def _job(name="train-a", namespace="ml", priority="medium", gpus=1, pool="default",
        submitted="2026-06-28T10:00:00Z", state="pending"):
    return QueuedJob(namespace=namespace, name=name, priority=priority, gpus=gpus,
                     pool=pool, owner=namespace, submitted_at=submitted, state=state)


class _FakeNode:
    def __init__(self, name, pool=None):
        self.metadata = type("M", (), {"name": name, "labels": {"runwhere.ai/pool": pool} if pool else {}})()


class _FakeNodeList:
    def __init__(self, nodes):
        self.items = nodes


# ── free_gpu_count ──────────────────────────────────────────────────────────────

def test_free_gpu_count_counts_only_truly_free_gpus(monkeypatch):
    """busy/unmanaged 都不算空闲——即便 k8s 完全不知道那个非托管进程的存在。"""
    monkeypatch.setattr(qa, "_pool_node_names", lambda pool: {"runw"})
    snapshot = {
        "runw": {"gpus": [
            _gpu(index=0, uuid="GPU-0", processes=[]),                       # free
            _gpu(index=1, uuid="GPU-1", processes=[_managed_proc()]),        # busy
            _gpu(index=2, uuid="GPU-2", processes=[GpuProcess(
                pid=1, name="python", used_mem_mb=100.0, kind="unmanaged",
                attrib="?", pod_namespace=None, pod_name=None)]),             # unmanaged
            _gpu(index=3, uuid="GPU-3", processes=[]),                       # free
        ]},
    }

    class _Store:
        def snapshot(self):
            return snapshot

    monkeypatch.setattr("src.console.gpu_prober.STORE", _Store())
    assert qa.free_gpu_count("default") == 2


def test_free_gpu_count_ignores_nodes_outside_pool(monkeypatch):
    monkeypatch.setattr(qa, "_pool_node_names", lambda pool: {"node-a"})
    snapshot = {
        "node-a": {"gpus": [_gpu(node="node-a", processes=[])]},
        "node-b": {"gpus": [_gpu(node="node-b", processes=[]), _gpu(node="node-b", index=1, uuid="GPU-1", processes=[])]},
    }

    class _Store:
        def snapshot(self):
            return snapshot

    monkeypatch.setattr("src.console.gpu_prober.STORE", _Store())
    assert qa.free_gpu_count("default") == 1  # node-b 的两张卡不算,不在这个 pool


@pytest.mark.parametrize("nodes,has_snapshot", [(None, True), ({"runw"}, False)])
def test_free_gpu_count_none_when_data_unavailable(monkeypatch, nodes, has_snapshot):
    """节点列表拿不到、或 prober 完全没数据 → None(不知道),不是 0(确定没有)。"""
    monkeypatch.setattr(qa, "_pool_node_names", lambda pool: nodes)

    class _Store:
        def snapshot(self):
            return {"runw": {"gpus": []}} if has_snapshot else {}

    monkeypatch.setattr("src.console.gpu_prober.STORE", _Store())
    assert qa.free_gpu_count("default") is None


def test_pool_node_names_buckets_unlabeled_nodes_as_default(monkeypatch):
    """未打 runwhere.ai/pool 标签的节点(如 runw 从没建过池)要落进 "default"——
    不是 PoolClient.get_pool('default') 那种精确 label_selector 查不到的行为。"""
    fake_nodes = _FakeNodeList([_FakeNode("runw"), _FakeNode("gpu-node-2", pool="h100")])

    class _FakeCoreV1:
        def list_node(self, _request_timeout=None):
            return fake_nodes

    monkeypatch.setattr("kubernetes.client.CoreV1Api", lambda: _FakeCoreV1())
    assert qa._pool_node_names("default") == {"runw"}
    assert qa._pool_node_names("h100") == {"gpu-node-2"}


# ── _job_has_landed ───────────────────────────────────────────────────────────

def test_job_has_landed_true_when_managed_process_matches(monkeypatch):
    snapshot = {"runw": {"gpus": [_gpu(processes=[_managed_proc("ml", "train-a")])]}}

    class _Store:
        def snapshot(self):
            return snapshot

    monkeypatch.setattr("src.console.gpu_prober.STORE", _Store())
    assert qa._job_has_landed("ml", "train-a") is True
    assert qa._job_has_landed("ml", "someone-else") is False


# ── AdmissionLoop.tick ──────────────────────────────────────────────────────────

def test_tick_admits_head_when_enough_free_capacity(monkeypatch):
    job = _job()
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([job], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 2)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    loop = qa.AdmissionLoop()
    loop.tick()

    assert released == [("ml", "train-a")]
    assert loop._inflight is not None
    assert loop._inflight[:2] == ("ml", "train-a")


def test_tick_does_not_admit_when_free_capacity_insufficient(monkeypatch):
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([_job(gpus=2)], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 1)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    qa.AdmissionLoop().tick()

    assert released == []


def test_tick_does_not_admit_when_free_capacity_unknown(monkeypatch):
    """核心原则:不知道就不放,即便队列里有任务在等。"""
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([_job()], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: None)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    qa.AdmissionLoop().tick()

    assert released == []


def test_tick_skips_new_candidate_while_inflight_not_landed(monkeypatch):
    """核心原则:一次只放一个在途——即便这一轮明明有空闲卡,也不该再放第二个。"""
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([_job(name="train-b")], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 4)
    monkeypatch.setattr(qa, "_job_has_landed", lambda ns, name: False)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    loop = qa.AdmissionLoop()
    loop._inflight = ("ml", "train-a", time.time())  # 上一个还没落地
    loop.tick()

    assert released == []
    assert loop._inflight == ("ml", "train-a", loop._inflight[2])  # 没被清掉


def test_tick_evaluates_next_candidate_once_inflight_has_landed(monkeypatch):
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([_job(name="train-b")], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 4)
    monkeypatch.setattr(qa, "_job_has_landed", lambda ns, name: True)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    loop = qa.AdmissionLoop()
    loop._inflight = ("ml", "train-a", time.time())
    loop.tick()

    assert released == [("ml", "train-b")]


def test_tick_times_out_stuck_inflight_and_moves_on(monkeypatch):
    """兜底:pod 一直没落地(拉镜像慢/启动失败)不能让队列永久卡死。"""
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([_job(name="train-b")], None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 4)
    monkeypatch.setattr(qa, "_job_has_landed", lambda ns, name: False)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    loop = qa.AdmissionLoop(landed_timeout=60.0)
    loop._inflight = ("ml", "train-a", time.time() - 61.0)  # 超过超时窗口
    loop.tick()

    assert released == [("ml", "train-b")]


def test_tick_noop_on_empty_queue(monkeypatch):
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([], None))
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    qa.AdmissionLoop().tick()

    assert released == []


def test_tick_noop_when_queue_unavailable(monkeypatch):
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: ([], "cluster unreachable"))
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    qa.AdmissionLoop().tick()

    assert released == []


def test_tick_picks_highest_priority_pending_job(monkeypatch):
    jobs = [
        _job(name="low-pri", priority="low", submitted="2026-06-28T08:00:00Z"),
        _job(name="high-pri", priority="high", submitted="2026-06-28T09:00:00Z"),
    ]
    monkeypatch.setattr(qa, "list_queued_jobs", lambda: (jobs, None))
    monkeypatch.setattr(qa, "free_gpu_count", lambda pool: 1)
    released = []
    monkeypatch.setattr(qa, "release_queued_job", lambda ns, name: released.append((ns, name)))

    qa.AdmissionLoop().tick()

    assert released == [("ml", "high-pri")]
