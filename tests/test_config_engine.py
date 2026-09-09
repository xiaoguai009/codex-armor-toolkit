"""Standard-library regression tests; never use the real CODEX_HOME."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))
import config_engine as engine

TEST_ROOT = Path(os.environ.get("XIAOGUAI_TEST_ROOT", tempfile.gettempdir())).resolve()
TEST_ROOT.mkdir(parents=True, exist_ok=True)


class IsolatedTest(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="xiaoguai-test-", dir=TEST_ROOT)).resolve()
        self.addCleanup(self._cleanup)
        self.home = self.scratch / "Codex 中文 home"
        self.home.mkdir()
        self.store = engine.ConfigStore(self.home)
        self.config = self.store.config_path

    def _cleanup(self):
        target = self.scratch.resolve()
        if target.parent != TEST_ROOT or not target.name.startswith("xiaoguai-test-"):
            raise RuntimeError("Refusing to clean outside the isolated test root.")
        shutil.rmtree(target)

    def install(self, content="# 测试\n中文配置\n", title="中文工作档"):
        return self.store.install_content(content, "中文配置.md", title, "test")

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}


class ConfigurationTests(IsolatedTest):
    def test_new_home_roundtrip(self):
        state = self.install()
        parsed = engine.ConfigDocument(self.config.read_bytes()).data
        self.assertEqual(Path(parsed[engine.KEY]), Path(state["prompt_path"]))
        self.assertEqual(self.store.current_profile(), "中文工作档")
        self.assertTrue(self.store.restore())
        self.assertFalse(self.config.exists())
        self.assertFalse(self.store.state_path.exists())
        self.assertFalse(Path(state["prompt_path"]).exists())
        self.assertFalse(self.store.restore())

    def test_empty_existing_config_is_preserved(self):
        self.config.write_bytes(b"")
        self.install()
        self.store.restore()
        self.assertEqual(self.config.read_bytes(), b"")

    def test_original_bytes_roundtrip(self):
        cases = [
            b'# original\nmodel = "demo"\n',
            b'# original\r\nmodel = "demo"\r\n',
            engine.BOM + b'# original\r\nmodel = "demo"\r\n',
            b'model_instructions_file = "C:/old.md" # keep comment\nmodel = "demo"\n',
            b"'model_instructions_file' = 'C:/old.md'\r\n",
            b'"model_instructions_file" = "C:/old.md"',
            b'"model\\u005finstructions_file" = "C:/old.md"\n',
            b'model_instructions_file = """C:/old.md"""\n',
            b"model_instructions_file = '''\nC:/old.md'''\n",
            b'model = "demo"\n[profiles.local]\nmodel_instructions_file = "C:/section.md"\n',
            b'note = """\n[fake_table]\nmodel_instructions_file = "not-a-key"\n"""\n',
            b"note = '''\n[fake_table]\n'''\nmodel_instructions_file = 'C:/old.md'\n",
            b'items = [\n  "[not-a-table]", # comment\n  "value",\n]\n',
        ]
        for original in cases:
            with self.subTest(original=original):
                self.config.write_bytes(original)
                self.install()
                self.assertEqual(self.store.backup_path.read_bytes(), original)
                self.assertTrue(self.store.restore())
                self.assertEqual(self.config.read_bytes(), original)

    def test_section_key_is_untouched(self):
        section = b'[profiles.local]\r\nmodel_instructions_file = "C:/section.md"\r\n'
        self.config.write_bytes(section)
        self.install()
        installed = self.config.read_bytes()
        self.assertTrue(installed.endswith(section))
        data = engine.ConfigDocument(installed).data
        self.assertIn(engine.KEY, data)
        self.assertEqual(data["profiles"]["local"][engine.KEY], "C:/section.md")

    def test_switch_profiles_keeps_original_backup(self):
        original = b'model_instructions_file = "C:/old.md"\nmodel = "demo"\n'
        self.config.write_bytes(original)
        first = self.install("first", "档位一")
        self.install("second", "档位二")
        self.install("third", "档位三")
        self.assertEqual(self.store.backup_path.read_bytes(), original)
        self.assertEqual(self.store.current_profile(), "档位三")
        self.assertEqual(Path(first["prompt_path"]).read_text("utf-8"), "third")
        self.store.restore()
        self.assertEqual(self.config.read_bytes(), original)

    def test_unrelated_post_install_changes_survive_restore(self):
        original = b'model_instructions_file = "C:/old.md"\n'
        extra = b'\n[features]\nexample = true\n'
        self.config.write_bytes(original)
        self.install()
        self.config.write_bytes(self.config.read_bytes() + extra)
        self.store.restore()
        self.assertEqual(self.config.read_bytes(), original + extra)

    def test_new_config_with_later_settings_is_not_deleted(self):
        self.install()
        self.config.write_bytes(self.config.read_bytes() + b'model = "new"\n')
        self.store.restore()
        self.assertEqual(self.config.read_bytes(), b'model = "new"\n')

    def test_external_reference_change_blocks_install_and_restore(self):
        self.install()
        self.config.write_bytes(b'model_instructions_file = "C:/external.md"\n')
        before = self.snapshot()
        with self.assertRaises(engine.ConfigConflictError):
            self.install("replacement")
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(engine.ConfigConflictError):
            self.store.restore()
        self.assertEqual(self.snapshot(), before)

    def test_malformed_config_is_not_modified(self):
        for original in [b"invalid = [", b"invalid = '\xff'", b"model_instructions_file = 12\n"]:
            with self.subTest(original=original):
                self.config.write_bytes(original)
                before = self.snapshot()
                with self.assertRaises(engine.ConfigError):
                    self.install()
                self.assertEqual(self.snapshot(), before)

    def test_empty_prompt_and_bad_filename_are_rejected(self):
        for content in ["", " \n", "\ufeff\n"]:
            with self.assertRaises(engine.ConfigError):
                self.install(content)
        with self.assertRaises(engine.ConfigError):
            self.store.install_content("content", "../outside.md", "bad")
        self.assertFalse(self.config.exists())

    def test_utf8_bom_prompt_is_normalized(self):
        state = self.install("\ufeff# 中文\n内容\n")
        raw = Path(state["prompt_path"]).read_bytes()
        self.assertFalse(raw.startswith(engine.BOM))
        self.assertEqual(raw.decode("utf-8"), "# 中文\n内容\n")

    def test_corrupt_state_is_not_overwritten(self):
        self.install()
        self.store.state_path.write_bytes(b"{bad json")
        before = self.snapshot()
        with self.assertRaises(engine.ConfigError):
            self.install()
        with self.assertRaises(engine.ConfigError):
            self.store.restore()
        self.assertEqual(self.snapshot(), before)

    def test_state_cannot_delete_outside_managed_directory(self):
        state = self.install()
        outside = self.home / "keep.md"
        outside.write_text("keep", encoding="utf-8")
        state["prompt_path"] = str(outside)
        self.store.state_path.write_text(json.dumps(state), encoding="utf-8")
        before = self.snapshot()
        with self.assertRaises(engine.ConfigError):
            self.store.restore()
        self.assertEqual(self.snapshot(), before)

    def test_existing_orphan_backup_is_preserved(self):
        self.store.managed_dir.mkdir(parents=True)
        self.store.backup_path.write_bytes(b"original backup")
        before = self.snapshot()
        with self.assertRaises(engine.ConfigConflictError):
            self.install()
        self.assertEqual(self.snapshot(), before)

    def test_existing_prompt_is_not_overwritten(self):
        self.store.managed_dir.mkdir(parents=True)
        existing = self.store.managed_dir / "active.md"
        existing.write_text("user data", encoding="utf-8")
        state = self.install()
        self.assertNotEqual(existing, Path(state["prompt_path"]))
        self.store.restore()
        self.assertEqual(existing.read_text("utf-8"), "user data")

    def test_manually_edited_prompt_is_preserved_on_restore(self):
        state = self.install()
        target = Path(state["prompt_path"])
        target.write_text("manual edits", encoding="utf-8")
        self.store.restore()
        self.assertEqual(target.read_text("utf-8"), "manual edits")
        self.assertIn(str(target), self.store.retained_paths)

    def test_switch_does_not_overwrite_manually_edited_prompt(self):
        state = self.install()
        target = Path(state["prompt_path"])
        target.write_text("manual edits", encoding="utf-8")
        updated = self.install("new content")
        self.assertNotEqual(target, Path(updated["prompt_path"]))
        self.assertEqual(target.read_text("utf-8"), "manual edits")
        self.store.restore()
        self.assertEqual(target.read_text("utf-8"), "manual edits")
        self.assertIn(str(target), self.store.retained_paths)

    def test_install_lock_blocks_concurrent_operation(self):
        self.store.managed_dir.mkdir(parents=True)
        lock = self.store.managed_dir / "install.lock"
        lock.write_bytes(b"test-lock")
        before = self.snapshot()
        with self.assertRaises(engine.ConfigConflictError):
            self.install()
        self.assertEqual(self.snapshot(), before)

    def test_config_symlink_is_rejected(self):
        real_check = engine._is_link
        with patch.object(engine, "_is_link", side_effect=lambda p: p == self.config or real_check(p)):
            with self.assertRaises(engine.ConfigError):
                self.install()
        self.assertFalse(self.config.exists())

    def test_install_rolls_back_after_write_failure(self):
        self.config.write_bytes(b'model = "original"\n')
        before = self.snapshot()
        real_write = engine._atomic_write

        def fail_on_config(path, data):
            if path == self.config:
                raise OSError("simulated write failure")
            return real_write(path, data)

        with patch.object(engine, "_atomic_write", side_effect=fail_on_config):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(self.snapshot(), before)

    def test_restore_rolls_back_after_write_failure(self):
        self.config.write_bytes(b'model = "original"\n')
        self.install()
        before = self.snapshot()
        real_write = engine._atomic_write

        def fail_on_state_delete(path, data):
            if path == self.store.state_path and data is None:
                raise OSError("simulated write failure")
            return real_write(path, data)

        with patch.object(engine, "_atomic_write", side_effect=fail_on_state_delete):
            with self.assertRaises(OSError):
                self.store.restore()
        self.assertEqual(self.snapshot(), before)

    def test_rollback_does_not_overwrite_concurrent_edits(self):
        first = self.home / "first.txt"
        second = self.home / "second.txt"
        first.write_bytes(b"original")
        real_write = engine._atomic_write

        def edit_then_fail(path, data):
            if path == second:
                first.write_bytes(b"external edit")
                raise OSError("simulated failure")
            return real_write(path, data)

        with patch.object(engine, "_atomic_write", side_effect=edit_then_fail):
            with self.assertRaises(engine.ConfigError):
                engine._transaction([(first, b"tool edit"), (second, b"other")], {})
        self.assertEqual(first.read_bytes(), b"external edit")

    def test_restore_detects_prompt_edits_after_planning(self):
        state = self.install()
        target = Path(state["prompt_path"])
        installed = self.config.read_bytes()
        real_transaction = engine._transaction

        def edit_before_transaction(updates, expected):
            target.write_bytes(b"external edit")
            return real_transaction(updates, expected)

        with patch.object(engine, "_transaction", side_effect=edit_before_transaction):
            with self.assertRaises(engine.ConfigConflictError):
                self.store.restore()
        self.assertEqual(target.read_bytes(), b"external edit")
        self.assertEqual(self.config.read_bytes(), installed)
        self.assertTrue(self.store.state_path.exists())



if __name__ == "__main__":
    unittest.main()
