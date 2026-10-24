#!/usr/bin/env python3
"""Host tests for the NX721J payload argument boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).with_name("build-nx721j-payload.py")
SPEC = importlib.util.spec_from_file_location("nx721j_payload", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Nx721jPayloadValidationTests(unittest.TestCase):
    def assert_rejected(self, arguments: list[str]) -> None:
        with self.assertRaises(SystemExit):
            MODULE.validate_arguments(arguments)

    def test_passive_probe_is_the_only_current_ufs_mode(self) -> None:
        line = MODULE.validate_arguments([
            "native-ufs-target=nx721j",
            "native-ufs-probe=2",
        ])
        self.assertEqual(line, "native-ufs-target=nx721j native-ufs-probe=2")

    def test_root_transport_is_rejected(self) -> None:
        self.assert_rejected(["native-ufs-root=1"])

    def test_probe_requires_explicit_nx721j_target(self) -> None:
        self.assert_rejected(["native-ufs-probe=2"])
        self.assert_rejected([
            "native-ufs-target=ace5",
            "native-ufs-probe=2",
        ])

    def test_only_probe_mode_two_is_accepted(self) -> None:
        self.assert_rejected([
            "native-ufs-target=nx721j",
            "native-ufs-probe=1",
        ])
        self.assert_rejected([
            "native-ufs-target=nx721j",
            "native-ufs-probe=3",
        ])


if __name__ == "__main__":
    unittest.main()
