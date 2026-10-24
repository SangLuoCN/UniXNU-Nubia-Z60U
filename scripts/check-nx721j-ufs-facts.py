#!/usr/bin/env python3
"""Validate the read-only NX721J UFS facts exported by proc-device-tree.

This tool consumes an external DT snapshot and writes no device data.  It is
intentionally stricter than a generic Qualcomm UFS checker: a snapshot must
describe the Pineapple UFS host, Pineapple PHY, GCC clock block, Apps SMMU
stream 0x60 and the two UFS interconnect paths before it can be used as input
to a target-specific driver.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import NoReturn


UFS_REG = ((0x1D84000, 0x3000), (0x1D88000, 0x8000),
           (0x1D90000, 0x9000), (0x1DA5000, 0x2000),
           (0x1DA4000, 0x10))
UFS_PHY_REG = (0x1D80000, 0x2000)
UFS_CLOCK_NAMES = ("core_clk", "bus_aggr_clk", "iface_clk", "core_clk_unipro",
                   "core_clk_ice", "ref_clk", "tx_lane0_sync_clk",
                   "rx_lane0_sync_clk", "rx_lane1_sync_clk")


def fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def read(path: Path) -> bytes:
    if not path.is_file():
        fail(f"missing DT property: {path}")
    return path.read_bytes()


def cells(path: Path) -> list[int]:
    raw = read(path)
    if len(raw) % 4:
        fail(f"DT property is not a 32-bit cell array: {path}")
    return list(struct.unpack(f">{len(raw) // 4}I", raw))


def strings(path: Path) -> list[str]:
    raw = read(path)
    if not raw or raw[-1] != 0:
        fail(f"DT string-list is not NUL terminated: {path}")
    return raw.rstrip(b"\0").decode("ascii").split("\0")


def string(path: Path) -> str:
    values = strings(path)
    if len(values) != 1:
        fail(f"DT property is not a single string: {path}")
    return values[0]


def reg_pairs(path: Path) -> list[tuple[int, int]]:
    values = cells(path)
    if len(values) % 2:
        fail(f"DT reg property is not 32-bit address/size pairs: {path}")
    return list(zip(values[::2], values[1::2]))


def expect(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        fail(f"{label}: expected {expected!r}, got {actual!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proc-device-tree", type=Path, required=True,
                        help="external read-only /proc/device-tree directory")
    parser.add_argument("--report", type=Path, default=None,
                        help="optional JSON report outside the repository")
    args = parser.parse_args()

    root = args.proc_device_tree.expanduser().resolve()
    ufshc = root / "soc" / "ufshc@1d84000"
    phy = root / "soc" / "ufsphy_mem@1d80000"
    gcc = root / "soc" / "clock-controller@100000"
    expect("UFS compatible", string(ufshc / "compatible"), "qcom,ufshc")
    expect("UFS status", string(ufshc / "status"), "ok")
    expect("UFS reg", reg_pairs(ufshc / "reg"), list(UFS_REG))
    expect("UFS interrupts", cells(ufshc / "interrupts"), [0, 0x109, 4])
    expect("UFS clock names", strings(ufshc / "clock-names"), list(UFS_CLOCK_NAMES))
    expect("UFS clock cell count", len(cells(ufshc / "clocks")), 2 * len(UFS_CLOCK_NAMES))
    expect("UFS reset specifier", cells(ufshc / "resets")[1], 0x19)
    expect("UFS PHY phandle cell count", len(cells(ufshc / "phys")), 1)
    expect("UFS interconnect names", strings(ufshc / "interconnect-names"), ["ufs-ddr", "cpu-ufs"])
    expect("UFS interconnect cell count", len(cells(ufshc / "interconnects")), 8)
    expect("UFS IOMMU stream ID", cells(ufshc / "iommus")[1:], [0x60, 0])
    expect("UFS DMA mode", string(ufshc / "qcom,iommu-dma"), "fastmap")
    expect("UFS DMA pool", cells(ufshc / "qcom,iommu-dma-addr-pool"), [0x1000, 0xFFFFF000])
    expect("UFS DMA coherent", (ufshc / "dma-coherent").is_file(), True)
    expect("UFS PHY compatible", string(phy / "compatible"), "qcom,ufs-phy-qmp-v4-pineapple")
    expect("UFS PHY reg", reg_pairs(phy / "reg"), [UFS_PHY_REG])
    expect("Pineapple GCC compatible", strings(gcc / "compatible")[:1], ["qcom,pineapple-gcc"])
    expect("Pineapple GCC reg", reg_pairs(gcc / "reg"), [(0x100000, 0x1F4200)])

    report_data = {
        "target": "ZTE Nubia Z60 Ultra NX721J",
        "ufs_reg": [[hex(address), hex(size)] for address, size in UFS_REG],
        "ufs_interrupt": "SPI 0x109",
        "clock_names": list(UFS_CLOCK_NAMES),
        "reset_id": "0x19",
        "smmu_stream_id": "0x60",
        "dma": {"mode": "fastmap", "pool": ["0x1000", "0xfffff000"], "coherent": True},
        "phy": {"compatible": "qcom,ufs-phy-qmp-v4-pineapple",
                "reg": [hex(UFS_PHY_REG[0]), hex(UFS_PHY_REG[1])]},
        "gcc": {"compatible": "qcom,pineapple-gcc", "reg": ["0x100000", "0x1f4200"]},
    }
    if args.report:
        report = args.report.expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(report_data, indent=2) + "\n", encoding="ascii", newline="\n")
        print(f"Report: {report}")
    print("NX721J UFS facts: PASS")
    print(json.dumps(report_data, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(1)
