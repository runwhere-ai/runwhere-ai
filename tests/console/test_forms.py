"""Contract tests for src.console.forms."""
from __future__ import annotations

import pytest
import yaml

from src.console.forms import (
    Priority,
    ResourceRequest,
    VolumeRef,
    WorkloadSpec,
)
from src.console.models import Kind


class TestResourceRequest:
    def test_defaults(self):
        r = ResourceRequest()
        assert r.cpu == "1"
        assert r.memory == "2Gi"
        assert r.gpu == 0

    def test_invalid_memory(self):
        with pytest.raises(ValueError):
            ResourceRequest(memory="weird")

    def test_negative_gpu(self):
        with pytest.raises(ValueError):
            ResourceRequest(gpu=-1)


class TestVolumeRef:
    def test_relative_path_rejected(self):
        with pytest.raises(ValueError):
            VolumeRef(type="pvc", name="data", mount_path="relative")

    def test_absolute_ok(self):
        v = VolumeRef(type="pvc", name="data", mount_path="/data")
        assert v.mount_path == "/data"


class TestWorkloadSpec:
    def test_valid_name(self):
        s = WorkloadSpec(kind=Kind.NOTEBOOK, name="bert-tune", image="img:v1")
        assert s.name == "bert-tune"

    @pytest.mark.parametrize("bad", ["Foo", "1abc", "abc!", "-abc", "abc_def"])
    def test_invalid_name_rejected(self, bad):
        with pytest.raises(ValueError):
            WorkloadSpec(kind=Kind.NOTEBOOK, name=bad, image="img")

    def test_default_priority_medium(self):
        s = WorkloadSpec(kind=Kind.NOTEBOOK, name="a", image="img")
        assert s.priority == Priority.MEDIUM

    def test_to_gpuctl_yaml_roundtrips(self):
        s = WorkloadSpec(
            kind=Kind.TRAINING,
            name="bert",
            namespace="ml",
            image="repo/bert:1",
            command=["python", "train.py"],
            env={"BATCH": "32"},
            resources=ResourceRequest(cpu="2", memory="8Gi", gpu=1, gpu_type="A100"),
            volumes=[VolumeRef(type="pvc", name="data", mount_path="/data")],
        )
        doc = yaml.safe_load(s.to_gpuctl_yaml())
        assert doc["kind"] == "training"
        assert doc["metadata"]["name"] == "bert"
        assert doc["spec"]["resources"]["gpu"] == 1
        assert doc["spec"]["volumes"][0]["mount_path"] == "/data"
        assert doc["spec"]["env"]["BATCH"] == "32"

    def test_to_gpuctl_yaml_drops_none(self):
        s = WorkloadSpec(kind=Kind.NOTEBOOK, name="n", image="img")
        doc = yaml.safe_load(s.to_gpuctl_yaml())
        # command / env / volumes were empty → must not appear in YAML output
        assert "command" not in doc["spec"]
        assert "env" not in doc["spec"]
        assert "volumes" not in doc["spec"]

    def test_from_form_flat(self):
        form = {
            "name": "abc",
            "namespace": "ml",
            "image": "img:v1",
            "pool": "a100-pool",
            "priority": "high",
            "resources.cpu": "4",
            "resources.memory": "16Gi",
            "resources.gpu": "2",
            "resources.gpu_type": "A100",
            "command": "python -u train.py --epochs 10",
            "env.BATCH_SIZE": "32",
            "env.LR": "1e-4",
        }
        s = WorkloadSpec.from_form(form, kind=Kind.TRAINING)
        assert s.image == "img:v1"
        assert s.resources.gpu == 2
        assert s.resources.gpu_type == "A100"
        assert s.priority == Priority.HIGH
        assert s.command == ["python", "-u", "train.py", "--epochs", "10"]
        assert s.env == {"BATCH_SIZE": "32", "LR": "1e-4"}
