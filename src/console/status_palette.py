"""K8s status → color + explanation mapping.

This is the **single source of truth** for the status palette (PRD §5.3,
spec FR-022 + FR-112). UI templates MUST consume this; no template should
hard-code its own colors.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal


class Color(str, Enum):
    GREEN = "running"     # maps to CSS class .badge-running
    BLUE = "succeeded"
    YELLOW = "pending"
    ORANGE = "warning"
    RED = "danger"
    GRAY = "neutral"


# Map K8s state strings → palette color. Includes:
#   - Pod phases (Running, Pending, Succeeded, Failed)
#   - Container waiting reasons (ImagePullBackOff, CrashLoopBackOff, ...)
#   - Container terminated reasons (OOMKilled, Error, ...)
#   - Custom states used by gpuctl (e.g. ContainerCreating)
_PALETTE: dict[str, Color] = {
    # Healthy / terminal-success
    "Running":            Color.GREEN,
    "Ready":              Color.GREEN,
    "Succeeded":          Color.BLUE,
    "Completed":          Color.BLUE,
    # Transient / scheduling
    "Pending":            Color.YELLOW,
    "ContainerCreating":  Color.YELLOW,
    "PodInitializing":    Color.YELLOW,
    # User-actionable warnings (need attention but recoverable)
    "ImagePullBackOff":   Color.ORANGE,
    "ErrImagePull":       Color.ORANGE,
    "InsufficientGPU":    Color.ORANGE,
    "Unschedulable":      Color.ORANGE,
    "NodeAffinity":       Color.ORANGE,
    "QuotaExceeded":      Color.ORANGE,
    # Hard failures
    "CrashLoopBackOff":   Color.RED,
    "OOMKilled":          Color.RED,
    "Error":              Color.RED,
    "Failed":             Color.RED,
    "DeadlineExceeded":   Color.RED,
    "Evicted":            Color.RED,
    # Stopped / terminal-neutral
    "Stopped":            Color.GRAY,
    "Deleted":            Color.GRAY,
    "Unknown":            Color.GRAY,
}

# Plain-language Chinese explanations for tooltips & error banners (FR-022).
# Keep short — the event list is the place for full reason+message.
_EXPLAIN_ZH: dict[str, str] = {
    "Running":            "运行中",
    "Ready":              "就绪",
    "Succeeded":          "已成功",
    "Completed":          "已完成",
    "Pending":            "调度中",
    "ContainerCreating":  "拉取镜像中",
    "PodInitializing":    "容器初始化中",
    "ImagePullBackOff":   "镜像拉取失败（检查镜像名或拉取凭据）",
    "ErrImagePull":       "镜像拉取失败",
    "InsufficientGPU":    "GPU 资源不足",
    "Unschedulable":      "暂时无可用节点",
    "NodeAffinity":       "无符合亲和性的节点",
    "QuotaExceeded":      "已超出 namespace 配额",
    "CrashLoopBackOff":   "容器反复崩溃",
    "OOMKilled":          "内存超限被杀",
    "Error":              "执行错误",
    "Failed":             "失败",
    "DeadlineExceeded":   "执行超时",
    "Evicted":            "已被驱逐",
    "Stopped":            "已停止",
    "Deleted":            "已删除",
    "Unknown":            "未知状态",
}


TerminalKind = Literal["success", "failure", "stopped", "active"]


class StatusPalette:
    """All status-related lookups go through this small static API.

    Used by:
      - Jinja `status_badge` macro (template uses `color()` to pick CSS class)
      - ViewModels (to decorate WorkloadListItemVM rows)
      - Idle Watcher / failure aggregator
    """

    @staticmethod
    def color(status: str) -> str:
        """Return the palette color name (matches CSS class suffix and design token)."""
        return _PALETTE.get(status, Color.GRAY).value

    @staticmethod
    def explain(status: str) -> str:
        """Return a short Chinese explanation suitable for tooltips."""
        return _EXPLAIN_ZH.get(status, status)

    @staticmethod
    def is_terminal(status: str) -> bool:
        """Has the workload reached a final state (cannot transition further)?"""
        return status in {"Succeeded", "Completed", "Failed", "Error", "Stopped", "Deleted"}

    @staticmethod
    def is_failure(status: str) -> bool:
        """Should this state be treated as a failure for "Why?" surfacing (FR-022)?"""
        return _PALETTE.get(status, Color.GRAY) in {Color.ORANGE, Color.RED}

    @staticmethod
    def is_recoverable(status: str) -> bool:
        """Orange-tier states: user can intervene (different from red-tier)."""
        return _PALETTE.get(status, Color.GRAY) == Color.ORANGE
