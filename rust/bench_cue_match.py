"""PERF-1 benchmark: pure-Python vs Rust cue matcher, same machine + data.

Usage:
  PYTHONPATH=runtime/python python3 rust/bench_cue_match.py [--skills N] [--repeats R]

Builds N synthetic skill headers (mixed CJK/Latin descriptions, like the
real registry), then times match_skill_headers() with the Rust extension
forced on vs forced off. Requires the extension built (rust/build_ext.sh);
ZN_PERF_RUST=0 forces the Python path for the baseline leg.
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime" / "python"))

from zn_agent.core import skill_routing
from zn_agent.core.skill_routing import SkillHeader, match_skill_headers

TOPICS = ["天气查询", "任务管理", "代码审查", "日历安排", "邮件处理",
          "文档生成", "数据分析", "网页搜索", "文件管理", "会议记录"]
VERBS = ["帮助用户", "自动完成", "智能识别", "快速处理", "定时执行",
         "批量操作", "实时监控", "深度分析"]
QUERIES = [
    "帮我查一下明天的天气任务管理安排",
    "do multi-source web research and managing tasks",
    "remind me to water the plants every sunday",
    "部署应用到生产环境并做代码审查",
    "查一下 Berlin 天气预报详情",
]


def make_headers(n: int, seed: int) -> list[SkillHeader]:
    rng = random.Random(seed)
    headers = []
    for i in range(n):
        topic = rng.choice(TOPICS)
        desc = "".join(rng.choice(VERBS) + rng.choice(TOPICS) for _ in range(6))
        headers.append(SkillHeader(name=f"skill-{i}-{topic}",
                                   description=f"{desc}技能{i}",
                                   version="1.0", path=Path(f"/tmp/skill{i}")))
    return headers


def bench(headers: list[SkillHeader], repeats: int) -> list[float]:
    for q in QUERIES:  # warmup
        match_skill_headers(headers, q)
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        for q in QUERIES:
            match_skill_headers(headers, q)
        times.append((time.perf_counter() - t0) / len(QUERIES))
    return times


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skills", type=int, default=200)
    ap.add_argument("--repeats", type=int, default=15)
    ap.add_argument("--seed", type=int, default=20261021)
    args = ap.parse_args()

    headers = make_headers(args.skills, args.seed)
    rust_fn = skill_routing._RUST_BEST_CUE
    print(f"skills={args.skills} queries={len(QUERIES)} "
          f"rust_available={rust_fn is not None}")

    results = {}
    for label, forced in (("python", None), ("rust", rust_fn)):
        if forced is None and label == "rust":
            print("rust: extension not built, skipping")
            continue
        saved = skill_routing._RUST_BEST_CUE
        skill_routing._RUST_BEST_CUE = forced
        try:
            results[label] = bench(headers, args.repeats)
        finally:
            skill_routing._RUST_BEST_CUE = saved
        ts = results[label]
        print(f"{label}: min={min(ts)*1000:.2f}ms "
              f"median={statistics.median(ts)*1000:.2f}ms "
              f"mean={statistics.mean(ts)*1000:.2f}ms")
    if "python" in results and "rust" in results:
        speedup = (statistics.median(results["python"])
                   / statistics.median(results["rust"]))
        print(f"speedup (median): {speedup:.1f}x")
    # restore ambient state for any importer
    os.environ.pop("ZN_PERF_RUST", None)


if __name__ == "__main__":
    main()
