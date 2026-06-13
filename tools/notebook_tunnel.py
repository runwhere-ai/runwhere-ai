#!/usr/bin/env python3
"""Local TCP proxy: 127.0.0.1:8088 -> ssh runw -> nc 127.0.0.1:30808 (runwhere-ai console in remote WSL2).

Why this exists
---------------
和 k3s_proxy.py 同一个原因:LEON-AIPC 的 WSL2 宿主↔WSL 网络不稳定,Windows 宿主无法可靠
访问 WSL2 的 NAT IP —— 所以 nginx/portproxy/`ssh -L` 都时通时断。但 `ssh runw` 落进 WSL 内部
(进程 exec,不走网络),里面 `nc 127.0.0.1 30808` 直达 console NodePort,稳定可靠。

本脚本本地监听 8088,每个连接经一条 `ssh runw "nc 127.0.0.1 30808"` 中继桥接(HTTP + WebSocket
都是裸字节转发,内核 WS 照样通)。console 的 notebook 反代(/nb/<ns>/<name>/)随之可用。

跑:  python tools/notebook_tunnel.py        (仅标准库;Ctrl-C 停)
然后浏览器打开:  http://127.0.0.1:8088/                              ← 控制台
                http://127.0.0.1:8088/nb/<ns>/<notebook>/lab?token=<token>   ← notebook
"""
import os
import socket
import subprocess
import threading

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8088
SSH_TARGET = "runw"
REMOTE_CMD = "nc 127.0.0.1 30808"
SSH_ARGS = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-T",
    SSH_TARGET,
    REMOTE_CMD,
]


def _sock_to_pipe(sock, wfd, done):
    try:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            os.write(wfd, data)
    except OSError:
        pass
    finally:
        try:
            os.close(wfd)
        except OSError:
            pass
        done.set()


def _pipe_to_sock(rfd, sock, done):
    try:
        while True:
            data = os.read(rfd, 65536)
            if not data:
                break
            sock.sendall(data)
    except OSError:
        pass
    finally:
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        done.set()


def handle(client):
    proc = subprocess.Popen(SSH_ARGS, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    done = threading.Event()
    threading.Thread(target=_sock_to_pipe, args=(client, proc.stdin.fileno(), done), daemon=True).start()
    threading.Thread(target=_pipe_to_sock, args=(proc.stdout.fileno(), client, done), daemon=True).start()
    done.wait()
    for fn in (proc.terminate, client.close):
        try:
            fn()
        except Exception:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((LISTEN_HOST, LISTEN_PORT))
    srv.listen(128)
    print(f"notebook-tunnel listening {LISTEN_HOST}:{LISTEN_PORT} -> ssh {SSH_TARGET} :: {REMOTE_CMD}", flush=True)
    print(f"  console : http://{LISTEN_HOST}:{LISTEN_PORT}/", flush=True)
    while True:
        client, _ = srv.accept()
        threading.Thread(target=handle, args=(client,), daemon=True).start()


if __name__ == "__main__":
    main()
