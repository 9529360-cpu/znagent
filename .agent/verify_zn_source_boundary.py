from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Legal attribution in LICENSE must remain verbatim. This verifier enforces the
# active source/product boundary everywhere else.
TEXT_SCAN_EXEMPT = {"LICENSE"}

# Retired reference-product identifiers are encoded so the active tree stays
# text-clean while this verifier can still prevent them from returning.
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

        if relative in TEXT_SCAN_EXEMPT:
            continue
        data = path.read_bytes()
        if is_binary(data):
            continue
        for line_number, line in enumerate(data.splitlines(), start=1):
            lowered_line = line.lower()
            for marker in FORBIDDEN_MARKERS:
                if marker in lowered_line:
                    snippet = line.decode("utf-8", errors="replace")
                    failures.append(
                        f"{relative}:{line_number}: retired marker {marker.hex()}: {snippet}"
                    )
                    break

    if failures:
        print("ZN source-boundary verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("ZN source-boundary verification passed: active tracked tree is reference-product text clean outside preserved legal attribution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
