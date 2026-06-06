"""Tests for the central Kubernetes config loader."""
from __future__ import annotations

import sys
import types

import pytest

from src.console.k8s_config import load_k8s_config


def _install_fake_k8s(monkeypatch, fake_config):
    fake_pkg = types.SimpleNamespace(config=fake_config)
    monkeypatch.setitem(sys.modules, "kubernetes_asyncio", fake_pkg)


@pytest.mark.asyncio
async def test_uses_incluster_when_service_host_is_present(monkeypatch):
    calls = []

    class FakeConfig:
        def load_incluster_config(self):
            calls.append("incluster")

        async def load_kube_config(self, **kwargs):
            calls.append(("kubeconfig", kwargs))

    _install_fake_k8s(monkeypatch, FakeConfig())
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")

    assert await load_k8s_config() == "incluster"
    assert calls == ["incluster"]


@pytest.mark.asyncio
async def test_uses_kubeconfig_outside_cluster(monkeypatch):
    calls = []

    class FakeConfig:
        def load_incluster_config(self):
            calls.append("incluster")

        async def load_kube_config(self, **kwargs):
            calls.append(("kubeconfig", kwargs))

    _install_fake_k8s(monkeypatch, FakeConfig())
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)

    assert await load_k8s_config() == "kubeconfig"
    assert calls == [("kubeconfig", {})]


@pytest.mark.asyncio
async def test_kubeconfig_exceptions_propagate(monkeypatch):
    calls = []

    class FakeConfig:
        def load_incluster_config(self):
            calls.append("incluster")

        async def load_kube_config(self, **kwargs):
            calls.append(("kubeconfig", kwargs))
            raise RuntimeError("bad kubeconfig")

    _install_fake_k8s(monkeypatch, FakeConfig())
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)

    with pytest.raises(RuntimeError):
        await load_k8s_config()
    assert calls == [("kubeconfig", {})]


@pytest.mark.asyncio
async def test_incluster_exceptions_propagate(monkeypatch):
    calls = []

    class FakeConfig:
        def load_incluster_config(self):
            calls.append("incluster")
            raise RuntimeError("not in cluster")

        async def load_kube_config(self, **kwargs):
            calls.append(("kubeconfig", kwargs))

    _install_fake_k8s(monkeypatch, FakeConfig())
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.0.0.1")

    with pytest.raises(RuntimeError):
        await load_k8s_config()
    assert calls == ["incluster"]
