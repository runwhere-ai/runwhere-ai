"""Internationalisation dictionary.

v1 ships zh-CN only. The interface is structured so a second locale can be
added later without touching call sites (FR-114).
"""
from __future__ import annotations

from typing import Final


# Flat dictionary keyed by dotted path. Keep keys short and stable; values
# are user-visible Chinese strings.
_ZH_CN: Final[dict[str, str]] = {
    # Global / nav
    "app.name":                    "runwhere-ai 一体化控制台",
    "nav.dashboard":               "控制面板",
    "nav.section.my_workspace":    "我的工作区",
    "nav.section.platform":        "平台管理",
    "nav.section.account":         "我的账号",
    "nav.notebooks":               "开发调试",
    "nav.notebooks.list":          "我的 Notebook",
    "nav.notebooks.new":           "新建 Notebook",
    "nav.trainings":               "训练任务",
    "nav.trainings.list":          "任务列表",
    "nav.trainings.new":           "新建训练",
    "nav.inferences":              "推理服务",
    "nav.inferences.list":         "服务列表",
    "nav.inferences.new":          "新建推理服务",
    "nav.computes":                "计算服务",
    "nav.computes.list":           "服务列表",
    "nav.computes.new":            "新建计算服务",
    "nav.pools":                   "资源管理",
    "nav.nodes":                   "节点",
    "nav.quotas":                  "配额",
    "nav.namespaces":              "命名空间",
    "nav.cluster_config":          "集群配置",
    "nav.account":                 "我的信息",
    "nav.logout":                  "退出登录",

    # Auth
    "auth.login.title":            "登录 runwhere-ai",
    "auth.login.token_label":      "Bearer Token",
    "auth.login.submit":           "登录",
    "auth.login.error.invalid":    "Token 无效或已过期",
    "auth.login.help":             "使用 kubectl create token <sa> 创建 Token",
    "auth.session.expired":        "会话已过期，请重新登录",

    # Conn status (FR-104)
    "conn.online":                 "实时同步",
    "conn.degraded":               "实时连接中断，已切换到刷新模式",
    "conn.reconnecting":           "正在重连…",

    # Generic page states (FR-110)
    "state.loading":               "加载中…",
    "state.empty.title":           "暂无数据",
    "state.error.title":           "出错了",
    "state.error.retry":           "重试",
    "state.forbidden":             "无权访问该资源",

    # Why? (FR-022)
    "why.recent_events":           "最近事件",

    # Confirmations (FR-026)
    "confirm.stop":                "确认停止？",
    "confirm.delete":              "确认删除？此操作不可恢复",

    # Conflicts (FR-102)
    "conflict.title":              "对象已被其他人修改",
    "conflict.merge":              "对比并合并",
    "conflict.discard":            "放弃我的修改",

    # Dev mode banner (RWAI_AUTH_PROVIDER=bypass)
    "dev.banner.title":            "DEV 模式",
    "dev.banner.detail":           "鉴权已绕过 · 任意请求都以虚拟 admin 身份处理 · 切勿用于生产",
}


def t(key: str, **kwargs: object) -> str:
    """Translate ``key`` into the current locale, with optional ``{var}`` interp.

    Unknown keys fall back to the key itself so missing translations are
    visible in development.
    """
    template = _ZH_CN.get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def has(key: str) -> bool:
    """Return True if the dictionary contains a value for ``key``."""
    return key in _ZH_CN


def keys() -> list[str]:
    """All registered keys (used by audit task T159)."""
    return sorted(_ZH_CN.keys())
