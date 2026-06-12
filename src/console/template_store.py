"""任务模板存储 — 本地文件,零外部依赖。

设计取舍(评审记录见 docs/templates-design.md §10):**不用 ConfigMap/数据库**。
平台自身的应用数据不写进被管理的 K8s 集群;安装保持「一条 docker 命令」
(挂 `-v ./data:/app/data` 即持久化,不挂则自定义模板不跨容器重启)。

存储格式:`<data_dir>/templates/<name>.yaml`,元数据放在文件头的 `#@ ` 注释里,
因此**文件本体就是合法的 gpuctl YAML**,可直接 `gpuctl create -f` 使用:

    #@ display: 我的 SFT 微调
    #@ kind: training
    #@ description: 团队标准微调配置
    #@ tags: 需 GPU,LLM 微调
    kind: training
    job:
      name: __NAME__
      ...

内置模板(templates_builtin.TEMPLATES)随代码发布、只读;list/get 时合并。
保存时若 YAML 为具体值(无 __NAME__ 等令牌),自动令牌化,使启动页表单可覆盖。
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import replace
from pathlib import Path

from src.config import CONFIG
from src.console.templates_builtin import TEMPLATES as BUILTIN_TEMPLATES, Template


logger = logging.getLogger("src.console.template_store")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_NAME_RE = re.compile(r"^[a-z]([a-z0-9-]{0,38}[a-z0-9])?$")
_KINDS = {"notebook", "training", "inference", "compute"}
_TOKENS = ("__NAME__", "__NAMESPACE__", "__POOL__", "__GPU__", "__CPU__", "__MEMORY__", "__IMAGE__")

# 校验时的令牌占位值(纯解析用,不创建任何资源)
_PLACEHOLDERS = {
    "__NAME__": "tpl-check", "__NAMESPACE__": "default", "__POOL__": "default",
    "__GPU__": "0", "__CPU__": "1", "__MEMORY__": "1Gi", "__IMAGE__": "placeholder:latest",
}

_META_LINE = re.compile(r"^#@\s*([a-z]+)\s*:\s*(.*)$")


class TemplateError(ValueError):
    """校验/权限错误,message 直接面向用户。"""


def _substitute(yaml_text: str, **overrides: str) -> str:
    values = {**_PLACEHOLDERS, **{f"__{k.upper()}__": v for k, v in overrides.items()}}
    for token, val in values.items():
        yaml_text = yaml_text.replace(token, val)
    return yaml_text


def _parse_gpuctl(yaml_text: str):
    """gpuctl 纯解析(延迟导入,便于单测替换)。"""
    from gpuctl.parser.base_parser import BaseParser
    return BaseParser.parse_yaml(yaml_text)


def tokenize(yaml_text: str) -> tuple[str, dict]:
    """把具体值 YAML 令牌化(逐字段、行级、各替换一次),返回 (令牌化文本, 表单默认值)。

    需要 yaml_text 可被 gpuctl 解析(具体值);失败抛 TemplateError。
    """
    try:
        obj = _parse_gpuctl(yaml_text)
    except Exception as exc:
        raise TemplateError(f"YAML 解析失败:{exc}") from exc

    res = getattr(obj, "resources", None)
    env = getattr(obj, "environment", None)
    fields = [
        ("name", getattr(obj.job, "name", None), "__NAME__"),
        ("namespace", getattr(obj.job, "namespace", None), "__NAMESPACE__"),
        ("pool", getattr(res, "pool", None), "__POOL__"),
        ("gpu", getattr(res, "gpu", None), "__GPU__"),
        ("cpu", getattr(res, "cpu", None), "__CPU__"),
        ("memory", getattr(res, "memory", None), "__MEMORY__"),
        ("image", getattr(env, "image", None), "__IMAGE__"),
    ]
    defaults: dict = {}
    for key, val, token in fields:
        if val is None or val == "":
            continue
        defaults[key] = val
        pattern = re.compile(rf"(?m)^(\s*{key}:\s*)(['\"]?){re.escape(str(val))}\2\s*$")
        yaml_text, _n = pattern.subn(rf"\g<1>{token}", yaml_text, count=1)
    return yaml_text, defaults


def validate_template_yaml(yaml_text: str) -> str:
    """令牌替换占位值后纯解析;返回解析出的 kind。失败抛 TemplateError。"""
    if len(yaml_text.encode()) > CONFIG.yaml_max_bytes:
        raise TemplateError(f"YAML 超过大小上限({CONFIG.yaml_max_bytes} 字节)")
    try:
        obj = _parse_gpuctl(_substitute(yaml_text))
    except Exception as exc:
        raise TemplateError(f"YAML 校验失败:{exc}") from exc
    return obj.kind


def _serialize(t: Template) -> str:
    lines = [
        f"#@ display: {t.display}",
        f"#@ kind: {t.kind}",
        f"#@ description: {t.description}",
    ]
    if t.tags:
        lines.append(f"#@ tags: {','.join(t.tags)}")
    for key in ("gpu", "cpu", "memory", "image"):
        val = getattr(t, key)
        if val not in (None, ""):
            lines.append(f"#@ {key}: {val}")
    return "\n".join(lines) + "\n" + t.yaml.lstrip("\n")


def _deserialize(name: str, text: str) -> Template:
    meta: dict = {}
    body_lines: list[str] = []
    in_header = True
    for line in text.splitlines():
        m = _META_LINE.match(line) if in_header else None
        if m:
            meta[m.group(1)] = m.group(2).strip()
        else:
            if line.strip() or not in_header:
                in_header = False
                body_lines.append(line)
    tags = tuple(s.strip() for s in meta.get("tags", "").split(",") if s.strip())
    return Template(
        name=name,
        display=meta.get("display", name),
        description=meta.get("description", ""),
        kind=meta.get("kind", "compute"),
        tags=tags,
        builtin=False,
        gpu=int(meta.get("gpu", 0) or 0),
        cpu=int(meta.get("cpu", 1) or 1),
        memory=meta.get("memory", "1Gi"),
        image=meta.get("image", ""),
        yaml="\n".join(body_lines).strip("\n") + "\n",
    )


class TemplateStore:
    """内置(代码) + 自定义(本地文件)合并视图;自定义可 CRUD,内置只读。"""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        base = Path(data_dir) if data_dir else Path(CONFIG.data_dir)
        if not base.is_absolute():
            base = _PROJECT_ROOT / base
        self.dir = base / "templates"
        self._lock = threading.Lock()
        self._builtin = {t.name: t for t in BUILTIN_TEMPLATES}

    # ── 读 ────────────────────────────────────────────────────────────────────
    def _load_custom(self) -> dict[str, Template]:
        out: dict[str, Template] = {}
        if not self.dir.is_dir():
            return out
        for f in sorted(self.dir.glob("*.yaml")):
            name = f.stem
            if name in self._builtin:
                logger.warning("custom template %s shadows a builtin; skipped", name)
                continue
            try:
                out[name] = _deserialize(name, f.read_text(encoding="utf-8"))
            except Exception as exc:  # 单个坏文件不拖垮列表
                logger.warning("skip broken template file %s: %s", f, exc)
        return out

    def list_all(self, kind: str | None = None) -> list[Template]:
        items = list(BUILTIN_TEMPLATES) + list(self._load_custom().values())
        if kind:
            items = [t for t in items if t.kind == kind]
        return items

    def get(self, name: str) -> Template | None:
        if name in self._builtin:
            return self._builtin[name]
        f = self.dir / f"{name}.yaml"
        if f.is_file():
            try:
                return _deserialize(name, f.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("broken template file %s: %s", f, exc)
        return None

    # ── 写 ────────────────────────────────────────────────────────────────────
    def _prepare(self, name: str, display: str, description: str, kind: str,
                 tags: tuple, yaml_text: str) -> Template:
        if not _NAME_RE.match(name or ""):
            raise TemplateError("模板名需以小写字母开头,仅含小写字母/数字/中划线(≤40 字符)")
        if kind not in _KINDS:
            raise TemplateError(f"kind 必须是 {sorted(_KINDS)} 之一")
        defaults: dict = {}
        if "__NAME__" not in yaml_text:
            yaml_text, defaults = tokenize(yaml_text)  # 具体值 → 自动令牌化
        parsed_kind = validate_template_yaml(yaml_text)
        if parsed_kind != kind:
            raise TemplateError(f"YAML 的 kind={parsed_kind} 与所选类型 {kind} 不一致")
        return Template(
            name=name, display=display or name, description=description or "",
            kind=kind, tags=tuple(tags), builtin=False,
            gpu=int(defaults.get("gpu", 0) or 0),
            cpu=int(defaults.get("cpu", 1) or 1),
            memory=str(defaults.get("memory", "1Gi")),
            image=str(defaults.get("image", "")),
            yaml=yaml_text,
        )

    def create(self, *, name: str, display: str, description: str, kind: str,
               tags: tuple = (), yaml_text: str) -> Template:
        with self._lock:
            if name in self._builtin:
                raise TemplateError(f"{name} 是内置模板名,请换一个(或「复制为新模板」)")
            f = self.dir / f"{name}.yaml"
            if f.exists():
                raise TemplateError(f"模板 {name} 已存在")
            t = self._prepare(name, display, description, kind, tags, yaml_text)
            self.dir.mkdir(parents=True, exist_ok=True)
            f.write_text(_serialize(t), encoding="utf-8")
            return t

    def update(self, *, name: str, display: str, description: str, kind: str,
               tags: tuple = (), yaml_text: str) -> Template:
        with self._lock:
            if name in self._builtin:
                raise TemplateError("内置模板只读,请使用「复制为新模板」")
            f = self.dir / f"{name}.yaml"
            if not f.is_file():
                raise TemplateError(f"模板 {name} 不存在")
            t = self._prepare(name, display, description, kind, tags, yaml_text)
            f.write_text(_serialize(t), encoding="utf-8")
            return t

    def delete(self, name: str) -> None:
        with self._lock:
            if name in self._builtin:
                raise TemplateError("内置模板只读,不能删除")
            f = self.dir / f"{name}.yaml"
            if not f.is_file():
                raise TemplateError(f"模板 {name} 不存在")
            f.unlink()


STORE = TemplateStore()
