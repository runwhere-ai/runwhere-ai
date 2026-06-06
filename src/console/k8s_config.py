"""gpuctl-compatible Kubernetes client config loader."""
from __future__ import annotations


async def load_k8s_config() -> str:
    from kubernetes_asyncio import config as k8s_config  # type: ignore
    from gpuctl.kube_config import load_k8s_config_async

    return await load_k8s_config_async(k8s_config)
