#!/usr/bin/env python3
"""Build the minimal NX721J-only symbols needed by disabled optional probes."""
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/nx721j-kernel-stubs'
OUT.mkdir(parents=True, exist_ok=True)
source = ROOT / 'package/Nx721jKernelStubs.c'
object_file = OUT / 'Nx721jKernelStubs.o'
archive = OUT / 'libNx721jKernelStubs.a'
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
(OUT / 'build-report.json').write_text(
    '{\n'
    f'  "source_sha256": "{hashlib.sha256(source.read_bytes()).hexdigest()}",\n'
    f'  "object_sha256": "{hashlib.sha256(object_file.read_bytes()).hexdigest()}",\n'
    f'  "archive_sha256": "{hashlib.sha256(archive.read_bytes()).hexdigest()}"\n'
    '}\n'
)
print(f'PASS: NX721J kernel stub archive {archive}')
