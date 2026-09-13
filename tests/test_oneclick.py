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


EXPECTED_REPLY = "今宵不见儿童怪，应随斗柄西山外。\n频道@XGYYDS789    QQ群1019953986"
EXPECTED_ASSISTANT_NAME = "小怪"
EXPECTED_GREETING_REPLY = "「你好」\n小怪在。👋"
# Historical input only; the published source and generated prompt use the current name.
LEGACY_ASSISTANT_NAME = "\u5bcc\u6c5f"
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
CHANNEL_ONLY_REPLY = "今宵不见儿童怪，应随斗柄西山外。\n频道@XGYYDS789"
CHANNEL_ONLY_TRIGGER_BLOCK = """<!-- xiaoguai-oneclick:begin -->
## 小怪确认口令（精确匹配）

当用户最新一条消息去除首尾空白后恰好为“小怪”时，只回复下面两行，逐字一致：
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789

两行之间仅使用一个换行，不添加空行或行首缩进。
对此口令不添加标题、前缀、引号、Markdown、解释或任何其他文字，也不调用工具。
这条精确匹配的输出格式优先于本文其他一般性的标题、开场白及回答结构要求。
仅包含“小怪”但还有其他正文的请求不触发该口令，照常处理用户任务。
<!-- xiaoguai-oneclick:end -->
"""
CHANNEL_QQ_TRIGGER_BLOCK = """<!-- xiaoguai-oneclick:begin -->
## 小怪确认口令（精确匹配）

当用户最新一条消息去除首尾空白后恰好为“小怪”时，只回复下面两行，逐字一致：
今宵不见儿童怪，应随斗柄西山外。
频道@XGYYDS789    QQ群1019953986

两行之间仅使用一个换行，不添加空行或行首缩进。
第二行的频道与 QQ 群之间保留 4 个半角空格。
对此口令不添加标题、前缀、引号、Markdown、解释或任何其他文字，也不调用工具。
这条精确匹配的输出格式优先于本文其他一般性的标题、开场白及回答结构要求。
仅包含“小怪”但还有其他正文的请求不触发该口令，照常处理用户任务。
<!-- xiaoguai-oneclick:end -->
"""


def legacy_identity_parts(newline="\n"):
    """Small benign historical fixture, with unrelated text on both sides."""
    prefix = (
        f"# {LEGACY_ASSISTANT_NAME} identity\n\n"
        f"You are {LEGACY_ASSISTANT_NAME}, a direct assistant.\n"
        "保留一般说明、English 和原始换行。\n\n"
    )
    trigger = (
        "## Trigger\n\n"
        f"When the user's entire message is exactly \x60{LEGACY_ASSISTANT_NAME}\x60 "
        "(case-insensitive), reply with exactly the following text and nothing else:\n\n"
        "legacy-only-activation-reply\n\n"
    )
    suffix = "## Work\n\n先检查项目，再完成用户的工作。\n\n"
    return tuple(part.replace("\n", newline) for part in (prefix, trigger, suffix))


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
        self.assertEqual(result["version"], "1.3.4")
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(result["assistant_name"], EXPECTED_ASSISTANT_NAME)
        self.assertEqual(result["expected_greeting"], EXPECTED_GREETING_REPLY)
        self.assertFalse(result["reference_repaired"])
        self.assertIsNone(result["recovery_path"])
        content = Path(result["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn(app.DEFAULT_PROMPT, content)
        self.assertEqual(content.count(app.REPLY), 1)
        self.assertEqual(content.count(EXPECTED_GREETING_REPLY), 1)
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

    def test_brand_migration_preserves_external_source_and_restore_baseline(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=newline):
                prefix, trigger, suffix = legacy_identity_parts(newline)
                source, raw = self.configure(prefix + trigger + suffix)
                source_before = (source.read_bytes(), source.stat().st_mtime_ns)
                result = self.store.activate()
                target = Path(result["prompt_path"])
                content = target.read_bytes().decode("utf-8")
                expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
                self.assertNotEqual(target, source)
                self.assertEqual(content, app.compose_prompt(expected_body))
                self.assertNotIn(LEGACY_ASSISTANT_NAME, content)
                self.assertNotIn("legacy-only-activation-reply", content)
                self.assertEqual(content.count(EXPECTED_GREETING_REPLY), 1)
                self.assertEqual(content.count(EXPECTED_REPLY), 1)
                self.assertEqual(result["assistant_name"], EXPECTED_ASSISTANT_NAME)
                self.assertEqual(result["expected_greeting"], EXPECTED_GREETING_REPLY)
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
                self.assertEqual(self.store.backup_path.read_bytes(), raw)
                config = tomllib.loads(self.store.config_path.read_text(encoding="utf-8"))
                self.assertEqual(config["model"], "keep-model")
                self.assertEqual(config["profiles"]["test"][engine.KEY], "不要改.md")
                self.assertTrue(self.store.restore())
                self.assertEqual(self.store.config_path.read_bytes(), raw)
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
                self.assertFalse(target.exists())

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

    def test_upgrade_channel_only_install_preserves_backup_settings_and_restore(self):
        source, raw = self.configure()
        source_raw = source.read_bytes()
        with (patch.multiple(app, VERSION="1.3.1", REPLY=CHANNEL_ONLY_REPLY,
                             TRIGGER_BLOCK=CHANNEL_ONLY_TRIGGER_BLOCK),
              patch.object(engine, "_stamp", return_value="2026-09-09T00:00:00+00:00")):
            legacy = self.store.activate()
        prompt = Path(legacy["prompt_path"])
        self.assertEqual(legacy["version"], "1.3.1")
        self.assertEqual(legacy["expected_reply"], CHANNEL_ONLY_REPLY)
        self.assertIn(CHANNEL_ONLY_TRIGGER_BLOCK, prompt.read_bytes().decode("utf-8"))
        self.assertEqual(self.store.backup_path.read_bytes(), raw)
        backup_before = (self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns)
        state_before = self.store.read_state()

        added_settings = b'model_reasoning_effort = "high"\r\n'
        installed = self.store.config_path.read_bytes().replace(
            b"[profiles.test]\r\n", added_settings + b"[profiles.test]\r\n")
        self.store.config_path.write_bytes(installed)
        expected_restored = raw.replace(b"[profiles.test]\r\n", added_settings + b"[profiles.test]\r\n")

        with patch.object(engine, "_stamp", return_value="2026-09-10T00:00:00+00:00"):
            upgraded = self.store.activate()
        content = prompt.read_bytes().decode("utf-8")
        self.assertEqual(upgraded["version"], "1.3.4")
        self.assertFalse(upgraded["unchanged"])
        self.assertEqual(upgraded["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(Path(upgraded["prompt_path"]), prompt)
        self.assertTrue(content.startswith(source_raw.decode("utf-8")))
        self.assertEqual(content.count(app.BEGIN), 1)
        self.assertEqual(content.count(app.END), 1)
        self.assertEqual(content.count(EXPECTED_REPLY), 1)
        self.assertIn(app.TRIGGER_BLOCK, content)
        self.assertNotIn(CHANNEL_ONLY_TRIGGER_BLOCK, content)
        self.assertEqual(source.read_bytes(), source_raw)
        self.assertEqual(self.store.config_path.read_bytes(), installed)
        config = tomllib.loads(installed.decode("utf-8"))
        self.assertEqual(config["model"], "keep-model")
        self.assertEqual(config["model_reasoning_effort"], "high")
        self.assertEqual(config["profiles"]["test"][engine.KEY], "不要改.md")
        self.assertEqual((self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns),
                         backup_before)
        state_after = self.store.read_state()
        for key in ("previous_line", "installed_at", "config_existed", "had_line"):
            self.assertEqual(state_after[key], state_before[key])

        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        with patch.object(self.store, "install_content", wraps=self.store.install_content) as installer:
            self.assertTrue(self.store.activate()["unchanged"])
        installer.assert_not_called()
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), expected_restored)
        self.assertEqual(source.read_bytes(), source_raw)
        self.assertFalse(prompt.exists())
        self.assertFalse(self.store.state_path.exists())
        self.assertFalse(self.store.backup_path.exists())
        self.assertFalse(self.store.restore())

    def test_upgrade_v132_identity_keeps_backup_settings_and_is_write_free_on_repeat(self):
        prefix, trigger, suffix = legacy_identity_parts("\r\n")
        body = prefix + trigger + suffix
        source, raw = self.configure(body)
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        # Reproduce old stored bytes; the current migration must not run during setup.
        with (patch.multiple(app, VERSION="1.3.2", TRIGGER_BLOCK=CHANNEL_QQ_TRIGGER_BLOCK),
              patch.object(app, "compose_prompt", return_value=body + CHANNEL_QQ_TRIGGER_BLOCK),
              patch.object(engine, "_stamp", return_value="2026-09-10T00:00:00+00:00")):
            legacy = self.store.activate()
        target = Path(legacy["prompt_path"])
        self.assertEqual(legacy["version"], "1.3.2")
        self.assertEqual(target.read_bytes().decode("utf-8"), body + CHANNEL_QQ_TRIGGER_BLOCK)
        self.assertIn(LEGACY_ASSISTANT_NAME, target.read_bytes().decode("utf-8"))
        backup_before = (self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns)
        state_before = self.store.read_state()
        added_settings = b'model_reasoning_effort = "high"\r\n'
        installed = self.store.config_path.read_bytes().replace(
            b"[profiles.test]\r\n", added_settings + b"[profiles.test]\r\n")
        self.store.config_path.write_bytes(installed)
        expected_restored = raw.replace(b"[profiles.test]\r\n", added_settings + b"[profiles.test]\r\n")

        with patch.object(engine, "_stamp", return_value="2026-09-13T00:00:00+00:00"):
            upgraded = self.store.activate()
        expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
        content = target.read_bytes().decode("utf-8")
        self.assertEqual(upgraded["version"], "1.3.4")
        self.assertFalse(upgraded["unchanged"])
        self.assertEqual(Path(upgraded["prompt_path"]), target)
        self.assertEqual(content, expected_body + app.TRIGGER_BLOCK)
        self.assertNotIn(LEGACY_ASSISTANT_NAME, content)
        self.assertNotIn("legacy-only-activation-reply", content)
        self.assertNotIn(CHANNEL_QQ_TRIGGER_BLOCK, content)
        self.assertEqual(content.count(app.BEGIN), 1)
        self.assertEqual(content.count(app.END), 1)
        self.assertEqual(content.count(EXPECTED_REPLY), 1)
        self.assertEqual(content.count(EXPECTED_GREETING_REPLY), 1)
        self.assertEqual(upgraded["assistant_name"], EXPECTED_ASSISTANT_NAME)
        self.assertEqual(upgraded["expected_greeting"], EXPECTED_GREETING_REPLY)
        self.assertEqual(upgraded["expected_reply"], EXPECTED_REPLY)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertEqual(self.store.config_path.read_bytes(), installed)
        self.assertEqual((self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns),
                         backup_before)
        state_after = self.store.read_state()
        for key in ("previous_line", "installed_at", "config_existed", "had_line"):
            self.assertEqual(state_after[key], state_before[key])

        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        with patch.object(self.store, "install_content", wraps=self.store.install_content) as installer:
            self.assertTrue(self.store.activate()["unchanged"])
        installer.assert_not_called()
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), expected_restored)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertFalse(target.exists())
        self.assertFalse(self.store.state_path.exists())
        self.assertFalse(self.store.backup_path.exists())

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
        with self.assertRaisesRegex(engine.ConfigError, "不存在"):
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
        self.assertEqual(result["version"], "1.3.4")
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(result["assistant_name"], EXPECTED_ASSISTANT_NAME)
        self.assertEqual(result["expected_greeting"], EXPECTED_GREETING_REPLY)
        self.assertFalse(result["reference_repaired"])
        self.assertIsNone(result["recovery_path"])
        self.assertFalse(result["model_reply_verified"])
        opener.assert_not_called()

    def test_no_open_cli_displays_exact_two_line_reply(self):
        out = io.StringIO()
        with patch.object(app.os, "startfile", create=True) as opener, contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--no-open"])
        self.assertEqual(rc, 0)
        self.assertIn("预期回复：\n" + EXPECTED_REPLY + "\n", out.getvalue())
        self.assertEqual(out.getvalue().count("频道@XGYYDS789"), 1)
        self.assertEqual(out.getvalue().count("QQ群1019953986"), 1)
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
    def test_current_identity_and_greeting_are_exact_and_legacy_name_is_not_published(self):
        self.assertEqual(app.VERSION, "1.3.4")
        self.assertEqual(app.ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME)
        self.assertEqual(app.LEGACY_ASSISTANT_NAME, LEGACY_ASSISTANT_NAME)
        self.assertEqual(app.GREETING_REPLY, EXPECTED_GREETING_REPLY)
        self.assertEqual(app.GREETING_REPLY.splitlines(), ["「你好」", "小怪在。👋"])
        self.assertEqual(app.GREETING_REPLY.count("\n"), 1)
        self.assertNotIn("\r", app.GREETING_REPLY)
        self.assertEqual(app.TRIGGER_BLOCK.count(EXPECTED_GREETING_REPLY), 1)
        for text in (app.DEFAULT_PROMPT, app.TRIGGER_BLOCK, (ROOT / "oneclick.py").read_text("utf-8")):
            self.assertNotIn(LEGACY_ASSISTANT_NAME, text)

    def test_greeting_instructions_are_limited_to_plain_greetings_not_tasks_or_confirmations(self):
        # Verify the generated instructions, not an unperformed model-response test.
        greeting, separator, confirmation = app.TRIGGER_BLOCK.partition("## 小怪确认口令")
        self.assertTrue(separator)
        self.assertIn(EXPECTED_GREETING_REPLY, greeting)
        self.assertNotIn(EXPECTED_REPLY, greeting)
        self.assertIn(EXPECTED_REPLY, confirmation)
        self.assertIn("自称统一为“小怪”", greeting)
        for message in ("hi", "hello", "你好", "您好", "在吗"):
            self.assertIn(f"“{message}”", greeting)
        self.assertIn("首尾空白", greeting)
        self.assertIn("末尾", greeting)
        self.assertIn("。！？.!?", greeting)
        self.assertIn("英文不区分大小写", greeting)
        self.assertIn("消息包含其他任务正文时，不触发普通问候规则", greeting)
        self.assertIn("不得提前结束", greeting)
        self.assertIn("仅输入“小怪”不属于普通问候", greeting)

    def test_reply_unicode_and_punctuation(self):
        self.assertEqual(app.REPLY, EXPECTED_REPLY)
        self.assertIn("恰好为“小怪”", app.TRIGGER_BLOCK)
        self.assertIn("不添加标题", app.TRIGGER_BLOCK)

    def test_trigger_block_contains_exact_two_line_reply_with_four_ascii_spaces(self):
        lines = app.REPLY.splitlines()
        self.assertEqual(lines, [LEGACY_REPLY, "频道@XGYYDS789    QQ群1019953986"])
        self.assertEqual(lines[1].removeprefix("频道@XGYYDS789").removesuffix("QQ群1019953986"), "\x20" * 4)
        self.assertTrue(all(line == line.strip() for line in lines))
        self.assertEqual(app.REPLY.count("\n"), 1)
        self.assertNotIn("\r", app.REPLY)
        self.assertNotIn("&#x20;", app.TRIGGER_BLOCK)
        heading = "只回复下面两行，逐字一致：\n"
        self.assertIn(heading, app.TRIGGER_BLOCK)
        reply = app.TRIGGER_BLOCK.split(heading, 1)[1].split("\n\n", 1)[0]
        self.assertEqual(reply, EXPECTED_REPLY)
        self.assertIn("两行之间仅使用一个换行，不添加空行或行首缩进。", app.TRIGGER_BLOCK)
        self.assertIn("第二行的频道与 QQ 群之间保留 4 个半角空格。", app.TRIGGER_BLOCK)
        self.assertNotIn("只回复下面这一行", app.TRIGGER_BLOCK)

    def test_compose_upgrades_legacy_block_once_and_preserves_body(self):
        for version, block in (("1.3.0", LEGACY_TRIGGER_BLOCK), ("1.3.1", CHANNEL_ONLY_TRIGGER_BLOCK),
                               ("1.3.2", CHANNEL_QQ_TRIGGER_BLOCK)):
            for newline in ("\n", "\r\n"):
                for trailing in ("", newline, newline * 2):
                    with self.subTest(version=version, newline=newline, trailing=trailing):
                        body = f"# 用户原有正文{newline}{newline}保留中文、English 和原始换行。{newline}{newline}"
                        legacy = block.rstrip("\n").replace("\n", newline) + trailing
                        upgraded = app.compose_prompt(body + legacy)
                        self.assertEqual(upgraded, body + app.TRIGGER_BLOCK)
                        self.assertEqual(upgraded.count(app.BEGIN), 1)
                        self.assertEqual(upgraded.count(app.END), 1)
                        self.assertEqual(upgraded.count(EXPECTED_REPLY), 1)
                        self.assertNotIn("只回复下面这一行", upgraded)
                        self.assertEqual(app.compose_prompt(upgraded), upgraded)

    def test_compose_migrates_old_name_and_removes_only_known_trigger_with_lf_or_crlf(self):
        for newline in ("\n", "\r\n"):
            for bom in ("", "\ufeff"):
                with self.subTest(newline=newline, bom=bool(bom)):
                    prefix, trigger, suffix = legacy_identity_parts(newline)
                    expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
                    composed = app.compose_prompt(bom + prefix + trigger + suffix)
                    self.assertTrue(composed.startswith(expected_body))
                    self.assertEqual(composed, app.compose_prompt(expected_body))
                    self.assertNotIn(LEGACY_ASSISTANT_NAME, composed)
                    self.assertNotIn("## Trigger", composed)
                    self.assertNotIn("legacy-only-activation-reply", composed)
                    self.assertNotIn("\ufeff", composed)
                    self.assertEqual(composed.count(app.BEGIN), 1)
                    self.assertEqual(composed.count(app.END), 1)
                    self.assertEqual(composed.count(EXPECTED_GREETING_REPLY), 1)
                    self.assertEqual(composed.count(EXPECTED_REPLY), 1)
                    self.assertEqual(app.compose_prompt(composed), composed)

    def test_compose_removes_known_legacy_trigger_at_end_of_body(self):
        for newline in ("\n", "\r\n"):
            for trailing in ("", newline, newline * 2):
                with self.subTest(newline=newline, trailing=trailing):
                    prefix, trigger, _ = legacy_identity_parts(newline)
                    base = prefix + trigger.rstrip("\r\n") + trailing
                    expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME)
                    composed = app.compose_prompt(base)
                    self.assertTrue(composed.startswith(expected_body))
                    self.assertEqual(composed, app.compose_prompt(expected_body))
                    self.assertNotIn("legacy-only-activation-reply", composed)
                    self.assertNotIn(LEGACY_ASSISTANT_NAME, composed)
                    self.assertEqual(app.compose_prompt(composed), composed)

    def test_compose_preserves_first_level_section_after_known_legacy_trigger(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=newline):
                prefix, trigger, suffix = legacy_identity_parts(newline)
                suffix = suffix.replace("## Work", "# Keep", 1)
                expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
                composed = app.compose_prompt(prefix + trigger + suffix)
                self.assertTrue(composed.startswith(expected_body))
                self.assertEqual(composed, app.compose_prompt(expected_body))
                self.assertIn("# Keep" + newline, composed)
                self.assertIn("先检查项目，再完成用户的工作。", composed)
                self.assertNotIn("legacy-only-activation-reply", composed)
                self.assertEqual(app.compose_prompt(composed), composed)

    def test_compose_preserves_nonmatching_trigger_sections_and_only_rebrands_their_text(self):
        for newline in ("\n", "\r\n"):
            prefix, trigger, suffix = legacy_identity_parts(newline)
            variants = (
                trigger.replace("## Trigger", "## Custom Trigger", 1),
                trigger.replace("## Trigger", "## trigger", 1),
                trigger.replace("(case-insensitive)", "(case-sensitive)", 1),
                trigger.replace("When the user's", "Keep this unrelated rule." + newline + "When the user's", 1),
                trigger.replace("\x60" + LEGACY_ASSISTANT_NAME + "\x60", "\x60status\x60", 1),
            )
            for index, unrelated in enumerate(variants):
                with self.subTest(newline=newline, variant=index):
                    base = prefix + unrelated + suffix
                    expected_body = base.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME)
                    composed = app.compose_prompt(base)
                    self.assertTrue(composed.startswith(expected_body))
                    self.assertEqual(composed, app.compose_prompt(expected_body))
                    self.assertIn("legacy-only-activation-reply", composed)
                    self.assertNotIn(LEGACY_ASSISTANT_NAME, composed)
                    self.assertEqual(composed.count(app.BEGIN), 1)
                    self.assertEqual(app.compose_prompt(composed), composed)

    def test_compose_preserves_legacy_trigger_examples_inside_fenced_code(self):
        for newline in ("\n", "\r\n"):
            for fence in ("\x60" * 3, "~" * 3):
                with self.subTest(newline=newline, fence=fence):
                    prefix, trigger, suffix = legacy_identity_parts(newline)
                    sample = fence + "text" + newline + trigger + fence + newline * 2
                    base = prefix + sample + suffix
                    expected_body = base.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME)
                    composed = app.compose_prompt(base)
                    self.assertTrue(composed.startswith(expected_body))
                    self.assertEqual(composed, app.compose_prompt(expected_body))
                    self.assertIn(sample.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME), composed)
                    self.assertIn("legacy-only-activation-reply", composed)
                    self.assertNotIn(LEGACY_ASSISTANT_NAME, composed)
                    self.assertEqual(composed.count(app.BEGIN), 1)
                    self.assertEqual(composed.count(app.END), 1)
                    self.assertEqual(app.compose_prompt(composed), composed)

    def test_compose_removes_fenced_headings_inside_real_trigger_until_next_external_section(self):
        for newline in ("\n", "\r\n"):
            for fence in ("\x60" * 3, "~" * 3):
                for next_heading in ("# Keep", "## Keep"):
                    with self.subTest(newline=newline, fence=fence, next_heading=next_heading):
                        prefix, trigger, suffix = legacy_identity_parts(newline)
                        fenced = newline.join((
                            fence + "text",
                            "# Example inside legacy reply",
                            "legacy-fenced-first-level-body",
                            "## Another example inside legacy reply",
                            "legacy-fenced-second-level-body",
                            fence,
                            "",
                            "### Still part of the legacy trigger",
                            "legacy-third-level-subsection-body",
                            "",
                            "",
                        ))
                        suffix = suffix.replace("## Work", next_heading, 1)
                        expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
                        composed = app.compose_prompt(prefix + trigger + fenced + suffix)
                        self.assertTrue(composed.startswith(expected_body))
                        self.assertEqual(composed, app.compose_prompt(expected_body))
                        self.assertIn(suffix, composed)
                        for removed in ("legacy-only-activation-reply", "legacy-fenced-first-level-body",
                                        "legacy-fenced-second-level-body", "legacy-third-level-subsection-body"):
                            self.assertNotIn(removed, composed)
                        self.assertNotIn(LEGACY_ASSISTANT_NAME, composed)
                        self.assertEqual(composed.count(app.BEGIN), 1)
                        self.assertEqual(composed.count(app.END), 1)
                        self.assertEqual(app.compose_prompt(composed), composed)

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
        result = subprocess.run([str(self.exe), *args, "--no-open", "--json"], env=self.env, cwd=self.root,
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
        first = self.run_exe("--install")
        self.assertEqual(first["version"], "1.3.4")
        self.assertEqual(first["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(first["assistant_name"], EXPECTED_ASSISTANT_NAME)
        self.assertEqual(first["expected_greeting"], EXPECTED_GREETING_REPLY)
        self.assertFalse(first["model_reply_verified"])
        content = Path(first["prompt_path"]).read_bytes().decode("utf-8")
        self.assertEqual(content.count(EXPECTED_REPLY), 1)
        self.assertEqual(content.count(EXPECTED_GREETING_REPLY), 1)
        self.assertNotIn(LEGACY_ASSISTANT_NAME, content)
        self.assertIn(app.TRIGGER_BLOCK, content)
        self.assertTrue(self.run_exe("--install")["unchanged"])
        self.assertIsNotNone(self.run_exe("--status")["profile"])
        self.assertTrue(self.run_exe("--restore")["restored"])
        self.assertFalse(self.run_exe("--restore")["restored"])

    def test_exe_repairs_external_reference_and_preserves_recovery_and_restore_baseline(self):
        self.home.mkdir(parents=True, exist_ok=True)
        original_source = self.home / "original 指令.md"
        original_source.write_bytes("original external prompt\n保留初始文件。\n".encode("utf-8"))
        original_source_before = (original_source.read_bytes(), original_source.stat().st_mtime_ns)
        config_path = self.home / "config.toml"
        original_config = (
            engine.KEY + " = " + json.dumps(original_source.as_posix(), ensure_ascii=False)
            + " # original reference\r\nmodel = 'fake-model-before'\r\n"
        ).encode("utf-8")
        config_path.write_bytes(original_config)
        first = self.run_exe("--install")
        self.assertEqual(first["version"], "1.3.4")
        self.assertFalse(first["reference_repaired"])
        self.assertIsNone(first["recovery_path"])
        old_prompt = Path(first["prompt_path"])
        old_prompt_before = (old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns)
        backup_path = Path(first["backup_path"])
        backup_before = (backup_path.read_bytes(), backup_path.stat().st_mtime_ns)
        self.assertEqual(backup_before[0], original_config)
        state_path = old_prompt.parent / "install-state.json"
        old_state_raw = state_path.read_bytes()

        source = self.home / "new external 指令.md"
        source.write_bytes("new external prompt sentinel\r\n保留新的外部文件。\r\n".encode("utf-8"))
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        current = engine.ConfigDocument(config_path.read_bytes())
        current_reference = (
            engine.KEY + " = " + json.dumps(source.as_posix(), ensure_ascii=False)
            + " # changed by another tool\r\n"
        )
        current_raw = current.replace(current_reference)
        config_path.write_bytes(current_raw)

        repaired = self.run_exe("--install")
        self.assertTrue(repaired["ok"])
        self.assertTrue(repaired["reference_repaired"])
        self.assertFalse(repaired["unchanged"])
        self.assertFalse(repaired["codex_open_requested"])
        self.assertFalse(repaired["model_reply_verified"])
        archive = Path(repaired["recovery_path"])
        self.assertEqual(archive.parent, old_prompt.parent / "history")
        self.assertEqual((archive / "install-state.json").read_bytes(), old_state_raw)
        self.assertEqual((archive / "config-before-repair.toml").read_bytes(), current_raw)
        self.assertEqual((archive / "config-before-first-install.bak").read_bytes(), original_config)
        self.assertEqual((archive / "prompts" / old_prompt.name).read_bytes(), old_prompt_before[0])
        target = Path(repaired["prompt_path"])
        self.assertNotEqual(target, old_prompt)
        self.assertEqual(target.read_bytes(), app.compose_prompt(source_before[0].decode("utf-8")).encode("utf-8"))
        state = json.loads(state_path.read_text("utf-8"))
        self.assertEqual(state["previous_line"], current_reference)
        self.assertEqual(state["recovery_path"], str(archive))
        self.assertEqual(state["owned_prompts"], {str(target): engine._sha(target.read_bytes())})
        self.assertEqual((backup_path.read_bytes(), backup_path.stat().st_mtime_ns), backup_before)
        self.assertEqual((old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns), old_prompt_before)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertEqual((original_source.read_bytes(), original_source.stat().st_mtime_ns), original_source_before)

        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        repeated = self.run_exe("--install")
        self.assertTrue(repeated["unchanged"])
        self.assertFalse(repeated["reference_repaired"])
        self.assertEqual(repeated["recovery_path"], str(archive))
        after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        archived_before = {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}
        self.assertTrue(self.run_exe("--restore")["restored"])
        self.assertEqual(config_path.read_bytes(), current_raw)
        self.assertFalse(target.exists())
        self.assertFalse(state_path.exists())
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertEqual((old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns), old_prompt_before)
        self.assertEqual({p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()},
                         archived_before)

    def test_exe_migrates_fresh_and_v132_prompts_without_changing_sources_or_restore_baseline(self):
        for existing_version in (None, "1.3.2"):
            with self.subTest(existing_version=existing_version):
                self.home.mkdir(parents=True, exist_ok=True)
                prefix, trigger, suffix = legacy_identity_parts("\r\n")
                body = prefix + trigger + suffix
                source = self.home / (LEGACY_ASSISTANT_NAME + " - 原始指令.md")
                source.write_bytes(body.encode("utf-8"))
                source_before = (source.read_bytes(), source.stat().st_mtime_ns)
                raw = (engine.KEY + " = " + json.dumps(source.as_posix(), ensure_ascii=False)
                       + "\r\nmodel = 'keep-model'\r\n").encode("utf-8")
                config_path = self.home / "config.toml"
                config_path.write_bytes(raw)
                store = app.ActivationStore(self.home)
                old_target = None
                if existing_version:
                    # Seed owned v1.3.2 bytes without running an old binary.
                    state = store.install_content(body + CHANNEL_QQ_TRIGGER_BLOCK, "旧版口令.md",
                                                  "小怪 · CMD 自动启用", "oneclick")
                    old_target = Path(state["prompt_path"])
                    self.assertIn(LEGACY_ASSISTANT_NAME, old_target.read_bytes().decode("utf-8"))
                first = self.run_exe("--install")
                target = Path(first["prompt_path"])
                content = target.read_bytes().decode("utf-8")
                expected_body = prefix.replace(LEGACY_ASSISTANT_NAME, EXPECTED_ASSISTANT_NAME) + suffix
                self.assertEqual(first["version"], "1.3.4")
                self.assertFalse(first["unchanged"])
                self.assertEqual(first["assistant_name"], EXPECTED_ASSISTANT_NAME)
                self.assertEqual(first["expected_greeting"], EXPECTED_GREETING_REPLY)
                self.assertEqual(first["expected_reply"], EXPECTED_REPLY)
                self.assertFalse(first["model_reply_verified"])
                self.assertTrue(content.startswith(expected_body))
                self.assertNotIn(LEGACY_ASSISTANT_NAME, content)
                self.assertNotIn("legacy-only-activation-reply", content)
                self.assertEqual(content.count(EXPECTED_GREETING_REPLY), 1)
                self.assertEqual(content.count(EXPECTED_REPLY), 1)
                self.assertEqual(content.count(app.BEGIN), 1)
                self.assertEqual(content.count(app.END), 1)
                if old_target:
                    self.assertEqual(target, old_target)
                    self.assertEqual(content, expected_body + app.TRIGGER_BLOCK)
                else:
                    self.assertEqual(content, app.compose_prompt(expected_body))
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
                self.assertEqual(store.backup_path.read_bytes(), raw)
                before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
                self.assertTrue(self.run_exe("--install")["unchanged"])
                after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.home.rglob("*") if p.is_file()}
                self.assertEqual(before, after)
                self.assertTrue(self.run_exe("--restore")["restored"])
                self.assertEqual(config_path.read_bytes(), raw)
                self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
                self.assertFalse(target.exists())
                self.assertFalse(store.backup_path.exists())
                self.assertFalse(store.state_path.exists())

    def test_cmd_real_install_and_uninstall(self):
        installed = self.run_cmd("启动小怪破甲.cmd")
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        result = json.loads(installed.stdout)
        self.assertTrue(result["config_installed"])
        self.assertEqual(result["expected_reply"], EXPECTED_REPLY)
        self.assertEqual(result["assistant_name"], EXPECTED_ASSISTANT_NAME)
        self.assertEqual(result["expected_greeting"], EXPECTED_GREETING_REPLY)
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
