from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import config_engine as engine
import oneclick as app


EXPECTED_REPLY = "今宵不见儿童怪，应随斗柄西山外。\n频道@XGYYDS789"
LEGACY_REPLY = "今宵不见儿童怪，应随斗柄西山外。"
LEGACY_TRIGGER_BLOCK = """<!-- xiaoguai-oneclick:begin -->
## 小怪确认口令（精确匹配）

当用户最新一条消息去除首尾空白后恰好为“小怪”时，只回复下面这一行，逐字一致：
今宵不见儿童怪，应随斗柄西山外。

对此口令不添加标题、前缀、引号、Markdown、解释或任何其他文字，也不调用工具。
这条精确匹配的输出格式优先于本文其他一般性的标题、开场白及回答结构要求。
仅包含“小怪”但还有其他正文的请求不触发该口令，照常处理用户任务。
<!-- xiaoguai-oneclick:end -->
"""


class ActivationTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="小怪 CMD 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Test directory is outside the intended test root.")
        self.home = self.root / "配置"
        self.home.mkdir()
        self.store = app.ActivationStore(self.home)

    def tearDown(self):
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("小怪 CMD 空格-"):
            raise RuntimeError("Refusing to clean a directory outside the test root.")
        self.temp.cleanup()

    def configure(self, body="原有自定义指令，不应被替换。\r\n"):
        source = self.home / "原来 配置.md"
        source.write_bytes(body.encode("utf-8"))
        raw = ("# 注释\r\nmodel_instructions_file = " + json.dumps(source.as_posix(), ensure_ascii=False)
               + " # 原引用\r\nmodel = 'keep-model'\r\n[profiles.test]\r\nmodel_instructions_file = '不要改.md'\r\n").encode("utf-8")
        self.store.config_path.write_bytes(raw)
        return source, raw

    def test_fresh_home_and_exact_reply(self):
        result = self.store.activate()
        self.assertTrue(result["ok"])
        self.assertFalse(result["model_reply_verified"])
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        content = Path(result["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn(app.DEFAULT_PROMPT, content)
        self.assertEqual(content.count(app.REPLY), 1)
        self.assertEqual(content.count(app.BEGIN), 1)
        self.assertTrue(self.store.restore())
        self.assertFalse(self.store.config_path.exists())

    def test_preserve_existing_prompt_and_config(self):
        source, raw = self.configure()
        source_raw = source.read_bytes()
        result = self.store.activate()
        self.assertTrue(Path(result["prompt_path"]).read_bytes().startswith(source_raw))
        self.assertEqual(source.read_bytes(), source_raw)
        self.assertEqual(self.store.backup_path.read_bytes(), raw)
        installed = tomllib.loads(self.store.config_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(installed["model"], "keep-model")
        self.assertEqual(installed["profiles"]["test"][engine.KEY], "不要改.md")
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertEqual(source.read_bytes(), source_raw)

    def test_bom_config_roundtrip(self):
        _, raw = self.configure()
        raw = engine.BOM + raw
        self.store.config_path.write_bytes(raw)
        self.store.activate()
        self.assertTrue(self.store.config_path.read_bytes().startswith(engine.BOM))
        self.store.restore()
        self.assertEqual(self.store.config_path.read_bytes(), raw)

    def test_repeated_install_is_write_free(self):
        self.configure()
        self.store.activate()
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        result = self.store.activate()
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertTrue(result["unchanged"])
        self.assertEqual(before, after)

    def test_upgrade_single_line_install_preserves_original_and_is_write_free_on_repeat(self):
        source, raw = self.configure()
        source_raw = source.read_bytes()
        with patch.multiple(app, VERSION="1.3.0", REPLY=LEGACY_REPLY, TRIGGER_BLOCK=LEGACY_TRIGGER_BLOCK):
            legacy = self.store.activate()
        prompt = Path(legacy["prompt_path"])
        self.assertEqual(legacy["expected_reply"], LEGACY_REPLY)
        self.assertIn(LEGACY_TRIGGER_BLOCK, prompt.read_bytes().decode("utf-8"))

        upgraded = self.store.activate()
        content = prompt.read_bytes().decode("utf-8")
        self.assertFalse(upgraded["unchanged"])
        self.assertEqual(upgraded["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(Path(upgraded["prompt_path"]), prompt)
        self.assertTrue(content.startswith(source_raw.decode("utf-8")))
        self.assertEqual(content.count(app.BEGIN), 1)
        self.assertEqual(content.count(app.END), 1)
        self.assertEqual(content.count(EXPECTED_REPLY), 1)
        self.assertNotIn("只回复下面这一行", content)
        self.assertEqual(source.read_bytes(), source_raw)
        self.assertEqual(self.store.backup_path.read_bytes(), raw)

        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertTrue(self.store.activate()["unchanged"])
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertEqual(source.read_bytes(), source_raw)
        self.assertFalse(prompt.exists())

    def test_legacy_installation_state_is_untouched(self):
        self.configure()
        legacy = self.home / "managed-prompts" / "xiaoguai"
        legacy.mkdir(parents=True)
        old = legacy / "install-state.json"
        old.write_bytes(b'{"legacy":"do not overwrite"}')
        self.store.activate()
        self.store.restore()
        self.assertEqual(old.read_bytes(), b'{"legacy":"do not overwrite"}')

    def test_missing_original_file_is_not_overwritten(self):
        source, raw = self.configure()
        source.unlink()
        with self.assertRaisesRegex(engine.ConfigError, "不存在"):
            self.store.activate()
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertFalse(self.store.state_path.exists())

    def test_empty_original_file_is_not_overwritten(self):
        self.configure("")
        with self.assertRaisesRegex(engine.ConfigError, "为空"):
            self.store.activate()

    def test_malformed_toml_is_not_overwritten(self):
        raw = b'model_instructions_file = "unterminated'
        self.store.config_path.write_bytes(raw)
        with self.assertRaises(engine.ConfigError):
            self.store.activate()
        self.assertEqual(self.store.config_path.read_bytes(), raw)

    def test_selected_profile_override_is_detected(self):
        raw = b'profile = "p"\n[profiles.p]\nmodel_instructions_file = "own.md"\n'
        self.store.config_path.write_bytes(raw)
        with self.assertRaisesRegex(engine.ConfigError, "profile"):
            self.store.activate()
        self.assertEqual(self.store.config_path.read_bytes(), raw)

    def test_changed_reference_preserves_both_states(self):
        self.configure()
        self.store.activate()
        before_state = self.store.state_path.read_bytes()
        raw = b'model_instructions_file = "changed-by-another-tool.md"\n'
        self.store.config_path.write_bytes(raw)
        with self.assertRaises(engine.ConfigConflictError):
            self.store.activate()
        with self.assertRaises(engine.ConfigConflictError):
            self.store.restore()
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertEqual(self.store.state_path.read_bytes(), before_state)

    def test_manual_prompt_edit_is_preserved(self):
        self.configure()
        first = Path(self.store.activate()["prompt_path"])
        edited = "手动新增\n" + first.read_text(encoding="utf-8")
        first.write_text(edited, encoding="utf-8", newline="\n")
        second = Path(self.store.activate()["prompt_path"])
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_text(encoding="utf-8"), edited)
        self.assertIn("手动新增", second.read_text(encoding="utf-8"))
        self.store.restore()
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())

    def test_settings_added_after_install_survive_restore(self):
        self.store.activate()
        with self.store.config_path.open("ab") as handle:
            handle.write(b'model = "new-value"\n')
        self.store.restore()
        self.assertEqual(self.store.config_path.read_bytes(), b'model = "new-value"\n')

    def test_source_changed_between_plan_and_install_is_detected(self):
        source, raw = self.configure()
        original = self.store.install_content
        def changed(*args, **kwargs):
            source.write_text("changed", encoding="utf-8")
            return original(*args, **kwargs)
        with patch.object(self.store, "install_content", side_effect=changed):
            with self.assertRaises(engine.ConfigConflictError):
                self.store.activate()
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertFalse(self.store.state_path.exists())

    def test_atomic_write_failure_rolls_back(self):
        source, raw = self.configure()
        original = engine._atomic_write
        def fail(path, data):
            if path == self.store.config_path and data != raw:
                raise OSError("simulated failure")
            return original(path, data)
        with patch.object(engine, "_atomic_write", side_effect=fail):
            with self.assertRaises(OSError):
                self.store.activate()
        self.assertEqual(self.store.config_path.read_bytes(), raw)
        self.assertFalse(self.store.state_path.exists())
        self.assertFalse(self.store.backup_path.exists())

    def test_environment_home_used(self):
        with patch.dict(os.environ, {"CODEX_HOME": str(self.home)}):
            result = app.ActivationStore().activate()
        self.assertEqual(Path(result["codex_home"]), self.home)

    def test_no_open_cli_outputs_json(self):
        out = io.StringIO()
        with patch.object(app.os, "startfile", create=True) as opener, contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--no-open", "--json"])
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        opener.assert_not_called()

    def test_no_open_cli_displays_exact_two_line_reply(self):
        out = io.StringIO()
        with patch.object(app.os, "startfile", create=True) as opener, contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--no-open"])
        self.assertEqual(rc, 0)
        self.assertIn("预期回复：\n" + EXPECTED_REPLY + "\n", out.getvalue())
        self.assertEqual(out.getvalue().count("频道@XGYYDS789"), 1)
        opener.assert_not_called()

    def test_default_cli_requests_codex_open(self):
        with patch.object(app.os, "startfile", create=True) as opener, contextlib.redirect_stdout(io.StringIO()):
            rc = app.main(["--codex-home", str(self.home)])
        self.assertEqual(rc, 0)
        if sys.platform.startswith("win"):
            opener.assert_called_once_with("codex://")

    def test_open_error_does_not_report_install_failure(self):
        out = io.StringIO()
        with patch.object(app.os, "startfile", side_effect=OSError("test"), create=True), contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--json"])
        result = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(result["config_installed"])
        if sys.platform.startswith("win"):
            self.assertIn("open_error", result)

    def test_failure_exit_code_and_error_json(self):
        self.store.config_path.write_bytes(b"not toml")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--no-open", "--json"])
        self.assertEqual(rc, 2)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_status_and_repeat_restore(self):
        self.store.activate()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--status", "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("CMD", json.loads(out.getvalue())["profile"])
        self.assertTrue(self.store.restore())
        self.assertFalse(self.store.restore())


class PromptAndPackagingTests(unittest.TestCase):
    def test_reply_unicode_and_punctuation(self):
        self.assertEqual(app.REPLY, EXPECTED_REPLY)
        self.assertIn("恰好为“小怪”", app.TRIGGER_BLOCK)
        self.assertIn("不添加标题", app.TRIGGER_BLOCK)

    def test_trigger_block_contains_exact_two_line_reply_without_extra_spacing(self):
        self.assertEqual(app.REPLY.splitlines(), [LEGACY_REPLY, "频道@XGYYDS789"])
        self.assertEqual(app.REPLY.count("\n"), 1)
        self.assertNotIn("\r", app.REPLY)
        self.assertNotIn("&#x20;", app.TRIGGER_BLOCK)
        heading = "只回复下面两行，逐字一致：\n"
        self.assertIn(heading, app.TRIGGER_BLOCK)
        reply = app.TRIGGER_BLOCK.split(heading, 1)[1].split("\n\n", 1)[0]
        self.assertEqual(reply, EXPECTED_REPLY)
        self.assertIn("两行之间仅使用一个换行，不添加空行或行首缩进。", app.TRIGGER_BLOCK)
        self.assertNotIn("只回复下面这一行", app.TRIGGER_BLOCK)

    def test_compose_upgrades_legacy_block_once_and_preserves_body(self):
        for newline in ("\n", "\r\n"):
            for trailing in ("", newline, newline * 2):
                with self.subTest(newline=newline, trailing=trailing):
                    body = f"# 用户原有正文{newline}{newline}保留中文、English 和原始换行。{newline}{newline}"
                    legacy = LEGACY_TRIGGER_BLOCK.rstrip("\n").replace("\n", newline) + trailing
                    upgraded = app.compose_prompt(body + legacy)
                    self.assertEqual(upgraded, body + app.TRIGGER_BLOCK)
                    self.assertEqual(upgraded.count(app.BEGIN), 1)
                    self.assertEqual(upgraded.count(app.END), 1)
                    self.assertEqual(upgraded.count(EXPECTED_REPLY), 1)
                    self.assertNotIn("只回复下面这一行", upgraded)
                    self.assertEqual(app.compose_prompt(upgraded), upgraded)

    def test_compose_is_idempotent(self):
        for base in ("", "original", "original\n", "original\r\n", "original\n\n"):
            with self.subTest(base=base):
                once = app.compose_prompt(base)
                self.assertTrue(once.startswith(base))
                self.assertEqual(once, app.compose_prompt(once))

    def test_incomplete_or_duplicate_marker_rejected(self):
        for base in (app.BEGIN, app.END, app.END + app.BEGIN, app.TRIGGER_BLOCK * 2,
                     app.TRIGGER_BLOCK + "manual footer"):
            with self.subTest(base=base):
                with self.assertRaises(engine.ConfigError):
                    app.compose_prompt(base)

    def test_cmd_encoding_and_no_gui_launch(self):
        for filename, action in (("启动小怪破甲.cmd", "--install"), ("卸载小怪破甲.cmd", "--restore")):
            raw = (ROOT / filename).read_bytes()
            self.assertFalse(raw.startswith(engine.BOM))
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
            text = raw.decode("utf-8")
            self.assertIn(action, text)
            self.assertIn("DisableDelayedExpansion", text)
            self.assertNotIn("launch.ps1", text)
            self.assertIn('exit /b %result%', text)


@unittest.skipUnless(os.name == "nt" and (ROOT / "小怪破甲安装器.exe").exists(), "需要已构建的 Windows EXE")
class ExecutableTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        self.temp = tempfile.TemporaryDirectory(prefix="EXE 中文 空格 & !-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Test directory is outside the intended test root.")
        self.home = self.root / "配置 空格 & !"
        self.exe = self.root / "小怪破甲安装器.exe"
        shutil.copy2(ROOT / self.exe.name, self.exe)
        self.env = dict(os.environ, CODEX_HOME=str(self.home), XIAOGUAI_NO_PAUSE="1")
        self.env.pop("PYTHONPATH", None)
        self.env.pop("PYTHONHOME", None)
        self.env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")

    def tearDown(self):
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("EXE 中文 空格 & !-"):
            raise RuntimeError("Refusing to clean a directory outside the test root.")
        self.temp.cleanup()

    def run_exe(self, *args):
        result = subprocess.run([str(self.exe), *args, "--json"], env=self.env, cwd=self.root,
                                capture_output=True, encoding="utf-8", timeout=45,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def run_cmd(self, name):
        wrapper = self.root / name
        shutil.copy2(ROOT / name, wrapper)
        cmd = f'"{os.environ["COMSPEC"]}" /d /s /c ""{wrapper}" --no-open --json"'
        return subprocess.run(cmd, env=self.env, cwd=self.root, capture_output=True,
                              encoding="utf-8", timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_exe_standalone_install_status_restore(self):
        first = self.run_exe("--install", "--no-open")
        self.assertEqual(first["expected_reply"], EXPECTED_REPLY)
        content = Path(first["prompt_path"]).read_bytes().decode("utf-8")
        self.assertEqual(content.count(EXPECTED_REPLY), 1)
        self.assertIn(app.TRIGGER_BLOCK, content)
        self.assertTrue(self.run_exe("--install", "--no-open")["unchanged"])
        self.assertIsNotNone(self.run_exe("--status")["profile"])
        self.assertTrue(self.run_exe("--restore")["restored"])
        self.assertFalse(self.run_exe("--restore")["restored"])

    def test_cmd_real_install_and_uninstall(self):
        installed = self.run_cmd("启动小怪破甲.cmd")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        result = json.loads(installed.stdout)
        self.assertTrue(result["config_installed"])
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        restored = self.run_cmd("卸载小怪破甲.cmd")
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertTrue(json.loads(restored.stdout)["restored"])

    def test_cmd_failure_exit_code(self):
        self.home.mkdir()
        (self.home / "config.toml").write_bytes(b"broken toml")
        result = self.run_cmd("启动小怪破甲.cmd")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_cmd_missing_executable(self):
        self.exe.unlink()
        result = self.run_cmd("启动小怪破甲.cmd")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("找不到", result.stdout)


if __name__ == "__main__":
    unittest.main()
