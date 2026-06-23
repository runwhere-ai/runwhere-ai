"""Unit tests for _job_rows pod→job grouping.

gpuctl /api/v1/jobs is Pod-level (one entry per pod). The UI list must show ONE row
per job — pods of the same job (failed retries / multi-node) are grouped in the UI
layer (_job_rows), with a representative pod chosen by status priority. Each pod's
detail stays on the detail page. This keeps the shared /api/v1/jobs contract Pod-level.
"""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, patch


def _item(job_id, name, namespace, status, ready="0/1"):
    return types.SimpleNamespace(
        jobId=job_id, name=name, namespace=namespace, status=status,
        ready=ready, node="node-1", ip="10.0.0.1", age="5m", kind="training",
    )


def _delbtn(row):
    for cell in row:
        if isinstance(cell, dict) and "delbtn" in cell:
            return cell["delbtn"]
    return None


async def test_job_rows_groups_failed_retry_pods_into_one_row():
    """同一个作业的多个 Pod(失败重试 backoff)折叠成一行;删除按作业名 + namespace。"""
    from src.webui.pages import stubs

    resp = types.SimpleNamespace(items=[
        _item("axolotl-ft-aaa1", "axolotl-ft", "default", "Failed"),
        _item("axolotl-ft-bbb2", "axolotl-ft", "default", "Failed"),
        _item("axolotl-ft-ccc3", "axolotl-ft", "default", "Failed"),
    ])
    with patch("server.routes.jobs.get_jobs", new=AsyncMock(return_value=resp)):
        rows = await stubs._job_rows("training", namespace="default")

    assert len(rows) == 1                       # 3 个 Pod → 1 行
    db = _delbtn(rows[0])
    assert db is not None
    assert db["name"] == "axolotl-ft"           # 删除按作业名(控制器名)
    assert db["namespace"] == "default"


async def test_job_rows_representative_prefers_running():
    """混合状态时,代表 Pod 取状态优先级最高的(Running 优先于 Failed);
    删除轮询用的 pod(=代表 jobId)、GPU 遥测列都跟着代表 Pod。"""
    from src.webui.pages import stubs

    resp = types.SimpleNamespace(items=[
        _item("job-x-0", "job-x", "default", "Failed"),
        _item("job-x-1", "job-x", "default", "Running", ready="1/1"),
    ])
    with patch("server.routes.jobs.get_jobs", new=AsyncMock(return_value=resp)):
        rows = await stubs._job_rows("training", namespace="default")

    assert len(rows) == 1
    db = _delbtn(rows[0])
    assert db["name"] == "job-x"
    assert db["pod"] == "job-x-1"               # 代表 = Running 的那个 Pod


async def test_job_rows_distinct_jobs_stay_separate_and_ordered():
    """不同作业不被误并;行序按首次出现稳定。"""
    from src.webui.pages import stubs

    resp = types.SimpleNamespace(items=[
        _item("a-1", "job-a", "default", "Running"),
        _item("b-1", "job-b", "default", "Running"),
        _item("a-2", "job-a", "default", "Failed"),
    ])
    with patch("server.routes.jobs.get_jobs", new=AsyncMock(return_value=resp)):
        rows = await stubs._job_rows("training", namespace="default")

    assert len(rows) == 2
    names = [_delbtn(r)["name"] for r in rows]
    assert names == ["job-a", "job-b"]          # 稳定:按首次出现
