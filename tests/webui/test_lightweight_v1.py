from __future__ import annotations

import pytest

from src.console.job_queue import QueuedJob


class _EmptyGpuStore:
    def snapshot(self):
        return {}


@pytest.mark.asyncio
async def test_gpu_overview_empty_store_shows_unknown_not_demo(client, monkeypatch):
    import src.webui.pages.gpu_overview as gpu_overview

    monkeypatch.setattr(gpu_overview, "STORE", _EmptyGpuStore())

    r = await client.get("/gpu", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "GPU 真实占用未知" in r.text
    assert "演示数据" not in r.text


@pytest.mark.asyncio
async def test_free_cards_empty_store_is_unknown(client, monkeypatch):
    import src.webui.pages.gpu_overview as gpu_overview

    monkeypatch.setattr(gpu_overview, "STORE", _EmptyGpuStore())

    r = await client.get("/api/gpu/free-cards")

    assert r.status_code == 200
    assert r.json() == {"cards": [], "unknown": True}


@pytest.mark.asyncio
async def test_queue_empty_cluster_shows_no_demo_data(client, monkeypatch):
    import src.webui.pages.gpu_queue as gpu_queue

    monkeypatch.setattr(gpu_queue, "list_queued_jobs", lambda: ([], None))

    r = await client.get("/queue", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "暂无排队任务" in r.text
    assert "演示数据" not in r.text


@pytest.mark.asyncio
async def test_queue_unavailable_is_unknown_not_zero_truth(client, monkeypatch):
    import src.webui.pages.gpu_queue as gpu_queue

    monkeypatch.setattr(gpu_queue, "list_queued_jobs", lambda: ([], "boom"))

    r = await client.get("/queue", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "队列状态未知" in r.text
    assert "队列不可用" in r.text


@pytest.mark.asyncio
async def test_queue_manual_release_uses_namespace_and_job_name(client, monkeypatch):
    import src.webui.pages.gpu_queue as gpu_queue

    called = []
    jobs = [
        QueuedJob(
            namespace="team-a",
            name="train-a",
            priority="medium",
            gpus=1,
            pool="default",
            owner="alice",
            submitted_at="2026-07-01T00:00:00+00:00",
            state="pending",
        )
    ]

    monkeypatch.setattr(gpu_queue, "list_queued_jobs", lambda: (jobs, None))
    monkeypatch.setattr(gpu_queue, "release_queued_job",
                        lambda namespace, name: called.append((namespace, name)))

    page = await client.get("/queue", headers={"Accept": "text/html"})
    assert "releaseQueuedJob('team-a', 'train-a')" in page.text

    r = await client.post("/queue/team-a/train-a/release")

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called == [("team-a", "train-a")]


@pytest.mark.asyncio
async def test_dashboard_queue_card_shows_counts(client, monkeypatch):
    import src.webui.pages.dashboard as dashboard
    import src.webui.pages.gpu_queue as gpu_queue

    async def _stats(_namespace=None):
        return {
            "running_jobs": 0,
            "total_jobs": 0,
            "gpu_util_pct": None,
            "gpu_mem_pct": None,
            "tele_n": 0,
            "node_count": 0,
        }

    monkeypatch.setattr(dashboard, "_dashboard_stats", _stats)
    monkeypatch.setattr(gpu_queue, "queued_counts", lambda: (2, 1, True))

    r = await client.get("/dashboard", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "排队中" in r.text
    assert "排不上" in r.text
    assert "Queued Jobs" in r.text


@pytest.mark.asyncio
async def test_dashboard_queue_card_shows_unknown_when_unavailable(client, monkeypatch):
    import src.webui.pages.dashboard as dashboard
    import src.webui.pages.gpu_queue as gpu_queue

    async def _stats(_namespace=None):
        return {
            "running_jobs": 0,
            "total_jobs": 0,
            "gpu_util_pct": None,
            "gpu_mem_pct": None,
            "tele_n": 0,
            "node_count": 0,
        }

    monkeypatch.setattr(dashboard, "_dashboard_stats", _stats)
    monkeypatch.setattr(gpu_queue, "queued_counts", lambda: (0, 0, False))

    r = await client.get("/dashboard", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "Unavailable" in r.text


@pytest.mark.asyncio
async def test_quickstart_keeps_advanced_interactions_honest(client):
    r = await client.get("/quickstart/team-std-batch", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "指定数量" in r.text
    assert "指定卡号" in r.text
    assert "读取空闲卡" in r.text
    assert "未知状态不会当作空闲" in r.text
    assert "空了自动跑" not in r.text
