"""NFS registration on the cluster-config page (writes kube-system/gpuctl-config).

The console reuses gpuctl's ``init_storage`` (same path as ``gpuctl init``).
``_read_nfs`` wraps ``BaseBuilder.read_nfs_config`` and returns (None, None)
off-cluster, so the page renders "未配置" without a live cluster.
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_cluster_config_shows_nfs_card(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))

    r = await client.get("/cluster-config", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "NFS 持久化存储" in r.text
    assert "未配置" in r.text  # no NFS registered in tests


@pytest.mark.asyncio
async def test_cluster_config_shows_nfs_status_when_configured(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))
    monkeypatch.setattr(
        "src.webui.pages.cluster_config._read_nfs",
        lambda: ("10.0.0.5", "/exports"),
    )

    r = await client.get("/cluster-config", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "10.0.0.5" in r.text
    assert "/exports" in r.text


@pytest.mark.asyncio
async def test_nfs_register_happy_path_calls_init_storage(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))
    calls: dict = {}

    def fake_init(server, path):
        calls["server"], calls["path"] = server, path
        return {"status": "created"}

    # 路由内 `from gpuctl.cli.init import init_storage`,patch 源模块属性即可。
    monkeypatch.setattr("gpuctl.cli.init.init_storage", fake_init)

    r = await client.post(
        "/cluster-config/nfs",
        data={"nfs_server": "  10.0.0.5  ", "nfs_path": "  /exports  "},
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert r.headers["location"] == "/cluster-config?message=nfs-saved"
    assert calls == {"server": "10.0.0.5", "path": "/exports"}  # 已 strip


@pytest.mark.asyncio
async def test_nfs_register_rejects_bad_path(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))

    # 真 init_storage 在碰 K8s 前先校验参数;路径不以 / 开头 → ValueError。
    r = await client.post(
        "/cluster-config/nfs",
        data={"nfs_server": "10.0.0.5", "nfs_path": "exports"},
    )

    assert r.status_code == 400
    assert "nfs-path" in r.text
