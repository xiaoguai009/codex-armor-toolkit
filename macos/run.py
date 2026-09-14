#!/usr/bin/env python3
"""小怪破甲 macOS 独立入口；共享配置引擎，不运行 Windows 安装器。"""

from __future__ import annotations

import sys

# Running the downloaded source must not create caches in the release directory.
sys.dont_write_bytecode = True

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oneclick import ASSISTANT_NAME, VERSION, ActivationStore


EDITION_VERSION = "1.3.4-mac.1"
PLATFORM = "macos"
OPEN_COMMAND = ["/usr/bin/open", "-a", "Codex"]
OPEN_TIMEOUT = 15


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # Even invalid arguments retain a single machine-readable JSON result.
        raise ValueError("参数错误：" + message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description="小怪破甲 macOS 独立版：安装、恢复或查看本地配置", allow_abbrev=False)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--install", action="store_true", help="安装（默认操作）")
    actions.add_argument("--restore", action="store_true", help="恢复本次安装前的引用")
    actions.add_argument("--status", action="store_true", help="只读取本地安装状态")
    parser.add_argument("--codex-home", type=Path, help="指定配置目录；默认使用 CODEX_HOME 或 ~/.codex")
    parser.add_argument("--json", action="store_true", help="输出单个 JSON 结果")
    parser.add_argument("--no-open", action="store_true", help="安装后不打开 Codex")
    return parser


def _request_open(result: dict) -> None:
    # Match the Windows entry: true means the open command accepted the request,
    # not proof that a window opened or that a custom CODEX_HOME was adopted.
    try:
        completed = subprocess.run(OPEN_COMMAND, timeout=OPEN_TIMEOUT, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        result["open_error"] = f"打开 Codex 的请求超时（{OPEN_TIMEOUT} 秒）。"
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        result["open_error"] = str(exc)
    else:
        if completed.returncode == 0:
            result["codex_open_requested"] = True
        else:
            detail = (completed.stderr or completed.stdout or "").strip()
            result["open_error"] = f"open 命令退出码 {completed.returncode}" + ("：" + detail if detail else "")


def _print_result(result: dict, json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
    elif not result["ok"]:
        print("执行未完成：" + result["error"], file=sys.stderr)
    elif result["action"] == "restore":
        print("已恢复本次安装前的配置引用。" if result["restored"] else "没有需要恢复的小怪安装记录。")
        for path in result["retained_paths"]:
            print("保留手动修改的文件：" + path)
    elif result["action"] == "status":
        print("本地状态：" + (ASSISTANT_NAME + "已启用" if result["profile"] else "未安装"))
        print("配置目录：" + result["codex_home"])
    else:
        print("小怪破甲 macOS 独立版 " + EDITION_VERSION)
        if result["reference_repaired"]:
            print("已按当前引用修复旧安装记录；原记录、原提示词和首次备份已保留。")
            print("本次修复历史备份：" + result["recovery_path"])
        print("本地配置已就绪。" if result["unchanged"] else "本地配置已写入，原文件保留；生成副本已统一小怪身份。")
        if result["backup_path"]:
            print("原配置备份：" + result["backup_path"])
        print("普通问候（hi / 你好）的预期回复：\n" + result["expected_greeting"])
        print("在 Codex 新任务中输入：" + result["trigger"])
        print("预期回复：\n" + result["expected_reply"])
        print("已运行的旧任务可能仍使用旧指令；此安装器不终止正在进行的任务。")
        if "open_error" in result:
            print("Codex 未能自动打开：" + result["open_error"])
            print("本地配置已保留，请从“应用程序”打开 Codex。")
        elif not result["codex_open_requested"]:
            print("未请求自动打开 Codex，可从“应用程序”手动打开。")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    result = {
        "ok": False,
        "action": None,
        "version": VERSION,
        "platform": PLATFORM,
        "edition_version": EDITION_VERSION,
        "codex_open_requested": False,
    }
    try:
        args = _parser().parse_args(argv)
        json_output = args.json
        result["action"] = "restore" if args.restore else "status" if args.status else "install"
        if sys.platform != "darwin":
            raise ValueError(f"此独立版仅支持 macOS（当前平台：{sys.platform}）；未修改配置。")
        # The shared store owns CODEX_HOME, the default home and all backup rules.
        store = ActivationStore(args.codex_home)
        result["codex_home"] = str(store.codex_home)
        if args.restore:
            result.update(ok=True, restored=store.restore(), retained_paths=store.retained_paths)
        elif args.status:
            result.update(ok=True, profile=store.current_profile())
        else:
            result.update(store.activate())
            if not args.no_open:
                _request_open(result)
    except (OSError, ValueError, RuntimeError) as exc:
        result.update(ok=False, error=str(exc))
    _print_result(result, json_output)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
