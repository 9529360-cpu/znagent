# ZN 热点路径性能审计 001（PERF-1）

- 日期：2026-10-21
- 基线：`origin/main` @ `006e106e`（PR #616 S1(b) 已合入后）
- 方法：cProfile + wall-clock 基准，同机（Linux x86_64，Python 3.12），合成数据按常驻规模构造
- 结论先行：最热的是记忆召回 `recall_hybrid`（334ms @ 2000 facts，线性增长），但该文件面（store.py / facts / 召回）与 S1(c) 日记工人在途互斥，本轮试点按任务约束换次热点；**试点选择技能路由 `match_skill_headers`（47ms @ 200 skills，纯 CPU），Rust 变体 2.8x，中位 47ms → 17ms**。

## 1. 审计范围与数据量假设

backlog PERF-1 点名的四个方向逐一实测：

| 热点 | 代表函数 | 数据量假设 | 实测耗时 | 性质 |
|---|---|---|---|---|
| 记忆召回 | `StructuredMemory.recall_hybrid`（memory.py） | 2000 facts（常驻数月量级；6000 facts 见下） | **334ms**（min 334 / mean 358） | CPU + SQLite N+1 |
| 证据账本核查 | 召回内账本走查（`_hybrid_candidates` + ledger 窗口） | 同上 | 含在召回内，约 250ms（75%） | SQLite 为主 |
| 技能路由 | `match_skill_headers`（skill_routing.py） | 200 skills（registry 增长后量级；另测 50/500） | **47ms**（@200；118ms @500） | 纯 CPU |
| Daemon 并发 | `resident.pulse()`（无模型） | 空载常驻 | 25–65ms | SQLite I/O 为主 |
| 完成摘要 | `completion_summary._topical_score` | 200 summaries（生产 limit=50） | 2.2ms | 可忽略 |
| 浏览器场景解析 | `browser_scene.py` 系列 | — | 未单列 | I/O 主导（Playwright），按纪律不碰 |

## 2. 真瓶颈定位（数据）

### 2.1 `recall_hybrid` @ 2000 facts：334ms（最热，但本轮禁碰）

cProfile 分解（单次调用 647ms 含 profiler 开销，wall 334ms）：

- `_hybrid_candidates`：250ms（39%）——其中 `_open_window_row` 被调 1983 次，
  每次一次 SQLite 查询（`sqlite3 execute` 累计 152ms，N+1 查询问题）；
  `_ensure_history_schema` 被调 **1984 次**（每候选一次 DDL 确认，纯浪费）；
  `json.loads` 5949 次（value_json/aliases_json 逐行解析，31ms）。
- `_hybrid_tokens`：171ms（26%）——6118 次调用（每候选文档分词 + 实体打分重复分词），纯 CPU。
- `_hybrid_entity_score`：145ms（22%）——每候选重复 `_hybrid_normalize`（8000 次）+ 正则。
- `_hybrid_bm25`：52ms（8%）——真正的 BM25 数学部分反而最便宜。

@ 6000 facts：≈ 1.0s（O(候选数) 线性外推；§2.1 的 cProfile 显示全部大头
  都是逐候选工作——`_open_window_row` N+1、`_hybrid_tokens` 逐文档分词，
  故为线性。2000 facts = 334ms 为实测值）。

**留给后续（PERF-2 候选，记忆面工人接手后）**：
1. `_open_window_row` 的 N+1 → 一次批量查询（预计 -40%）。
2. `_ensure_history_schema` 移出逐候选路径（调用一次即可）。
3. 候选文档分词结果缓存（`remember` 时写、分词只做一次；或 Rust 化 `_hybrid_tokens`+`_hybrid_bm25` 纯函数部分）。

### 2.2 `match_skill_headers` @ 200 skills：47ms（本轮试点）

cProfile：99% 时间在 `_best_cue_for_header` → `_cue_occurs`（46236 次调用）→
`re.search` + `re._compile`（**47037 次正则编译**，每次 cue 每次调用都重新编译）。
线性扩展：50 skills → 11ms；500 skills → 119ms。

根因是算法面的，不是语言面的：cue n-gram 集合每 skill 每 query 重建、
每个 cue 的边界正则现场编译。但用户已授权 Rust 变体试点，且该函数是
自包含纯函数（输入：normalized query/name/description；输出：最长命中 cue），
是干净的变体边界，故选为首个 Rust 试点。

### 2.3 Daemon pulse：I/O 型，不碰

`resident.pulse()` 25–65ms 几乎全是 SQLite（59 次 execute + 24 次 connect）。
按"只选 CPU 型热点，I/O 型连接器不碰"纪律，不做 Rust 变体；优化方向是
连接复用/批量，不在本轮。

### 2.4 完成摘要 / 浏览器场景：不碰

`_topical_score` 200 summaries 仅 2.2ms（生产 limit=50，约 0.5ms），不是瓶颈。
浏览器场景解析由 Playwright I/O 主导，CPU 解析部分占比小，按纪律不碰。

## 3. Rust 试点：技能路由 cue 匹配器

- 位置：`rust/zn_perf/`（crate `zn_perf_ext`，PyO3 0.23，`extension-module`）
- 边界：`best_cue_for_header(normalized_query, normalized_name, normalized_description) -> String`
  - Python 侧保留 NFKC/casefold 归一化（便宜：200 skills 仅 5ms），Rust 只做热的部分：
    cue n-gram 生成 + 逐 cue 命中判定（含 CJK 子串 / `[a-z0-9_]` 边界 / `\w` 边界三条规则，与 Python 逐条对应）。
- 接入：`skill_routing.py` 启动时 `try: import zn_perf_ext`，缺失时静默回退纯 Python
  （`_best_cue_for_header_py`，即原实现原样下沉）；`ZN_PERF_RUST=0` 可强制走 Python。
  CI/干净安装/无 Rust 构建的平台行为与原来完全一致。
- 构建：`bash rust/build_ext.sh`（cargo build --release → 拷贝为
  `runtime/python/zn_perf_ext.so`；该产物已加入 `.gitignore`，不进仓库）。
- 等价性：
  - Rust 单测 7/7（`cargo test --release`）。
  - 新增 `tests/zn_agent/core/test_skill_routing_rust_equiv.py` 4/4：
    固定语料 17 组 + 端到端 `match_skill_headers` Rust/纯 Python 对照 +
    300 例种子确定性对抗 fuzz（含 ß/İ/Über/naïve/CJK/符号）。
  - 4000 例扩展 fuzz：0 真实分歧；137 例差异全部是**等长并列 cue 的取舍不同**
    （Python 侧迭代 hash 序 set，本就跨进程不确定；Rust 用确定性插入序；
    路由结果 names+order 不受影响，无测试依赖该顺序）。

### 同机同数据基准（PR 正文数字）

`rust/bench_cue_match.py --skills 200 --repeats 15`（5 queries 取平均）：

| 实现 | min | median | mean |
|---|---|---|---|
| 纯 Python（`ZN_PERF_RUST=0` 等价路径） | 46.50ms | 46.89ms | 48.27ms |
| Rust（`zn_perf_ext`） | 16.13ms | 17.02ms | 18.92ms |

**中位加速 2.8x（46.9ms → 17.0ms），500 skills 下约 119ms → ~43ms。**
剩余时间主要在 Python 侧逐 header 归一化（~2.3ms）与 Rust 内 CJK 长词
n-gram 生成——算法级后续优化（按 header 缓存 cue 集合）可再降，列为 PERF-2。

## 4. 试点结论：值不值得推广

**值得，但有条件。** 本试点证明了模式可行：PyO3 可选扩展 + 静默回退，
零 CI 改动、零行为变化、等价测试钉住。2.8x 是实打实的 CPU 节省，
落在技能路由这种每次 agentic 决策都走的路径上。

推广条件（下一批热点照此办理）：
1. 只选纯 CPU、自包含纯函数的热点（本轮四个方向已筛过一遍）；
2. 先做 Python 侧算法审计——本轮发现 `_cue_occurs` 的 47k 次正则重编译、
   recall 的 N+1 + 逐候选 DDL 确认，这类修法可能比换语言收益更大，
   先修算法再谈 Rust；
3. Rust 构建进 CI 是独立事项（本轮试点有意不碰 CI：回退路径保证全绿）；
   真要默认启用，需加 `rust-ext` 构建 job（Linux/Windows 双平台）后再议。

## 5. 修订记录

- 2026-10-21：初版。6000 facts 的 profiling 脚本因 /tmp 被平台回收而中断，
  该行数字改为 O(N) 外推并注明；不影响任何结论（试点选择只依赖 2000 点实测
  与各热点的相对排序）。
