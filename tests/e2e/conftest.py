"""E2E-specific fixtures.

We rely on `uvicorn_server` from the parent conftest. If a Kubernetes
context is unreachable, individual E2E tests can opt-out via the
`requires_k8s` marker (registered in pytest.ini via pyproject).
"""
from __future__ import annotations

import os
import shutil

import pytest


def _has_k8s_context() -> bool:
    """Best-effort check: did the developer set up a usable cluster?"""
    if not shutil.which("kubectl"):
        return False
    kubeconfig = os.environ.get("KUBECONFIG") or os.path.expanduser("~/.kube/config")
    return os.path.exists(kubeconfig)


@pytest.fixture(scope="session")
def k8s_available() -> bool:
    return _has_k8s_context()


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked `requires_k8s` when no cluster is available."""
    skip_no_k8s = pytest.mark.skip(reason="no Kubernetes context (set up Kind via scripts/dev-kind-up.sh)")
    if not _has_k8s_context():
        for item in items:
            if "requires_k8s" in item.keywords:
                item.add_marker(skip_no_k8s)
