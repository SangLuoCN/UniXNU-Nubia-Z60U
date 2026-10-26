# UniXNU-Nubia-Z60U

NX721J device repository for the ZTE Nubia Z60 Ultra (Qualcomm Pineapple).
Generic XNU, DarwinBoot, and the UniXNU build system remain in the official UniXNU tree.

- [UniXNU documentation](https://unixnu.com)
- [Device repository guide](https://unixnu.com/porting/)
- [Build guide](https://unixnu.com/building)
- UEFI firmware: [UEFI-Nubia-Z60U](https://github.com/SangLuoCN/UEFI-Nubia-Z60U)

## Current stage

This repository is at XNU first-entry diagnostics. The defconfig enables the generic ARM device-tree platform, CPU, and architectural timer, while disabling NativeUfs, other storage backends, root discovery, and peripheral drivers. A separate payload workflow patches only a copy of the kernel to report progress through XNU entry and the MMU transition.

The known UEFI v21 path reaches the UniXNU menu and DarwinBoot kernel handoff. The green DarwinBoot bar does not prove XNU completed initialization. The new diagnostic has not yet been tested on the NX721J; no storage, root filesystem, or iOS userspace boot is claimed.

The kernel workflow uses the iPad7,1 / iPadOS 17.7.11 kernelcache as the UniXNU/Ace5 prelink ABI reference. It is not an NX721J driver or the target userspace. The iPhone X / iOS 16.7.16 userspace is a separate later-stage input.

## Build

From the official UniXNU checkout, with this repository alongside it as `../UniXNU-Z60U`:

```sh
./unixnu defconfig nx721j_probe_defconfig -D ../UniXNU-Z60U
./unixnu fetch xnu libplatform libdispatch AvailabilityVersions libpthread corecrypto-2023 -D ../UniXNU-Z60U
./unixnu build kernel -D ../UniXNU-Z60U
```

GitHub Actions builds only the kernel. A separate workflow consumes its successful artifact to generate the NX721J ADT and diagnostic FAT payload. Inspect the artifacts before using `fastboot boot`; neither workflow flashes.

## Hardware boundary

NX721J clock, reset, memory, SMMU, DMA, and storage behavior requires NX721J evidence. The sheng NativeUfs implementation and Ace5 Giulia probe are references only; their target-specific transport code and hardware values are not used by this first-entry configuration.

No UFS writes, userdata image, GPT changes, or permanent firmware changes are part of this stage. Preserve Android and partition backups; do not use `fastboot flash` for this bring-up stage.

## License

BSD-2-Clause-Patent. See [LICENSE](LICENSE).
