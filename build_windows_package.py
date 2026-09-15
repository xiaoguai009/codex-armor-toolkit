#!/usr/bin/env python3
"""Package only explicitly listed public Windows release files, never a user home."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION = "1.4.0"
PACKAGE_NAME = f"xiaoguai-oneclick-v{VERSION}.zip"
PREFIX = "小怪破甲-Windows版/"
FILES = (
    "README.txt", "验证记录.txt", "build-requirements.txt", "build_windows_package.py",
    "config_engine.py", "oneclick.py", "task_support.py", "privacy_check.py",
    "启动小怪破甲.cmd", "卸载小怪破甲.cmd", "准备ACE资料.cmd", "检查提示词暴露.cmd",
    "小怪破甲安装器.exe", "免责声明.txt", "直接点击启动小怪破甲.txt",
    "docs/ACE-AND-PRIVACY.md", "tests/test_config_engine.py", "tests/test_oneclick.py",
    "tests/test_reference_repair.py", "tests/test_privacy_check.py", "tests/test_windows_package.py",
)


def snapshot(root: Path) -> dict[str, bytes]:
    root = root.resolve(strict=True)
    files = {}
    for name in FILES:
        path = root / name
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Missing or linked package source: " + name) from exc
        if path.is_symlink() or resolved != path or not resolved.is_relative_to(root) or not path.is_file():
            raise ValueError("Missing or linked package source: " + name)
        raw = path.read_bytes()
        if name.endswith(".exe"):
            if not raw.startswith(b"MZ"):
                raise ValueError("Windows executable header missing")
        else:
            raw.decode("utf-8")
            if raw.startswith(b"\xef\xbb\xbf"):
                raise ValueError("Package text must not contain a UTF-8 BOM: " + name)
            if name.endswith(".py"):
                compile(raw, name, "exec")
            if name.endswith(".cmd") and not raw.lower().startswith(b"@echo off\r\n"):
                raise ValueError("CMD source must start with @echo off and CRLF: " + name)
        files[name] = raw
    return files


def verify_archive(path: Path, files: dict[str, bytes]) -> dict:
    with zipfile.ZipFile(path) as archive:
        expected = {PREFIX + name for name in files}
        if set(archive.namelist()) != expected or len(archive.infolist()) != len(expected):
            raise ValueError("Unexpected or duplicated package members")
        if archive.testzip():
            raise ValueError("ZIP CRC mismatch")
        for name, raw in files.items():
            if archive.read(PREFIX + name) != raw:
                raise ValueError("Package bytes differ: " + name)
    return {
        "version": VERSION, "package": str(path.resolve()), "file_count": len(files),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "all_package_bytes_verified": True,
    }


def build(root: Path, output: Path, *, force: bool = False) -> dict:
    if output.name != PACKAGE_NAME:
        raise ValueError("Use the current Windows package filename: " + PACKAGE_NAME)
    if not force and (output.exists() or output.is_symlink()):
        raise FileExistsError(output)
    files = snapshot(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".xiaoguai-win-", suffix=".zip", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, raw in files.items():
                info = zipfile.ZipInfo(PREFIX + name)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, raw, compresslevel=9)
        verify_archive(temporary, files)
        if force:
            os.replace(temporary, output)
        else:
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
    parser = argparse.ArgumentParser(description="Build a Windows ZIP using the public-file allowlist")
    parser.add_argument("--output", type=Path, default=ROOT / "downloads" / PACKAGE_NAME)
    parser.add_argument("--force", action="store_true", help="Replace only this version's Windows ZIP")
    parser.add_argument("--check", action="store_true", help="Verify package bytes against current sources")
    args = parser.parse_args(argv)
    try:
        result = verify_archive(args.output, snapshot(ROOT)) if args.check else build(ROOT, args.output, force=args.force)
    except SyntaxError:
        print(json.dumps({"ok": False, "error": "Package Python syntax validation failed; no source text printed."}), file=sys.stderr)
        return 2
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(dict(ok=True, **result), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
