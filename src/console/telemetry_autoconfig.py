"""GPU 指标采集(telemetry)自动配置。

GPU 利用率/显存这类指标 k8s apiserver 不提供(只在显卡驱动 NVML 层),所以必须有
采集器去读卡。gpuctl 用「每个 GPU 任务 Pod 注入一个采集 sidecar」的方式实现——
它天然支持多机:任务调度到哪个节点,sidecar 就跟到哪、读那张卡、上报回 console。

本模块解决「sidecar 往哪上报」这唯一需要按部署方式适配的点,**全自动、零手动配置**:
- 集群内(Pod):上报到 console 自己的 Service DNS —— 所有节点的 Pod 都可达,多机就绪。
- host/docker:上报到本机节点的可达 IP(默认路由出口 IP)—— 别的节点 Pod 也访问得到。

推导出的地址写入 ``os.environ['GPUCTL_TELEMETRY_ENDPOINT']`` 供 gpuctl 的
``build_telemetry_sidecar`` 读取。管理员/用户**无需设置任何 IP 或 endpoint**。
"""
from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger("src.console.telemetry")

_K8S_NS_FILE = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def _detect_host_ip() -> str:
    """本机默认路由出口 IP(= 该节点对外可达、Pod 也能访问的 IP)。

    用一个不真正发包的 UDP socket 让内核选出口接口,从而拿到本机主 IP;
    比硬编码 10.42.0.1(每节点本地网关、跨节点不可达)正确,单机多机都适用。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()


def _in_cluster_namespace() -> str:
    ns = os.getenv("RWAI_NAMESPACE")
    if ns:
        return ns
    try:
        with open(_K8S_NS_FILE, encoding="utf-8") as f:
            return f.read().strip() or "default"
    except Exception:  # noqa: BLE001
        return "default"


def configure_telemetry(port: int | str = 8000) -> str:
    """推导并设置 GPU 采集 sidecar 的上报端点 + 采集模式。返回最终 endpoint。

    幂等:已显式给了 GPUCTL_TELEMETRY_ENDPOINT 则尊重(内部兜底,常规无需)。
    """
    endpoint = os.getenv("GPUCTL_TELEMETRY_ENDPOINT")
    if endpoint:
        logger.info("telemetry endpoint 由 env 显式指定: %s", endpoint)
    else:
        if os.getenv("KUBERNETES_SERVICE_HOST"):  # 集群内运行
            ns = _in_cluster_namespace()
            svc = os.getenv("RWAI_SERVICE_NAME", "runwhere-ai")
            host = f"{svc}.{ns}.svc.cluster.local"
            mode = "in-cluster→Service"
        else:  # host 进程 / docker(--network host)
            host = _detect_host_ip()
            mode = "host/docker→node-ip"
        endpoint = f"http://{host}:{port}/api/v1/telemetry"
        os.environ["GPUCTL_TELEMETRY_ENDPOINT"] = endpoint
        logger.info("telemetry endpoint 自动推导[%s]: %s", mode, endpoint)
    # shell 采集器(cuda base + bash,无需自建镜像)。已设则尊重。
    os.environ.setdefault("GPUCTL_TELEMETRY_MODE", "shell")
    return endpoint
