from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Legal attribution in LICENSE must remain verbatim. Markdown is product/research
# documentation rather than executable product source, so it may name external
# systems that ZN studies or compares against. Paths are still checked below, so
# a retired/reference product cannot return as a tracked namespace simply by
# being placed in a Markdown file.
TEXT_SCAN_EXEMPT = {"LICENSE"}
TEXT_SCAN_EXEMPT_SUFFIXES = {".md"}

# Retired reference-product identifiers are encoded so the active tree stays
# text-clean while this verifier can still prevent them from returning as source,
# runtime, build, test, tooling, or tracked-path identities.
FORBIDDEN_MARKERS = tuple(
    bytes.fromhex(value)
    for value in (
        "6865726d6573",
        "6e6f75737265736561726368",
        "6e6f7573207265736561726368",
        "6167656e742e6b65726e656c",
        "6167656e742f6b65726e656c",
    )
)

# The private source repository is maintainer infrastructure, not installed
# product identity. Keep its literal out of the shipped resident core and desktop
# package metadata while allowing repository-internal docs/tests/release tooling to
# identify the source repository where that is actually necessary.
PRIVATE_SOURCE_MARKER = bytes.fromhex("393532393336302d6370752f7a6e6167656e74")
SHIPPED_PRIVATE_SCAN_PREFIX = "runtime/python/zn_agent/core/"
SHIPPED_PRIVATE_SCAN_FILES = {"apps/desktop/package.json"}


def tracked_paths() -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
    )
    return [ROOT / raw.decode("utf-8", errors="surrogateescape") for raw in output.split(b"\0") if raw]


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def main() -> int:
    failures: list[str] = []
    for path in tracked_paths():
        relative = path.relative_to(ROOT).as_posix()
        lowered_path = relative.encode("utf-8", errors="surrogateescape").lower()
        for marker in FORBIDDEN_MARKERS:
            if marker in lowered_path:
                failures.append(f"{relative}: path contains retired marker {marker.hex()}")

        if relative in TEXT_SCAN_EXEMPT or path.suffix.lower() in TEXT_SCAN_EXEMPT_SUFFIXES:
            continue
        data = path.read_bytes()
        if is_binary(data):
            continue

        private_source_scan = (
            relative.startswith(SHIPPED_PRIVATE_SCAN_PREFIX)
            or relative in SHIPPED_PRIVATE_SCAN_FILES
        )
        for line_number, line in enumerate(data.splitlines(), start=1):
            lowered_line = line.lower()
            for marker in FORBIDDEN_MARKERS:
                if marker in lowered_line:
                    snippet = line.decode("utf-8", errors="replace")
                    failures.append(
                        f"{relative}:{line_number}: retired marker {marker.hex()}: {snippet}"
                    )
                    break
            if private_source_scan and PRIVATE_SOURCE_MARKER in lowered_line:
                failures.append(
                    f"{relative}:{line_number}: installed product embeds private source repository identity"
                )

    if failures:
        print("ZN source-boundary verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(
        "ZN source-boundary verification passed: active source is reference-product clean; documentation may name studied systems; shipped product metadata does not embed private source identity."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
