#!/usr/bin/env python3
"""Build the NX721J UniXNU userdata payload.

The loader is already embedded in the NX721J firmware volume.  This image
therefore contains only the official UniXNU configuration and the explicit
NX721J kernel inputs supplied by the caller:

  EFI/UniXNU/unixnu.toml
  EFI/UniXNU/Payloads/kernel.macho
  EFI/UniXNU/Payloads/kernel.macho.adt

Optional trust-cache and Data seed files are copied only when explicitly
provided.  No sheng, sweet, Xiaomi, SM8550, or Ace5 defaults are inferred.
The script uses mtools and never mounts or writes a device partition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
from typing import NoReturn
from pathlib import Path


EPOCH = 315532800  # 1980-01-01, deterministic FAT timestamps
MACHO_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
ARGUMENT_RE = re.compile(r"[A-Za-z0-9_.\-]+(=[A-Za-z0-9_.,\-]+)?$")
FORBIDDEN_IDENTITY = re.compile(r"(?:sheng|sweet|xiaomi|sm8550|ipad7[,.]1)", re.IGNORECASE)


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        fail(f"{label} not found: {path}")
    if path.stat().st_size == 0:
        fail(f"{label} is empty: {path}")
    return path


def validate_kernel(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) < 32:
        fail(f"kernel is shorter than a 64-bit Mach-O header: {path}")

    little_magic = struct.unpack_from("<I", raw)[0]
    big_magic = struct.unpack_from(">I", raw)[0]
    if little_magic == MACHO_MAGIC_64:
        endian = "little"
        prefix = "<"
    elif big_magic == MACHO_MAGIC_64:
        endian = "big"
        prefix = ">"
    else:
        fail(f"kernel is not a 64-bit Mach-O image: {path}")

    cpu_type, cpu_subtype, file_type, load_commands, command_size, flags = struct.unpack_from(
        f"{prefix}6I", raw, 4
    )
    if cpu_type != CPU_TYPE_ARM64:
        fail(f"kernel CPU type is 0x{cpu_type:08x}, expected ARM64 0x{CPU_TYPE_ARM64:08x}")
    if load_commands == 0 or command_size == 0:
        fail("kernel Mach-O has no load commands")
    if 32 + command_size > len(raw):
        fail("kernel Mach-O load-command area exceeds the file")
    return {
        "magic": f"0x{MACHO_MAGIC_64:08x}",
        "endian": endian,
        "cpu_type": f"0x{cpu_type:08x}",
        "cpu_subtype": f"0x{cpu_subtype:08x}",
        "file_type": f"0x{file_type:08x}",
        "load_commands": load_commands,
        "load_command_bytes": command_size,
        "flags": f"0x{flags:08x}",
    }


def validate_adt(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    lowered = raw.lower()
    for token in (b"sheng", b"sweet", b"xiaomi", b"sm8550"):
        if token in lowered:
            fail(f"ADT contains forbidden non-NX721J identity token {token.decode()}: {path}")
    required = (b"device-tree", b"compatible")
    missing = [token.decode() for token in required if token not in raw]
    if missing:
        fail(f"ADT does not look like an Apple device tree; missing {', '.join(missing)}")
    if len(raw) < 64:
        fail(f"ADT is implausibly small: {path}")
    return {"bytes": len(raw), "sha256": sha256(path)}


def validate_optional(path: Path | None, label: str) -> Path | None:
    return require_file(path, label) if path else None


def validate_arguments(arguments: list[str]) -> str:
    ufs_target: list[str] = []
    ufs_probe: list[str] = []
    for argument in arguments:
        if not ARGUMENT_RE.fullmatch(argument):
            fail(f"unsupported kernel argument: {argument}")
        if FORBIDDEN_IDENTITY.search(argument):
            fail(f"kernel argument contains a non-NX721J identity: {argument}")
        key, separator, value = argument.partition("=")
        if separator and key == "native-ufs-target":
            ufs_target.append(value)
        elif separator and key == "native-ufs-probe":
            ufs_probe.append(value)

    if any(value != "nx721j" for value in ufs_target):
        fail("native-ufs-target must be nx721j for an NX721J payload")
    if any(argument.startswith("native-ufs-root=") for argument in arguments):
        fail("native-ufs-root is not qualified on NX721J; use passive native-ufs-probe=2")
    if ufs_probe:
        if ufs_target != ["nx721j"]:
            fail("native-ufs-probe requires native-ufs-target=nx721j")
        if ufs_probe != ["2"]:
            fail("NX721J currently permits only native-ufs-probe=2")

    line = " ".join(arguments)
    if len(line) > 1000:
        fail(f"kernel command line is {len(line)} bytes; DarwinBoot accepts at most 1000")
    return line


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def run_tool(command: list[str], env: dict[str, str]) -> None:
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True)
    except OSError as exc:
        fail(f"failed to execute {command[0]}: {exc}")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        fail(f"{' '.join(command)} failed: {detail or 'no diagnostic'}")


def write_fat_volume(stage: Path, image: Path, label: str, size_mib: int) -> None:
    mformat = shutil.which("mformat")
    mcopy = shutil.which("mcopy")
    if not mformat or not mcopy:
        fail("mtools is required: install mformat and mcopy, then rerun")
    image.parent.mkdir(parents=True, exist_ok=True)
    image.unlink(missing_ok=True)
    env = dict(os.environ, MTOOLS_SKIP_CHECK="1", TZ="UTC")
    sectors = size_mib * 2048
    run_tool(
        [mformat, "-C", "-F", "-T", str(sectors), "-v", label, "-N", "4e583732", "-i", str(image), "::"],
        env,
    )
    for entry in sorted(stage.iterdir(), key=lambda item: item.name):
        run_tool([mcopy, "-i", str(image), "-s", "-Q", "-m", str(entry), "::/"], env)


def stage_payload(args: argparse.Namespace, kernel: Path, adt: Path,
                  trust_cache: Path | None, data_ramdisk: Path | None,
                  kernel_args: str, stage: Path) -> None:
    payloads = stage / "EFI" / "UniXNU" / "Payloads"
    payloads.mkdir(parents=True)
    shutil.copyfile(kernel, payloads / "kernel.macho")
    shutil.copyfile(adt, payloads / "kernel.macho.adt")
    if trust_cache:
        shutil.copyfile(trust_cache, payloads / "kernel.macho.trustcache")
    if data_ramdisk:
        shutil.copyfile(data_ramdisk, payloads / "scratch-data.img")

    initrd = "initrd = \"Payloads/scratch-data.img\"\n" if data_ramdisk else ""
    config = (
        "version = 1\n"
        "[boot]\n"
        f"timeout = {args.timeout}\n"
        "default = \"xnu\"\n"
        "[kits]\n"
        "autoload = false\n"
        "[[entry]]\n"
        "id = \"xnu\"\n"
        f"title = {toml_string(args.title)}\n"
        "type = \"xnu\"\n"
        "path = \"Payloads/kernel.macho\"\n"
        f"{initrd}"
        f"args = {toml_string(kernel_args)}\n"
    )
    (stage / "EFI" / "UniXNU" / "unixnu.toml").write_text(config, encoding="ascii", newline="\n")
    for path in [stage, *stage.rglob("*")]:
        os.utime(path, (EPOCH, EPOCH))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True,
                        help="NX721J ARM64 Mach-O kernel; no board default is used")
    parser.add_argument("--adt", type=Path, required=True,
                        help="NX721J Apple device-tree sidecar generated from target facts")
    parser.add_argument("--output", type=Path, required=True,
                        help="output FAT image; this is a host-side artifact")
    parser.add_argument("--kernel-arg", action="append", default=[],
                        help="one explicit DarwinBoot/XNU argument; repeatable")
    parser.add_argument("--trust-cache", type=Path, default=None,
                        help="optional target trust-cache sidecar")
    parser.add_argument("--data-ramdisk", type=Path, default=None,
                        help="optional Data seed/ramdisk sidecar")
    parser.add_argument("--title", default="Boot NX721J",
                        help="UniXNU menu title")
    parser.add_argument("--timeout", type=int, default=3,
                        help="UniXNU menu timeout in seconds")
    parser.add_argument("--size-mib", type=int, default=192,
                        help="FAT image size in MiB")
    parser.add_argument("--volume-label", default="NX721J",
                        help="FAT volume label, at most 11 ASCII characters")
    args = parser.parse_args()

    if not 0 <= args.timeout <= 600:
        fail("--timeout must be between 0 and 600 seconds")
    if args.size_mib < 16:
        fail("--size-mib must be at least 16")
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,11}", args.volume_label):
        fail("--volume-label must be 1-11 ASCII letters, digits, underscore, or hyphen")
    if FORBIDDEN_IDENTITY.search(args.title):
        fail("menu title contains a non-NX721J identity")

    kernel = require_file(args.kernel, "kernel")
    adt = require_file(args.adt, "ADT")
    trust_cache = validate_optional(args.trust_cache, "trust cache")
    data_ramdisk = validate_optional(args.data_ramdisk, "Data ramdisk")
    macho_info = validate_kernel(kernel)
    adt_info = validate_adt(adt)
    kernel_args = validate_arguments(args.kernel_arg)

    output = args.output.expanduser().resolve()
    report = output.with_suffix(output.suffix + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nx721j-payload-", dir=str(output.parent)) as temp_dir:
        stage = Path(temp_dir) / "stage"
        stage_payload(args, kernel, adt, trust_cache, data_ramdisk, kernel_args, stage)
        content_bytes = sum(path.stat().st_size for path in stage.rglob("*") if path.is_file())
        if content_bytes > args.size_mib * 1024 * 1024 * 0.95:
            fail(f"payload files use {content_bytes} bytes; increase --size-mib")
        write_fat_volume(stage, output, args.volume_label, args.size_mib)

    report_data = {
        "target": "ZTE Nubia Z60 Ultra NX721J",
        "loader": "firmware: official UniXNU + official DarwinBoot",
        "kernel": {"path": str(kernel), "sha256": sha256(kernel), **macho_info},
        "adt": {"path": str(adt), **adt_info},
        "trust_cache_sha256": sha256(trust_cache) if trust_cache else None,
        "data_ramdisk_sha256": sha256(data_ramdisk) if data_ramdisk else None,
        "kernel_args": kernel_args,
        "payload_sha256": sha256(output),
        "payload_bytes": output.stat().st_size,
        "hardware_tested": False,
    }
    report.write_text(json.dumps(report_data, indent=2) + "\n", encoding="ascii", newline="\n")
    print(f"NX721J payload: {output} ({output.stat().st_size >> 20} MiB)")
    print(f"SHA256: {report_data['payload_sha256']}")
    print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
