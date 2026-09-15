from __future__ import annotations

import os
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import build_windows_package as app


class WindowsPackageTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="win-package-中文 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.assertEqual(self.root.parent, self.parent)
        self.source = self.root / "public-source"
        self.source.mkdir()
        self.output = self.root / "downloads" / app.PACKAGE_NAME
        for name in app.FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b"MZ synthetic fixture" if name.endswith(".exe") else b"@echo off\r\nexit /b 0\r\n" if name.endswith(".cmd") else b"# public fixture\n"
            path.write_bytes(raw)

    def tearDown(self):
        if self.root.parent != self.parent or not self.root.name.startswith("win-package-中文 空格-"):
            raise RuntimeError("Refusing cleanup outside the intended test root")
        self.temp.cleanup()

    def test_allowlist_is_unique_relative_and_has_both_new_modules_and_commands(self):
        self.assertEqual(len(app.FILES), len(set(app.FILES)))
        for name in app.FILES:
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn("..", Path(name).parts)
            self.assertNotIn(".codex", Path(name).parts)
        for name in ("task_support.py", "privacy_check.py", "准备ACE资料.cmd", "检查提示词暴露.cmd"):
            self.assertIn(name, app.FILES)

    def test_private_files_config_logs_and_backups_are_not_packaged(self):
        for name in (".codex/config.toml", "auth.json", "private-prompt.md", "history/config.bak", "private.log", "macos/private.txt"):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"PRIVATE_SENTINEL")
        result = app.build(self.source, self.output)
        self.assertEqual(result["file_count"], len(app.FILES))
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {app.PREFIX + name for name in app.FILES})
            self.assertTrue(all(b"PRIVATE_SENTINEL" not in archive.read(name) for name in archive.namelist()))

    def test_archive_bytes_crc_unicode_names_and_hash_are_verified(self):
        result = app.build(self.source, self.output)
        self.assertTrue(result["all_package_bytes_verified"])
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(app.verify_archive(self.output, app.snapshot(self.source)), result)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertTrue(all(info.flag_bits & 0x800 for info in archive.infolist()))

    def test_missing_file_is_rejected_before_output_is_created(self):
        (self.source / "task_support.py").unlink()
        with self.assertRaises(ValueError):
            app.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_linked_source_is_rejected_without_following_it(self):
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(ValueError):
                app.snapshot(self.source)

    def test_invalid_executable_header_is_rejected(self):
        (self.source / "小怪破甲安装器.exe").write_bytes(b"not an EXE")
        with self.assertRaisesRegex(ValueError, "header"):
            app.snapshot(self.source)

    def test_invalid_python_and_cmd_encoding_are_rejected(self):
        path = self.source / "task_support.py"
        path.write_bytes(b"not valid python !!!")
        with self.assertRaises(SyntaxError):
            app.snapshot(self.source)
        path.write_bytes(b"# restored\n")
        (self.source / "准备ACE资料.cmd").write_bytes(b"@echo off\nexit /b 0\n")
        with self.assertRaisesRegex(ValueError, "CRLF"):
            app.snapshot(self.source)

    def test_wrong_or_historical_output_filename_is_rejected(self):
        for name in ("xiaoguai-oneclick-v1.3.4.zip", "xiaoguai-oneclick-v1.4.0-mac.1.zip"):
            with self.assertRaises(ValueError):
                app.build(self.source, self.root / name)

    def test_existing_output_is_preserved_without_force(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b"existing release")
        with self.assertRaises(FileExistsError):
            app.build(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing release")

    def test_force_updates_only_current_output_and_keeps_old_release(self):
        self.output.parent.mkdir()
        old = self.output.parent / "xiaoguai-oneclick-v1.3.4.zip"
        old.write_bytes(b"old release")
        self.output.write_bytes(b"replace me")
        app.build(self.source, self.output, force=True)
        self.assertEqual(old.read_bytes(), b"old release")
        self.assertTrue(zipfile.is_zipfile(self.output))

    def test_publish_race_preserves_other_writer_and_removes_only_temporary_file(self):
        def raced(source, destination):
            destination.write_bytes(b"other writer")
            raise FileExistsError(destination)
        with patch.object(app.os, "link", side_effect=raced):
            with self.assertRaises(FileExistsError):
                app.build(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"other writer")
        self.assertFalse(list(self.output.parent.glob(".xiaoguai-win-*.zip")))

    def test_unexpected_archive_members_are_rejected(self):
        app.build(self.source, self.output)
        with zipfile.ZipFile(self.output, "a") as archive:
            archive.writestr(app.PREFIX + "auth.json", b"PRIVATE_SENTINEL")
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            app.verify_archive(self.output, app.snapshot(self.source))

    def test_cli_syntax_failure_is_json_without_source_text(self):
        stderr = io.StringIO()
        with patch.object(app, "build", side_effect=SyntaxError("PRIVATE_SOURCE_SENTINEL")), contextlib.redirect_stderr(stderr):
            code = app.main(["--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(stderr.getvalue())["ok"])
        self.assertNotIn("PRIVATE_SOURCE_SENTINEL", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
