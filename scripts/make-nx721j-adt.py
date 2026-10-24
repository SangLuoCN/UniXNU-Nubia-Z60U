#!/usr/bin/env python3
"""Generate an Apple-format ADT for the Nubia Z60 Ultra (NX721J).

The values in this generator are either taken from the NX721J live device tree
or are generic Apple/UniXNU ABI fields.  It deliberately does not inherit the
sheng board identity, SM8550 compatible strings, or a contiguous-memory guess.

The live device exposes three DDR banks (2 GiB + 6 GiB + 8 GiB).  The
``dram-base``/``dram-size`` pair describes the single XNU-managed window, not
the sum of all physical banks, so both values are required from the caller.
The initial bring-up should use one CPU and a qualified contiguous window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import zlib
from pathlib import Path
from typing import Iterable, NoReturn, Sequence


ROOT_COMPATIBLE = (
    "qcom,pineapple-mtp\0"
    "qcom,pineapple\0"
    "qcom,pineapplep-mtp\0"
    "qcom,pineapplep\0"
    "qcom,mtp\0"
).encode("ascii")
ROOT_MODEL = "Qualcomm Technologies, Inc. Pineapple MTP"
CPU_COMPATIBLE = b"qcom,kryo\0"
CPU_REGS = (0x000, 0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700)
TIMEBASE_FREQUENCY = 0x124F800  # 19.2 MHz, from /soc/timer/clock-frequency
GIC_DIST = 0x17100000
GIC_DIST_SIZE = 0x10000
GIC_REDIST = 0x17180000
GIC_REDIST_SIZE = 0x200000
GIC_REDIST_STRIDE = 0x40000
UFS_HC = 0x1D84000
UFS_HC_REGIONS = ((0x1D84000, 0x3000), (0x1D88000, 0x8000),
                  (0x1D90000, 0x9000), (0x1DA5000, 0x2000),
                  (0x1DA4000, 0x10))
UFS_PHY = (0x1D80000, 0x2000)
UFS_INTERRUPT = (0x0, 0x109, 0x4)
TIMER_INTERRUPTS = ((0x1, 0xD, 0xFF08), (0x1, 0xE, 0xFF08),
                    (0x1, 0xB, 0xFF08), (0x1, 0xC, 0xFF08))
FORBIDDEN_IDENTITY = re.compile(r"(?:sheng|sweet|xiaomi|sm8550|ipad7[,.]1|ace5|giulia)", re.IGNORECASE)
HEX_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def parse_integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        try:
            return int(value, 16)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"not an integer: {value}") from exc


def u32(value: int) -> bytes:
    return struct.pack("<I", value)


def u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def cstr(value: str) -> bytes:
    return value.encode("ascii") + b"\0"


def cells(values: Iterable[int]) -> bytes:
    return b"".join(u32(value) for value in values)


def node(name: str, properties: Sequence[tuple[str, bytes]] = (),
         children: Sequence[bytes] = ()) -> bytes:
    all_properties = [("name", cstr(name)), *properties]
    result = bytearray(struct.pack("<II", len(all_properties), len(children)))
    for key, data in all_properties:
        encoded_key = key.encode("ascii")
        if len(encoded_key) > 31:
            fail(f"ADT property name is longer than 31 bytes: {key}")
        result.extend(struct.pack("<32sI", encoded_key, len(data)))
        result.extend(data)
        result.extend(bytes(-len(data) % 4))
    for child in children:
        result.extend(child)
    return bytes(result)


def empty_nvram_proxy() -> list[tuple[str, bytes]]:
    """Return a fresh volatile CHRP bank for the generic XNU NVRAM path."""

    def header(name: bytes, size: int) -> bytearray:
        raw = bytearray(struct.pack("<BBH12s", 0x70, 0, size // 16, name))
        checksum = sum(raw)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        raw[1] = checksum
        return raw

    image = bytearray(8192)
    image[:16] = header(b"nvram", 32)
    image[32:48] = header(b"common", 16 + 2048)
    free_at = 32 + 16 + 2048
    image[free_at:free_at + 16] = header(b"free", len(image) - free_at)
    struct.pack_into("<I", image, 16, zlib.adler32(image[20:]))
    return [("nvram-bank-size", u32(len(image))),
            ("nvram-bank-count", u32(1)),
            ("nvram-current-bank", u32(0)),
            ("nvram-proxy-data", bytes(image))]


def validate_window(name: str, value: int, *, minimum: int = 0x200000) -> None:
    if value < minimum or value % 0x200000:
        fail(f"{name} must be at least 2 MiB and 2 MiB aligned: {value:#x}")


def validate_identity(value: str, label: str) -> None:
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        fail(f"{label} must be ASCII")
    if FORBIDDEN_IDENTITY.search(value):
        fail(f"{label} contains a non-NX721J identity")


def parse_cpu_regs(value: str) -> list[int]:
    try:
        regs = [parse_integer(item.strip()) for item in value.split(",")]
    except argparse.ArgumentTypeError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if (not regs or len(regs) > len(CPU_REGS) or len(set(regs)) != len(regs)
            or tuple(regs) != CPU_REGS[:len(regs)]):
        raise argparse.ArgumentTypeError(
            "CPU MPIDR values must be a distinct prefix of 0x0,0x100,...,0x700 with boot CPU 0 first"
        )
    return regs


def root_matching(uuid: str | None) -> list[tuple[str, bytes]]:
    if not uuid:
        return []
    if not HEX_UUID.fullmatch(uuid):
        fail("--root-match-volume-uuid must be a canonical UUID")
    xml = ("<dict><key>IOProviderClass</key><string>IOMedia</string>"
           "<key>IOPropertyMatch</key><dict><key>UUID</key><string>"
           + uuid.upper() + "</string></dict></dict>\0")
    return [("root-matching", xml.encode("ascii"))]


def relative_reg(regions: Sequence[tuple[int, int]], base: int) -> bytes:
    return b"".join(struct.pack("<QQ", address - base, size) for address, size in regions)


def build_tree(args: argparse.Namespace, cpu_regs: Sequence[int]) -> bytes:
    if args.arm_io_size < 0x200000 or args.arm_io_size % 0x1000:
        fail("--arm-io-size must be at least 2 MiB and 4 KiB aligned")
    resources = [(GIC_DIST, GIC_DIST_SIZE), (GIC_REDIST, GIC_REDIST_SIZE),
                 *UFS_HC_REGIONS, UFS_PHY]
    for address, size in resources:
        if address < args.arm_io_base or address - args.arm_io_base + size > args.arm_io_size:
            fail(f"resource {address:#x}/{size:#x} is outside the arm-io range; adjust --arm-io-base/--arm-io-size")

    chosen_properties = [
        ("random-seed", os.urandom(64)),
        ("osenvironment", cstr("main")),
        ("dram-base", u64(args.dram_base)),
        ("dram-size", u64(args.dram_size)),
        ("crypto-hash-method", cstr("sha2-384")),
        ("amfi-only-platform-code", u32(1)),
        *root_matching(args.root_match_volume_uuid),
        *([("unique-chip-id", u64(args.unique_chip_id)), ("chip-id", u32(args.chip_id))]
          if args.unique_chip_id is not None else []),
        *([("ephemeral-storage", u32(1))]
          if args.data_ramdisk or args.packed_data_ramdisk else []),
        *([("darwinboot-memory-size", u64(args.owned_memory_size))]
          if args.owned_memory_size is not None else []),
        *empty_nvram_proxy(),
    ]
    memory_map = []
    if args.data_ramdisk:
        memory_map.append(("RAMDisk", bytes(16)))
    if args.packed_data_ramdisk:
        memory_map.append(("PackedRAMDisk", bytes(16)))
    if args.trust_cache:
        memory_map.append(("TrustCache", bytes(16)))

    cpu_nodes = []
    for index, reg in enumerate(cpu_regs):
        cpu_nodes.append(node(f"cpu{index}", [
            ("state", cstr("running" if index == 0 else "waiting")),
            ("reg", u32(reg)),
            ("device_type", cstr("cpu")),
            ("compatible", CPU_COMPATIBLE),
            ("timebase-frequency", u32(TIMEBASE_FREQUENCY)),
        ]))

    gic_regions = ((GIC_DIST - args.arm_io_base, GIC_DIST_SIZE),
                   (GIC_REDIST - args.arm_io_base, GIC_REDIST_SIZE))
    gic = node("intc", [
        ("compatible", cstr("arm,gic-v3")),
        ("reg", relative_reg(gic_regions, 0)),
        ("redistributor-stride", u64(GIC_REDIST_STRIDE)),
        ("#redistributor-regions", u32(1)),
        ("interrupts", cells((0x1, 0x9, 0x4))),
    ])
    timer = node("timer", [
        ("compatible", cstr("arm,armv8-timer")),
        ("clock-frequency", u32(TIMEBASE_FREQUENCY)),
        ("interrupts", cells(value for triplet in TIMER_INTERRUPTS for value in triplet)),
    ])
    ufs = node("ufshc", [
        ("compatible", cstr("qcom,ufshc")),
        ("status", cstr("ok")),
        ("reg", relative_reg(UFS_HC_REGIONS, args.arm_io_base)),
        ("interrupts", cells(UFS_INTERRUPT)),
    ])
    ufs_phy = node("ufsphy", [
        ("compatible", cstr("qcom,ufs-phy-qmp-v4-pineapple")),
        ("status", cstr("ok")),
        ("reg", relative_reg((UFS_PHY,), args.arm_io_base)),
    ])
    arm_io = node("arm-io", [
        ("device_type", cstr("arm-io")),
        ("#address-cells", u32(2)),
        ("#size-cells", u32(2)),
        # This is an ADT translation window chosen to cover the verified GIC
        # and UFS resources; it is not a claim that the Linux FDT has an
        # arm-io node with this parent base.
        ("ranges", struct.pack("<QQQ", 0, args.arm_io_base, args.arm_io_size)),
    ], [gic, timer, ufs, ufs_phy])

    children = [
        node("chosen", chosen_properties, [
            node("memory-map", memory_map),
            node("manifest-properties"),
        ]),
        node("cpus", [
            ("#address-cells", u32(1)),
            ("#size-cells", u32(0)),
        ], cpu_nodes),
        node("psci", [("compatible", cstr("arm,psci-1.0")),
                       ("method", cstr(args.psci_method))]),
        node("defaults", [("sleep-disabled", u32(1))]),
        node("options"),
        node("product", [("product-name", cstr(args.product_name)),
                          ("model", cstr(args.product_model))]),
        arm_io,
    ]
    return node("device-tree", [
        ("model", cstr(args.model)),
        ("compatible", ROOT_COMPATIBLE),
        ("#address-cells", u32(2)),
        ("#size-cells", u32(2)),
    ], children)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="output Apple-format ADT file")
    parser.add_argument("--dram-base", type=parse_integer, required=True,
                        help="explicit physical base of the XNU-managed contiguous window")
    parser.add_argument("--dram-size", type=parse_integer, required=True,
                        help="explicit size of the XNU-managed contiguous window")
    parser.add_argument("--owned-memory-size", type=parse_integer, default=None,
                        help="DarwinBoot allocation request, 256 MiB..8 GiB, 2 MiB aligned")
    parser.add_argument("--arm-io-base", type=parse_integer, default=0x01000000,
                        help="ADT translation parent base covering verified GIC/UFS resources")
    parser.add_argument("--arm-io-size", type=parse_integer, default=0x18000000,
                        help="ADT translation window size")
    parser.add_argument("--cpu-regs", type=parse_cpu_regs, default=[0],
                        help="comma-separated MPIDR affinity prefix; default is boot CPU only")
    parser.add_argument("--psci-method", choices=["smc", "hvc"], default="smc",
                        help="verified NX721J PSCI conduit")
    parser.add_argument("--unique-chip-id", type=parse_integer, default=None,
                        help="explicit 64-bit platform seed; never inferred from device serial")
    parser.add_argument("--chip-id", type=parse_integer, default=None,
                        help="explicit 32-bit platform seed, supplied with --unique-chip-id")
    parser.add_argument("--root-match-volume-uuid", default=None,
                        help="UUID of the target IOMedia root volume")
    parser.add_argument("--data-ramdisk", action="store_true",
                        help="reserve the dense RAMDisk placeholder")
    parser.add_argument("--packed-data-ramdisk", action="store_true",
                        help="reserve the PackedRAMDisk placeholder")
    parser.add_argument("--trust-cache", action="store_true",
                        help="reserve the TrustCache placeholder")
    parser.add_argument("--model", default=ROOT_MODEL,
                        help="live root model string")
    parser.add_argument("--product-name", default="Nubia Z60 Ultra",
                        help="XNU product node name")
    parser.add_argument("--product-model", default="zte,nx721j",
                        help="XNU product node model")
    parser.add_argument("--report", type=Path, default=None,
                        help="optional JSON audit report")
    args = parser.parse_args()

    if args.dram_base < 0 or args.dram_size <= 0:
        fail("--dram-base must be non-negative and --dram-size must be positive")
    validate_window("--dram-base", args.dram_base)
    validate_window("--dram-size", args.dram_size)
    if args.owned_memory_size is not None:
        if not 0x10000000 <= args.owned_memory_size <= 0x200000000 or args.owned_memory_size % 0x200000:
            fail("--owned-memory-size must be 256 MiB..8 GiB and 2 MiB aligned")
    if (args.unique_chip_id is None) != (args.chip_id is None):
        fail("--unique-chip-id and --chip-id must be supplied together")
    if args.unique_chip_id is not None and not (0 < args.unique_chip_id < 1 << 64 and 0 < args.chip_id < 1 << 32):
        fail("platform seeds must fit their 64-bit/32-bit fields and be non-zero")
    if args.data_ramdisk and args.packed_data_ramdisk:
        fail("--data-ramdisk and --packed-data-ramdisk are mutually exclusive")
    for value, label in ((args.model, "--model"), (args.product_name, "--product-name"),
                         (args.product_model, "--product-model")):
        validate_identity(value, label)

    tree = build_tree(args, args.cpu_regs)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(tree)
    print(f"NX721J ADT: {output} ({len(tree)} bytes)")
    print(f"DRAM window: {args.dram_base:#x} + {args.dram_size:#x}")
    print(f"CPUs: {','.join(f'{reg:#x}' for reg in args.cpu_regs)}")

    if args.report:
        report = args.report.expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({
            "target": "ZTE Nubia Z60 Ultra NX721J",
            "root_model": args.model,
            "root_compatible": ROOT_COMPATIBLE.rstrip(b"\0").decode("ascii").split("\0"),
            "dram_base": hex(args.dram_base),
            "dram_size": hex(args.dram_size),
            "arm_io_base": hex(args.arm_io_base),
            "arm_io_size": hex(args.arm_io_size),
            "cpu_regs": [hex(reg) for reg in args.cpu_regs],
            "psci_method": args.psci_method,
            "timebase_frequency": TIMEBASE_FREQUENCY,
            "gic": {"dist": hex(GIC_DIST), "redist": hex(GIC_REDIST),
                    "redist_stride": hex(GIC_REDIST_STRIDE)},
            "ufs": {"host": hex(UFS_HC), "phy": hex(UFS_PHY[0]),
                    "compatible": "qcom,ufshc",
                    "phy_compatible": "qcom,ufs-phy-qmp-v4-pineapple"},
            "bytes": len(tree),
        }, indent=2) + "\n", encoding="ascii", newline="\n")
        print(f"Report: {report}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
