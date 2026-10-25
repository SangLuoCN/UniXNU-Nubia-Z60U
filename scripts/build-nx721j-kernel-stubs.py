#!/usr/bin/env python3
"""Build the minimal NX721J-only symbols needed by disabled optional probes."""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def resolve_source(root):
    # Device repositories stage package/ as kits/<board.kit> in the build tree.
    candidates = (
        root / 'package/Nx721jKernelStubs.c',
        root / 'kits/nx721j/Nx721jKernelStubs.c',
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit('NX721J stub source not found in package/ or kits/nx721j/')


def main():
    out = ROOT / 'build/nx721j-kernel-stubs'
    out.mkdir(parents=True, exist_ok=True)
    source = resolve_source(ROOT)
    object_file = out / 'Nx721jKernelStubs.o'
    archive = out / 'libNx721jKernelStubs.a'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    command = [
        'xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk,
        '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
        '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
        '-Wall', '-Wextra', '-Werror', '-c', str(source), '-o', str(object_file),
    ]
    subprocess.run(command, check=True)
    symbols = subprocess.check_output(['xcrun', 'nm', '-gU', str(object_file)], text=True)
    if '_native_legacy_display_probe' not in symbols:
        raise SystemExit('NX721J stub object does not export native_legacy_display_probe')
    archive.unlink(missing_ok=True)
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(object_file)], check=True)
    (out / 'build-report.json').write_text(
        '{\n'
        f'  "source_sha256": "{hashlib.sha256(source.read_bytes()).hexdigest()}",\n'
        f'  "object_sha256": "{hashlib.sha256(object_file.read_bytes()).hexdigest()}",\n'
        f'  "archive_sha256": "{hashlib.sha256(archive.read_bytes()).hexdigest()}"\n'
        '}\n'
    )
    print(f'PASS: NX721J kernel stub archive {archive}')


if __name__ == '__main__':
    main()
