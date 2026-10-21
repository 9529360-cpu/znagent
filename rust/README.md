# ZN Rust 性能变体（PERF 系列）

`zn_perf/` 下的 crate 是 ZN 热点路径的 Rust 实现试点（首个：技能路由 cue 匹配器）。
设计原则（AGENTS.md 性能变体条）：

- **先测量再动手**：每个变体对应 `docs/ZN-PERF-AUDIT-*.md` 里的一处实测 CPU 热点；
  I/O 型路径不做 Rust 变体。
- **可选扩展 + 静默回退**：Python 侧永远 `try: import zn_perf_ext`，
  缺失时走纯 Python 实现（行为一致）。CI、干净安装、无 Rust 工具链的平台
  不需要构建它。
- **行为等价**：每个变体有 `tests/zn_agent/core/test_*_rust_equiv.py`
  钉住 Rust/纯 Python 一致（固定语料 + 种子 fuzz）；`cargo test` 先过。

## 构建

需要 Rust stable（`rustup`，2026-10-21 实测 1.99.1）：

```bash
bash rust/build_ext.sh
```

产物为 `runtime/python/zn_perf_ext.so`（Linux）/ `.pyd`（Windows），
已在 `.gitignore` 中忽略，不提交。`ZN_PERF_RUST=0` 可强制走纯 Python 路径。

## 基准

```bash
PYTHONPATH=runtime/python python3 rust/bench_cue_match.py --skills 200 --repeats 15
```

2026-10-21 同机数字（Linux x86_64）：纯 Python 中位 46.9ms →
Rust 中位 17.0ms，**2.8x**。详见 `docs/ZN-PERF-AUDIT-001.md`。

## 当前变体

| crate 函数 | 对应 Python | 说明 |
|---|---|---|
| `zn_perf_ext.best_cue_for_header` | `zn_agent.core.skill_routing._best_cue_for_header_py` | 技能路由逐 header 最长 cue 匹配 |

新增变体时：在此表登记 + 审计报告编号 + 等价测试文件名。
