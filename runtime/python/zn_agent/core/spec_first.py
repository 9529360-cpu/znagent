from __future__ import annotations

"""W-3 Spec-first workflow: no approved spec, no implementation work.

Default flow, not an exception: every feature starts with a spec
directory (``PRODUCT.md`` + ``TECH.md``) under ``specs/<slug>/``. Two
label gates control the two kinds of "starting work":

1. ``ready-to-spec`` -- starting to *write* the spec. Checked by
   :func:`can_start_spec` against the labels on the feature request /
   assignment. The team loop never writes a spec itself: a missing spec
   is a gap, not an invitation to invent scope.
2. ``ready-to-implement`` -- starting *implementation*. Checked by
   :func:`check_implementation_gate` against the spec files on disk:
   both files present, every required section filled (no placeholder
   bodies), and the ``ready-to-implement`` label in TECH.md's
   ``<!-- SPEC LABELS: ... -->`` marker. The label lives in the spec
   file itself (single source of truth, editable like the rest of the
   spec), so fixing the spec unblocks the team on the next pulse with
   no resume ceremony.

Wiring (built on existing interfaces, no parallel flow):

* P2b ``gap_report``: a blocked gate produces a gap-shaped dict
  (``missing`` / ``needed`` / ``impact``) via :func:`spec_gate_gap`,
  stored in the working-state mirror under
  ``SPEC_GATE_STATE_KEY`` and surfaced in the blocked ``next_action``.
  It is deliberately NOT recorded as an LG-2 interrupt: an interrupt
  needs an explicit resume value to clear, but a spec gate must
  self-heal the moment the spec files on disk are fixed.
* CUR-2 Plan Mode: the resident checks the spec gate *before*
  ``owner.advance`` (and therefore before any plan proposal can be
  made) -- a spec precedes even the plan. When the gate passes, the
  spec summary rides into the specialist's question next to Plan
  Mode's ``plan_text``.

The natural-language "assemble a team" path never invents a
``spec_slug``: the assigner binds the work to a spec via
``team_request["spec_slug"]``. No slug means the gate is not
consulted (legacy flows unchanged).
"""

import re
from pathlib import Path

#: Workspace-relative directory holding one spec directory per feature.
SPEC_DIR = "specs"
#: The two spec files every spec directory must contain.
SPEC_PRODUCT_FILE = "PRODUCT.md"
SPEC_TECH_FILE = "TECH.md"
#: Working-state mirror key for a blocked spec gate (not an interrupt).
SPEC_GATE_STATE_KEY = "team_spec_gate"
#: Gate 1 label: starting to write the spec is allowed.
LABEL_READY_TO_SPEC = "ready-to-spec"
#: Gate 2 label: starting implementation is allowed.
LABEL_READY_TO_IMPLEMENT = "ready-to-implement"
#: Placeholder token marking an unfilled template section. A section
#: whose body is only this token (or shorter than the minimum) is
#: incomplete -- the gate fails closed instead of accepting a template.
SPEC_PLACEHOLDER = "【待填写】"
#: Minimum non-placeholder body length (chars) for a section to count.
_MIN_SECTION_BODY = 20
#: Cap for the spec excerpt injected into a specialist question.
_MAX_EXCERPT = 800

#: Required PRODUCT.md sections, in template order.
PRODUCT_REQUIRED_SECTIONS = ("背景", "目标", "范围", "非目标", "验收")
#: Required TECH.md sections, in template order.
TECH_REQUIRED_SECTIONS = ("方案", "改动点", "验收", "风险")

_LABEL_MARKER_RE = re.compile(
    r"<!--\s*SPEC\s+LABELS\s*:\s*(.*?)\s*-->", re.IGNORECASE | re.DOTALL
)
_SECTION_HEADER_RE = re.compile(r"^##\s+(.+?)\s*$")


def spec_slug(value: object) -> str:
    """Sanitize a spec slug (same shape as ``plan_file_rel_path``)."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip())
    return safe.strip("-")[:64]


def spec_dir_rel_path(slug: str) -> str:
    """Workspace-relative path of one spec directory."""
    return f"{SPEC_DIR}/{spec_slug(slug) or 'spec'}"


def spec_file_rel_path(slug: str, filename: str) -> str:
    """Workspace-relative path of one file inside a spec directory."""
    return f"{spec_dir_rel_path(slug)}/{filename}"


def spec_slug_from_event(event: object) -> str:
    """The bound spec slug from ``team_request["spec_slug"]``, or ""."""
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return ""
    request = payload.get("team_request")
    if not isinstance(request, dict):
        return ""
    return spec_slug(request.get("spec_slug"))


def normalize_labels(labels: object) -> tuple[str, ...]:
    """Normalize a labels value to deduped, lowercased label strings."""
    if isinstance(labels, str):
        raw = re.split(r"[,，\s]+", labels)
    elif isinstance(labels, (list, tuple, set)):
        raw = [str(item) for item in labels]
    else:
        return ()
    out: list[str] = []
    for item in raw:
        cleaned = str(item).strip().lower()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return tuple(out)


def parse_spec_labels(markdown: object) -> tuple[str, ...]:
    """Labels from ``<!-- SPEC LABELS: a, b -->`` markers in spec text."""
    if not isinstance(markdown, str):
        return ()
    found: list[str] = []
    for match in _LABEL_MARKER_RE.finditer(markdown):
        for label in normalize_labels(match.group(1)):
            if label not in found:
                found.append(label)
    return tuple(found)


def can_start_spec(labels: object) -> tuple[bool, str]:
    """Gate 1: may spec-writing start for these assignment labels?

    Only ``ready-to-spec`` opens the gate. A ``ready-to-implement``
    label alone does not authorize writing a spec -- the two gates
    are separate, and skipping the spec-writing gate is exactly how
    an unreviewed spec gets invented under schedule pressure.
    """
    normalized = normalize_labels(labels)
    if LABEL_READY_TO_SPEC in normalized:
        return True, ""
    if LABEL_READY_TO_IMPLEMENT in normalized:
        return (
            False,
            "不能开始写 spec：只有 ready-to-implement 标签，缺少 "
            "ready-to-spec 标签（实现标签不能替代写 spec 的门控）",
        )
    return False, "不能开始写 spec：缺少 ready-to-spec 标签"


def _section_bodies(markdown: str) -> dict[str, str]:
    """Map ``## <name>`` section names to their raw bodies."""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current is not None:
            sections[current] = "\n".join(buf)

    for line in markdown.splitlines():
        header = _SECTION_HEADER_RE.match(line)
        if header:
            _flush()
            current = header.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    _flush()
    return sections


def _section_complete(markdown: str, name: str) -> bool:
    """True when a section exists with a real (non-placeholder) body."""
    body = _section_bodies(markdown).get(name, "")
    cleaned = body.replace(SPEC_PLACEHOLDER, "").strip()
    return len(cleaned) >= _MIN_SECTION_BODY


def _first_incomplete(markdown: str, required: tuple[str, ...]) -> str:
    for name in required:
        if not _section_complete(markdown, name):
            return name
    return ""


def check_implementation_gate(
    *, slug: str, spec_files: dict[str, str | None]
) -> tuple[bool, str]:
    """Gate 2: may implementation start for this spec?

    ``spec_files`` maps ``PRODUCT.md`` / ``TECH.md`` to file text
    (missing file -> absent key or None). Fail closed: any missing
    file, any incomplete section, or a missing
    ``ready-to-implement`` label blocks with a specific reason.
    Returns (allowed, "") on success, (False, reason) when blocked.
    """
    slug = spec_slug(slug)
    if not slug:
        return False, "未绑定 spec：team_request 缺少 spec_slug，先绑定 spec 再开工"
    rel_dir = spec_dir_rel_path(slug)
    product = spec_files.get(SPEC_PRODUCT_FILE)
    if not isinstance(product, str) or not product.strip():
        return (
            False,
            f"缺少 spec：{rel_dir}/{SPEC_PRODUCT_FILE} 不存在，先写 spec",
        )
    tech = spec_files.get(SPEC_TECH_FILE)
    if not isinstance(tech, str) or not tech.strip():
        return (
            False,
            f"缺少 spec：{rel_dir}/{SPEC_TECH_FILE} 不存在，先写 spec",
        )
    incomplete = _first_incomplete(product, PRODUCT_REQUIRED_SECTIONS)
    if incomplete:
        return (
            False,
            f"spec 不完整：{SPEC_PRODUCT_FILE} 的“{incomplete}”章节"
            "为空或仍是占位，先补齐 spec",
        )
    incomplete = _first_incomplete(tech, TECH_REQUIRED_SECTIONS)
    if incomplete:
        return (
            False,
            f"spec 不完整：{SPEC_TECH_FILE} 的“{incomplete}”章节"
            "为空或仍是占位，先补齐 spec",
        )
    if LABEL_READY_TO_IMPLEMENT not in parse_spec_labels(tech):
        return (
            False,
            "spec 已齐全但未贴 ready-to-implement 标签：请评审后在 "
            f"{SPEC_TECH_FILE} 的 SPEC LABELS 标记里加上 "
            "ready-to-implement",
        )
    return True, ""


def spec_gate_gap(*, slug: str, reason: str) -> dict[str, str]:
    """A blocked spec gate as a gap_report-shaped dict.

    Same three fields (``missing`` / ``needed`` / ``impact``) the
    P2b gap channel uses, so the blocked reason travels in the shape
    the team flow already understands.
    """
    slug = spec_slug(slug) or "spec"
    rel_dir = spec_dir_rel_path(slug)
    return {
        "missing": f"approved spec：{rel_dir}/ 未就绪——{reason}",
        "needed": (
            f"补齐 {rel_dir}/ 的 PRODUCT.md + TECH.md，评审后在 "
            "TECH.md 的 SPEC LABELS 标记里加上 ready-to-implement"
        ),
        "impact": "无 approved spec 时团队不开工，避免按发明的范围动手",
    }


def load_spec_files(workspace_path: object, slug: str) -> dict[str, str]:
    """Load a spec directory's two files from a workspace.

    Missing/unreadable files are absent keys (the gate treats them as
    missing). The slug is sanitized and the resolved directory must
    stay inside the workspace -- a hostile slug never escapes it.
    """
    slug = spec_slug(slug)
    if not slug or not isinstance(workspace_path, str):
        return {}
    root = Path(workspace_path)
    try:
        base = (root / SPEC_DIR / slug).resolve()
        resolved_root = root.resolve()
        if base != resolved_root and resolved_root not in base.parents:
            return {}
        out: dict[str, str] = {}
        for filename in (SPEC_PRODUCT_FILE, SPEC_TECH_FILE):
            try:
                out[filename] = (base / filename).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        return out
    except (OSError, RuntimeError, ValueError):
        return {}


def spec_prompt_excerpt(*, slug: str, spec_files: dict[str, str | None]) -> str:
    """Compact spec summary for a specialist question (capped)."""
    product = spec_files.get(SPEC_PRODUCT_FILE)
    tech = spec_files.get(SPEC_TECH_FILE)
    parts: list[str] = []
    if isinstance(product, str):
        goal = _section_bodies(product).get("目标", "").strip()
        if goal:
            parts.append(f"spec 目标：{goal[:_MAX_EXCERPT]}")
    if isinstance(tech, str):
        approach = _section_bodies(tech).get("方案", "").strip()
        if approach:
            parts.append(f"spec 方案：{approach[:_MAX_EXCERPT]}")
    if not parts:
        return ""
    return " ".join(parts)


def render_spec_templates(
    *, slug: str, title: str, goal: str = ""
) -> dict[str, str]:
    """Render the two spec files for a new spec directory.

    Every required section starts with the placeholder token, so a
    fresh template always fails the gate -- a template is not a spec.
    The caller fills each section, then flips the TECH.md label marker
    to ``ready-to-implement`` after review.
    """
    slug = spec_slug(slug) or "spec"
    heading = (title or slug).strip()
    goal_body = goal.strip() or (
        f"{SPEC_PLACEHOLDER}一句话：这个功能为谁解决什么问题，成功是什么样。"
    )
    placeholder_line = f"{SPEC_PLACEHOLDER}写满本节后再删掉本行。"
    product_lines = [
        f"# Spec：{heading}",
        "",
        f"> spec 目录：{spec_dir_rel_path(slug)}/ · 先有 spec 再动手是默认流程。",
        "> 实现开工需 TECH.md 贴 ready-to-implement 标签；无 approved spec 时团队不开工。",
        "",
        "## 背景",
        "",
        placeholder_line,
        "",
        "## 目标",
        "",
        goal_body,
        "",
        "## 范围",
        "",
        placeholder_line,
        "",
        "## 非目标",
        "",
        placeholder_line,
        "",
        "## 验收",
        "",
        placeholder_line,
        "",
    ]
    tech_lines = [
        f"# Spec（技术）：{heading}",
        "",
        f"> 对应产品 spec：{spec_dir_rel_path(slug)}/{SPEC_PRODUCT_FILE}。",
        "> 评审通过后，把下面标记改为 <!-- SPEC LABELS: ready-to-implement -->，团队才开工。",
        "",
        "<!-- SPEC LABELS: draft -->",
        "",
        "## 方案",
        "",
        placeholder_line,
        "",
        "## 改动点",
        "",
        placeholder_line,
        "",
        "## 验收",
        "",
        placeholder_line,
        "",
        "## 风险",
        "",
        placeholder_line,
        "",
    ]
    return {
        SPEC_PRODUCT_FILE: "\n".join(product_lines),
        SPEC_TECH_FILE: "\n".join(tech_lines),
    }


__all__ = [
    "LABEL_READY_TO_IMPLEMENT",
    "LABEL_READY_TO_SPEC",
    "PRODUCT_REQUIRED_SECTIONS",
    "SPEC_DIR",
    "SPEC_GATE_STATE_KEY",
    "SPEC_PLACEHOLDER",
    "SPEC_PRODUCT_FILE",
    "SPEC_TECH_FILE",
    "TECH_REQUIRED_SECTIONS",
    "can_start_spec",
    "check_implementation_gate",
    "load_spec_files",
    "parse_spec_labels",
    "normalize_labels",
    "render_spec_templates",
    "spec_dir_rel_path",
    "spec_file_rel_path",
    "spec_gate_gap",
    "spec_prompt_excerpt",
    "spec_slug",
    "spec_slug_from_event",
]
