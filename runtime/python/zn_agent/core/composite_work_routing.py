from __future__ import annotations

"""Route durable cross-surface Work before narrow single-surface understanding.

This module is descriptive only. It never creates action authority, chooses a
browser target, mutates a workspace, or claims completion. Its only job is to
keep a narrow browser-language proposal from consuming a Work request that
clearly spans both the current browser reference and an attached workspace.

The rule follows ordinary router specificity: a structurally bound composite
Work route wins before a generic browser catch-all; ambiguous requests keep the
existing narrow route.
"""

from dataclasses import dataclass


_BROWSER_REFERENCE_MARKERS = (
    "this website",
    "current website",
    "this site",
    "current site",
    "this page",
    "current page",
    "browser",
    "api docs",
    "api documentation",
    "documentation",
    "这个网站",
    "当前网站",
    "这个页面",
    "当前页面",
    "浏览器",
    "api 文档",
    "api文档",
)

_WORKSPACE_OBJECT_MARKERS = (
    "project",
    "repo",
    "repository",
    "workspace",
    "codebase",
    "source code",
    "project files",
    "sdk project",
    "项目",
    "仓库",
    "工作区",
    "代码库",
    "源码",
    "项目文件",
)

_WORKSPACE_MUTATION_MARKERS = (
    "adapt",
    "upgrade",
    "update",
    "modify",
    "change",
    "implement",
    "develop",
    "fix",
    "refactor",
    "build",
    "适配",
    "升级",
    "更新",
    "修改",
    "改造",
    "实现",
    "开发",
    "修复",
    "重构",
    "构建",
)

_LOCAL_VERIFICATION_MARKERS = (
    "run it",
    "run the project",
    "run tests",
    "test it",
    "verify",
    "confirm",
    "跑起来",
    "运行",
    "测试",
    "验证",
    "确认能用",
    "确认",
)


@dataclass(frozen=True, slots=True)
class CompositeWorkRouteDecision:
    preempt_narrow_browser: bool
    surfaces: tuple[str, ...]
    reason: str


def classify_composite_work_route(event) -> CompositeWorkRouteDecision:
    """Classify only a durable Work-bound browser + workspace request."""

    kind = str(getattr(event, "kind", "") or "").strip().lower()
    payload = getattr(event, "payload", {}) or {}
    if kind != "desktop_user_event":
        return _deny("event is not a desktop user Work request")
    if payload.get("body_action") or payload.get("native_action"):
        return _deny("action execution events stay on their admitted action path")

    required_bindings = (
        str(payload.get("work_thread_id") or "").strip(),
        str(payload.get("work_item_id") or "").strip(),
        str(payload.get("workspace_path") or "").strip(),
    )
    if not all(required_bindings):
        return _deny("request is not bound to durable Work plus an attached workspace")

    task = " ".join(str(getattr(event, "task", "") or "").casefold().split())
    if not task:
        return _deny("task text is empty")

    browser_reference = any(marker in task for marker in _BROWSER_REFERENCE_MARKERS)
    workspace_object = any(marker in task for marker in _WORKSPACE_OBJECT_MARKERS)
    workspace_mutation = any(marker in task for marker in _WORKSPACE_MUTATION_MARKERS)
    local_verification = any(marker in task for marker in _LOCAL_VERIFICATION_MARKERS)

    surfaces: list[str] = []
    if browser_reference:
        surfaces.append("browser_reference")
    if workspace_object and workspace_mutation:
        surfaces.append("workspace_mutation")
    if local_verification:
        surfaces.append("local_verification")

    if "browser_reference" not in surfaces or "workspace_mutation" not in surfaces:
        return CompositeWorkRouteDecision(
            preempt_narrow_browser=False,
            surfaces=tuple(surfaces),
            reason="request does not prove both browser-reference and workspace-mutation intent",
        )

    return CompositeWorkRouteDecision(
        preempt_narrow_browser=True,
        surfaces=tuple(surfaces),
        reason=(
            "durable Work spans a browser reference and an attached workspace mutation; "
            "the composite Work owner is more specific than generic browser understanding"
        ),
    )


def composite_work_preempts_browser_understanding(event) -> bool:
    return classify_composite_work_route(event).preempt_narrow_browser


def _deny(reason: str) -> CompositeWorkRouteDecision:
    return CompositeWorkRouteDecision(
        preempt_narrow_browser=False,
        surfaces=(),
        reason=reason,
    )
