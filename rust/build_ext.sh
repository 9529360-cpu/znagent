#!/bin/bash
# PERF-1: build the optional zn_perf_ext PyO3 extension and drop it next to
# the Python package so `import zn_perf_ext` works with
# PYTHONPATH=runtime/python.
#
# The extension is OPTIONAL: skill_routing.py falls back to pure Python when
# it is absent, so CI and clean installs never need Rust. This script is for
# local benchmarking and for deployments that want the faster path.
#
# Usage: bash rust/build_ext.sh
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.cargo/bin:$PATH"

cd "$REPO_ROOT/rust/zn_perf"
cargo build --release

SO_SRC="$REPO_ROOT/rust/zn_perf/target/release/libzn_perf_ext.so"
SO_DST="$REPO_ROOT/runtime/python/zn_perf_ext.so"
cp -f "$SO_SRC" "$SO_DST"
echo "installed: $SO_DST"

PYTHONPATH="$REPO_ROOT/runtime/python" python3 -c "
import zn_perf_ext
print('import ok:', zn_perf_ext.best_cue_for_header('do web research', 'deep research', 'use when doing multi source web research'))
"
