#!/usr/bin/env python3
"""Check that the NX721J probe defconfig has no sheng/Ace5 board options."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "nx721j_probe_defconfig"
STUB_BUILDER = ROOT / "scripts" / "build-nx721j-kernel-stubs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "macos-kernel.yml"
PINNED_UNIXNU = "d1559e69a1c181e68ecfe70a721bc0a436caf2e7"
FORBIDDEN = re.compile(r"(?:SHENG|SWEET|ACE5|GIULIA|SM8550|NOVATEK|ADRENO)", re.IGNORECASE)

SPEC = importlib.util.spec_from_file_location("nx721j_kernel_stubs", STUB_BUILDER)
STUB_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STUB_MODULE)

PATCHER = ROOT / "scripts" / "patch-xnu-entry-probe.py"
PATCHER_SPEC = importlib.util.spec_from_file_location("nx721j_entry_probe", PATCHER)
PATCHER_MODULE = importlib.util.module_from_spec(PATCHER_SPEC)
PATCHER_SPEC.loader.exec_module(PATCHER_MODULE)


class Nx721jDefconfigTests(unittest.TestCase):
    def test_file_is_present_and_well_formed(self) -> None:
        self.assertTrue(CONFIG.is_file())
        for number, line in enumerate(CONFIG.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#") or not line.strip():
                continue
            self.assertRegex(line, r"^CONFIG_[A-Z0-9_]+=(?:y|n|[0-9]+|\"[^\"]*\")$", f"line {number}")

    def test_first_entry_has_only_generic_required_switches(self) -> None:
        text = CONFIG.read_text(encoding="utf-8")
        enabled = "\n".join(
            line for line in text.splitlines()
            if line.startswith("CONFIG_") and line.endswith("=y")
        )
        self.assertNotRegex(enabled, FORBIDDEN)
        for key in (
            "CONFIG_XNU_BUILD_ARCHIVES=y",
            "CONFIG_XNU_SOURCE_CORECRYPTO14=y",
            "CONFIG_XNU_SOURCE_PTHREAD=y",
            "CONFIG_XNU_NATIVE_PAN=y",
            "CONFIG_XNU_ARM_DT_PLATFORM=y",
            "CONFIG_XNU_ARMCPU=y",
            "CONFIG_XNU_NATIVE_ARCH_TIMER=y",
            "CONFIG_XNU_NATIVE_UFS=n",
            'CONFIG_XNU_EXTRA_LD_ARCHIVES="{tree}/build/nx721j-kernel-stubs/libNx721jKernelStubs.a"',
            "CONFIG_XNU_NATIVE_VIRTIO_BLOCK=n",
            "CONFIG_XNU_NATIVE_RAM_BLOCK=n",
            "CONFIG_XNU_OWNER_ROOT_AUDIT=n",
            "CONFIG_XNU_BOOT_PROGRESS=n",
            "CONFIG_XNU_NATIVE_MOBILE_DISPLAY=n",
            "CONFIG_XNU_NATIVE_LEGACY_DISPLAY=n",
            "CONFIG_XNU_NATIVE_ADRENO=n",
            "CONFIG_XNU_ARMVIRT_PLATFORM=n",
        ):
            self.assertIn(key, text)

    def test_first_entry_does_not_link_native_ufs_archive(self) -> None:
        import tomllib

        board = tomllib.loads((ROOT / "board.toml").read_text(encoding="utf-8"))
        self.assertNotIn("build-arm-driver.py NativeUfs", board["kernel"]["archives"])

    def test_kernel_stub_builder_resolves_local_and_staged_package_layouts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_source = root / "package" / "Nx721jKernelStubs.c"
            local_source.parent.mkdir()
            local_source.touch()
            self.assertEqual(STUB_MODULE.resolve_source(root), local_source)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged_source = root / "kits" / "nx721j" / "Nx721jKernelStubs.c"
            staged_source.parent.mkdir(parents=True)
            staged_source.touch()
            self.assertEqual(STUB_MODULE.resolve_source(root), staged_source)

    def test_panic_screen_font_resolves_uefi_source_or_bundled_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "package"
            bundled.mkdir()
            (bundled / "Font.h").touch()
            self.assertEqual(PATCHER_MODULE.resolve_font_dir(root), bundled)

            uefi_font = root / "uefi" / "Silicon/Silicium/SiliciumPkg/Library/FrameBufferSerialPortLib"
            uefi_font.mkdir(parents=True)
            (uefi_font / "Font.h").touch()
            self.assertEqual(PATCHER_MODULE.resolve_font_dir(root, root / "uefi"), uefi_font)

    def test_workflow_uses_pinned_official_xnu_without_native_ufs_mutation(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count(PINNED_UNIXNU), 2)
        self.assertNotIn("unixnu_ref || 'main'", workflow)
        self.assertNotIn("prepare-nx721j-native-ufs.py", workflow)
        self.assertNotIn("IOStorageFamily", workflow)

    def test_payload_workflow_continues_without_reset_and_passes_no_ufs_args(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "macos-nx721j-payload.yml").read_text(encoding="utf-8")
        self.assertIn("cp \"$KERNEL_PATH\" out/nx721j/kernel.entry-probe.macho", workflow)
        self.assertIn("scripts/patch-xnu-entry-probe.py", workflow)
        self.assertIn("--panic-screen", workflow)
        self.assertIn("--no-reset", workflow)
        self.assertNotIn("--reset-delay", workflow)
        self.assertNotIn("native-ufs-target=nx721j", workflow)
        self.assertNotIn("native-ufs-probe=2", workflow)
        self.assertNotIn("native-ufs-root=1", workflow)


if __name__ == "__main__":
    unittest.main()
