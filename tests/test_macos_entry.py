from __future__ import annotations

import contextlib
import importlib.util
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
ENTRY = ROOT / "macos" / "run.py"
sys.path.insert(0, str(ROOT))
import config_engine as engine
import oneclick as core

_spec = importlib.util.spec_from_file_location("xiaoguai_macos_entry", ENTRY)
assert _spec and _spec.loader
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)
_DEFAULT_HOME = object()


class MacEntryTests(unittest.TestCase):
    """Use temporary fixtures only; every in-process open request is mocked."""

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="mac-entry-中文 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Test directory is outside the intended test root.")
        self.home = self.root / "隔离 配置"
        self.config_path = self.home / "config.toml"
        self.managed_dir = self.home / "managed-prompts" / "xiaoguai-oneclick"
        self.state_path = self.managed_dir / "install-state.json"
        self.backup_path = self.managed_dir / "config.toml.before-oneclick.bak"
        self.environment = patch.dict(os.environ, {"CODEX_HOME": str(self.root / "环境 默认 配置")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("mac-entry-中文 空格-"):
            raise RuntimeError("Refusing to clean a directory outside the test root.")
        self.temp.cleanup()

    def call(self, *args, home=_DEFAULT_HOME, platform="darwin", no_open=True,
             json_output=True, open_result=None, open_error=None):
        arguments = list(args)
        if home is _DEFAULT_HOME:
            home = self.home
        if home is not None:
            arguments.extend(["--codex-home", str(home)])
        if no_open:
            arguments.append("--no-open")
        if json_output:
            arguments.append("--json")
        stdout, stderr = io.StringIO(), io.StringIO()
        if open_result is None:
            open_result = subprocess.CompletedProcess(app.OPEN_COMMAND, 0, "", "")
        with (patch.object(app.sys, "platform", platform),
              patch.object(app.subprocess, "run", return_value=open_result, side_effect=open_error) as opened,
              contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr)):
            code = app.main(arguments)
        text, errors = stdout.getvalue(), stderr.getvalue()
        if json_output:
            self.assertEqual(errors, "", errors)
            result = json.loads(text)
            self.assertIsInstance(result, dict)
            self.assertEqual(len(text.splitlines()), 1, "JSON output must be exactly one object, without progress text")
            self.assertEqual(result["platform"], "macos")
            self.assertEqual(result["edition_version"], "1.4.0-mac.1")
            self.assertEqual(result["version"], "1.4.0")
            return code, result, opened
        return code, text, errors, opened

    def configure(self):
        self.home.mkdir(parents=True, exist_ok=True)
        source = self.home / "原来 中文 指令.md"
        source.write_bytes("保留原始说明。\r\n".encode("utf-8"))
        raw = ("# fixture-only configuration\r\n" + engine.KEY + " = "
               + json.dumps(source.as_posix(), ensure_ascii=False) + " # 原引用\r\n"
               + "model = 'fixture-only-model'\r\n[profiles.keep]\r\nmodel = 'fixture-profile'\r\n").encode("utf-8")
        self.config_path.write_bytes(raw)
        return source, raw

    def snapshot(self, directory=None):
        directory = self.home if directory is None else directory
        return {path.relative_to(directory).as_posix():
                (path.read_bytes(), path.stat().st_mtime_ns) if path.is_file() else None
                for path in directory.rglob("*")}

    def test_default_action_installs_exact_identity_and_metadata(self):
        code, result, opened = self.call()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "install")
        self.assertTrue(result["config_installed"])
        self.assertFalse(result["model_reply_verified"])
        self.assertFalse(result["codex_open_requested"])
        self.assertEqual(result["assistant_name"], "小怪")
        self.assertEqual(result["expected_greeting"], "「你好」\n小怪在。👋")
        self.assertEqual(result["expected_reply"], core.REPLY)
        self.assertEqual(result["codex_home"], str(self.home))
        self.assertFalse(result["reference_repaired"])
        self.assertIsNone(result["recovery_path"])
        prompt = Path(result["prompt_path"])
        self.assertIn(core.TRIGGER_BLOCK, prompt.read_text(encoding="utf-8"))
        self.assertEqual(tomllib.loads(self.config_path.read_text(encoding="utf-8"))[engine.KEY], prompt.as_posix())
        opened.assert_not_called()

    def test_explicit_install_preserves_existing_source_and_backup(self):
        source, raw = self.configure()
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        code, result, opened = self.call("--install")
        self.assertEqual(code, 0)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertEqual(self.backup_path.read_bytes(), raw)
        self.assertEqual(result["backup_path"], str(self.backup_path))
        self.assertEqual(tomllib.loads(self.config_path.read_text(encoding="utf-8"))["model"], "fixture-only-model")
        self.assertTrue(Path(result["prompt_path"]).read_bytes().startswith(source_before[0]))
        opened.assert_not_called()

    def test_status_fresh_is_read_only_and_does_not_open(self):
        self.assertFalse(self.home.exists())
        code, result, opened = self.call("--status", no_open=False)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIsNone(result["profile"])
        self.assertFalse(result["codex_open_requested"])
        self.assertFalse(self.home.exists())
        opened.assert_not_called()

    def test_installed_status_is_read_only_and_does_not_open(self):
        self.call()
        before = self.snapshot()
        code, result, opened = self.call("--status", no_open=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "status")
        self.assertIsNotNone(result["profile"])
        self.assertEqual(before, self.snapshot())
        self.assertFalse(result["codex_open_requested"])
        opened.assert_not_called()

    def test_restore_restores_original_reference_and_other_settings(self):
        source, raw = self.configure()
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        _, installed, _ = self.call()
        code, result, opened = self.call("--restore", no_open=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["action"], "restore")
        self.assertTrue(result["restored"])
        self.assertEqual(result["retained_paths"], [])
        self.assertEqual(self.config_path.read_bytes(), raw)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assertFalse(Path(installed["prompt_path"]).exists())
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.backup_path.exists())
        self.assertFalse(result["codex_open_requested"])
        opened.assert_not_called()

    def test_restore_without_record_is_read_only(self):
        code, result, opened = self.call("--restore", no_open=False)
        self.assertEqual(code, 0)
        self.assertFalse(result["restored"])
        self.assertFalse(self.home.exists())
        self.assertFalse(result["codex_open_requested"])
        opened.assert_not_called()

    def test_repeated_install_is_byte_and_timestamp_preserving(self):
        self.configure()
        self.call()
        before = self.snapshot()
        code, result, opened = self.call("--install")
        self.assertEqual(code, 0)
        self.assertTrue(result["unchanged"])
        self.assertEqual(before, self.snapshot())
        opened.assert_not_called()

    def test_reference_repair_archives_old_state_and_restores_current_relative_reference(self):
        source, initial_raw = self.configure()
        initial_source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        _, installed, _ = self.call()
        old_prompt = Path(installed["prompt_path"])
        old_prompt_before = (old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns)
        old_state = self.state_path.read_bytes()
        backup_before = (self.backup_path.read_bytes(), self.backup_path.stat().st_mtime_ns)
        current_source = self.home / "新的 中文 配置.md"
        current_source.write_bytes("保留新来源。\n".encode("utf-8"))
        current_source_before = (current_source.read_bytes(), current_source.stat().st_mtime_ns)
        current_line = engine.KEY + " = " + json.dumps(current_source.name, ensure_ascii=False) + " # 修改后的引用\r\n"
        current_raw = engine.ConfigDocument(self.config_path.read_bytes()).replace(current_line)
        self.config_path.write_bytes(current_raw)
        code, repaired, opened = self.call()
        self.assertEqual(code, 0)
        self.assertTrue(repaired["reference_repaired"])
        self.assertFalse(repaired["unchanged"])
        archive = Path(repaired["recovery_path"])
        self.assertEqual(archive.parent, self.managed_dir / "history")
        self.assertEqual((archive / "install-state.json").read_bytes(), old_state)
        self.assertEqual((archive / "config-before-repair.toml").read_bytes(), current_raw)
        self.assertEqual((archive / "config-before-first-install.bak").read_bytes(), initial_raw)
        self.assertEqual((archive / "prompts" / old_prompt.name).read_bytes(), old_prompt_before[0])
        new_prompt = Path(repaired["prompt_path"])
        self.assertNotEqual(new_prompt, old_prompt)
        self.assertTrue(new_prompt.read_bytes().startswith(current_source_before[0]))
        self.assertEqual((self.backup_path.read_bytes(), self.backup_path.stat().st_mtime_ns), backup_before)
        self.assertEqual((old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns), old_prompt_before)
        self.assertEqual((current_source.read_bytes(), current_source.stat().st_mtime_ns), current_source_before)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), initial_source_before)
        opened.assert_not_called()
        before = self.snapshot()
        self.assertTrue(self.call()[1]["unchanged"])
        self.assertEqual(before, self.snapshot())
        archive_before = self.snapshot(archive)
        self.assertTrue(self.call("--restore")[1]["restored"])
        self.assertEqual(self.config_path.read_bytes(), current_raw)
        self.assertTrue(current_source.exists())
        self.assertFalse(new_prompt.exists())
        self.assertEqual((old_prompt.read_bytes(), old_prompt.stat().st_mtime_ns), old_prompt_before)
        self.assertEqual(self.snapshot(archive), archive_before)

    def test_restore_conflict_leaves_current_configuration_and_backup_untouched(self):
        self.configure()
        self.call()
        self.config_path.write_bytes(b"model_instructions_file = 'external.md'\n")
        before = self.snapshot()
        code, result, opened = self.call("--restore", no_open=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertIn("已被其他操作更改", result["error"])
        self.assertFalse(result["codex_open_requested"])
        self.assertEqual(self.snapshot(), before)
        opened.assert_not_called()

    def test_environment_home_is_delegated_to_shared_store(self):
        expected = Path(os.environ["CODEX_HOME"])
        code, result, _ = self.call(home=None)
        self.assertEqual(code, 0)
        self.assertEqual(result["codex_home"], str(expected))
        self.assertTrue((expected / "config.toml").exists())
        self.assertFalse(self.home.exists())

    def test_explicit_home_takes_precedence_over_environment(self):
        ignored_home = Path(os.environ["CODEX_HOME"])
        code, result, _ = self.call()
        self.assertEqual(code, 0)
        self.assertEqual(result["codex_home"], str(self.home))
        self.assertFalse(ignored_home.exists())

    def test_fallback_home_is_mocked_and_never_reads_real_codex_home(self):
        fake_user_home = self.root / "假的 用户主目录"
        with patch.dict(os.environ, {"CODEX_HOME": ""}), patch.object(Path, "home", return_value=fake_user_home):
            code, result, _ = self.call(home=None)
        self.assertEqual(code, 0)
        self.assertEqual(result["codex_home"], str(fake_user_home / ".codex"))
        self.assertTrue((fake_user_home / ".codex" / "config.toml").exists())

    def test_non_macos_actions_never_construct_store_or_write(self):
        self.configure()
        before = self.snapshot(self.root)
        for platform in ("win32", "linux"):
            for action in ("--install", "--status", "--restore"):
                with self.subTest(platform=platform, action=action), patch.object(app, "ActivationStore") as store:
                    code, result, opened = self.call(action, platform=platform, no_open=False)
                self.assertEqual(code, 2)
                self.assertFalse(result["ok"])
                self.assertIn("仅支持 macOS", result["error"])
                self.assertFalse(result["codex_open_requested"])
                store.assert_not_called()
                opened.assert_not_called()
                self.assertEqual(before, self.snapshot(self.root))

    def test_non_macos_default_home_is_never_resolved(self):
        with patch.object(Path, "home", side_effect=AssertionError("Must not inspect actual home")):
            code, result, opened = self.call(platform="linux", home=None, no_open=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertFalse(self.home.exists())
        self.assertFalse(Path(os.environ["CODEX_HOME"]).exists())
        opened.assert_not_called()

    def test_open_success_uses_exact_mac_command_and_marks_request(self):
        code, result, opened = self.call(no_open=False)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["codex_open_requested"])
        self.assertNotIn("open_error", result)
        opened.assert_called_once_with(["/usr/bin/open", "-a", "Codex"], timeout=15,
                                       capture_output=True, text=True)

    def test_open_nonzero_is_visible_without_undoing_configuration(self):
        for stdout, stderr, expected in (("", "Codex not found", "Codex not found"),
                                         ("stdout detail", "", "stdout detail"),
                                         ("", "", "退出码 1")):
            with self.subTest(stderr=stderr, stdout=stdout):
                code, result, opened = self.call(no_open=False, open_result=
                                               subprocess.CompletedProcess(app.OPEN_COMMAND, 1, stdout, stderr))
                self.assertEqual(code, 0)
                self.assertTrue(result["ok"])
                self.assertTrue(result["config_installed"])
                self.assertFalse(result["codex_open_requested"])
                self.assertIn(expected, result["open_error"])
                self.assertTrue(self.config_path.exists())
                self.assertTrue(self.state_path.exists())
                self.assertTrue(Path(result["prompt_path"]).exists())
                opened.assert_called_once()

    def test_open_os_error_is_visible_and_keeps_installed_files(self):
        self.configure()
        _, first, _ = self.call()
        before = self.snapshot()
        code, result, opened = self.call(no_open=False, open_error=OSError("isolated open error"))
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["codex_open_requested"])
        self.assertIn("isolated open error", result["open_error"])
        self.assertEqual(result["prompt_path"], first["prompt_path"])
        self.assertEqual(before, self.snapshot())
        opened.assert_called_once()

    def test_open_timeout_keeps_successful_configuration(self):
        code, result, opened = self.call(no_open=False, open_error=subprocess.TimeoutExpired(app.OPEN_COMMAND, 15))
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["codex_open_requested"])
        self.assertIn("超时", result["open_error"])
        self.assertIn("15", result["open_error"])
        self.assertTrue(self.config_path.exists())
        self.assertTrue(Path(result["prompt_path"]).exists())
        opened.assert_called_once()

    def test_open_output_decode_error_does_not_turn_install_into_failure(self):
        error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "fixture decode error")
        code, result, _ = self.call(no_open=False, open_error=error)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertFalse(result["codex_open_requested"])
        self.assertIn("fixture decode error", result["open_error"])
        self.assertTrue(Path(result["prompt_path"]).exists())

    def test_invalid_configuration_never_requests_open_or_writes(self):
        self.home.mkdir()
        self.config_path.write_bytes(b"not valid toml")
        before = self.snapshot()
        code, result, opened = self.call(no_open=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertIn("UTF-8 TOML", result["error"])
        self.assertFalse(result["codex_open_requested"])
        self.assertEqual(before, self.snapshot())
        opened.assert_not_called()

    def test_invalid_arguments_emit_single_json_object_and_never_write(self):
        for arguments in (("--install", "--status"), ("--restore", "--status"), ("--unknown",)):
            with self.subTest(arguments=arguments), patch.object(app, "ActivationStore") as store:
                code, result, opened = self.call(*arguments, no_open=False)
                self.assertEqual(code, 2)
                self.assertFalse(result["ok"])
                self.assertIn("参数错误", result["error"])
                self.assertFalse(result["codex_open_requested"])
                self.assertFalse(self.home.exists())
                store.assert_not_called()
                opened.assert_not_called()

    def test_human_install_has_identity_backup_and_visible_open_error(self):
        self.configure()
        code, output, errors, _ = self.call(no_open=False, json_output=False, open_error=OSError("fixture error"))
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn("macOS 独立版 1.4.0-mac.1", output)
        self.assertIn(core.GREETING_REPLY, output)
        self.assertIn(core.REPLY, output)
        self.assertIn(str(self.backup_path), output)
        self.assertIn("fixture error", output)
        self.assertIn("本地配置已保留", output)

    def test_human_restore_reports_completion_and_retained_manual_prompt(self):
        self.configure()
        _, installed, _ = self.call()
        prompt = Path(installed["prompt_path"])
        prompt.write_bytes(prompt.read_bytes() + "手动增加的说明。\n".encode("utf-8"))
        code, output, errors, opened = self.call("--restore", json_output=False, no_open=False)
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn("已恢复本次安装前的配置引用", output)
        self.assertIn("保留手动修改的文件：" + str(prompt), output)
        self.assertTrue(prompt.exists())
        opened.assert_not_called()

    def test_human_reference_repair_reports_history_location(self):
        source, _ = self.configure()
        self.call()
        current = engine.ConfigDocument(self.config_path.read_bytes())
        self.config_path.write_bytes(current.installed(source))
        code, output, errors, _ = self.call(json_output=False)
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertIn("已按当前引用修复旧安装记录", output)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("本次修复历史备份：" + state["recovery_path"], output)

    def copied_entry(self):
        release = self.root / "独立 下载 Mac 版"
        (release / "macos").mkdir(parents=True)
        for filename in ("oneclick.py", "config_engine.py", "task_support.py", "privacy_check.py"):
            shutil.copy2(ROOT / filename, release / filename)
        target = release / "macos" / "run.py"
        shutil.copy2(ENTRY, target)
        return release, target

    def run_copied_entry(self, entry, action, platform):
        unrelated_cwd = self.root / "无关 工作目录"
        unrelated_cwd.mkdir(exist_ok=True)
        argv = [str(entry), action, "--codex-home", str(self.home), "--no-open", "--json"]
        code = ("import runpy, sys\n"
                + "sys.platform = " + repr(platform) + "\n"
                + "sys.argv = " + repr(argv) + "\n"
                + "runpy.run_path(" + repr(str(entry)) + ", run_name='__main__')\n")
        # -I removes inherited module paths; --no-open prevents actual app launch.
        flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = subprocess.run([sys.executable, "-B", "-I", "-c", code], cwd=unrelated_cwd,
                                 env=dict(os.environ, CODEX_HOME=str(self.root / "unused isolated home")),
                                 capture_output=True, encoding="utf-8", timeout=30, **flags)
        self.assertEqual(process.stderr, "", process.stderr)
        return process.returncode, json.loads(process.stdout)

    def test_copied_chinese_space_release_works_from_independent_cwd(self):
        release, entry = self.copied_entry()
        for action in ("--install", "--status", "--ace-template", "--privacy-check", "--restore"):
            with self.subTest(action=action):
                code, result = self.run_copied_entry(entry, action, "darwin")
                self.assertEqual(code, 0, result)
                self.assertTrue(result["ok"])
                self.assertEqual(result["action"], action[2:])
                self.assertEqual(result["edition_version"], "1.4.0-mac.1")
                self.assertFalse(result["codex_open_requested"])
        self.assertFalse(self.config_path.exists())
        self.assertEqual(list(release.rglob("__pycache__")), [])

    def test_copied_entry_rejects_non_mac_without_creating_configuration_or_cache(self):
        release, entry = self.copied_entry()
        before = self.snapshot(release)
        code, result = self.run_copied_entry(entry, "--install", "linux")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertFalse(result["codex_open_requested"])
        self.assertFalse(self.home.exists())
        self.assertEqual(before, self.snapshot(release))


if __name__ == "__main__":
    unittest.main()
