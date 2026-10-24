#!/usr/bin/env python3
"""Check that the NX721J probe defconfig has no sheng/Ace5 board options."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "nx721j_probe_defconfig"
FORBIDDEN = re.compile(r"(?:SHENG|SWEET|ACE5|GIULIA|SM8550|NOVATEK|ADRENO)", re.IGNORECASE)


class Nx721jDefconfigTests(unittest.TestCase):
    def test_file_is_present_and_well_formed(self) -> None:
        self.assertTrue(CONFIG.is_file())
        for number, line in enumerate(CONFIG.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#") or not line.strip():
                continue
            self.assertRegex(line, r"^CONFIG_[A-Z0-9_]+=(?:y|n|[0-9]+|\"[^\"]*\")$", f"line {number}")

    def test_probe_has_only_generic_required_switches(self) -> None:
        text = CONFIG.read_text(encoding="utf-8")
        enabled = "\n".join(
            line for line in text.splitlines()
            if line.startswith("CONFIG_") and line.endswith("=y")
        )
        self.assertNotRegex(enabled, FORBIDDEN)
        for key in (
            "CONFIG_XNU_ARM_DT_PLATFORM=y",
            "CONFIG_XNU_ARMCPU=y",
            "CONFIG_XNU_NATIVE_ARCH_TIMER=y",
            "CONFIG_XNU_NATIVE_UFS=y",
            "CONFIG_XNU_BOOT_PROGRESS=y",
            "CONFIG_XNU_NATIVE_MOBILE_DISPLAY=n",
            "CONFIG_XNU_NATIVE_LEGACY_DISPLAY=n",
            "CONFIG_XNU_NATIVE_ADRENO=n",
            "CONFIG_XNU_ARMVIRT_PLATFORM=n",
        ):
            self.assertIn(key, text)


if __name__ == "__main__":
    unittest.main()
