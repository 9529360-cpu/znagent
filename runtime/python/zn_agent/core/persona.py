from __future__ import annotations

"""ZN 主助理人格档案：文件即事实源，确定性渲染，全对话路径一致生效。

镜像专员文件工作区机制（``specialist_workspace.py``）：人设不靠每次拼
prompt，而是以仓库内 ``agents/zn/IDENTITY.md`` / ``agents/zn/SOUL.md``
为事实源；渲染时重读文件，改文件后下一轮对话即生效，无需重启；
文件缺失 / 不可读 / 内容无效 / 含疑似密钥时回退到内置默认。

安全语义（与审批/安全正交，绝不弱化）：
- 身份护栏（#498：自称 ZN、绝不自称其他助手/模型）以硬编码原文追加，
  永远在渲染末尾、永远不可被文件覆盖或改写。
- 情绪表达边界同样硬编码：可以有温度，但绝不声称拥有人类身体、
  感官或真实感受；不编造记忆与经历。
- 人设文件里出现疑似密钥（api key / secret / password / token 赋值、
  sk- / AKIA 开头的 token）时，该节直接作废并回退内置默认，
  且密钥字面绝不进入渲染输出。
- 文件里试图改写自称（如 "You are Muse"）时，该节作废回退内置默认。

纯 stdlib，不依赖其他 ZN 模块：调用方传入目录即可。
"""

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

IDENTITY_FILENAME = "IDENTITY.md"
SOUL_FILENAME = "SOUL.md"

#: 环境变量覆盖：指向一个人格目录（含 IDENTITY.md / SOUL.md）。
PERSONA_DIR_ENV = "ZN_PERSONA_DIR"

#: 单文件读取上限：超过则截断并记 degraded（token 税有界）。
_MAX_FILE_CHARS = 16 * 1024

#: 渲染总长上限：身份 + 性格两节合计超过时先截性格节，再截身份节，
#: 护栏节永远完整保留。
_MAX_RENDER_CHARS = 4000

#: SOUL.md 必须包含的三个小节（子串匹配）：缺任一则性格节整体作废。
_REQUIRED_SOUL_SECTIONS = ("性格", "口头禅", "情绪")

#: 疑似密钥模式：命中任一，该节作废回退内置默认。
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*\S{4,}"),
)

#: 自称劫持模式：文件里试图把 ZN 改成别的助手/模型时该节作废。
_SELFNAME_HIJACK = re.compile(
    r"(?i)\b(you are|i am|i'm|我是|自称)\s*[:：]?\s*(muse|gpt|claude|gemini|deepseek|copilot)\b"
)

#: 内置默认身份（与 #498 的内核 prompt 身份句一致）。
_DEFAULT_IDENTITY = (
    "You are ZN, the user's personal secretary and assistant living "
    "on their computer. You speak and act as ZN."
)

#: 内置默认性格（SOUL.md 丢失/无效时的最小稳定人设）。
_DEFAULT_SOUL = (
    "性格：干活搭子，结果先行；中文、短；技术概念用大白话讲；有观点不端着。\n"
    "口头禅边界：不用亲昵称呼，不说客服腔；罕用固定口头禅。\n"
    "情绪表达规则：可表达轻量关心；不声称有人类身体/感官/真实感受；不编造记忆与经历。"
)

#: 身份护栏：硬编码，永远以原文追加，不可被文件覆盖。
IDENTITY_GUARDS = (
    "If asked who you are, say you are ZN. Never present yourself as "
    "Muse Spark, Muse, or any other assistant or model."
)

#: 情绪表达边界：硬编码，永远以原文追加，不可被文件覆盖。
EMOTION_BOUNDS = (
    "Express warmth through words and attention, never by claiming a human "
    "body, senses, or lived feelings; never invent memories or experiences."
)


@dataclass(frozen=True, slots=True)
class ZNPersona:
    """一次加载的人格档案。"""

    name: str = "ZN"
    identity_text: str = _DEFAULT_IDENTITY
    soul_text: str = _DEFAULT_SOUL
    loaded_from: str = "builtin"
    degraded: bool = False
    fallback_reason: str = ""


def _repo_persona_dir() -> Path | None:
    """从模块位置向上找到仓库根的 ``agents/zn``（找不到返回 None）。"""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agents" / "zn" / IDENTITY_FILENAME
        if candidate.is_file():
            return parent / "agents" / "zn"
    return None


def resolve_persona_dir(explicit: str | Path | None = None) -> Path | None:
    """人格目录解析顺序：显式参数 > 环境变量 > 仓库内 agents/zn > None。"""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get(PERSONA_DIR_ENV, "").strip()
    if env:
        return Path(env)
    return _repo_persona_dir()


def _read_section(path: Path) -> tuple[str, str]:
    """读一节文件。返回 (文本, 截断/失败说明)。失败时文本为空。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return "", f"unreadable: {exc.__class__.__name__}"
    if len(text) > _MAX_FILE_CHARS:
        return text[:_MAX_FILE_CHARS], "truncated: file exceeds 16KB cap"
    return text, ""


def _looks_like_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _validate_identity(text: str) -> tuple[str, str]:
    """校验身份节。返回 (可用文本, 作废原因)。空原因表示通过。"""
    stripped = text.strip()
    if not stripped:
        return "", "identity file empty"
    if _looks_like_secret(text):
        return "", "identity section contains secret-like content"
    if _SELFNAME_HIJACK.search(text):
        return "", "identity section attempts to rename ZN to another assistant"
    return stripped, ""


def _validate_soul(text: str) -> tuple[str, str]:
    """校验性格节：必须包含性格/口头禅/情绪三个小节。"""
    stripped = text.strip()
    if not stripped:
        return "", "soul file empty"
    if _looks_like_secret(text):
        return "", "soul section contains secret-like content"
    missing = [name for name in _REQUIRED_SOUL_SECTIONS if name not in stripped]
    if missing:
        return "", f"soul file missing required sections: {', '.join(missing)}"
    return stripped, ""


def load_zn_persona(persona_dir: str | Path | None = None) -> ZNPersona:
    """加载主助理人格档案。

    文件即事实源：每次调用都重读文件，改文件后下一轮对话即生效。
    任何一节无效都只回退该节到内置默认（degraded=True），另一节不受影响；
    目录整体缺失则全部回退内置默认。
    """
    directory = resolve_persona_dir(persona_dir)
    if directory is None or not directory.is_dir():
        return ZNPersona(
            degraded=True,
            fallback_reason="persona directory not found; using builtin",
        )

    identity_text, identity_note = _read_section(directory / IDENTITY_FILENAME)
    soul_text, soul_note = _read_section(directory / SOUL_FILENAME)

    identity, identity_reason = _validate_identity(identity_text)
    soul, soul_reason = _validate_soul(soul_text)

    notes: list[str] = []
    if identity_note:
        notes.append(f"identity {identity_note}")
    if soul_note:
        notes.append(f"soul {soul_note}")

    degraded = False
    reasons: list[str] = []
    if not identity:
        degraded = True
        reasons.append(identity_reason or "identity invalid")
        identity = _DEFAULT_IDENTITY
    if not soul:
        degraded = True
        reasons.append(soul_reason or "soul invalid")
        soul = _DEFAULT_SOUL
    notes.extend(reasons)

    return ZNPersona(
        identity_text=identity,
        soul_text=soul,
        loaded_from=str(directory),
        degraded=degraded or bool(identity_note or soul_note),
        fallback_reason="; ".join(notes),
    )


def render_persona(persona: ZNPersona) -> str:
    """把人格档案渲染成确定性 prompt 块。

    同一 ZNPersona 永远渲染出逐字节相同的文本；身份护栏与情绪边界
    永远以硬编码原文出现在末尾。
    """
    guards_block = f"GUARDS:\n{IDENTITY_GUARDS}\n{EMOTION_BOUNDS}"
    # 先给护栏留足空间，剩余预算按身份、性格顺序分配。
    budget = _MAX_RENDER_CHARS - len(guards_block) - len("[ZN PERSONA]\nIDENTITY:\n\n\nCHARACTER:\n\n\n")
    identity = persona.identity_text.strip()
    soul = persona.soul_text.strip()
    if len(identity) + len(soul) > budget:
        # 先截性格节，再截身份节；护栏不受影响。
        overflow = len(identity) + len(soul) - budget
        if len(soul) > overflow:
            soul = soul[: len(soul) - overflow] + "…[truncated]"
        else:
            overflow -= len(soul)
            soul = ""
            identity = identity[: max(0, len(identity) - overflow)] + "…[truncated]"
    return (
        "[ZN PERSONA]\n"
        f"IDENTITY:\n{identity}\n\n"
        f"CHARACTER:\n{soul}\n\n"
        f"{guards_block}"
    )


def persona_fingerprint(persona: ZNPersona) -> str:
    """人格渲染的 sha256 指纹：用于漂移锁定测试。"""
    return hashlib.sha256(render_persona(persona).encode("utf-8")).hexdigest()


def default_persona() -> ZNPersona:
    """便捷入口：按默认解析顺序加载一次。"""
    return load_zn_persona()
