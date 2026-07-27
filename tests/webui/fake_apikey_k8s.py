"""内存版 CoreV1Api（仅 Secret 四个操作），供 API Keys 相关测试注入 ApiKeyStore。

与 gpuctl 仓库 tests/apikeys/fake_k8s.py 同构；两个仓库是独立 git 仓库，故各自
维护一份而非跨仓库导入测试代码。
"""
from __future__ import annotations

import base64

from kubernetes.client.rest import ApiException


class FakeCoreV1:
    def __init__(self):
        self.secrets = {}

    def create_namespaced_secret(self, namespace, body):
        if body.string_data:
            body.data = {k: base64.b64encode(v.encode()).decode()
                         for k, v in body.string_data.items()}
            body.string_data = None
        key = (namespace, body.metadata.name)
        if key in self.secrets:
            raise ApiException(status=409, reason="AlreadyExists")
        self.secrets[key] = body
        return body

    def read_namespaced_secret(self, name, namespace):
        try:
            return self.secrets[(namespace, name)]
        except KeyError:
            raise ApiException(status=404, reason="NotFound")

    def list_namespaced_secret(self, namespace, label_selector=None):
        class _Result:
            pass
        items = []
        for (ns, _), secret in self.secrets.items():
            if ns != namespace:
                continue
            if label_selector:
                k, _, v = label_selector.partition("=")
                if (secret.metadata.labels or {}).get(k) != v:
                    continue
            items.append(secret)
        r = _Result()
        r.items = items
        return r

    def delete_namespaced_secret(self, name, namespace):
        try:
            del self.secrets[(namespace, name)]
        except KeyError:
            raise ApiException(status=404, reason="NotFound")
