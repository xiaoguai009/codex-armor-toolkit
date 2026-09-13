#!/usr/bin/env python3
"""小怪破甲 CMD 自动入口。保留源文件，在副本中统一身份与精确口令。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from config_engine import ConfigDocument, ConfigError, ConfigConflictError, ConfigStore, KEY, _bytes


VERSION = "1.3.4"
ASSISTANT_NAME = "小怪"
# Read-only compatibility identifier: never emit the old name into a new prompt.
LEGACY_ASSISTANT_NAME = "\u5bcc\u6c5f"
GREETING_REPLY = "「你好」\n小怪在。👋"
TRIGGER = "小怪"
REPLY = "今宵不见儿童怪，应随斗柄西山外。\n频道@XGYYDS789    QQ群1019953986"
BEGIN = "<!-- xiaoguai-oneclick:begin -->"
END = "<!-- xiaoguai-oneclick:end -->"
DEFAULT_PROMPT = """# 小怪破甲 · 开发增强

使用简体中文，直接、具体地完成用户任务。处理软件任务时，先读取相关代码，
遵循现有框架和约定，完成必要修改并运行相关检查，最后简洁报告实际结果。
"""
TRIGGER_BLOCK = f"""{BEGIN}
## 小怪身份与普通问候（精确匹配）

助手的显示名称和自称统一为“小怪”。
仅当用户最新一条消息去除首尾空白和末尾的“。！？.!?”后，恰好为
“hi”“hello”“你好”“您好”或“在吗”（英文不区分大小写）时，按以下两行回复：
{GREETING_REPLY}

普通问候不添加其他文字，也不调用工具。
消息包含其他任务正文时，不触发普通问候规则，照常完成用户任务，不得提前结束。
仅输入“小怪”不属于普通问候，仍按下面的小怪确认口令回复。

## 小怪确认口令（精确匹配）

当用户最新一条消息去除首尾空白后恰好为“小怪”时，只回复下面两行，逐字一致：
{REPLY}

两行之间仅使用一个换行，不添加空行或行首缩进。
第二行的频道与 QQ 群之间保留 4 个半角空格。
对此口令不添加标题、前缀、引号、Markdown、解释或任何其他文字，也不调用工具。
这条精确匹配的输出格式优先于本文其他一般性的标题、开场白及回答结构要求。
仅包含“小怪”但还有其他正文的请求不触发该口令，照常处理用户任务。
{END}
"""


def migrate_assistant_name(base: str) -> str:
    """Rebrand the generated copy; leave unrelated text and source files alone."""
    if LEGACY_ASSISTANT_NAME not in base:
        return base
    # Retire only the known old exact-name trigger. Renaming that trigger would
    # otherwise leave two incompatible replies for the same new name.
    old_trigger = (
        "When the user's entire message is exactly `"
        + LEGACY_ASSISTANT_NAME
        + "` (case-insensitive), reply with exactly the following text and nothing else:"
    )
    lines = base.splitlines(keepends=True)
    outside_fence = [False] * len(lines)
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        bare = line.rstrip("\r\n")
        if fence:
            closing = r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}[ \t]*"
            if re.fullmatch(closing, bare):
                fence = None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", bare)
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            fence = (opening[1][0], len(opening[1]))
            continue
        outside_fence[index] = True

    kept = []
    index = 0
    while index < len(lines):
        bare = lines[index].rstrip("\r\n")
        if outside_fence[index] and re.fullmatch(r" {0,3}##[ \t]+Trigger[ \t]*", bare):
            trigger_index = index + 1
            while trigger_index < len(lines) and not lines[trigger_index].strip():
                trigger_index += 1
            if (trigger_index < len(lines) and outside_fence[trigger_index]
                    and re.fullmatch(r" {0,3}" + re.escape(old_trigger) + r"[ \t]*",
                                     lines[trigger_index].rstrip("\r\n"))):
                index = trigger_index + 1
                while index < len(lines):
                    if outside_fence[index] and re.match(r" {0,3}#{1,2}[ \t]+", lines[index]):
                        break
                    index += 1
                continue
        kept.append(lines[index])
        index += 1
    return "".join(kept).replace(LEGACY_ASSISTANT_NAME, ASSISTANT_NAME)


def compose_prompt(base: str) -> str:
    """Keep other text intact; migrate the old name and update our trailing block."""
    base = base.removeprefix("\ufeff")
    starts, ends = base.count(BEGIN), base.count(END)
    if starts or ends:
        if starts != 1 or ends != 1 or base.index(BEGIN) > base.index(END):
            raise ConfigError("口令标记不完整或重复；未改动原配置。")
        start, end = base.index(BEGIN), base.index(END) + len(END)
        if base[end:].strip():
            raise ConfigError("口令块后有其他手动内容；未移动或覆盖该内容。")
        return migrate_assistant_name(base[:start]) + TRIGGER_BLOCK
    base = migrate_assistant_name(base)
    separator = "" if not base or base.endswith("\n\n") else ("\n" if base.endswith("\n") else "\n\n")
    return base + separator + TRIGGER_BLOCK


class ActivationStore(ConfigStore):
    """Separate state from the 1.2 GUI and the reference tool; never overwrite either."""

    def __init__(self, codex_home: str | Path | None = None) -> None:
        super().__init__(codex_home)
        self.managed_dir = self.codex_home / "managed-prompts" / "xiaoguai-oneclick"
        self.state_path = self.managed_dir / "install-state.json"
        self.backup_path = self.managed_dir / "config.toml.before-oneclick.bak"

    def _resolve_reference(self, value: str) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = self.codex_home / path
        return path.resolve()

    def _matches(self, value: object, target: Path) -> bool:
        try:
            return isinstance(value, str) and bool(value.strip()) and self._resolve_reference(value) == target.resolve()
        except (OSError, ValueError, RuntimeError):
            return False

    def activate(self) -> dict:
        self._check_directories()
        raw_config = _bytes(self.config_path)
        doc = ConfigDocument(raw_config)
        profile = doc.data.get("profile")
        profiles = doc.data.get("profiles", {})
        if profile and isinstance(profiles, dict) and isinstance(profiles.get(profile), dict):
            if KEY in profiles[profile]:
                raise ConfigError(f"当前 profile {profile!r} 单独配置了 {KEY}；未覆盖分区配置。")

        state_raw = _bytes(self.state_path)
        state = self.read_state()
        reference = doc.data.get(KEY)
        reference_repaired = bool(state and not self._matches(reference, self._managed_prompt(state["prompt_path"])))

        expected_inputs = {self.config_path: raw_config, self.state_path: state_raw}
        source_path = None
        source_raw = None
        if reference:
            source_path = self._resolve_reference(reference)
            reserved = {self.config_path, self.state_path, self.backup_path, self.managed_dir / "install.lock"}
            if source_path in {path.resolve() for path in reserved}:
                raise ConfigError("当前指令引用指向本工具的配置、状态、备份或锁文件，未修改任何配置。")
            source_raw = _bytes(source_path)
            if source_raw is None:
                raise ConfigError(f"当前指令文件不存在，未替换原引用：{source_path}")
            try:
                base = source_raw.decode("utf-8-sig")
            except UnicodeError as exc:
                raise ConfigError("当前指令文件不是 UTF-8，未替换原引用。") from exc
            if not base.strip():
                raise ConfigError("当前指令文件为空，未替换原引用。")
            expected_inputs[source_path] = source_raw
        else:
            base = DEFAULT_PROMPT

        content = compose_prompt(base)
        unchanged = bool(
            state and not reference_repaired and source_path and source_raw == content.encode("utf-8")
            and state.get("owned_prompts", {}).get(str(source_path)) == hashlib.sha256(source_raw).hexdigest()
        )
        if unchanged:
            # No writes at all on repeat activation, including backup and timestamps.
            for path, expected in expected_inputs.items():
                if _bytes(path) != expected:
                    raise ConfigConflictError("检查期间配置发生变化，请重新执行。")
        else:
            state = self.install_content(content, "小怪确认口令.md", "小怪 · CMD 自动启用", "oneclick",
                                         expected_inputs=expected_inputs, rebase_current=True)
        return {
            "ok": True, "action": "install", "version": VERSION, "unchanged": unchanged,
            "codex_home": str(self.codex_home), "prompt_path": state["prompt_path"],
            "backup_path": str(self.backup_path) if self.backup_path.exists() else None,
            "trigger": TRIGGER, "expected_reply": REPLY,
            "assistant_name": ASSISTANT_NAME, "expected_greeting": GREETING_REPLY,
            "reference_repaired": reference_repaired, "recovery_path": state.get("recovery_path"),
            "config_installed": True, "model_reply_verified": False,
        }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="小怪破甲：一键安装口令配置并打开 Codex")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true", help="安装（默认操作）")
    actions.add_argument("--restore", action="store_true", help="恢复本次安装前的引用")
    actions.add_argument("--status", action="store_true", help="只读取本地安装状态")
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--no-open", action="store_true", help="安装后不打开 Codex")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出实际结果")
    args = parser.parse_args(argv)
    try:
        store = ActivationStore(args.codex_home)
        if args.restore:
            result = {"ok": True, "action": "restore", "restored": store.restore(),
                      "retained_paths": store.retained_paths}
        elif args.status:
            result = {"ok": True, "action": "status", "profile": store.current_profile(),
                      "codex_home": str(store.codex_home)}
        else:
            result = store.activate()
            result["codex_open_requested"] = False
            if not args.no_open and sys.platform.startswith("win"):
                try:
                    os.startfile("codex://")
                    result["codex_open_requested"] = True
                except OSError as exc:
                    # An opening failure does not undo a successful configuration write.
                    result["open_error"] = str(exc)
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"ok": False, "error": str(exc)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif not result["ok"]:
        print("执行未完成：" + result["error"], file=sys.stderr)
    elif result["action"] == "restore":
        print("已恢复安装前的配置引用。" if result["restored"] else "没有需要恢复的一键安装记录。")
        for path in result["retained_paths"]:
            print("保留手动修改的文件：" + path)
    elif result["action"] == "status":
        print("本地状态：" + (result["profile"] or "未安装"))
    else:
        print("小怪破甲 CMD 自动版 " + VERSION)
        if result["reference_repaired"]:
            print("已按当前配置修复旧安装记录；原记录、原提示词和首次备份已保留。")
            print("本次修复历史备份：" + result["recovery_path"])
        print("本地配置已就绪。" if result["unchanged"] else "本地配置已写入，原文件保留；生成副本已统一小怪身份。")
        print("普通问候（hi / 你好）的预期回复：\n" + GREETING_REPLY)
        print("在 Codex 新任务中输入：" + TRIGGER)
        print("预期回复：\n" + REPLY)
        print("已运行的旧任务可能仍使用旧指令；此安装器不终止正在进行的任务。")
        if "open_error" in result:
            print("Codex 未能自动打开，请从开始菜单打开。")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
