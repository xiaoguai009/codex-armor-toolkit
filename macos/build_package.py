#!/usr/bin/env python3
"""Build the separate macOS ZIP without altering any Windows release files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITION_VERSION = "1.3.4-mac.1"
PACKAGE_NAME = f"xiaoguai-oneclick-v{EDITION_VERSION}.zip"
PREFIX = "小怪破甲-Mac版/"
# Explicit allow-list: never package a user configuration, cache, runtime, or log.
FILES = {
    "oneclick.py": "oneclick.py",
    "config_engine.py": "config_engine.py",
    "启动小怪破甲.command": "启动小怪破甲.command",
    "卸载小怪破甲.command": "卸载小怪破甲.command",
    "查看小怪状态.command": "查看小怪状态.command",
    "macos/run.py": "macos/run.py",
    "macos/launch.sh": "macos/launch.sh",
    "macos/bootstrap-python.sh": "macos/bootstrap-python.sh",
    "macos/runtime-pins.sh": "macos/runtime-pins.sh",
    "macos/publish-runtime.py": "macos/publish-runtime.py",
    "macos/README.md": "README.md",
    "macos/验证记录.txt": "验证记录.txt",
    "macos/RUNTIME.md": "macos/RUNTIME.md",
    "tests/test_macos_entry.py": "tests/test_macos_entry.py",
    "tests/test_macos_shell.py": "tests/test_macos_shell.py",
    "tests/test_macos_bootstrap.py": "tests/test_macos_bootstrap.py",
}


def file_mode(name: str) -> int:
    return 0o755 if name.endswith((".command", ".sh")) else 0o644


def snapshot(root: Path) -> dict[str, bytes]:
    root = root.resolve(strict=True)
    files = {}
    for source, destination in FILES.items():
        path = root / source
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"Missing or linked package source: {source}") from exc
        # Reject linked parent directories as well as linked files. In
        # particular, a Windows junction must not import files from elsewhere.
        if (path.is_symlink() or resolved != path
                or not resolved.is_relative_to(root) or not path.is_file()):
            raise ValueError(f"Missing or linked package source: {source}")
        raw = path.read_bytes()
        raw.decode("utf-8")
        if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError(f"Mac source must be UTF-8 without BOM and use LF: {source}")
        if source.endswith(".py"):
            compile(raw, source, "exec")
        if destination.endswith((".command", ".sh")) and not raw.startswith(b"#!/bin/bash\n"):
            raise ValueError(f"Missing Bash shebang: {source}")
        files[destination] = raw
    return files


def verify_archive(path: Path, files: dict[str, bytes]) -> dict:
    with zipfile.ZipFile(path) as archive:
        expected = {PREFIX + name for name in files}
        if set(archive.namelist()) != expected or len(archive.infolist()) != len(expected):
            raise ValueError("Unexpected or duplicated package members")
        bad = archive.testzip()
        if bad:
            raise ValueError("ZIP CRC mismatch: " + bad)
        for name, raw in files.items():
            info = archive.getinfo(PREFIX + name)
            mode = info.external_attr >> 16
            if archive.read(info) != raw:
                raise ValueError("Package bytes differ: " + name)
            if info.create_system != 3 or not stat.S_ISREG(mode) or stat.S_IMODE(mode) != file_mode(name):
                raise ValueError("Incorrect Unix mode: " + name)
            if name.lower().endswith((".exe", ".cmd")):
                raise ValueError("Windows artifact in Mac-only package")
    return {
        "edition_version": EDITION_VERSION,
        "package": str(path.resolve()),
        "file_count": len(files),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "unix_executable_bits_verified": True,
        "all_package_bytes_verified": True,
    }


def build(root: Path, output: Path, *, force: bool = False) -> dict:
    if output.name != PACKAGE_NAME:
        raise ValueError("Use the separate Mac package filename: " + PACKAGE_NAME)
    if not force and (output.exists() or output.is_symlink()):
        raise FileExistsError(output)
    files = snapshot(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".xiaoguai-mac-", suffix=".zip", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, raw in files.items():
                source = next(source for source, destination in FILES.items() if destination == name)
                modified = time.localtime((root / source).stat().st_mtime)[:6]
                info = zipfile.ZipInfo(PREFIX + name, modified)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | file_mode(name)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw, compresslevel=9)
        verify_archive(temporary, files)
        if force:
            os.replace(temporary, output)
        else:
            # Both paths are in the same directory. Linking the completed ZIP
            # publishes it atomically and fails if ANY destination exists,
            # including a symlink or a file created after the initial check.
            os.link(temporary, output)
            temporary.unlink()
        temporary = None
        return verify_archive(output, files)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build the separate macOS ZIP with Unix executable modes")
    parser.add_argument("--output", type=Path, default=ROOT / "downloads" / PACKAGE_NAME)
    parser.add_argument("--force", action="store_true", help="Replace only this version's Mac ZIP")
    parser.add_argument("--check", action="store_true", help="Verify an existing ZIP against current sources")
    args = parser.parse_args(argv)
    try:
        if args.check:
            result = verify_archive(args.output, snapshot(ROOT))
        else:
            result = build(ROOT, args.output, force=args.force)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(dict(ok=True, **result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
