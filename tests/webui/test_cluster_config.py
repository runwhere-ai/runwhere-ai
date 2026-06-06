"""Cluster config UI backed by gpuctl config."""
from __future__ import annotations

import pytest

from gpuctl.kube_config import load_gpuctl_config


@pytest.mark.asyncio
async def test_cluster_config_page_renders(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))

    r = await client.get("/cluster-config", headers={"Accept": "text/html"})

    assert r.status_code == 200
    assert "集群配置" in r.text
    assert "kubeconfig 文件路径" in r.text
    assert "gpuctl 配置文件" in r.text


@pytest.mark.asyncio
async def test_cluster_config_post_saves_gpuctl_config(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))
    kubeconfig = tmp_path / "admin.conf"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")

    r = await client.post(
        "/cluster-config",
        data={"kubeconfig": str(kubeconfig), "context": "prod"},
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert r.headers["location"] == "/cluster-config?message=saved"
    settings = load_gpuctl_config()
    assert settings.kubeconfig == str(kubeconfig)
    assert settings.context == "prod"


@pytest.mark.asyncio
async def test_cluster_config_post_rejects_missing_file(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))

    r = await client.post(
        "/cluster-config",
        data={"kubeconfig": str(tmp_path / "missing.conf"), "context": ""},
    )

    assert r.status_code == 400
    assert "does not exist" in r.text


@pytest.mark.asyncio
async def test_cluster_config_clear(client, tmp_path, monkeypatch):
    monkeypatch.setenv("GPUCTL_CONFIG_HOME", str(tmp_path / "gpuctl"))
    kubeconfig = tmp_path / "admin.conf"
    kubeconfig.write_text("apiVersion: v1\n", encoding="utf-8")
    await client.post("/cluster-config", data={"kubeconfig": str(kubeconfig), "context": "prod"})

    r = await client.post("/cluster-config/clear", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/cluster-config?message=cleared"
    assert load_gpuctl_config().kubeconfig is None

