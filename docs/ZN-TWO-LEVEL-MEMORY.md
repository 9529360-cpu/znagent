# ZN 两级记忆（KWP-2，一次落地）

热缓存 ~100 条 + 深存解码表 + 晋升/降级规则 + 昵称/代号捕获。

来源：机制借鉴 anthropics/knowledge-work-plugins（Apache 2.0），实现为 ZN 自有代码，
贴合现有 `StructuredMemory` API。

## 定位：只管生命周期，不改架构

与已落地的 CM-1（结构化观察记录格式）、GR-1/GR-2（时间有效期窗口/失效不删除）、
M0-1（ADD + linked_memory_ids）互补不重复。KWP-2 只管记忆的生命周期：

- 热/深两级是**分级标签**，不是两个存储。facts 表仍是唯一事实 owner；降级永不删除事实。
- 不碰存储格式：facts 表 schema 与行格式不变；分级元数据存在新增侧边表 `memory_tiers`。
- 不碰检索算法：`StructuredMemory.recall / relevant_context / bind_cognition_context` 行为不变。

## 规则（可执行，`runtime/python/zn_agent/core/two_level_memory.py` 为权威）

| 规则 | 内容 |
|---|---|
| 新事实 | 进热缓存（HOT）。 |
| 热容量 | ~100 条（`HOT_CAPACITY = 100`）。`remember` 时立即强制执行。 |
| 降级（HOT → DEEP） | 热缓存超容时，降最冷的：命中数最少 → 上次命中最早 → key 顺序。触发：`remember` 自动，或显式 `demote()` / `rebalance()`。 |
| 晋升（DEEP → HOT） | 深存事实累计被召回 `promote_after_hits` 次（默认 3 次）即晋升。触发：经适配器召回（`recall` / `recall_deep` / `relevant_context`），或显式 `promote()`。晋升时若热缓存已满，挤掉最冷的其他事实，绝不挤掉刚晋升的。 |
| 降级后召回 | 降级事实仍在 facts 表中，普通精确召回照常工作；`decode_table()` 是深存的解码表（key + aliases + ~200 字摘要 + 更新/降级时间戳），`recall_deep(key)` 是显式深存召回路径，计命中、可触发晋升。 |
| KWP-2 之前的事实 | 无分级行，计为热、0 命中（未知 = 冷，先降级），被触碰后建行。 |

## 昵称/代号捕获

- `capture_nickname(memory, 昵称, 标准名, source=...)`：存为普通事实 `nickname:<昵称>` →
  `{"canonical": 标准名, "source": ...}`，走 facts 表的召回/合并/解散清理路径。
- 写入绕过 supersession 是有意的：昵称是身份键，supersession 会把 `阿豪` 与 `阿豪哥`
  合并成一条而丢映射；也不存 alias，避免 consolidation 合并昵称行。
- `resolve_nickname()` 查标准名；`resolve_reference(text)` 把文本中已知昵称改写为标准名
  （最长昵称优先），供后续指代消解；`list_nicknames()` / `forget_nickname()` 列出/删除。
- 昵称是全局的（非按专员），操作对象是底层 `StructuredMemory`。

## 使用

```python
from zn_agent.core.two_level_memory import (
    TwoLevelMemory, capture_nickname, resolve_reference,
)

two = TwoLevelMemory(memory)          # 包一层 StructuredMemory
two.remember("喜好", "茶")
two.recall("喜好")                    # 计命中，深存事实达 3 次自动晋升
two.decode_table()                    # 深存索引/摘要
two.stats()                           # {"hot": …, "deep": …, "hot_capacity": 100}

capture_nickname(memory, "阿豪", "用户")
resolve_reference(memory, "阿豪说明天开会")  # "用户说明天开会"
```

## 证据

- `tests/zn_agent/core/test_two_level_memory.py`：22 个测试，覆盖容量降级不丢事实、
  解码表、显式晋升/降级、晋升边界（低于阈值不升、达到阈值升）、最冷优先、
  晋升挤掉最冷而非自身、深存召回、`relevant_context` 计命中、昵称捕获/改写/最长优先/
  忘记、以及 KWP-2 之前事实计为热。
- 现有记忆相关套件全绿（见 PR 正文）。
