#!/usr/bin/env python3
"""Codex instruction-file configuration, shared by the GUI and install.ps1.

Python 3.11+; standard library only. No Codex process is stopped or patched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import tomllib
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


KEY = "model_instructions_file"
BOM = b"\xef\xbb\xbf"


class ConfigError(ValueError):
    pass


class ConfigConflictError(ConfigError):
    pass


class _Lexer:
    """Track TOML strings/containers, so table-like text in strings is ignored."""

    def __init__(self) -> None:
        self.quote = ""
        self.depth = 0

    @property
    def idle(self) -> bool:
        return not self.quote and self.depth == 0

    def feed(self, line: str) -> None:
        i = 0
        while i < len(line):
            ch = line[i]
            if self.quote:
                if self.quote.startswith('"') and ch == "\\":
                    i += 2
                    continue
                if line.startswith(self.quote, i):
                    size = len(self.quote)
                    if size == 3:
                        while i + size < len(line) and line[i + size] == ch:
                            size += 1
                    self.quote = ""
                    i += size
                    continue
                i += 1
                continue
            if ch == "#":
                break
            if ch in "\"'":
                self.quote = ch * 3 if line.startswith(ch * 3, i) else ch
                i += len(self.quote)
                continue
            if ch in "[{":
                self.depth += 1
            elif ch in "]}":
                self.depth -= 1
            i += 1


def _assignment_key(statement: str) -> str | None:
    quote = ""
    i = 0
    while i < len(statement):
        ch = statement[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return None
        elif ch == "=":
            try:
                parsed = tomllib.loads(statement[:i] + " = 0")
            except tomllib.TOMLDecodeError:
                return None
            if len(parsed) == 1:
                key, value = next(iter(parsed.items()))
                return key if value == 0 else None
            return None
        i += 1
    return None


def _root_span(text: str) -> tuple[int, int] | None:
    lexer = _Lexer()
    offset = start = 0
    for line in text.splitlines(keepends=True):
        if lexer.idle:
            if line.lstrip(" \t").startswith("["):
                break
            start = offset
        lexer.feed(line)
        offset += len(line)
        if lexer.idle and _assignment_key(text[start:offset]) == KEY:
            return start, offset
    return None


class ConfigDocument:
    def __init__(self, raw: bytes | None) -> None:
        self.raw = raw
        self.bom = bool(raw and raw.startswith(BOM))
        try:
            self.text = (raw or b"").decode("utf-8-sig")
            self.data = tomllib.loads(self.text)
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"config.toml 不是有效的 UTF-8 TOML：{exc}") from exc
        if KEY in self.data and not isinstance(self.data[KEY], str):
            raise ConfigError(f"顶层 {KEY} 必须是字符串，未修改配置。")
        self.span = _root_span(self.text)
        if KEY in self.data and self.span is None:
            raise ConfigError(f"无法定位顶层 {KEY}，未修改配置。")

    @property
    def line(self) -> str | None:
        return self.text[slice(*self.span)] if self.span else None

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.text else "\n"

    def encode(self, text: str) -> bytes:
        return (BOM if self.bom else b"") + text.encode("utf-8")

    def replace(self, replacement: str) -> bytes:
        if self.span:
            start, end = self.span
            return self.encode(self.text[:start] + replacement + self.text[end:])
        return self.encode(replacement + self.text)

    def installed(self, target: Path) -> bytes:
        if self.line is None:
            ending = self.newline
        elif self.line.endswith("\r\n"):
            ending = "\r\n"
        elif self.line.endswith("\n"):
            ending = "\n"
        else:
            ending = ""
        value = json.dumps(target.as_posix(), ensure_ascii=False)
        return self.replace(f"{KEY} = {value}{ending}")


def _bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _atomic_write(path: Path, data: bytes | None) -> None:
    if _is_link(path):
        raise ConfigError(f"不覆盖符号链接或目录联接：{path}")
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".xiaoguai-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


def _transaction(updates: list[tuple[Path, bytes | None]], expected: dict[Path, bytes | None]) -> None:
    snapshots = {path: expected[path] if path in expected else _bytes(path) for path, _ in updates}
    written = dict(updates)
    changed: list[Path] = []
    try:
        for path, data in updates:
            if _bytes(path) != snapshots[path]:
                raise ConfigConflictError(f"文件在操作期间被更改，未覆盖新内容：{path}")
            _atomic_write(path, data)
            changed.append(path)
    except Exception as original:
        failures = []
        for path in reversed(changed):
            try:
                if _bytes(path) != written[path]:
                    failures.append(f"{path}: 回滚前出现其他修改，已保留新内容")
                    continue
                _atomic_write(path, snapshots[path])
            except (OSError, ConfigError) as exc:
                failures.append(f"{path}: {exc}")
        if failures:
            raise ConfigError("操作失败，部分回滚未完成：" + "; ".join(failures)) from original
        raise


class ConfigStore:
    def __init__(self, codex_home: str | Path | None = None) -> None:
        home = codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex"
        self.codex_home = Path(home).expanduser().resolve()
        self.config_path = self.codex_home / "config.toml"
        self.managed_dir = self.codex_home / "managed-prompts" / "xiaoguai"
        self.state_path = self.managed_dir / "install-state.json"
        self.backup_path = self.managed_dir / "config.toml.before-xiaoguai.bak"
        self.retained_paths: list[str] = []

    def _check_directories(self) -> None:
        for path in (self.managed_dir.parent, self.managed_dir, self.config_path, self.state_path, self.backup_path):
            if _is_link(path):
                raise ConfigError(f"不修改符号链接或目录联接：{path}")

    def _managed_prompt(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute() or path.parent.resolve() != self.managed_dir.resolve() or path.suffix.lower() != ".md" or _is_link(path):
            raise ConfigError("安装状态中的配置档路径不属于本工具目录，未操作该文件。")
        return path

    def read_state(self) -> dict | None:
        self._check_directories()
        raw = _bytes(self.state_path)
        if raw is None:
            return None
        try:
            state = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(state, dict) or state.get("version") not in (1, 2):
                raise ValueError("版本无效")
            if not isinstance(state.get("config_existed"), bool) or not isinstance(state.get("had_line"), bool):
                raise ValueError("恢复基线不完整")
            if state["had_line"] and not isinstance(state.get("previous_line"), str):
                raise ValueError("原配置行缺失")
            if not isinstance(state.get("prompt_path"), str):
                raise ValueError("配置档路径缺失")
            self._managed_prompt(state["prompt_path"])
            owned = state.get("owned_prompts", {})
            if not isinstance(owned, dict):
                raise ValueError("文件记录无效")
            for path, digest in owned.items():
                self._managed_prompt(path)
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise ValueError("文件校验值无效")
            return state
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ConfigError(f"安装状态无法读取，原配置和备份均已保留：{exc}") from exc

    @contextmanager
    def _lock(self):
        self._check_directories()
        self.managed_dir.mkdir(parents=True, exist_ok=True)
        lock = self.managed_dir / "install.lock"
        try:
            handle = lock.open("xb")
        except FileExistsError as exc:
            raise ConfigConflictError("另一个安装/恢复操作正在运行；请在它结束后重试。") from exc
        try:
            handle.write(str(os.getpid()).encode("ascii"))
            handle.close()
            yield
        finally:
            handle.close()
            lock.unlink(missing_ok=True)

    @staticmethod
    def _matches(value: object, target: Path) -> bool:
        try:
            return isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve() == target.resolve()
        except (OSError, ValueError):
            return False

    def current_profile(self) -> str | None:
        state = self.read_state()
        doc = ConfigDocument(_bytes(self.config_path))
        if state:
            target = self._managed_prompt(state["prompt_path"])
            if self._matches(doc.data.get(KEY), target) and target.is_file():
                return str(state.get("profile_title") or "自定义配置")
            return None
        value = doc.data.get(KEY)
        if isinstance(value, str):
            path = Path(value)
            if path.is_absolute() and path.parent.resolve() == self.managed_dir.resolve():
                return "已配置（未登记）"
        return None

    def install_content(self, content: str, filename: str, title: str, key: str = "custom", *,
                        expected_inputs: dict[Path, bytes | None] | None = None) -> dict:
        content = content.removeprefix("\ufeff")
        if not content.strip():
            raise ConfigError("配置内容不能为空。")
        if Path(filename).name != filename or not filename.lower().endswith(".md"):
            raise ConfigError("配置档必须使用不含目录的 .md 文件名。")
        with self._lock():
            for path, expected_raw in (expected_inputs or {}).items():
                if _bytes(path) != expected_raw:
                    raise ConfigConflictError(f"配置来源在安装前发生变化，未覆盖：{path}")
            state_raw = _bytes(self.state_path)
            state = self.read_state()
            doc = ConfigDocument(_bytes(self.config_path))
            if state:
                target = self._managed_prompt(state["prompt_path"])
                if not self._matches(doc.data.get(KEY), target):
                    raise ConfigConflictError("当前指令引用已被其他操作更改，未覆盖；原备份仍保留。")
                target_raw = _bytes(target)
                digest = state.get("owned_prompts", {}).get(str(target))
                if target_raw is not None and digest != _sha(target_raw):
                    # A switched profile must not erase manual edits to the old file.
                    target = self._unused_prompt_path()
                    target_raw = None
            else:
                if self.backup_path.exists():
                    raise ConfigConflictError("发现没有安装状态的旧备份，未覆盖该备份。")
                target = self._unused_prompt_path()
                target_raw = None
                state = {
                    "version": 2,
                    "installed_at": _stamp(),
                    "config_existed": doc.raw is not None,
                    "had_line": doc.line is not None,
                    "previous_line": doc.line,
                }
            raw_prompt = content.encode("utf-8")
            owned = dict(state.get("owned_prompts", {}))
            owned[str(target)] = _sha(raw_prompt)
            state = dict(state, version=2, profile_title=title, profile_key=key, source_filename=filename,
                         prompt_path=str(target), owned_prompts=owned, updated_at=_stamp())
            raw_state = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            installed = doc.installed(target)
            ConfigDocument(installed)
            updates = []
            expected = {self.config_path: doc.raw, self.state_path: state_raw, target: target_raw}
            if state_raw is None and doc.raw is not None:
                updates.append((self.backup_path, doc.raw))
                expected[self.backup_path] = None
            updates.extend([(target, raw_prompt), (self.state_path, raw_state), (self.config_path, installed)])
            for path, expected_raw in (expected_inputs or {}).items():
                if _bytes(path) != expected_raw:
                    raise ConfigConflictError(f"配置来源在安装期间发生变化，未覆盖：{path}")
            _transaction(updates, expected)
            return state

    def _unused_prompt_path(self) -> Path:
        target = self.managed_dir / "active.md"
        while target.exists() or _is_link(target):
            target = self.managed_dir / f"active-{uuid.uuid4().hex[:12]}.md"
        return target

    def restore(self) -> bool:
        self.retained_paths = []
        if not self.state_path.exists():
            return False
        with self._lock():
            state_raw = _bytes(self.state_path)
            state = self.read_state()
            if state is None:
                return False
            target = self._managed_prompt(state["prompt_path"])
            doc = ConfigDocument(_bytes(self.config_path))
            if not self._matches(doc.data.get(KEY), target):
                raise ConfigConflictError("当前指令引用已被其他操作更改，未覆盖；原备份仍保留。")
            restored = doc.replace(state["previous_line"] if state["had_line"] else "")
            ConfigDocument(restored)
            data = None if not state["config_existed"] and restored == b"" else restored
            updates: list[tuple[Path, bytes | None]] = [(self.config_path, data)]
            expected = {self.config_path: doc.raw, self.state_path: state_raw}
            owned = state.get("owned_prompts", {})
            paths = set(owned) | {str(target)}
            for value in sorted(paths):
                path = self._managed_prompt(value)
                raw = _bytes(path)
                if raw is None:
                    continue
                if owned.get(value) == _sha(raw):
                    updates.append((path, None))
                    expected[path] = raw
                else:
                    self.retained_paths.append(str(path))
            updates.extend([(self.state_path, None), (self.backup_path, None)])
            _transaction(updates, expected)
        for directory in (self.managed_dir, self.managed_dir.parent):
            try:
                directory.rmdir()  # Empty tool directories only; never recursive.
            except OSError:
                pass
        return True


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小怪破甲本地配置安装器")
    parser.add_argument("--codex-home")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--source-prompt", type=Path)
    action.add_argument("--uninstall", action="store_true")
    action.add_argument("--status", action="store_true")
    parser.add_argument("--profile-title")
    parser.add_argument("--profile-key", default="custom")
    args = parser.parse_args(argv)
    try:
        store = ConfigStore(args.codex_home)
        result = {"ok": True, "codex_home": str(store.codex_home)}
        if args.uninstall:
            result.update(action="uninstall", restored=store.restore(), retained_paths=store.retained_paths)
        elif args.status:
            result.update(action="status", profile=store.current_profile())
        else:
            content = args.source_prompt.read_text(encoding="utf-8-sig")
            state = store.install_content(content, args.source_prompt.name, args.profile_title or args.source_prompt.stem, args.profile_key)
            result.update(action="install", profile=state["profile_title"], prompt_path=state["prompt_path"])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
