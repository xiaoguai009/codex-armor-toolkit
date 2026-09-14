#!/usr/bin/env python3
"""Atomically publish a prepared macOS runtime without replacing any target."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

RENAME_EXCL = 0x00000004  # Darwin sys/stdio.h: fail if destination already exists.


def publish(source: Path, destination: Path) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("运行时提交只适用于 macOS。")
    if not source.is_absolute() or not destination.is_absolute():
        raise ValueError("运行时提交路径必须是绝对路径。")
    cache = destination.parent
    if source.name != "tree" or source.parent.parent != cache:
        raise ValueError("运行时临时目录不在目标缓存内。")
    if not source.parent.name.startswith(".prepare-" + destination.name + "."):
        raise ValueError("运行时临时目录与目标版本不匹配。")
    for path in (cache, source.parent, source):
        if path.is_symlink() or not path.is_dir() or path.resolve() != path:
            raise ValueError("运行时提交路径不是普通的独立目录。")
    # A pre-check plus mv/os.rename is not sufficient: a newly created directory
    # or symlink could redirect publication. Darwin performs no-replace atomically.
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    rename_exclusive = library.renamex_np
    rename_exclusive.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename_exclusive.restype = ctypes.c_int
    if rename_exclusive(os.fsencode(source), os.fsencode(destination), RENAME_EXCL) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) != 2:
            raise ValueError("需要指定临时运行时目录和最终目录。")
        publish(Path(arguments[0]), Path(arguments[1]))
    except (OSError, ValueError, RuntimeError, AttributeError) as exc:
        print("运行时原子提交失败：" + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
