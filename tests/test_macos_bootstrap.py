from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from test_macos_shell import find_bash, process_options, shell_path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "macos" / "bootstrap-python.sh"
PINS = ROOT / "macos" / "runtime-pins.sh"
PUBLISHER = ROOT / "macos" / "publish-runtime.py"
RUNTIME_ID_PREFIX = "python-3.12.14-20260901-"
PYTHON_BINARY = "python3.12"

FAKE_PYTHON = """#!/bin/bash
printf '%s\\0' "$@" >> "$XG_TEST_PYTHON_ARGUMENTS"
[ "$1" = -I ] || exit 98
if [ "$2" = -c ]; then
    printf 'python-probe\\n' >> "$XG_TEST_EVENTS"
    printf 'fixture python stdout must not leak\\n'
    printf 'fixture python stderr must not leak\\n' >&2
    [ "$#" -eq 3 ] || exit 98
    exit "${XG_TEST_PYTHON_EXIT:-0}"
fi
[ "$#" -eq 4 ] && [ "${2##*/}" = publish-runtime.py ] || exit 98
printf 'python-publish\\n' >> "$XG_TEST_EVENTS"
printf 'fixture publication output\\n'
if [ "${XG_TEST_PUBLISH_EXIT:-0}" != 0 ]; then exit "$XG_TEST_PUBLISH_EXIT"; fi
"$XG_TEST_NATIVE_PYTHON" -B "$XG_TEST_NATIVE_HELPER" publish "$3" "$4"
""".encode("utf-8")

# Native Python is only a fixture utility, not the downloaded runtime. Every
# path it can access must resolve below the temporary root set by the test.
FIXTURE_HELPER = r'''import hashlib
import ctypes
import os
from pathlib import Path
import shutil
import sys
import tarfile

sys.stdout.reconfigure(encoding="utf-8")
root = Path(os.environ["XG_TEST_ROOT_NATIVE"]).resolve()
shell_root = os.environ["XG_TEST_ROOT_SHELL"]

def isolated(value):
    if value == shell_root:
        target = root
    elif value.startswith(shell_root + "/"):
        target = root / value[len(shell_root) + 1:]
    else:
        target = Path(value)
    resolved = target.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeError("Fixture helper refused a path outside its temporary root")
    return target

operation = sys.argv[1]
if operation == "hash":
    path = isolated(sys.argv[2])
    print(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + sys.argv[2])
elif operation == "list":
    with tarfile.open(isolated(sys.argv[2]), "r:gz") as archive:
        for member in archive.getmembers():
            print(member.name + ("/" if member.isdir() and not member.name.endswith("/") else ""))
elif operation == "extract":
    target = isolated(sys.argv[3])
    with tarfile.open(isolated(sys.argv[2]), "r:gz") as archive:
        for member in archive.getmembers():
            path = isolated(str(target / member.name))
            if not path.resolve().is_relative_to(target.resolve()):
                raise RuntimeError("Fixture archive traversal rejected")
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream:
                    path.write_bytes(stream.read())
                path.chmod(member.mode)
            else:
                raise RuntimeError("Fixture archive contains an unsupported member")
elif operation == "chmod":
    isolated(sys.argv[3]).chmod(int(sys.argv[2], 8))
elif operation == "publish":
    source, target = isolated(sys.argv[2]), isolated(sys.argv[3])
    race = os.environ.get("XG_TEST_PUBLISH_RACE", "")
    if race == "directory":
        target.mkdir()
        (target / "foreign.txt").write_bytes(b"preserve foreign directory")
    elif race == "file":
        target.write_bytes(b"preserve foreign file")
    elif race == "symlink":
        outside = isolated(os.environ["XG_TEST_RACE_DESTINATION"])
        try:
            target.symlink_to(outside, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                raise
            # MSYS recognizes system-marked Cygwin symlink files without the
            # Windows privilege required for native NTFS symbolic links.
            shell_target = shell_root + "/" + outside.relative_to(root).as_posix()
            target.write_bytes(b"!<symlink>\xff\xfe" + (shell_target + "\0").encode("utf-16le"))
            library = ctypes.WinDLL("kernel32", use_last_error=True)
            setter = library.SetFileAttributesW
            setter.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
            setter.restype = ctypes.c_int
            if not setter(str(target), 4):
                raise ctypes.WinError(ctypes.get_last_error())
    # Simulate the no-replace syscall contract. The real helper's ctypes call is
    # tested separately; no macOS runtime or libSystem is executed in this suite.
    if os.path.lexists(target):
        raise FileExistsError("Fixture exclusive publication refused an existing destination")
    if os.name == "nt":
        # Windows cannot rename a directory containing the executing fake Bash
        # file. Model the successful publication by an exclusive fixture copy;
        # the bootstrap trap removes its original staging tree afterwards.
        shutil.copytree(source, target)
    else:
        source.rename(target)
else:
    raise RuntimeError("Unexpected fixture operation")
'''


class MacBootstrapTests(unittest.TestCase):
    """Real Bash control flow against fake tools; this is not a Mac hardware test."""

    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()
        if not cls.bash:
            raise unittest.SkipTest("Bash unavailable; set XIAOGUAI_TEST_BASH to native or Git Bash.")
        result = subprocess.run([cls.bash, "--version"], capture_output=True, timeout=15, **process_options())
        if result.returncode or b"GNU bash" not in result.stdout:
            raise unittest.SkipTest("XIAOGUAI_TEST_BASH must be a working Bash executable.")

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="mac-bootstrap-中文 空格 $Dollar-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Bootstrap fixture is outside the intended test root.")
        self.home = self.root / "隔离 home $HOME"
        self.home.mkdir()
        self.cache = self.home / "Library" / "Caches" / "xiaoguai-oneclick"
        self.package = self.root / "Mac package 中文 $not_expanded"
        self.macos = self.package / "macos"
        self.macos.mkdir(parents=True)
        self.script = self.macos / "bootstrap-python.sh"
        shutil.copyfile(BOOTSTRAP, self.script)
        shutil.copyfile(PUBLISHER, self.macos / "publish-runtime.py")
        self.bin = self.root / "fixture bin $tools"
        self.bin.mkdir()
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.events = self.logs / "events.txt"
        self.cwd = self.root / "unrelated cwd $PWD"
        self.cwd.mkdir()
        self.archive = self.root / "fixture archive.tar.gz"
        self.helper = self.root / "fixture tools.py"
        self.helper.write_text(FIXTURE_HELPER, encoding="utf-8", newline="\n")
        self.make_archive()

        self.env = dict(os.environ)
        for key in ("BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "CDPATH", "PYTHONPATH", "PYTHONHOME"):
            self.env.pop(key, None)
        for key in list(self.env):
            if key.startswith("BASH_FUNC_") or key.startswith("XG_TEST_"):
                self.env.pop(key)
        support = [shell_path(Path(self.bash).parent)]
        if os.name != "nt":
            support.extend(["/usr/bin", "/bin"])
        self.env.update({
            "HOME": shell_path(self.home),
            "CODEX_HOME": shell_path(self.home / ".codex"),
            "TMPDIR": shell_path(self.root),
            "TMP": str(self.root),
            "TEMP": str(self.root),
            "PATH": ":".join([shell_path(self.bin), *support]),
            "XG_TEST_ROOT_NATIVE": str(self.root),
            "XG_TEST_ROOT_SHELL": shell_path(self.root),
            "XG_TEST_NATIVE_PYTHON": shell_path(Path(sys.executable)),
            "XG_TEST_NATIVE_HELPER": str(self.helper),
            "XG_TEST_ARCHIVE": shell_path(self.archive),
            "XG_TEST_EVENTS": shell_path(self.events),
            "XG_TEST_CURL_ARGUMENTS": shell_path(self.logs / "curl.args"),
            "XG_TEST_PYTHON_ARGUMENTS": shell_path(self.logs / "python.args"),
            "XG_TEST_SYSTEM": "Darwin",
            "XG_TEST_MACHINE": "arm64",
            "XG_TEST_HARDWARE_ARM64": "1",
            "XG_TEST_OS_VERSION": "14.5.1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "MSYS2_ARG_CONV_EXCL": "*",
            "MSYS2_ENV_CONV_EXCL": "*",
        })
        self.make_tools()

    def tearDown(self):
        if (self.root.resolve().parent != self.expected_parent
                or not self.root.name.startswith("mac-bootstrap-中文 空格 $Dollar-")):
            raise RuntimeError("Refusing to clean a directory outside the bootstrap test root.")
        self.temp.cleanup()

    def make_archive(self, extra_members=()):
        with tarfile.open(self.archive, "w:gz") as archive:
            for name in ("python", "python/bin"):
                member = tarfile.TarInfo(name)
                member.type = tarfile.DIRTYPE
                member.mode = 0o755
                archive.addfile(member)
            for name, raw in [("python/bin/" + PYTHON_BINARY, FAKE_PYTHON), *extra_members]:
                member = tarfile.TarInfo(name)
                member.mode = 0o755
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        self.archive_sha = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.executable_sha = hashlib.sha256(FAKE_PYTHON).hexdigest()
        pins = PINS.read_text(encoding="utf-8")
        for arch in ("ARM64", "X86_64"):
            pins, count = re.subn(r"(readonly XG_" + arch + r"_SHA256=')[0-9a-f]{64}(')",
                                 r"\g<1>" + self.archive_sha + r"\2", pins)
            self.assertEqual(count, 1, "Pinned digest definition changed; update the isolated fixture adapter")
        (self.macos / "runtime-pins.sh").write_text(pins, encoding="utf-8", newline="\n")

    def write_script(self, name, content):
        path = self.bin / name
        path.write_text(content, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def make_tools(self):
        self.write_script("uname", """#!/bin/bash
printf 'uname:%s\\n' "$1" >> "$XG_TEST_EVENTS"
case "$1" in
  -s) printf '%s\\n' "$XG_TEST_SYSTEM" ;;
  -m) printf '%s\\n' "$XG_TEST_MACHINE" ;;
  *) exit 97 ;;
esac
exit "${XG_TEST_UNAME_EXIT:-0}"
""")
        self.write_script("sysctl", """#!/bin/bash
printf 'sysctl\\n' >> "$XG_TEST_EVENTS"
[ "$*" = '-in hw.optional.arm64' ] || exit 97
printf '%s\\n' "$XG_TEST_HARDWARE_ARM64"
exit "${XG_TEST_SYSCTL_EXIT:-0}"
""")
        self.write_script("sw_vers", """#!/bin/bash
printf 'sw_vers\\n' >> "$XG_TEST_EVENTS"
[ "$1" = -productVersion ] || exit 97
printf '%s\\n' "$XG_TEST_OS_VERSION"
exit "${XG_TEST_SW_VERS_EXIT:-0}"
""")
        self.write_script("curl", """#!/bin/bash
printf 'curl\\n' >> "$XG_TEST_EVENTS"
printf '%s\\0' "$@" > "$XG_TEST_CURL_ARGUMENTS"
output=
while [ "$#" -gt 0 ]; do
    if [ "$1" = --output ]; then shift; output=$1; fi
    shift
done
[ -n "$output" ] || exit 97
cp "$XG_TEST_ARCHIVE" "$output" || exit 96
if [ "${XG_TEST_CORRUPT_DOWNLOAD:-0}" = 1 ]; then printf 'corrupt fixture' >> "$output"; fi
printf 'fixture curl stdout\\n'
printf 'fixture curl stderr\\n' >&2
exit "${XG_TEST_CURL_EXIT:-0}"
""")
        self.write_script("shasum", """#!/bin/bash
[ "$#" -eq 3 ] && [ "$1" = -a ] && [ "$2" = 256 ] || exit 97
case "$3" in
  */runtime.tar.gz.part) kind=archive ;;
  *) kind=executable ;;
esac
printf 'hash-%s\\n' "$kind" >> "$XG_TEST_EVENTS"
if [ "${XG_TEST_SHASUM_FAILURE:-}" = "$kind" ]; then exit 29; fi
"$XG_TEST_NATIVE_PYTHON" -B "$XG_TEST_NATIVE_HELPER" hash "$3"
""")
        self.write_script("tar", """#!/bin/bash
case "$1" in
  -tzf)
    printf 'tar-list\\n' >> "$XG_TEST_EVENTS"
    if [ "${XG_TEST_TAR_FAILURE:-}" = list ]; then exit 31; fi
    "$XG_TEST_NATIVE_PYTHON" -B "$XG_TEST_NATIVE_HELPER" list "$2"
    ;;
  -xzf)
    printf 'tar-extract\\n' >> "$XG_TEST_EVENTS"
    [ "$3" = -C ] || exit 97
    "$XG_TEST_NATIVE_PYTHON" -B "$XG_TEST_NATIVE_HELPER" extract "$2" "$4" || exit 96
    printf 'fixture tar stdout\\n'
    printf 'fixture tar stderr\\n' >&2
    if [ "${XG_TEST_TAR_FAILURE:-}" = extract ]; then exit 32; fi
    ;;
  *) exit 97 ;;
esac
""")
        self.write_script("chmod", """#!/bin/bash
if [ "${XG_TEST_CHMOD_EXIT:-0}" != 0 ]; then exit "$XG_TEST_CHMOD_EXIT"; fi
"$XG_TEST_NATIVE_PYTHON" -B "$XG_TEST_NATIVE_HELPER" chmod "$@"
""")
        self.write_script("sleep", """#!/bin/bash
printf 'sleep\\n' >> "$XG_TEST_EVENTS"
[ "$1" = 1 ] || exit 97
exit 0
""")

    def execute(self):
        # MSYS normalizes inherited HOME at process startup; set it inside Bash
        # so the production script sees precisely the Mac-style fixture value.
        env = dict(self.env, XG_TEST_REQUESTED_HOME=self.env["HOME"])
        return subprocess.run([self.bash, "-c", 'HOME=$XG_TEST_REQUESTED_HOME; export HOME; . "$1"',
                               "bootstrap-fixture", shell_path(self.script)], cwd=self.cwd, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=35, **process_options())

    def recorded(self):
        return self.events.read_text(encoding="utf-8").splitlines() if self.events.exists() else []

    def reset_events(self):
        self.events.write_bytes(b"")
        (self.logs / "curl.args").unlink(missing_ok=True)
        (self.logs / "python.args").unlink(missing_ok=True)

    def target(self, arch="arm64"):
        return self.cache / (RUNTIME_ID_PREFIX + arch)

    def interpreter(self, arch="arm64"):
        return self.target(arch) / "python" / "bin" / PYTHON_BINARY

    def lock(self, arch="arm64"):
        return self.cache / ("." + RUNTIME_ID_PREFIX + arch + ".lock")

    def assert_cleanup(self, arch="arm64", own_lock=True):
        self.assertEqual(list(self.cache.glob(".prepare-*")), [], "Staging directory leaked after completion")
        if own_lock:
            self.assertFalse(self.lock(arch).exists(), "Owned lock leaked after completion")
        self.assertFalse((self.home / ".codex").exists(), "Bootstrap must never change Codex configuration")

    def assert_failed(self, result, *, text=None, arch="arm64", final_absent=True, own_lock=True):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "", "Failure output must not resemble an interpreter path")
        self.assertTrue(result.stderr)
        if text:
            self.assertIn(text, result.stderr)
        if final_absent:
            self.assertFalse(self.target(arch).exists())
        self.assert_cleanup(arch, own_lock)

    def assert_success(self, result, arch="arm64"):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, shell_path(self.interpreter(arch)) + "\n")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertTrue(result.stdout.startswith("/"))
        self.assertNotIn("fixture python", result.stderr)
        self.assertEqual(self.interpreter(arch).read_bytes(), FAKE_PYTHON)
        receipt = (self.target(arch) / ".xiaoguai-runtime").read_text(encoding="utf-8")
        self.assertEqual(receipt, RUNTIME_ID_PREFIX + arch + "\n" + self.archive_sha + "\n" + self.executable_sha + "\n")
        self.assert_cleanup(arch)

    def cache_snapshot(self):
        # Do not walk into cache links; preserve their own link text instead.
        result = {}
        for path in self.cache.rglob("*"):
            name = path.relative_to(self.cache).as_posix()
            if path.is_symlink():
                result[name] = ("link", os.readlink(path))
            elif path.is_file():
                result[name] = ("file", path.read_bytes(), path.stat().st_mtime_ns)
            else:
                result[name] = ("directory",)
        return result

    def make_symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as exc:
            if os.name != "nt":
                self.skipTest("Host does not permit creating test symlinks: " + str(exc))
            link.write_bytes(b"!<symlink>\xff\xfe" + (shell_path(target) + "\0").encode("utf-16le"))
            library = ctypes.WinDLL("kernel32", use_last_error=True)
            setter = library.SetFileAttributesW
            setter.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
            setter.restype = ctypes.c_int
            if not setter(str(link), 4):
                raise ctypes.WinError(ctypes.get_last_error())
        self.assert_shell_symlink(link)

    def assert_shell_symlink(self, link):
        # shell_path(link) follows native links, so resolve only its parent here.
        path = shell_path(link.parent) + "/" + link.name
        result = subprocess.run([self.bash, "-c", '[ -L "$1" ]', "link-check", path], env=self.env,
                                capture_output=True, text=True, encoding="utf-8", timeout=15, **process_options())
        self.assertEqual(result.returncode, 0, "Bash did not recognize the isolated symbolic-link fixture: " + result.stderr)

    def test_bootstrap_and_pin_files_are_lf_utf8_with_valid_bash_syntax(self):
        for path in (BOOTSTRAP, PINS):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"#!/bin/bash\n"))
                self.assertNotIn(b"\r", raw)
                self.assertTrue(raw.endswith(b"\n"))
                raw.decode("utf-8")
                result = subprocess.run([self.bash, "-n", shell_path(path)], capture_output=True,
                                        timeout=15, **process_options())
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_download_digest_extraction_probe_and_single_absolute_stdout_path(self):
        result = self.execute()
        self.assert_success(result)
        events = self.recorded()
        self.assertEqual(events, ["uname:-s", "uname:-m", "sysctl", "sw_vers", "curl", "hash-archive",
                                  "tar-list", "tar-extract", "python-probe", "hash-executable",
                                  "python-publish", "hash-executable", "python-probe"])
        arguments = (self.logs / "curl.args").read_bytes().decode("utf-8").rstrip("\0").split("\0")
        self.assertIn("--fail", arguments)
        self.assertIn("--proto", arguments)
        self.assertIn("--proto-redir", arguments)
        self.assertEqual(arguments.count("=https"), 2)
        self.assertIn("aarch64-apple-darwin", arguments[-1])
        self.assertIn("fixture curl stdout", result.stderr)
        self.assertIn("fixture tar stdout", result.stderr)
        self.assertFalse((self.cwd / "not_expanded").exists())

    def test_verified_cache_is_reused_without_curl_tar_or_file_rewrites(self):
        self.assert_success(self.execute())
        before = self.cache_snapshot()
        self.reset_events()
        self.env["XG_TEST_CURL_EXIT"] = "99"
        result = self.execute()
        self.assert_success(result)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.recorded(), ["uname:-s", "uname:-m", "sysctl", "sw_vers", "hash-executable", "python-probe"])
        self.assertFalse((self.logs / "curl.args").exists())
        self.assertEqual(before, self.cache_snapshot())

    def test_missing_pins_fails_before_platform_or_download(self):
        (self.macos / "runtime-pins.sh").unlink()
        self.assert_failed(self.execute(), text="缺少运行时清单")
        self.assertEqual(self.recorded(), [])
        self.assertFalse(self.cache.exists())

    def test_missing_publisher_fails_before_platform_or_download(self):
        (self.macos / "publish-runtime.py").unlink()
        self.assert_failed(self.execute(), text="缺少运行时提交组件")
        self.assertEqual(self.recorded(), [])
        self.assertFalse(self.cache.exists())

    def test_non_darwin_platform_is_rejected_before_cache_or_download(self):
        self.env["XG_TEST_SYSTEM"] = "Linux"
        self.assert_failed(self.execute(), text="只适用于 macOS")
        self.assertEqual(self.recorded(), ["uname:-s"])
        self.assertFalse(self.cache.exists())

    def test_unknown_architecture_is_rejected_before_cache_or_download(self):
        self.env.update(XG_TEST_MACHINE="ppc64", XG_TEST_HARDWARE_ARM64="0")
        self.assert_failed(self.execute(), text="不支持此处理器架构")
        self.assertNotIn("curl", self.recorded())
        self.assertFalse(self.cache.exists())

    def test_arm_requires_macos_11_and_rejects_older_versions(self):
        self.env["XG_TEST_OS_VERSION"] = "10.15.7"
        self.assert_failed(self.execute(), text="macOS 11")
        self.assertNotIn("curl", self.recorded())
        self.assertFalse(self.cache.exists())

    def test_intel_requires_macos_10_15(self):
        self.env.update(XG_TEST_MACHINE="x86_64", XG_TEST_HARDWARE_ARM64="0", XG_TEST_OS_VERSION="10.14.6")
        self.assert_failed(self.execute(), text="macOS 10.15", arch="x86_64")
        self.assertNotIn("curl", self.recorded())
        self.assertFalse(self.cache.exists())

    def test_intel_minimum_os_uses_x86_64_archive(self):
        self.env.update(XG_TEST_MACHINE="x86_64", XG_TEST_HARDWARE_ARM64="0", XG_TEST_OS_VERSION="10.15.0")
        self.assert_success(self.execute(), "x86_64")
        self.assertIn(b"x86_64-apple-darwin", (self.logs / "curl.args").read_bytes())

    def test_native_arm_minimum_os_and_aarch64_alias_are_supported(self):
        self.env.update(XG_TEST_MACHINE="aarch64", XG_TEST_HARDWARE_ARM64="0", XG_TEST_OS_VERSION="11.0")
        self.assert_success(self.execute())

    def test_rosetta_x86_shell_selects_native_arm_archive(self):
        self.env.update(XG_TEST_MACHINE="x86_64", XG_TEST_HARDWARE_ARM64="1")
        self.assert_success(self.execute())
        self.assertIn(b"aarch64-apple-darwin", (self.logs / "curl.args").read_bytes())
        self.assertFalse(self.target("x86_64").exists())

    def test_sysctl_failure_on_intel_falls_back_to_uname(self):
        self.env.update(XG_TEST_MACHINE="x86_64", XG_TEST_HARDWARE_ARM64="1", XG_TEST_SYSCTL_EXIT="1")
        self.assert_success(self.execute(), "x86_64")

    def test_uname_and_version_failures_do_not_download_or_create_cache(self):
        for flag in ("XG_TEST_UNAME_EXIT", "XG_TEST_SW_VERS_EXIT"):
            with self.subTest(flag=flag):
                self.env[flag] = "1"
                self.assert_failed(self.execute())
                self.env.pop(flag)
                self.assertNotIn("curl", self.recorded())
                self.assertFalse(self.cache.exists())
                self.reset_events()

    def test_malformed_os_version_is_rejected(self):
        self.env["XG_TEST_OS_VERSION"] = "11.invalid"
        self.assert_failed(self.execute(), text="无法识别 macOS 版本")
        self.assertNotIn("curl", self.recorded())
        self.assertFalse(self.cache.exists())

    def test_relative_home_is_rejected_without_creating_cache(self):
        self.env["HOME"] = "relative-home"
        self.assert_failed(self.execute(), text="绝对路径")
        self.assertFalse(self.cache.exists())
        self.assertFalse((self.cwd / "relative-home").exists())

    def test_hash_mismatch_stops_before_any_extraction_or_runtime_execution(self):
        self.env["XG_TEST_CORRUPT_DOWNLOAD"] = "1"
        self.assert_failed(self.execute(), text="SHA256 不匹配")
        events = self.recorded()
        self.assertIn("curl", events)
        self.assertIn("hash-archive", events)
        self.assertNotIn("tar-list", events)
        self.assertNotIn("tar-extract", events)
        self.assertNotIn("python-probe", events)

    def test_curl_failure_cleans_partial_archive_staging_and_owned_lock(self):
        self.env["XG_TEST_CURL_EXIT"] = "22"
        self.assert_failed(self.execute(), text="下载失败")
        self.assertIn("curl", self.recorded())
        self.assertNotIn("hash-archive", self.recorded())
        self.assertNotIn("tar-list", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_archive_hash_command_failure_cleans_staging_without_extracting(self):
        self.env["XG_TEST_SHASUM_FAILURE"] = "archive"
        self.assert_failed(self.execute(), text="无法校验")
        self.assertNotIn("tar-list", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_tar_listing_failure_leaves_no_final_cache_or_lock(self):
        self.env["XG_TEST_TAR_FAILURE"] = "list"
        self.assert_failed(self.execute(), text="压缩包无法读取")
        self.assertIn("tar-list", self.recorded())
        self.assertNotIn("tar-extract", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_tar_extraction_failure_cleans_partially_extracted_runtime(self):
        self.env["XG_TEST_TAR_FAILURE"] = "extract"
        self.assert_failed(self.execute(), text="解压失败")
        self.assertIn("tar-extract", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_archive_member_outside_python_is_rejected_before_extraction(self):
        self.make_archive([("outside.txt", b"fixture")])
        self.assert_failed(self.execute(), text="不在 python 目录内")
        self.assertNotIn("tar-extract", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_archive_parent_traversal_is_rejected_before_extraction(self):
        self.make_archive([("python/../outside.txt", b"fixture")])
        self.assert_failed(self.execute(), text="包含上级目录")
        self.assertNotIn("tar-extract", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_runtime_probe_failure_leaves_no_final_cache_staging_or_lock(self):
        self.env["XG_TEST_PYTHON_EXIT"] = "41"
        self.assert_failed(self.execute(), text="Python 无法在本机运行")
        self.assertEqual(self.recorded().count("python-probe"), 1)
        self.assertNotIn("hash-executable", self.recorded())

    def test_executable_hash_failure_cleans_verified_but_unpublished_runtime(self):
        self.env["XG_TEST_SHASUM_FAILURE"] = "executable"
        self.assert_failed(self.execute(), text="无法登记 Python 校验值")
        self.assertEqual(self.recorded().count("python-probe"), 1)
        self.assertEqual(self.recorded().count("hash-executable"), 1)

    def test_cache_receipt_corruption_is_preserved_without_download_or_probe(self):
        self.assert_success(self.execute())
        (self.target() / ".xiaoguai-runtime").write_text("corrupt receipt\n", encoding="utf-8")
        before = self.cache_snapshot()
        self.reset_events()
        self.assert_failed(self.execute(), text="现有运行时缓存未通过检查", final_absent=False)
        self.assertEqual(self.cache_snapshot(), before)
        self.assertNotIn("curl", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_modified_cached_executable_is_not_run_or_overwritten(self):
        self.assert_success(self.execute())
        self.interpreter().write_bytes(FAKE_PYTHON + b"# locally modified fixture\n")
        before = self.cache_snapshot()
        self.reset_events()
        self.assert_failed(self.execute(), text="现有运行时缓存未通过检查", final_absent=False)
        self.assertEqual(before, self.cache_snapshot())
        self.assertIn("hash-executable", self.recorded())
        self.assertNotIn("python-probe", self.recorded())
        self.assertNotIn("curl", self.recorded())

    def test_existing_non_directory_cache_target_is_not_overwritten(self):
        self.cache.mkdir(parents=True)
        self.target().write_bytes(b"preserve this user file")
        before = self.cache_snapshot()
        self.assert_failed(self.execute(), text="现有运行时缓存未通过检查", final_absent=False)
        self.assertEqual(before, self.cache_snapshot())
        self.assertNotIn("curl", self.recorded())

    def test_symlinked_cache_base_is_not_followed(self):
        outside = self.root / "untouched linked cache"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_bytes(b"preserve destination")
        self.cache.parent.mkdir(parents=True)
        self.make_symlink(self.cache, outside, directory=True)
        result = self.execute()
        self.assert_failed(result, text="不能是符号链接")
        self.assert_shell_symlink(self.cache)
        self.assertEqual(sentinel.read_bytes(), b"preserve destination")
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertNotIn("curl", self.recorded())

    def test_symlinked_runtime_target_is_not_followed_or_replaced(self):
        self.cache.mkdir(parents=True)
        outside = self.root / "untouched runtime"
        outside.mkdir()
        self.make_symlink(self.target(), outside, directory=True)
        self.assert_failed(self.execute(), text="运行时目标不能是符号链接", final_absent=False)
        self.assert_shell_symlink(self.target())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertNotIn("curl", self.recorded())
        self.assertNotIn("python-probe", self.recorded())

    def test_symlinked_cached_executable_is_never_run(self):
        self.assert_success(self.execute())
        outside = self.root / "linked executable"
        outside.write_bytes(FAKE_PYTHON)
        outside.chmod(0o755)
        self.interpreter().unlink()
        self.make_symlink(self.interpreter(), outside)
        before = self.cache_snapshot()
        self.reset_events()
        self.assert_failed(self.execute(), text="现有运行时缓存未通过检查", final_absent=False)
        self.assertEqual(before, self.cache_snapshot())
        self.assertNotIn("python-probe", self.recorded())
        self.assertNotIn("curl", self.recorded())

    def test_foreign_lock_content_survives_bounded_contention(self):
        self.lock().mkdir(parents=True)
        owner = self.lock() / "owner"
        owner.write_bytes(b"another-process-token\n")
        sentinel = self.lock() / "other-data"
        sentinel.write_bytes(b"do not delete")
        before = self.cache_snapshot()
        self.assert_failed(self.execute(), text="其他运行时准备操作尚未结束", own_lock=False)
        self.assertEqual(before, self.cache_snapshot())
        self.assertEqual(owner.read_bytes(), b"another-process-token\n")
        self.assertEqual(self.recorded().count("sleep"), 29)
        self.assertNotIn("curl", self.recorded())

    def test_symlinked_foreign_lock_is_not_followed_or_deleted(self):
        self.cache.mkdir(parents=True)
        outside = self.root / "foreign lock"
        outside.mkdir()
        owner = outside / "owner"
        owner.write_bytes(b"foreign-owner\n")
        self.make_symlink(self.lock(), outside, directory=True)
        self.assert_failed(self.execute(), text="运行时锁不能是符号链接", own_lock=False)
        self.assert_shell_symlink(self.lock())
        self.assertEqual(owner.read_bytes(), b"foreign-owner\n")
        self.assertNotIn("curl", self.recorded())

    def test_publication_failure_leaves_no_final_cache_staging_or_lock(self):
        self.env["XG_TEST_PUBLISH_EXIT"] = "73"
        self.assert_failed(self.execute(), text="无法原子保存运行环境")
        self.assertEqual(self.recorded().count("python-publish"), 1)
        self.assertEqual(self.recorded().count("python-probe"), 1)

    def test_directory_created_at_publication_is_preserved_without_nested_tree(self):
        self.env["XG_TEST_PUBLISH_RACE"] = "directory"
        self.assert_failed(self.execute(), text="无法原子保存运行环境", final_absent=False)
        self.assertEqual((self.target() / "foreign.txt").read_bytes(), b"preserve foreign directory")
        self.assertEqual([path.name for path in self.target().iterdir()], ["foreign.txt"])
        self.assertFalse((self.target() / "tree").exists())
        self.assertEqual(self.recorded().count("python-publish"), 1)

    def test_file_created_at_publication_is_preserved(self):
        self.env["XG_TEST_PUBLISH_RACE"] = "file"
        self.assert_failed(self.execute(), text="无法原子保存运行环境", final_absent=False)
        self.assertEqual(self.target().read_bytes(), b"preserve foreign file")
        self.assertFalse((self.target() / "tree").exists())
        self.assertEqual(self.recorded().count("python-publish"), 1)

    def test_symlink_created_at_publication_preserves_link_and_external_directory(self):
        outside = self.root / "publication race destination"
        outside.mkdir()
        sentinel = outside / "foreign.txt"
        sentinel.write_bytes(b"preserve linked destination")
        self.env.update(XG_TEST_PUBLISH_RACE="symlink", XG_TEST_RACE_DESTINATION=shell_path(outside))
        self.assert_failed(self.execute(), text="无法原子保存运行环境", final_absent=False)
        self.assert_shell_symlink(self.target())
        self.assertEqual(sentinel.read_bytes(), b"preserve linked destination")
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertFalse((outside / "tree").exists())
        self.assertFalse((self.target() / "tree").exists())
        self.assertEqual(self.recorded().count("python-publish"), 1)


class MacRuntimePublisherTests(unittest.TestCase):
    """Exercise the real Python helper with libSystem mocked, not loaded."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("xiaoguai_macos_runtime_publisher", PUBLISHER)
        assert spec and spec.loader
        cls.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.app)

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="mac-publish-中文 空格 $Dollar-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Publisher fixture is outside the intended test root.")
        self.cache = self.root / "cache"
        self.destination = self.cache / (RUNTIME_ID_PREFIX + "arm64")
        self.source = self.cache / (".prepare-" + self.destination.name + ".fixture") / "tree"
        self.source.mkdir(parents=True)
        (self.source / "sentinel").write_bytes(b"prepared fixture")

    def tearDown(self):
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("mac-publish-中文 空格 $Dollar-"):
            raise RuntimeError("Refusing to clean a directory outside the publisher test root.")
        self.temp.cleanup()

    def test_publish_calls_darwin_exclusive_rename_with_flag_four(self):
        library = Mock()
        library.renamex_np.return_value = 0
        with patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL", return_value=library) as loader:
            self.app.publish(self.source, self.destination)
        loader.assert_called_once_with("/usr/lib/libSystem.B.dylib", use_errno=True)
        library.renamex_np.assert_called_once_with(os.fsencode(self.source), os.fsencode(self.destination), 4)
        self.assertEqual(library.renamex_np.argtypes, [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint])
        self.assertEqual(library.renamex_np.restype, ctypes.c_int)

    def test_non_macos_refuses_before_loading_library_or_changing_source(self):
        with patch.object(self.app.sys, "platform", "win32"), patch.object(self.app.ctypes, "CDLL") as loader:
            with self.assertRaisesRegex(RuntimeError, "只适用于 macOS"):
                self.app.publish(self.source, self.destination)
        loader.assert_not_called()
        self.assertEqual((self.source / "sentinel").read_bytes(), b"prepared fixture")
        self.assertFalse(self.destination.exists())

    def test_relative_paths_are_rejected_before_loading_library(self):
        cases = ((Path("relative/tree"), self.destination), (self.source, Path("relative-cache/python")))
        for source, destination in cases:
            with self.subTest(source=source, destination=destination):
                with patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL") as loader:
                    with self.assertRaisesRegex(ValueError, "绝对路径"):
                        self.app.publish(source, destination)
                loader.assert_not_called()

    def test_wrong_cache_depth_source_name_and_version_are_rejected(self):
        cases = (self.root / "wrong-cache" / "prepared" / "tree", self.source.parent / "not-tree",
                 self.cache / ".prepare-wrong-version.fixture" / "tree")
        for source in cases:
            source.mkdir(parents=True)
            with self.subTest(source=source):
                with patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL") as loader:
                    with self.assertRaises(ValueError):
                        self.app.publish(source, self.destination)
                loader.assert_not_called()

    def test_missing_or_symbolic_source_components_are_rejected(self):
        for component in (self.cache, self.source.parent, self.source):
            with self.subTest(component=component):
                with (patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL") as loader,
                      patch.object(Path, "is_symlink", autospec=True, side_effect=lambda path: path == component)):
                    with self.assertRaisesRegex(ValueError, "普通的独立目录"):
                        self.app.publish(self.source, self.destination)
                loader.assert_not_called()
        missing = self.cache / (".prepare-" + self.destination.name + ".missing") / "tree"
        with patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL") as loader:
            with self.assertRaisesRegex(ValueError, "普通的独立目录"):
                self.app.publish(missing, self.destination)
        loader.assert_not_called()

    def test_existing_destination_errno_is_reported_without_mutation(self):
        self.destination.mkdir()
        (self.destination / "foreign").write_bytes(b"preserve existing destination")
        library = Mock()
        library.renamex_np.return_value = -1
        with (patch.object(self.app.sys, "platform", "darwin"), patch.object(self.app.ctypes, "CDLL", return_value=library),
              patch.object(self.app.ctypes, "get_errno", return_value=errno.EEXIST)):
            with self.assertRaises(OSError) as error:
                self.app.publish(self.source, self.destination)
        self.assertEqual(error.exception.errno, errno.EEXIST)
        self.assertEqual(error.exception.filename, str(self.destination))
        self.assertEqual((self.source / "sentinel").read_bytes(), b"prepared fixture")
        self.assertEqual((self.destination / "foreign").read_bytes(), b"preserve existing destination")
        self.assertFalse((self.destination / "tree").exists())

    def test_main_success_is_silent_and_errors_go_only_to_stderr(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.app, "publish") as publish, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.app.main([str(self.source), str(self.destination)])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        publish.assert_called_once_with(self.source, self.destination)
        for arguments in ([], [str(self.source)], [str(self.source), str(self.destination), "extra"]):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), patch.object(self.app, "publish") as publish:
                code = self.app.main(arguments)
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("运行时原子提交失败", stderr.getvalue())
            publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
