"""ViewModel builder — the contract between Service layer and HTML templates.

Templates MUST consume only fields defined here; raw K8s dicts never leak
into Jinja. Per-kind ViewModels are extended in user-story slices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.console.informer import SharedInformer
from src.console.models import Kind
from src.console.status_palette import StatusPalette


# ─── Page-level VMs ──────────────────────────────────────────────────────────

@dataclass
class StatusVM:
    raw: str
    color: str
    label: str
    explanation: str
    is_failure: bool
    is_terminal: bool


@dataclass
class WorkloadListItemVM:
    kind: Kind
    namespace: str
    name: str
    status: StatusVM
    pool: str = "default"
    gpu: int = 0
    age: str = "—"
    ready: str = ""
    detail_url: str = ""
    resource_version: str = ""


@dataclass
class WorkloadDetailVM:
    kind: Kind
    namespace: str
    name: str
    status: StatusVM
    pool: str = "default"
    age: str = "—"
    resource_version: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    access_methods: Optional[dict[str, Any]] = None
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkloadListPage:
    kind: Kind
    namespace: Optional[str]
    items: list[WorkloadListItemVM]
    total: int
    resource_version: str


# ─── Builder ──────────────────────────────────────────────────────────────────

class WorkloadViewModelBuilder:
    """Reads from a SharedInformer and produces ViewModels.

    Per-kind ViewModels are extended in their respective slices by
    composing this builder with kind-specific field extractors.
    """

    def __init__(self, informer: SharedInformer) -> None:
        self._informer = informer

    def _build_status(self, raw_status: str) -> StatusVM:
        return StatusVM(
            raw=raw_status,
            color=StatusPalette.color(raw_status),
            label=raw_status,
            explanation=StatusPalette.explain(raw_status),
            is_failure=StatusPalette.is_failure(raw_status),
            is_terminal=StatusPalette.is_terminal(raw_status),
        )

    def _row(self, obj: dict[str, Any], kind: Kind) -> WorkloadListItemVM:
        status = self._build_status(obj.get("status", "Unknown"))
        name = obj.get("name", "")
        ns = obj.get("namespace", "default")
        return WorkloadListItemVM(
            kind=kind,
            namespace=ns,
            name=name,
            status=status,
            pool=obj.get("pool") or obj.get("labels", {}).get("runwhere.ai/pool", "default"),
            gpu=int((obj.get("resources") or {}).get("gpu", 0) or 0),
            age=obj.get("age") or "—",
            ready=obj.get("ready", ""),
            detail_url=_detail_url(kind, name),
            resource_version=obj.get("resource_version", ""),
        )

    def list(
        self,
        kind: Kind,
        namespace: Optional[str] = None,
        filters: Optional[dict[str, str]] = None,
    ) -> WorkloadListPage:
        raw_items = self._informer.list(namespace=namespace, filters=filters)
        rows = [self._row(o, kind) for o in raw_items]
        return WorkloadListPage(
            kind=kind,
            namespace=namespace,
            items=rows,
            total=len(rows),
            resource_version=self._informer.latest_resource_version,
        )

    def detail(self, kind: Kind, namespace: str, name: str) -> Optional[WorkloadDetailVM]:
        obj = self._informer.get(namespace, name)
        if obj is None:
            return None
        return WorkloadDetailVM(
            kind=kind,
            namespace=namespace,
            name=name,
            status=self._build_status(obj.get("status", "Unknown")),
            pool=obj.get("pool", "default"),
            age=obj.get("age") or "—",
            resource_version=obj.get("resource_version", ""),
            raw=obj,
            events=obj.get("events", []),
            access_methods=obj.get("access_methods"),
            metrics=obj.get("metrics", {}),
        )


def _detail_url(kind: Kind, name: str) -> str:
    """Each kind has its own URL namespace (FR-011)."""
    return {
        Kind.NOTEBOOK: f"/notebooks/{name}",
        Kind.TRAINING: f"/trainings/{name}",
        Kind.INFERENCE: f"/inferences/{name}",
        Kind.COMPUTE: f"/computes/{name}",
    }.get(kind, f"/{kind.value}s/{name}")
