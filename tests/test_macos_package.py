from __future__ import annotations

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
import stat
import struct
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path, PurePosixPath
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "macos" / "build_package.py"
_spec = importlib.util.spec_from_file_location("xiaoguai_macos_package", BUILDER)
assert _spec and _spec.loader
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


class MacPackageTests(unittest.TestCase):
    """All package inputs and outputs are synthetic files below one temp root."""

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="mac-package-中文 space $-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Package test directory is outside the intended test root.")
        self.source = self.root / "synthetic source"
        self.source.mkdir()
        self.output = self.root / "downloads" / app.PACKAGE_NAME
        self.originals = {}
        for source, destination in app.FILES.items():
            if source.endswith(".py"):
                content = "# UTF-8 fixture; never executed.\nSOURCE = " + repr(source) + "\n"
            elif destination.endswith((".sh", ".command")):
                content = "#!/bin/bash\n# synthetic fixture: " + source + "\nexit 0\n"
            else:
                content = "# Synthetic source: " + source + "\n小怪 Mac 测试内容。\n"
            raw = content.encode("utf-8")
            path = self.source / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.originals[destination] = raw

    def tearDown(self):
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("mac-package-中文 space $-"):
            raise RuntimeError("Refusing to clean a directory outside the package test root.")
        self.temp.cleanup()

    def make_archive(self, files=None, *, omitted=(), extra=(), duplicates=(), modes=None, systems=None):
        """Construct valid stored ZIPs that individual tests can tamper with."""
        if files is None:
            files = self.originals
        modes, systems = modes or {}, systems or {}
        self.output.parent.mkdir(parents=True, exist_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.output, "w", compression=zipfile.ZIP_STORED) as archive:
                items = [(name, raw) for name, raw in files.items() if name not in omitted]
                items.extend(extra)
                items.extend((name, files[name]) for name in duplicates)
                for name, raw in items:
                    info = zipfile.ZipInfo(app.PREFIX + name)
                    info.create_system = systems.get(name, 3)
                    info.external_attr = modes.get(name, stat.S_IFREG | app.file_mode(name)) << 16
                    archive.writestr(info, raw)
        return self.output

    def assert_no_temporary_archives(self):
        self.assertFalse(list(self.output.parent.glob(".xiaoguai-mac-*.zip")))

    def test_allow_list_is_relative_unique_and_excludes_windows_artifacts(self):
        self.assertEqual(len(app.FILES.values()), len(set(app.FILES.values())))
        for source, destination in app.FILES.items():
            with self.subTest(source=source):
                for name in (source, destination):
                    self.assertFalse(PurePosixPath(name).is_absolute())
                    self.assertNotIn("..", PurePosixPath(name).parts)
                    self.assertFalse(name.lower().endswith((".exe", ".cmd")))
                    self.assertNotIn(".codex", PurePosixPath(name).parts)
        self.assertEqual(app.FILES["macos/README.md"], "README.md")
        self.assertEqual(app.FILES["macos/验证记录.txt"], "验证记录.txt")

    def test_snapshot_uses_only_allow_list_not_repository_or_user_files(self):
        for name in [".codex/config.toml", "private-token.txt", "小怪破甲安装器.exe", "启动小怪破甲.cmd", "macos/cache/python3", "macos/private.log"]:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not packaged\x00\xff\r\n")
        self.assertEqual(app.snapshot(self.source), self.originals)
        app.build(self.source, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {app.PREFIX + name for name in self.originals})

    def test_missing_allow_list_source_is_rejected(self):
        (self.source / "macos/验证记录.txt").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            app.snapshot(self.source)

    def test_directory_in_place_of_source_is_rejected(self):
        path = self.source / "oneclick.py"
        path.unlink()
        path.mkdir()
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            app.snapshot(self.source)

    def test_direct_source_symlink_is_rejected(self):
        target = self.root / "outside-source.py"
        target.write_bytes(b"MARKER = 'outside'\n")
        path = self.source / "oneclick.py"
        path.unlink()
        try:
            path.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Symlink creation unavailable on this host: " + str(exc))
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            app.snapshot(self.source)

    def test_parent_directory_junction_or_symlink_outside_source_root_is_rejected(self):
        linked_directory = self.source / "macos"
        outside_directory = self.root / "outside source root"
        self.assertTrue(linked_directory.resolve().is_relative_to(self.root))
        self.assertTrue(outside_directory.resolve().is_relative_to(self.root))
        linked_directory.rename(outside_directory)
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(outside_directory), str(linked_directory))
        else:
            linked_directory.symlink_to(outside_directory, target_is_directory=True)
        before = (outside_directory / "run.py").read_bytes()
        try:
            self.assertEqual(linked_directory.resolve(), outside_directory.resolve())
            with self.assertRaises(ValueError):
                app.snapshot(self.source)
            self.assertEqual((outside_directory / "run.py").read_bytes(), before)
        finally:
            if os.name == "nt":
                linked_directory.rmdir()
            else:
                linked_directory.unlink()

    def test_invalid_utf8_is_rejected(self):
        (self.source / "macos/README.md").write_bytes(b"invalid UTF-8: \xff\n")
        with self.assertRaises(UnicodeDecodeError):
            app.snapshot(self.source)

    def test_utf8_bom_is_rejected(self):
        path = self.source / "macos/README.md"
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        with self.assertRaisesRegex(ValueError, "without BOM"):
            app.snapshot(self.source)

    def test_crlf_source_is_rejected(self):
        path = self.source / "macos/README.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(ValueError, "use LF"):
            app.snapshot(self.source)

    def test_wrong_bash_shebang_is_rejected(self):
        path = self.source / "macos/launch.sh"
        path.write_bytes(b"#!/usr/bin/env bash\nexit 0\n")
        with self.assertRaisesRegex(ValueError, "Bash shebang"):
            app.snapshot(self.source)

    def test_invalid_python_source_fails_before_building(self):
        (self.source / "oneclick.py").write_bytes(b"def broken(:\n")
        with self.assertRaises(SyntaxError):
            app.build(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_package_name_and_prefix_are_separate_from_windows(self):
        self.assertEqual(app.EDITION_VERSION, "1.3.4-mac.1")
        self.assertEqual(app.PACKAGE_NAME, "xiaoguai-oneclick-v1.3.4-mac.1.zip")
        self.assertEqual(app.PREFIX, "小怪破甲-Mac版/")
        self.assertNotEqual(app.PACKAGE_NAME, "xiaoguai-oneclick-v1.3.4.zip")

    def test_wrong_package_name_is_refused_even_with_force(self):
        windows = self.root / "xiaoguai-oneclick-v1.3.4.zip"
        windows.write_bytes(b"existing Windows package")
        for force in (False, True):
            with self.subTest(force=force):
                with self.assertRaisesRegex(ValueError, "separate Mac package filename"):
                    app.build(self.source, windows, force=force)
                self.assertEqual(windows.read_bytes(), b"existing Windows package")

    def test_build_writes_only_utf8_lf_bytes_and_unix_regular_file_modes(self):
        result = app.build(self.source, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(archive.infolist()), len(self.originals))
            for name, expected in self.originals.items():
                with self.subTest(name=name):
                    info = archive.getinfo(app.PREFIX + name)
                    raw = archive.read(info)
                    self.assertEqual(raw, expected)
                    raw.decode("utf-8")
                    self.assertNotIn(b"\r", raw)
                    self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                    self.assertEqual(info.create_system, 3)
                    self.assertTrue(info.flag_bits & 0x800)
                    mode = info.external_attr >> 16
                    self.assertTrue(stat.S_ISREG(mode))
                    self.assertEqual(stat.S_IMODE(mode), 0o755 if name.endswith((".command", ".sh")) else 0o644)
        self.assertEqual(result["edition_version"], "1.3.4-mac.1")
        self.assertEqual(result["file_count"], len(self.originals))
        self.assertEqual(result["package"], str(self.output.resolve()))
        self.assertEqual(result["size"], self.output.stat().st_size)
        self.assertEqual(result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest().upper())
        self.assertTrue(result["unix_executable_bits_verified"])
        self.assertTrue(result["all_package_bytes_verified"])
        self.assert_no_temporary_archives()

    def test_default_build_refuses_to_overwrite_an_existing_package(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"do not overwrite")
        with self.assertRaises(FileExistsError):
            app.build(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b"do not overwrite")
        self.assert_no_temporary_archives()

    def test_default_publication_does_not_overwrite_a_concurrent_destination(self):
        real_link = os.link

        def competing_publisher(source, destination, *args, **kwargs):
            Path(destination).write_bytes(b"concurrent publisher owns this path")
            return real_link(source, destination, *args, **kwargs)

        with patch.object(app.os, "link", side_effect=competing_publisher) as publication:
            with self.assertRaises(FileExistsError):
                app.build(self.source, self.output)
        publication.assert_called_once()
        self.assertEqual(self.output.read_bytes(), b"concurrent publisher owns this path")
        self.assert_no_temporary_archives()

    def test_default_publication_never_uses_overwriting_replace(self):
        with patch.object(app.os, "replace", side_effect=AssertionError("Default publication must not replace")):
            result = app.build(self.source, self.output)
        self.assertTrue(result["all_package_bytes_verified"])
        self.assert_no_temporary_archives()

    def test_unsupported_atomic_link_fails_without_falling_back_to_overwrite(self):
        with patch.object(app.os, "link", side_effect=OSError(errno.ENOTSUP, "Atomic link unsupported")):
            with self.assertRaises(OSError):
                app.build(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assert_no_temporary_archives()

    def test_default_build_refuses_dangling_output_symlink(self):
        self.output.parent.mkdir(parents=True)
        missing_target = self.root / "missing target.zip"
        try:
            self.output.symlink_to(missing_target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Symlink creation unavailable on this host: " + str(exc))
        with self.assertRaises(FileExistsError):
            app.build(self.source, self.output)
        self.assertTrue(self.output.is_symlink())
        self.assertFalse(missing_target.exists())
        self.assert_no_temporary_archives()

    def test_force_replaces_only_correctly_named_mac_package(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"previous Mac package")
        result = app.build(self.source, self.output, force=True)
        self.assertTrue(result["all_package_bytes_verified"])
        self.assertEqual(app.verify_archive(self.output, self.originals), result)
        self.assert_no_temporary_archives()

    def test_prepublication_validation_failure_keeps_existing_output_intact(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"previous verified Mac package")
        with patch.object(app, "verify_archive", side_effect=ValueError("fixture validation failure")):
            with self.assertRaisesRegex(ValueError, "fixture validation failure"):
                app.build(self.source, self.output, force=True)
        self.assertEqual(self.output.read_bytes(), b"previous verified Mac package")
        self.assert_no_temporary_archives()

    def test_reverify_detects_changed_content_even_when_crc_is_valid(self):
        changed = dict(self.originals)
        changed["oneclick.py"] += b"CHANGED = True\n"
        self.make_archive(changed)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
        with self.assertRaisesRegex(ValueError, "Package bytes differ"):
            app.verify_archive(self.output, self.originals)

    def test_reverify_detects_payload_crc_corruption(self):
        self.make_archive()
        with zipfile.ZipFile(self.output) as archive:
            info = archive.getinfo(app.PREFIX + "oneclick.py")
        raw = bytearray(self.output.read_bytes())
        filename_size, extra_size = struct.unpack_from("<HH", raw, info.header_offset + 26)
        payload = info.header_offset + 30 + filename_size + extra_size
        raw[payload] ^= 0x01
        self.output.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "CRC mismatch"):
            app.verify_archive(self.output, self.originals)

    def test_reverify_rejects_missing_member(self):
        self.make_archive(omitted=("oneclick.py",))
        with self.assertRaisesRegex(ValueError, "Unexpected or duplicated"):
            app.verify_archive(self.output, self.originals)

    def test_reverify_rejects_duplicate_member(self):
        self.make_archive(duplicates=("oneclick.py",))
        with self.assertRaisesRegex(ValueError, "Unexpected or duplicated"):
            app.verify_archive(self.output, self.originals)

    def test_reverify_rejects_unexpected_or_traversal_members(self):
        for name in (".codex/config.toml", "unexpected.txt", "../outside.txt"):
            with self.subTest(name=name):
                self.make_archive(extra=((name, b"unexpected content\n"),))
                with self.assertRaisesRegex(ValueError, "Unexpected or duplicated"):
                    app.verify_archive(self.output, self.originals)

    def test_reverify_rejects_nonexecutable_command_and_executable_text(self):
        for name, mode in [("启动小怪破甲.command", 0o644), ("macos/launch.sh", 0o644), ("README.md", 0o755), ("oneclick.py", 0o755)]:
            with self.subTest(name=name):
                self.make_archive(modes={name: stat.S_IFREG | mode})
                with self.assertRaisesRegex(ValueError, "Incorrect Unix mode"):
                    app.verify_archive(self.output, self.originals)

    def test_reverify_rejects_symlink_mode_and_nonunix_origin(self):
        self.make_archive(modes={"oneclick.py": stat.S_IFLNK | 0o644})
        with self.assertRaisesRegex(ValueError, "Incorrect Unix mode"):
            app.verify_archive(self.output, self.originals)
        self.make_archive(systems={"oneclick.py": 0})
        with self.assertRaisesRegex(ValueError, "Incorrect Unix mode"):
            app.verify_archive(self.output, self.originals)

    def test_reverify_refuses_windows_artifact_even_if_in_expected_mapping(self):
        for name in ("installer.exe", "启动.CMD"):
            with self.subTest(name=name):
                files = dict(self.originals, **{name: b"Windows artifact fixture\n"})
                self.make_archive(files)
                with self.assertRaisesRegex(ValueError, "Windows artifact"):
                    app.verify_archive(self.output, files)

    def test_cli_check_returns_actual_verification_json_using_synthetic_sources(self):
        app.build(self.source, self.output)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(app, "ROOT", self.source), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = app.main(["--check", "--output", str(self.output)])
        self.assertEqual(status, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(result["file_count"], len(self.originals))
        self.assertEqual(result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest().upper())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_existing_output_error_does_not_claim_success_or_overwrite(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_bytes(b"keep old package")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(app, "ROOT", self.source), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = app.main(["--output", str(self.output)])
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        result = json.loads(stderr.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(self.output.read_bytes(), b"keep old package")


if __name__ == "__main__":
    unittest.main()
