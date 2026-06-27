"""_job_detail_ctx surfaces NFS mounts + multi-node distributed info.

NFS mounts come from the cluster-level ConfigMap (read_nfs_config); distributed
topology is derived from the live Job spec (Indexed completion mode + completions),
since the reconstructed yaml_content / _job_to_dict carry neither.
"""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _detail(**kw):
    base = dict(
        status="Running", age="5m", pool="training-pool", priority="medium",
        resource_type="Job", events=[], yaml_content={}, namespace="ml-team",
        access_methods=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def _batch_returning(completion_mode, completions):
    spec = types.SimpleNamespace(completion_mode=completion_mode, completions=completions)
    batch = MagicMock()
    batch.read_namespaced_job.return_value = types.SimpleNamespace(spec=spec)
    return batch


@pytest.mark.asyncio
async def test_detail_ctx_sets_nfs_mounts_when_configured():
    from src.webui.pages import stubs

    with patch("server.routes.jobs.get_job_detail", new=AsyncMock(return_value=_detail())), \
         patch("gpuctl.client.job_client.JobClient.list_pods", return_value=[]), \
         patch("gpuctl.builder.base_builder.BaseBuilder.read_nfs_config",
               return_value=("10.0.0.5", "/exports")), \
         patch("kubernetes.client.BatchV1Api", return_value=_batch_returning(None, 1)):
        ctx = await stubs._job_detail_ctx("training", "job1", "ml-team")

    assert ctx["nfs"]["server"] == "10.0.0.5"
    assert ctx["nfs"]["home"] == "10.0.0.5:/exports/home/ml-team"
    assert ctx["nfs"]["datasets"] == "10.0.0.5:/exports/datasets"


@pytest.mark.asyncio
async def test_detail_ctx_no_nfs_when_not_configured():
    from src.webui.pages import stubs

    with patch("server.routes.jobs.get_job_detail", new=AsyncMock(return_value=_detail())), \
         patch("gpuctl.client.job_client.JobClient.list_pods", return_value=[]), \
         patch("gpuctl.builder.base_builder.BaseBuilder.read_nfs_config", return_value=None), \
         patch("kubernetes.client.BatchV1Api", return_value=_batch_returning(None, 1)):
        ctx = await stubs._job_detail_ctx("training", "job1", "ml-team")

    assert "nfs" not in ctx


@pytest.mark.asyncio
async def test_detail_ctx_detects_multinode():
    from src.webui.pages import stubs

    with patch("server.routes.jobs.get_job_detail", new=AsyncMock(return_value=_detail())), \
         patch("gpuctl.client.job_client.JobClient.list_pods", return_value=[]), \
         patch("gpuctl.builder.base_builder.BaseBuilder.read_nfs_config", return_value=None), \
         patch("kubernetes.client.BatchV1Api", return_value=_batch_returning("Indexed", 4)):
        ctx = await stubs._job_detail_ctx("training", "llm-pretrain", "ml-team")

    assert ctx["distributed"]["mode"] == "multi-node"
    assert ctx["distributed"]["workers"] == 4
    assert ctx["distributed"]["headless"] == "llm-pretrain-headless.ml-team.svc.cluster.local"


@pytest.mark.asyncio
async def test_detail_ctx_standalone_has_no_distributed():
    from src.webui.pages import stubs

    with patch("server.routes.jobs.get_job_detail", new=AsyncMock(return_value=_detail())), \
         patch("gpuctl.client.job_client.JobClient.list_pods", return_value=[]), \
         patch("gpuctl.builder.base_builder.BaseBuilder.read_nfs_config", return_value=None), \
         patch("kubernetes.client.BatchV1Api", return_value=_batch_returning(None, 1)):
        ctx = await stubs._job_detail_ctx("training", "single", "ml-team")

    assert "distributed" not in ctx


@pytest.mark.asyncio
async def test_detail_ctx_distributed_probe_skipped_for_non_training():
    from src.webui.pages import stubs

    # notebook 详情不应触发分布式探测(BatchV1Api 不被调用)
    batch = _batch_returning("Indexed", 4)
    with patch("server.routes.jobs.get_job_detail",
               new=AsyncMock(return_value=_detail(resource_type="StatefulSet"))), \
         patch("gpuctl.client.job_client.JobClient.list_pods", return_value=[]), \
         patch("gpuctl.builder.base_builder.BaseBuilder.read_nfs_config", return_value=None), \
         patch("kubernetes.client.BatchV1Api", return_value=batch):
        ctx = await stubs._job_detail_ctx("notebook", "nb1", "ml-team")

    assert "distributed" not in ctx
    batch.read_namespaced_job.assert_not_called()
