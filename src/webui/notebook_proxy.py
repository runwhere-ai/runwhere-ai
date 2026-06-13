"""Notebook 反向代理:把 jupyter 经 console(唯一对外端口)透出,免去每个 notebook 的 NodePort。

访问 `/nb/{namespace}/{name}/<path>` → console 代理到 notebook 的 ClusterIP Service
`http://svc-{name}.{namespace}:8888/nb/{namespace}/{name}/<path>`(HTTP 与 WebSocket 都代理)。

前提:notebook 启动时 jupyter 的 base_url 设为 `/nb/{namespace}/{name}/`(由 gpuctl
notebook builder 经 NOTEBOOK_ARGS 注入),这样 jupyter 的内部链接/重定向/静态资源在
前缀下都正确。WS(内核/终端)与 HTTP 走同一路径前缀。

为什么这样:WSL2 + Tailscale + Windows 防火墙下逐个发布随机 NodePort 既脆又不可扩展;
反代让一切走已稳定发布的 console 端口,任何拓扑(含生产 ingress)通用。
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp
from fastapi import APIRouter, Depends, Request, WebSocket
from starlette.responses import Response

from src.console.models import AuthError, User
from src.webui.deps import get_auth_provider, get_current_user

logger = logging.getLogger("src.webui.notebook_proxy")
router = APIRouter(tags=["notebook-proxy"])

# 上游 jupyter 服务端口(notebook Service 的 port,约定 8888)
_NB_PORT = 8888
# 不应透传的逐跳头
_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer",
        "upgrade", "proxy-authorization", "proxy-authenticate", "content-length",
        "content-encoding", "host"}


def _svc_host(name: str, namespace: str) -> str:
    # gpuctl 的 notebook Service 名为 svc-<name>
    return f"svc-{name}.{namespace}"


@router.api_route(
    "/nb/{namespace}/{name}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy_http(namespace: str, name: str, path: str, request: Request,
                     _user: User = Depends(get_current_user)):
    # 与全站一致的会话鉴权:平台(kubeconfig)模式恒返回固定身份 → no-op;
    # 真实鉴权(bearer/oidc)模式下未登录则 401,堵住「代理绕过会话」的口子。
    # notebook 自身的 jupyter token 仍是内层第二道防线。
    url = f"http://{_svc_host(name, namespace)}:{_NB_PORT}/nb/{namespace}/{name}/{path}"
    fwd = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
    body = await request.body()
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(
                request.method, url,
                params=request.query_params, headers=fwd, data=body or None,
                allow_redirects=False,
            ) as resp:
                content = await resp.read()  # aiohttp 默认已解压
                out_headers = {k: v for k, v in resp.headers.items()
                               if k.lower() not in _HOP}
                return Response(content=content, status_code=resp.status,
                                headers=out_headers,
                                media_type=resp.headers.get("Content-Type"))
    except aiohttp.ClientError as exc:
        logger.warning("notebook proxy http %s/%s: %s", namespace, name, exc)
        return Response(content=b"notebook upstream unavailable", status_code=502)


@router.websocket("/nb/{namespace}/{name}/{path:path}")
async def proxy_ws(websocket: WebSocket, namespace: str, name: str, path: str):
    # WS 无 Request,无法用 Depends(get_current_user);手动用 provider 校验。
    # WebSocket 同为 Starlette HTTPConnection,provider 照样能读 cookie/session。
    # 平台模式 no-op;真实鉴权模式未登录则在握手前以 1008 关闭。
    try:
        await get_auth_provider().authenticate(websocket)
    except AuthError:
        await websocket.close(code=1008)  # policy violation
        return

    q = websocket.url.query
    ws_url = f"ws://{_svc_host(name, namespace)}:{_NB_PORT}/nb/{namespace}/{name}/{path}"
    if q:
        ws_url += f"?{q}"

    # 透传 cookie(jupyter 鉴权)与子协议(内核 WS 用 v1.kernel.websocket.jupyter.org)
    sub = websocket.headers.get("sec-websocket-protocol")
    protocols = [p.strip() for p in sub.split(",")] if sub else []
    headers = {}
    if websocket.headers.get("cookie"):
        headers["Cookie"] = websocket.headers["cookie"]

    session = aiohttp.ClientSession()
    try:
        upstream = await session.ws_connect(
            ws_url, headers=headers, protocols=protocols or (),
            heartbeat=None, max_msg_size=0, autoping=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("notebook proxy ws connect %s/%s: %s", namespace, name, exc)
        await session.close()
        await websocket.close(code=1011)
        return

    negotiated = getattr(upstream, "protocol", None) or (protocols[0] if protocols else None)
    await websocket.accept(subprotocol=negotiated)

    async def client_to_upstream():
        try:
            while True:
                msg = await websocket.receive()
                t = msg.get("type")
                if t == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await upstream.send_str(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send_bytes(msg["bytes"])
        except Exception:  # noqa: BLE001
            pass

    async def upstream_to_client():
        try:
            async for m in upstream:
                if m.type == aiohttp.WSMsgType.TEXT:
                    await websocket.send_text(m.data)
                elif m.type == aiohttp.WSMsgType.BINARY:
                    await websocket.send_bytes(m.data)
                else:
                    break
        except Exception:  # noqa: BLE001
            pass

    t1 = asyncio.create_task(client_to_upstream())
    t2 = asyncio.create_task(upstream_to_client())
    try:
        _, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    finally:
        await upstream.close()
        await session.close()
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
