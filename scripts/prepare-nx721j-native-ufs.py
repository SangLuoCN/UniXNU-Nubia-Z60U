#!/usr/bin/env python3
"""Apply the audited NX721J-only delta to the official NativeUfs module.

The workflow checks out UniXNU and its NativeUfs submodule independently of
this device repository.  Keep the board delta here so CI does not depend on a
local, unpublished UniXNU commit and never silently builds a different UFS
source revision.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OFFICIAL_NATIVE_UFS_SHA256 = "24f549be5006ab5c463c67aa01ee38511b185853f878e12b4bb70830313ae9ed"
# The canonical CI output is LF.  The second digest is the same source after
# Windows checkout line-ending conversion in the local reference worktree.
PATCHED_NATIVE_UFS_SHA256 = "66197f3a34934d9bc7469d2298e816bd042b17936235c81221ffa9edadff6ec4"
PATCHED_NATIVE_UFS_WINDOWS_SHA256 = "bd3a299aa22bb9b6d89f5839bf88060bb70e49dfd5ebd9c393a143e35d9db17b"

NX721J_HEADER = """// SPDX-License-Identifier: BSD-2-Clause-Patent
// NX721J (Nubia Z60 Ultra, Qualcomm Pineapple) UFS facts.
//
// These values are read-only inputs from the NX721J live device tree.  This
// header intentionally contains no Pineapple GCC clock offsets and no SMMU
// takeover policy: neither has been qualified for XNU ownership yet.
#ifndef NATIVE_UFS_NX721J_H
#define NATIVE_UFS_NX721J_H

#define NX721J_UFS_HOST_BASE             0x01d84000ULL
#define NX721J_UFS_HOST_SIZE             0x3000ULL
#define NX721J_UFS_PHY_BASE              0x01d80000ULL
#define NX721J_UFS_PHY_SIZE              0x2000ULL
#define NX721J_PINEAPPLE_GCC_BASE        0x00100000ULL
#define NX721J_PINEAPPLE_GCC_SIZE        0x1f4200ULL
#define NX721J_APPS_SMMU_BASE            0x15000000ULL
#define NX721J_APPS_SMMU_SIZE            0x100000ULL
#define NX721J_UFS_STREAM_ID             0x60U
#define NX721J_UFS_RESET_ID              0x19U
#define NX721J_UFS_DMA_POOL_BASE         0x1000ULL
#define NX721J_UFS_DMA_POOL_SIZE         0xfffff000ULL

// The live DT has five UFS register windows.  The HCI register window is the
// only one used by the passive probe; the remaining windows are retained as
// facts so a future bring-up cannot silently collapse the DT into a
// single-host-window assumption.
#define NX721J_UFS_REG_WINDOW_COUNT      5U

// The nine clock names and the Pineapple PHY identity are part of the target
// dependency contract, not proof that XNU may enable or reset them.
#define NX721J_UFS_CLOCK_COUNT           9U
#define NX721J_UFS_PHY_COMPATIBLE        "qcom,ufs-phy-qmp-v4-pineapple"
#define NX721J_UFS_HOST_COMPATIBLE       "qcom,ufshc"
#define NX721J_PLATFORM_COMPATIBLE       "qcom,pineapple-mtp"

#endif
"""

NX721J_REQUESTED = """// `qcom,ufshc` is shared by multiple Qualcomm generations.  A target boot
// argument is required before this driver may treat it as NX721J; matching the
// generic compatible alone would route Ace5 or another Pineapple board into
// the wrong clock/PHY policy.
static bool nx721jRequested (void)
{
  char target[16] = {};
  return PE_parse_boot_argn ("native-ufs-target", target, sizeof (target)) &&
         !strcmp (target, "nx721j");
}

"""

NX721J_INSPECT = """  if (nx721jRequested ()) {
    // NX721J passive survey.  The live DT proves these physical windows and
    // the UFS stream ID, but does not yet prove that XNU may change clocks,
    // resets, PHY state or SMMU routing.  Keep this path read-only.
    OSSharedPtr<IOMemoryMap> hcMap, smmuMap;
    uintptr_t hc = mapPhys (NX721J_UFS_HOST_BASE, NX721J_UFS_HOST_SIZE, hcMap);
    uintptr_t smmu = mapPhys (NX721J_APPS_SMMU_BASE, NX721J_APPS_SMMU_SIZE, smmuMap);
    if (!hc || !smmu) {
      panic ("NATIVE_UFS NX721J inspect: map failed host=%p smmu=%p",
             (void *) hc, (void *) smmu);
    }
    panic ("NATIVE_UFS NX721J passive survey\\n"
           "host=%llx/%llx phy=%llx/%llx gcc=%llx/%llx\\n"
           "stream=%x reset=%x dma=%llx/%llx clocks=%u\\n"
           "cap=%08x ver=%08x is=%08x hcs=%08x hce=%08x\\n"
           "list=%08x:%08x db=%08x rsr=%08x\\n"
           "smmu id0=%08x id1=%08x id2=%08x\\n"
           "read-only facts; no GCC/PHY/reset/SMMU writes",
           NX721J_UFS_HOST_BASE, NX721J_UFS_HOST_SIZE,
           NX721J_UFS_PHY_BASE, NX721J_UFS_PHY_SIZE,
           NX721J_PINEAPPLE_GCC_BASE, NX721J_PINEAPPLE_GCC_SIZE,
           NX721J_UFS_STREAM_ID, NX721J_UFS_RESET_ID,
           NX721J_UFS_DMA_POOL_BASE, NX721J_UFS_DMA_POOL_SIZE,
           NX721J_UFS_CLOCK_COUNT,
           read32 (hc, 0x00), read32 (hc, 0x08), read32 (hc, 0x20),
           read32 (hc, 0x30), read32 (hc, 0x34),
           read32 (hc, 0x54), read32 (hc, 0x50), read32 (hc, 0x58), read32 (hc, 0x60),
           read32 (smmu, 0x20), read32 (smmu, 0x24), read32 (smmu, 0x28));
  }
"""

NX721J_START_GUARD = """  if (nx721jRequested () && (rootMode || probe >= 3)) {
    // The existing queue/SMMU path below is qualified for sheng/SM8550.
    // Refuse all state-changing NX721J modes until Pineapple clocks, PHY,
    // DMA and SMMU ownership have their own evidence and implementation.
    IOLog ("NativeUfs: NX721J transport is passive-only; refusing probe=%u root=%u\\n",
           probe, rootMode);
    return false;
  }
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"NativeUfs base mismatch in {label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unixnu", type=Path, required=True)
    args = parser.parse_args()

    module = args.unixnu.resolve() / "drivers" / "NativeUfs"
    source = module / "NativeUfs.cpp"
    header = module / "Nx721jUfs.h"
    if not source.is_file():
        raise SystemExit(f"missing official NativeUfs source: {source}")

    current = digest(source)
    if current in (PATCHED_NATIVE_UFS_SHA256, PATCHED_NATIVE_UFS_WINDOWS_SHA256) and header.is_file():
        print("PASS: official NativeUfs already contains the audited NX721J profile")
        return 0
    if current != OFFICIAL_NATIVE_UFS_SHA256:
        raise SystemExit(
            "refusing unreviewed NativeUfs revision: "
            f"expected {OFFICIAL_NATIVE_UFS_SHA256}, found {current}"
        )

    text = source.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "// SPDX-License-Identifier: BSD-2-Clause-Patent\n"
        "// Native sheng SM8550 UFS bring-up. Default-off: no MMIO is touched unless\n"
        "// native-ufs-probe=1 is present. This is a register probe, not a storage driver.\n",
        "// SPDX-License-Identifier: BSD-2-Clause-Patent\n"
        "// Native UFS bring-up for the qualified sheng SM8550 path plus a passive\n"
        "// NX721J fact survey. Default-off: no MMIO is touched unless an explicit probe\n"
        "// or root argument is present. NX721J remains passive-only until its transport\n"
        "// ownership is independently qualified.\n",
        "source banner",
    )
    text = replace_once(text, '#include "GccUfs.h"\n', '#include "GccUfs.h"\n#include "Nx721jUfs.h"\n', "profile include")
    contains_end = """  return false;
}

IOService *NativeUfs::probe"""
    text = replace_once(text, contains_end, """  return false;
}

""" + NX721J_REQUESTED + """IOService *NativeUfs::probe""", "target gate")
    text = replace_once(
        text,
        '    match = text && contains (text, data->getLength (), "qcom,sm8550-ufshc");',
        '    match = text && (contains (text, data->getLength (), "qcom,sm8550-ufshc") ||\n'
        '                     (nx721jRequested () && contains (text, data->getLength (), NX721J_UFS_HOST_COMPATIBLE)));',
        "OSData matching",
    )
    text = replace_once(
        text,
        '    match = text && contains (text, string->getLength (), "qcom,sm8550-ufshc");',
        '    match = text && (contains (text, string->getLength (), "qcom,sm8550-ufshc") ||\n'
        '                     (nx721jRequested () && contains (text, string->getLength (), NX721J_UFS_HOST_COMPATIBLE)));',
        "OSString matching",
    )
    text = replace_once(text, "void NativeUfs::inspect (void)\n{\n", "void NativeUfs::inspect (void)\n{\n" + NX721J_INSPECT, "passive inspection")
    text = replace_once(text, "  unsigned diagnostic = 0;\n", NX721J_START_GUARD + "  unsigned diagnostic = 0;\n", "state-change guard")

    source.write_bytes(text.encode("utf-8"))
    header.write_bytes(NX721J_HEADER.encode("utf-8"))
    if digest(source) != PATCHED_NATIVE_UFS_SHA256:
        raise SystemExit("NX721J NativeUfs patch produced an unexpected source digest")
    print("PASS: applied audited NX721J passive NativeUfs profile to official source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
