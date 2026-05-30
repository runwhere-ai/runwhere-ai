"""Pydantic form schemas for creating workloads.

The base ``WorkloadSpec`` carries fields common to all four kinds. Kind-
specific extensions (``NotebookSpec`` etc.) are added by each user-story
slice in later phases. The contract guarantees:

  - validators run on raw HTML form data
  - ``to_gpuctl_yaml()`` produces text accepted by gpuctl's BaseParser
  - validation errors carry line numbers when the source is YAML

Spec FR-030, FR-031.  data-model.md §3.3.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from src.console.models import Kind


# ─── Subcomponents shared across kinds ────────────────────────────────────────

class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResourceRequest(BaseModel):
    cpu: str = "1"
    memory: str = "2Gi"
    gpu: int = Field(default=0, ge=0)
    gpu_type: Optional[str] = None

    @field_validator("memory")
    @classmethod
    def _validate_quantity(cls, v: str) -> str:
        # Loose K8s quantity check; full validation deferred to gpuctl parser.
        if not re.match(r"^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?$", v):
            raise ValueError(f"invalid K8s quantity: {v!r}")
        return v


class VolumeRef(BaseModel):
    type: str = Field(description="pvc | hostpath | s3 | ...")
    name: str
    mount_path: str

    @field_validator("mount_path")
    @classmethod
    def _absolute(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("mount_path must be absolute")
        return v


# ─── Base WorkloadSpec ────────────────────────────────────────────────────────

_NAME_RE = re.compile(r"^[a-z]([-a-z0-9]{0,61}[a-z0-9])?$")


class WorkloadSpec(BaseModel):
    """Common base — each user story adds an ``Optional[KindSpec]`` field.

    For now this is enough for the auth + boot path; kind-specific
    subclasses live in their own modules created during US1~US4.
    """

    kind: Kind
    name: str
    namespace: str = "default"
    image: str
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    resources: ResourceRequest = Field(default_factory=ResourceRequest)
    pool: str = "default"
    volumes: list[VolumeRef] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                "name must be lowercase alphanumeric + '-', start with a letter, end with alphanumeric"
            )
        return v

    # ── YAML interop ───────────────────────────────────────────────────────

    def to_gpuctl_yaml(self) -> str:
        """Serialise into the YAML shape gpuctl's BaseParser accepts.

        v1 returns a deliberately conservative subset; the real schema
        expansion happens per-kind in later slices.
        """
        doc = {
            "kind": self.kind.value,
            "metadata": {"name": self.name, "namespace": self.namespace},
            "spec": {
                "image": self.image,
                "command": self.command or None,
                "args": self.args or None,
                "env": self.env or None,
                "resources": self.resources.model_dump(),
                "pool": self.pool,
                "volumes": [v.model_dump() for v in self.volumes] or None,
                "priority": self.priority.value,
            },
        }
        return yaml.safe_dump(_drop_none(doc), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_form(cls, form_data: dict, kind: Kind) -> "WorkloadSpec":
        """Build a WorkloadSpec from a flat HTML form dict.

        Recognised flat keys (dot-notation for nested):
          ``name``, ``namespace``, ``image``, ``pool``, ``priority``,
          ``resources.cpu``, ``resources.memory``, ``resources.gpu``,
          ``resources.gpu_type``, ``command``, ``args``, ``env.<KEY>``.
        """
        nested: dict[str, dict] = {"resources": {}, "env": {}}
        flat: dict[str, str | int] = {}
        for k, v in form_data.items():
            if k.startswith("resources."):
                nested["resources"][k.split(".", 1)[1]] = v
            elif k.startswith("env."):
                nested["env"][k.split(".", 1)[1]] = v
            elif k in {"command", "args"}:
                flat[k] = [tok for tok in str(v).split() if tok]
            else:
                flat[k] = v
        # Coerce gpu to int if provided.
        if "gpu" in nested["resources"]:
            try:
                nested["resources"]["gpu"] = int(nested["resources"]["gpu"])
            except (TypeError, ValueError):
                pass
        return cls(kind=kind, **flat, env=nested["env"],
                   resources=ResourceRequest(**nested["resources"]))


def _drop_none(d):
    if isinstance(d, dict):
        return {k: _drop_none(v) for k, v in d.items() if v is not None}
    if isinstance(d, list):
        return [_drop_none(x) for x in d]
    return d
