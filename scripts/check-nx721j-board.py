#!/usr/bin/env python3
"""Validate the NX721J kernel-only board boundary."""

from __future__ import annotations

from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "board.toml"
FORBIDDEN = re.compile(r"(?:sheng|sweet|xiaomi|sm8550|ace5|giulia|native-ufs-root)", re.IGNORECASE)


def fail(message: str) -> int:
    print(f"FAIL: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if not BOARD.is_file():
        return fail(f"missing {BOARD}")
    text = BOARD.read_text(encoding="utf-8")
    if FORBIDDEN.search(text):
        return fail("board.toml contains a forbidden foreign-board identity or root transport")
    try:
        spec = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return fail(f"invalid TOML: {exc}")

    board = spec.get("board", {})
    if board.get("name") != "nx721j" or board.get("soc") != "Pineapple" or board.get("kit") != "nx721j":
        return fail("board name, soc and kit must be nx721j, Pineapple and nx721j")
    if spec.get("kernel", {}).get("defconfig") != "nx721j_probe_defconfig":
        return fail("kernel defconfig is not nx721j_probe_defconfig")
    for section in ("userdata", "firmware", "payload"):
        if section in spec:
            return fail(f"kernel-only baseline must not define [{section}]")
    prelink = spec.get("kernel", {}).get("prelink", {})
    for key in ("tool", "kernel", "kernelcache_sha256", "slide", "roots"):
        if not prelink.get(key):
            return fail(f"missing [kernel.prelink] {key}")
    archives = spec.get("kernel", {}).get("archives", [])
    required = {
        "build-corecrypto-14.py",
        "build-corecrypto-14.py --namespace",
        "build-arm-driver.py ArmDTPlatform",
        "build-arm-driver.py ArmCpu",
        "build-arm-driver.py NativeUfs",
        "build-nx721j-kernel-stubs.py",
        "build-libpthread-kernel.py",
    }
    if not required.issubset(archives):
        return fail("kernel archive list is incomplete")
    print("PASS: NX721J kernel-only board boundary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
