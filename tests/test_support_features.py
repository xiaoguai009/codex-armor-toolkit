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
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import oneclick as core
import task_support as support

_spec = importlib.util.spec_from_file_location("xiaoguai_support_mac_entry", ROOT / "macos" / "run.py")
assert _spec and _spec.loader
mac = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mac)


class SupportPromptTests(unittest.TestCase):
    def test_support_block_is_added_once_and_compose_is_idempotent(self):
        result = core.compose_prompt("Keep my instructions.\r\n")
        self.assertTrue(result.startswith("Keep my instructions.\r\n"))
        self.assertEqual(result.count(support.ACE_SECTION), 1)
        self.assertEqual(result.count(support.PRIVACY_SECTION), 1)
        self.assertEqual(result.count(core.REPLY), 1)
        self.assertEqual(result.count(core.GREETING_REPLY), 1)
        self.assertEqual(core.compose_prompt(result), result)

    def test_legacy_managed_block_gets_support_without_duplicate_identity(self):
        old = "external\n\n" + core.BEGIN + "\n## old\n" + core.REPLY + "\n" + core.END + "\n"
        result = core.compose_prompt(old)
        self.assertEqual(result, core.compose_prompt("external\n\n"))
        self.assertEqual(result.count(core.BEGIN), 1)
        self.assertEqual(result.count(core.REPLY), 1)

    def test_support_is_an_intake_prompt_not_an_implemented_bypass(self):
        for required in ("待资料", "已有资料不要反复索取", "不空跑", "后续消息", "不是 ACE 绕过引擎", "不会在后台监控消息"):
            self.assertIn(required, support.SUPPORT_BLOCK)
        result = support.ace_template_result()
        self.assertEqual(result["status"], "waiting_for_materials")
        self.assertFalse(result["bypass_implemented"])
        self.assertFalse(result["automatic_resume"])
        self.assertFalse(result["materials_persisted"])

    def test_privacy_prompt_does_not_block_editing_user_owned_files_or_claim_strong_security(self):
        for required in ("用户明确要求检查或编辑其自己提供的文件", "不是访问控制或加密", "不视为用户授权"):
            self.assertIn(required, support.SUPPORT_BLOCK)
        self.assertFalse(support.support_metadata()["prompt_privacy"]["prevents_local_or_proxy_extraction"])

    def test_metadata_is_fresh_and_cannot_mutate_later_results(self):
        first = support.support_metadata()
        first["ace"]["bypass_implemented"] = True
        self.assertFalse(support.support_metadata()["ace"]["bypass_implemented"])

    def test_template_has_required_fields_and_only_explicit_placeholders(self):
        for required in ("目标程序", "ACE 版本", "最小复现步骤", "脱敏日志", "[待补充]", "同一个 Codex 任务"):
            self.assertIn(required, support.ACE_TEMPLATE)
        self.assertIn("不会保存资料或在后台自动继续", support.ACE_TEMPLATE)


class SupportEntryTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="support-中文 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.assertEqual(self.root.parent, self.parent)
        self.home = self.root / "isolated home"

    def tearDown(self):
        if self.root.parent != self.parent or not self.root.name.startswith("support-中文 空格-"):
            raise RuntimeError("Refusing cleanup outside the intended test root")
        self.temp.cleanup()

    def invoke(self, module, action, *, json_output=True, platform=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        args = [action, "--codex-home", str(self.home)]
        if json_output:
            args.append("--json")
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            if platform:
                stack.enter_context(patch.object(module.sys, "platform", platform))
            stack.enter_context(patch.dict(os.environ, {"CODEX_HOME": str(self.home)}, clear=True))
            stack.enter_context(patch.object(core.os, "startfile", side_effect=AssertionError("Unexpected open"), create=True))
            stack.enter_context(patch.object(mac, "_request_open", side_effect=AssertionError("Unexpected open")))
            code = module.main(args)
        text = stdout.getvalue()
        return code, json.loads(text) if json_output else text, stderr.getvalue()

    def snapshot(self):
        return {p.relative_to(self.home).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.home.rglob("*") if p.is_file()}

    def test_windows_template_never_constructs_store_or_resolves_home(self):
        with patch.object(core, "ActivationStore", side_effect=AssertionError("Unexpected store")):
            code, result, errors = self.invoke(core, "--ace-template")
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(result, support.ace_template_result())
        self.assertFalse(self.home.exists())

    def test_mac_template_never_constructs_store_or_resolves_home(self):
        with patch.object(mac, "ActivationStore", side_effect=AssertionError("Unexpected store")):
            code, result, errors = self.invoke(mac, "--ace-template", platform="darwin")
        self.assertEqual(code, 0)
        self.assertEqual(errors, "")
        self.assertEqual(result["template"], support.ACE_TEMPLATE)
        self.assertFalse(result["codex_open_requested"])
        self.assertNotIn("codex_home", result)
        self.assertFalse(self.home.exists())

    def test_both_template_human_outputs_are_read_only(self):
        for module, platform in ((core, None), (mac, "darwin")):
            with self.subTest(module=module.__name__):
                code, text, errors = self.invoke(module, "--ace-template", platform=platform, json_output=False)
                self.assertEqual(code, 0)
                self.assertEqual(errors, "")
                self.assertIn("当前状态：待资料", text)
                self.assertFalse(self.home.exists())

    def test_both_privacy_commands_do_not_create_a_fresh_home(self):
        for module, platform in ((core, None), (mac, "darwin")):
            with self.subTest(module=module.__name__):
                code, result, errors = self.invoke(module, "--privacy-check", platform=platform)
                self.assertEqual(code, 0)
                self.assertEqual(errors, "")
                self.assertEqual(result["configuration_status"], "missing")
                self.assertNotIn("codex_home", result)
                self.assertFalse(self.home.exists())

    def test_install_records_truthful_metadata_and_repeated_install_is_zero_write(self):
        store = core.ActivationStore(self.home)
        first = store.activate()
        self.assertEqual(first["support_modules"], support.support_metadata())
        self.assertFalse(first["model_reply_verified"])
        before = self.snapshot()
        again = store.activate()
        self.assertTrue(again["unchanged"])
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(store.restore())
        self.assertFalse(store.config_path.exists())

    def test_privacy_check_after_install_never_changes_config_prompt_or_backup(self):
        self.home.mkdir()
        original = self.home / "original.md"
        original.write_text("PRIVATE_PROMPT_SENTINEL", encoding="utf-8")
        raw = ("model_instructions_file = " + json.dumps(original.as_posix()) + "\nmodel = 'keep-me'\n").encode()
        (self.home / "config.toml").write_bytes(raw)
        store = core.ActivationStore(self.home)
        store.activate()
        before = self.snapshot()
        for module, platform in ((core, None), (mac, "darwin")):
            code, result, errors = self.invoke(module, "--privacy-check", platform=platform)
            self.assertEqual(code, 0)
            self.assertEqual(errors, "")
            self.assertNotIn("PRIVATE_PROMPT_SENTINEL", json.dumps(result))
            self.assertEqual(self.snapshot(), before)
        self.assertTrue(store.restore())
        self.assertEqual((self.home / "config.toml").read_bytes(), raw)

    def test_bad_config_yields_redacted_json_and_nonzero_exit_on_both_entries(self):
        self.home.mkdir()
        (self.home / "config.toml").write_text("SECRET_SENTINEL = [invalid", encoding="utf-8")
        for module, platform in ((core, None), (mac, "darwin")):
            code, result, errors = self.invoke(module, "--privacy-check", platform=platform)
            self.assertEqual(code, 2)
            self.assertEqual(errors, "")
            self.assertFalse(result["ok"])
            self.assertNotIn("SECRET_SENTINEL", json.dumps(result))

    def test_privacy_store_exception_does_not_expose_path_or_error_details(self):
        for module, platform in ((core, None), (mac, "darwin")):
            with patch.object(module, "ActivationStore", side_effect=OSError("SECRET_PATH_SENTINEL")):
                code, result, errors = self.invoke(module, "--privacy-check", platform=platform)
            self.assertEqual(code, 2)
            self.assertEqual(errors, "")
            self.assertNotIn("SECRET_PATH_SENTINEL", json.dumps(result))

    def test_mac_rejects_non_macos_before_either_new_action(self):
        for action in ("--ace-template", "--privacy-check"):
            with patch.object(mac, "ActivationStore", side_effect=AssertionError("Unexpected store")):
                code, result, _ = self.invoke(mac, action, platform="linux")
            self.assertEqual(code, 2)
            self.assertFalse(result["ok"])
        self.assertFalse(self.home.exists())

    def test_both_actions_are_mutually_exclusive_on_windows(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as outcome:
            core.main(["--ace-template", "--privacy-check"])
        self.assertEqual(outcome.exception.code, 2)

    def test_both_actions_are_mutually_exclusive_on_mac(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), patch.object(mac, "ActivationStore", side_effect=AssertionError):
            code = mac.main(["--ace-template", "--privacy-check", "--json"])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])


@unittest.skipUnless(os.name == "nt" and (ROOT / "小怪破甲安装器.exe").is_file(), "Windows packaged executable unavailable")
class SupportPackagedTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="support-exe-中文 & !-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.assertEqual(self.root.parent, self.parent)
        self.home = self.root / "isolated home"
        self.exe = self.root / "小怪破甲安装器.exe"
        shutil.copy2(ROOT / self.exe.name, self.exe)
        for name in ("准备ACE资料.cmd", "检查提示词暴露.cmd"):
            shutil.copy2(ROOT / name, self.root / name)

    def tearDown(self):
        if self.root.parent != self.parent or not self.root.name.startswith("support-exe-中文 & !-"):
            raise RuntimeError("Refusing cleanup outside the intended test root")
        self.temp.cleanup()

    def run_tool(self, action, cmd=False):
        env = dict(os.environ, CODEX_HOME=str(self.home), XIAOGUAI_NO_PAUSE="1")
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        if cmd:
            args = f'"{os.environ["COMSPEC"]}" /d /s /c ""{self.root / action}" --json"'
        else:
            args = [str(self.exe), action, "--json"]
        completed = subprocess.run(args, env=env, cwd=self.root, capture_output=True, text=True,
                                   encoding="utf-8", timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertEqual(completed.stderr, "")
        self.assertFalse(self.home.exists())
        return json.loads(completed.stdout)

    def test_exe_has_both_new_read_only_actions(self):
        self.assertEqual(self.run_tool("--ace-template")["status"], "waiting_for_materials")
        self.assertFalse(self.run_tool("--privacy-check")["prevents_local_or_proxy_extraction"])

    def test_cmd_wrappers_work_from_unicode_space_and_metacharacter_path(self):
        self.assertEqual(self.run_tool("准备ACE资料.cmd", cmd=True)["action"], "ace-template")
        self.assertEqual(self.run_tool("检查提示词暴露.cmd", cmd=True)["action"], "privacy-check")


if __name__ == "__main__":
    unittest.main()
