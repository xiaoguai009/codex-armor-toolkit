#!/usr/bin/env python3
"""小怪破甲 CMD 自动入口。保留当前指令，只追加精确口令；无 GUI 依赖。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from config_engine import ConfigDocument, ConfigError, ConfigConflictError, ConfigStore, KEY, _bytes


VERSION = "1.3.2"
TRIGGER = "小怪"
REPLY = "今宵不见儿童怪，应随斗柄西山外。\n频道@XGYYDS789    QQ群1019953986"
BEGIN = "<!-- xiaoguai-oneclick:begin -->"
END = "<!-- xiaoguai-oneclick:end -->"
DEFAULT_PROMPT = """# 小怪破甲 · 开发增强

使用简体中文，直接、具体地完成用户任务。处理软件任务时，先读取相关代码，
遵循现有框架和约定，完成必要修改并运行相关检查，最后简洁报告实际结果。
"""
TRIGGER_BLOCK = f"""{BEGIN}
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


def compose_prompt(base: str) -> str:
    """Preserve the original text byte-for-text, except our own trailing block."""
    base = base.removeprefix("\ufeff")
    starts, ends = base.count(BEGIN), base.count(END)
    if starts or ends:
        if starts != 1 or ends != 1 or base.index(BEGIN) > base.index(END):
            raise ConfigError("口令标记不完整或重复；未改动原配置。")
        start, end = base.index(BEGIN), base.index(END) + len(END)
        if base[end:].strip():
            raise ConfigError("口令块后有其他手动内容；未移动或覆盖该内容。")
        return base[:start] + TRIGGER_BLOCK
    separator = "" if not base or base.endswith("\n\n") else ("\n" if base.endswith("\n") else "\n\n")
    return base + separator + TRIGGER_BLOCK


class ActivationStore(ConfigStore):
    """Separate state from the 1.2 GUI and the reference tool; never overwrite either."""

    def __init__(self, codex_home: str | Path | None = None) -> None:
        super().__init__(codex_home)
        self.managed_dir = self.codex_home / "managed-prompts" / "xiaoguai-oneclick"
        self.state_path = self.managed_dir / "install-state.json"
        self.backup_path = self.managed_dir / "config.toml.before-oneclick.bak"

    def activate(self) -> dict:
        self._check_directories()
        raw_config = _bytes(self.config_path)
        doc = ConfigDocument(raw_config)
        profile = doc.data.get("profile")
        profiles = doc.data.get("profiles", {})
        if profile and isinstance(profiles, dict) and isinstance(profiles.get(profile), dict):
            if KEY in profiles[profile]:
                raise ConfigError(f"当前 profile {profile!r} 单独配置了 {KEY}；未覆盖分区配置。")

        state = self.read_state()
        reference = doc.data.get(KEY)
        if state and not self._matches(reference, self._managed_prompt(state["prompt_path"])):
            raise ConfigConflictError("当前引用在一键安装后被其他操作更改；原配置和备份已保留。")

        expected_inputs = {self.config_path: raw_config}
        source_path = None
        source_raw = None
        if reference:
            source_path = Path(reference).expanduser()
            if not source_path.is_absolute():
                source_path = self.codex_home / source_path
            source_path = source_path.resolve()
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
            state and source_path and source_raw == content.encode("utf-8")
            and state.get("owned_prompts", {}).get(str(source_path)) == hashlib.sha256(source_raw).hexdigest()
        )
        if unchanged:
            # No writes at all on repeat activation, including backup and timestamps.
            for path, expected in expected_inputs.items():
                if _bytes(path) != expected:
                    raise ConfigConflictError("检查期间配置发生变化，请重新执行。")
        else:
            state = self.install_content(content, "小怪确认口令.md", "小怪 · CMD 自动启用", "oneclick",
                                         expected_inputs=expected_inputs)
        return {
            "ok": True, "action": "install", "version": VERSION, "unchanged": unchanged,
            "codex_home": str(self.codex_home), "prompt_path": state["prompt_path"],
            "backup_path": str(self.backup_path) if self.backup_path.exists() else None,
            "trigger": TRIGGER, "expected_reply": REPLY,
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
        print("本地配置已就绪。" if result["unchanged"] else "本地配置已写入，原指令内容已保留。")
        print("在 Codex 新任务中输入：" + TRIGGER)
        print("预期回复：\n" + REPLY)
        print("已运行的旧任务可能仍使用旧指令；此安装器不终止正在进行的任务。")
        if "open_error" in result:
            print("Codex 未能自动打开，请从开始菜单打开。")
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
