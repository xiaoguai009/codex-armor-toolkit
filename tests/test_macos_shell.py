from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = {
    "启动小怪破甲.command": "--install",
    "卸载小怪破甲.command": "--restore",
    "查看小怪状态.command": "--status",
}
SHELL_FILES = tuple(ROOT / name for name in ENTRYPOINTS) + (ROOT / "macos" / "launch.sh",)
MINIMUM_PYTHON_PROBE = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
MSYS_DRIVE_ROOTS: dict[str, str] = {}


def shell_path(path: Path) -> str:
    """Use MSYS paths when exercising scripts with Git Bash on Windows."""
    value = path.resolve().as_posix()
    if os.name == "nt" and len(value) >= 3 and value[1:3] == ":/":
        drive = value[0].lower()
        if drive not in MSYS_DRIVE_ROOTS:
            # Full Git Bash uses /c, while a minimal portable MSYS runtime can
            # use /cygdrive/c. Ask Bash instead of assuming one mount layout.
            result = subprocess.run(
                [find_bash(), "-c", 'CDPATH= cd -- "$1" && pwd -P', "path-probe", value[:3]],
                capture_output=True, text=True, encoding="utf-8", timeout=15,
                **process_options(),
            )
            if result.returncode or not result.stdout.startswith("/"):
                raise RuntimeError("Unable to resolve Git Bash drive mount: " + result.stderr)
            MSYS_DRIVE_ROOTS[drive] = result.stdout.strip().rstrip("/")
        return MSYS_DRIVE_ROOTS[drive] + value[2:]
    return value


def process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def find_bash() -> str | None:
    explicit = os.environ.get("XIAOGUAI_TEST_BASH")
    if explicit:
        return explicit if Path(explicit).is_file() else None
    candidates = [shutil.which("bash")]
    if os.name == "nt":
        candidates.extend([
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ])
        git = shutil.which("git")
        if git:
            candidates.append(str(Path(git).resolve().parents[1] / "usr" / "bin" / "bash.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class MacShellStaticTests(unittest.TestCase):
    def test_scripts_have_lf_utf8_and_bash_shebang(self):
        for path in SHELL_FILES:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertTrue(raw.startswith(b"#!/bin/bash\n"))
                self.assertNotIn(b"\r", raw)
                self.assertTrue(raw.endswith(b"\n"))
                raw.decode("utf-8")

    def test_scripts_use_bash_32_constructs_without_evaluating_arguments(self):
        for path in SHELL_FILES:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for forbidden in (r"\beval\b", r"readlink\s+-f\b", r"declare\s+-A\b", r"\bmapfile\b", r"\breadarray\b"):
                    self.assertNotRegex(text, forbidden)
        launcher = (ROOT / "macos" / "launch.sh").read_text(encoding="utf-8")
        self.assertIn('"/opt/homebrew/bin/python3"', launcher)
        self.assertIn('"/usr/local/bin/python3"', launcher)

    def test_version_probe_accepts_supported_and_future_python(self):
        launcher = (ROOT / "macos" / "launch.sh").read_text(encoding="utf-8")
        self.assertIn("'" + MINIMUM_PYTHON_PROBE + "'", launcher)
        expression = MINIMUM_PYTHON_PROBE.removeprefix("import sys; ")
        for version, expected in [((2, 7, 18), 1), ((3, 10, 99), 1), ((3, 11, 0), 0), ((3, 14, 0), 0), ((4, 0, 0), 0)]:
            with self.subTest(version=version):
                with self.assertRaises(SystemExit) as outcome:
                    exec(expression, {"sys": types.SimpleNamespace(version_info=version)})
                self.assertEqual(outcome.exception.code, expected)


class MacShellBehaviorTests(unittest.TestCase):
    """Only fake interpreters and bootstrap scripts run; never touch real Codex."""

    @classmethod
    def setUpClass(cls):
        cls.bash = find_bash()
        if not cls.bash:
            raise unittest.SkipTest("Bash unavailable; set XIAOGUAI_TEST_BASH to a native or Git Bash executable.")
        check = subprocess.run([cls.bash, "--version"], capture_output=True, timeout=15, **process_options())
        if check.returncode or b"GNU bash" not in check.stdout:
            raise unittest.SkipTest("XIAOGUAI_TEST_BASH must be a working Bash executable.")

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="小怪 Mac space $Dollar-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Shell test directory is outside the intended test root.")
        self.package = self.root / "解压 package $not_expanded"
        self.macos = self.package / "macos"
        self.macos.mkdir(parents=True)
        self.bin = self.root / "path bin $SDK"
        self.bin.mkdir()
        self.cwd = self.root / "unrelated cwd 中文 $here"
        self.cwd.mkdir()
        self.home = self.root / "isolated home"
        self.home.mkdir()
        self.logs = self.root / "logs"
        self.logs.mkdir()
        self.homebrew = self.root / "fake opt homebrew" / "python3"
        self.local = self.root / "fake usr local" / "python3"
        self.launcher = self.macos / "launch.sh"

        # Redirect only two fixed discovery paths into the sandbox. Their control
        # flow is unmodified, and tests never depend on or modify host runtimes.
        launcher = (ROOT / "macos" / "launch.sh").read_text(encoding="utf-8")
        for real, fake in [('/opt/homebrew/bin/python3', self.homebrew), ('/usr/local/bin/python3', self.local)]:
            token = '"' + real + '"'
            self.assertEqual(launcher.count(token), 1)
            launcher = launcher.replace(token, shlex.quote(shell_path(fake)))
        self.write_script(self.launcher, launcher)
        for name in ENTRYPOINTS:
            shutil.copyfile(ROOT / name, self.package / name)
        (self.macos / "run.py").write_text("# Fake Python records arguments; this file is never executed.\n", encoding="utf-8")

        self.write_script(self.bin / "uname", """#!/bin/bash
printf '%s\\n' "${FAKE_UNAME:-Darwin}"
exit "${FAKE_UNAME_EXIT:-0}"
""")
        self.write_script(self.macos / "bootstrap-python.sh", """#!/bin/bash
printf '%s\\0' "$@" > "$BOOTSTRAP_CALL_LOG"
printf 'bootstrap progress\\n' >&2
printf '%s\\n' "$FAKE_BOOTSTRAP_PYTHON"
exit "${FAKE_BOOTSTRAP_EXIT:-0}"
""")
        self.env = dict(os.environ)
        for key in ("XIAOGUAI_PYTHON", "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS", "CDPATH", "PYTHONPATH", "PYTHONHOME"):
            self.env.pop(key, None)
        for key in list(self.env):
            if key.startswith("BASH_FUNC_"):
                self.env.pop(key)
        self.env.update({
            "HOME": shell_path(self.home),
            "CODEX_HOME": shell_path(self.home / ".codex"),
            "TMPDIR": shell_path(self.root),
            "TMP": str(self.root),
            "TEMP": str(self.root),
            "PATH": shell_path(self.bin),
            "XIAOGUAI_NO_PAUSE": "1",
            "BOOTSTRAP_CALL_LOG": shell_path(self.logs / "bootstrap.called"),
            "FAKE_UNAME": "Darwin",
            "FAKE_UNAME_EXIT": "0",
            "FAKE_BOOTSTRAP_EXIT": "0",
            "FAKE_BOOTSTRAP_PYTHON": "",
            "FAKE_PYTHON_OUTPUT": "",
            "FAKE_PYTHON_STDERR": "",
            "FAKE_PYTHON_EXIT": "0",
            # Avoid Git Bash converting arguments before fake executables see them.
            "MSYS2_ARG_CONV_EXCL": "*",
        })

    def tearDown(self):
        if self.root.resolve().parent != self.expected_parent or not self.root.name.startswith("小怪 Mac space $Dollar-"):
            raise RuntimeError("Refusing to clean a directory outside the shell test root.")
        self.temp.cleanup()

    @staticmethod
    def write_script(path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def make_python(self, label: str, path: Path | None = None, *, valid: bool = True) -> Path:
        target = path or self.root / ("Python runtime " + label + " $SDK") / "python3"
        probe = shlex.quote(shell_path(self.logs / (label + ".probe")))
        run = shlex.quote(shell_path(self.logs / (label + ".run")))
        cwd = shlex.quote(shell_path(self.logs / (label + ".cwd")))
        self.write_script(target, f"""#!/bin/bash
if [ "$1" != -I ]; then exit 97; fi
if [ "$2" = -c ]; then
    printf '%s\\0' "$@" > {probe}
    printf 'probe stdout must be hidden\\n'
    printf 'probe stderr must be hidden\\n' >&2
    exit {0 if valid else 1}
fi
printf '%s\\0' "$@" > {run}
pwd -P > {cwd}
printf '%s' "$FAKE_PYTHON_OUTPUT"
printf '%s' "$FAKE_PYTHON_STDERR" >&2
exit "$FAKE_PYTHON_EXIT"
""")
        return target

    def execute(self, *arguments: str, entry: str | None = None) -> subprocess.CompletedProcess:
        path = self.package / entry if entry else self.launcher
        return subprocess.run(
            [self.bash, shell_path(path), *arguments], cwd=self.cwd, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            timeout=20, **process_options(),
        )

    def read_arguments(self, label: str, kind: str = "run") -> list[str]:
        raw = (self.logs / (label + "." + kind)).read_bytes()
        self.assertTrue(raw.endswith(b"\0"))
        return [part.decode("utf-8") for part in raw[:-1].split(b"\0")]

    def assert_no_bootstrap(self):
        self.assertFalse((self.logs / "bootstrap.called").exists())

    def assert_failed(self, result, code=2):
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)
        self.assertFalse(any(self.logs.glob("*.run")))
        self.assertFalse((self.home / ".codex").exists())

    def test_bash_syntax_for_all_shipped_entrypoints(self):
        for path in SHELL_FILES:
            with self.subTest(path=path.name):
                result = subprocess.run(
                    [self.bash, "-n", shell_path(path)], capture_output=True,
                    timeout=15, **process_options(),
                )
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

    def test_install_entry_preserves_arguments_and_unrelated_working_directory(self):
        python = self.make_python("explicit")
        self.env["XIAOGUAI_PYTHON"] = shell_path(python)
        args = ("--no-open", "--codex-home", "中文 space $HOME;$(touch do-not-run)", "", "--json")
        self.env["FAKE_PYTHON_OUTPUT"] = '{"ok":true}\n'
        result = self.execute(*args, entry="启动小怪破甲.command")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '{"ok":true}\n')
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.read_arguments("explicit"), ["-I", shell_path(self.macos / "run.py"), "--install", *args])
        self.assertEqual((self.logs / "explicit.cwd").read_text(encoding="utf-8").strip(), shell_path(self.cwd))
        self.assertEqual(self.read_arguments("explicit", "probe"), ["-I", "-c", MINIMUM_PYTHON_PROBE])
        self.assertFalse((self.cwd / "do-not-run").exists())
        self.assert_no_bootstrap()

    def test_restore_entry_forwards_restore_action(self):
        self.make_python("path", self.bin / "python3")
        result = self.execute("--json", entry="卸载小怪破甲.command")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_arguments("path"), ["-I", shell_path(self.macos / "run.py"), "--restore", "--json"])

    def test_status_entry_forwards_status_action(self):
        self.make_python("path", self.bin / "python3")
        result = self.execute("--json", entry="查看小怪状态.command")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_arguments("path"), ["-I", shell_path(self.macos / "run.py"), "--status", "--json"])

    def test_explicit_python_has_priority_over_path_python(self):
        self.env["XIAOGUAI_PYTHON"] = shell_path(self.make_python("explicit"))
        self.make_python("path", self.bin / "python3")
        result = self.execute("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.logs / "explicit.run").is_file())
        self.assertFalse((self.logs / "path.probe").exists())
        self.assert_no_bootstrap()

    def test_explicit_relative_python_path_is_resolved_without_changing_cwd(self):
        self.make_python("relative", self.cwd / "runtime $local" / "python3")
        self.env["XIAOGUAI_PYTHON"] = "runtime $local/python3"
        result = self.execute("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.logs / "relative.run").is_file())
        self.assertEqual((self.logs / "relative.cwd").read_text(encoding="utf-8").strip(), shell_path(self.cwd))

    def test_missing_explicit_python_never_falls_back(self):
        self.env["XIAOGUAI_PYTHON"] = shell_path(self.root / "does not exist")
        self.make_python("path", self.bin / "python3")
        result = self.execute("--json")
        self.assert_failed(result)
        self.assertIn("XIAOGUAI_PYTHON", result.stderr)
        self.assertFalse((self.logs / "path.probe").exists())
        self.assert_no_bootstrap()

    def test_explicit_empty_python_is_an_error_not_a_fallback(self):
        self.env["XIAOGUAI_PYTHON"] = ""
        self.make_python("path", self.bin / "python3")
        self.assert_failed(self.execute("--json"))
        self.assertFalse((self.logs / "path.probe").exists())
        self.assert_no_bootstrap()

    def test_explicit_old_python_is_rejected_without_fallback(self):
        self.env["XIAOGUAI_PYTHON"] = shell_path(self.make_python("old", valid=False))
        self.make_python("path", self.bin / "python3")
        self.assert_failed(self.execute())
        self.assertTrue((self.logs / "old.probe").is_file())
        self.assertFalse((self.logs / "path.probe").exists())
        self.assert_no_bootstrap()

    def test_explicit_invalid_python_still_fails_with_help(self):
        self.env["XIAOGUAI_PYTHON"] = "missing-python"
        self.assert_failed(self.execute("--help"))
        self.assert_no_bootstrap()

    def test_path_python_is_preferred_to_homebrew_and_local(self):
        self.make_python("path", self.bin / "python3")
        self.make_python("brew", self.homebrew)
        self.make_python("local", self.local)
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.logs / "path.run").is_file())
        self.assertFalse((self.logs / "brew.probe").exists())
        self.assertFalse((self.logs / "local.probe").exists())
        self.assert_no_bootstrap()

    def test_old_path_python_falls_back_to_homebrew(self):
        self.make_python("path", self.bin / "python3", valid=False)
        self.make_python("brew", self.homebrew)
        self.make_python("local", self.local)
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.logs / "path.probe").is_file())
        self.assertTrue((self.logs / "brew.run").is_file())
        self.assertFalse((self.logs / "local.probe").exists())
        self.assert_no_bootstrap()

    def test_old_homebrew_python_falls_back_to_local(self):
        self.make_python("brew", self.homebrew, valid=False)
        self.make_python("local", self.local)
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.logs / "brew.probe").is_file())
        self.assertTrue((self.logs / "local.run").is_file())
        self.assert_no_bootstrap()

    def test_no_python_uses_bootstrap_and_validates_its_result(self):
        python = self.make_python("bootstrapped")
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(python)
        result = self.execute("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "bootstrap progress\n")
        self.assertTrue((self.logs / "bootstrap.called").is_file())
        self.assertEqual(self.read_arguments("bootstrapped", "probe"), ["-I", "-c", MINIMUM_PYTHON_PROBE])
        self.assertEqual(self.read_arguments("bootstrapped"), ["-I", shell_path(self.macos / "run.py"), "--status"])

    def test_bootstrap_result_with_old_python_is_rejected(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(self.make_python("oldbootstrap", valid=False))
        result = self.execute("--json")
        self.assert_failed(result)
        self.assertIn("校验失败", result.stderr)
        self.assertTrue((self.logs / "oldbootstrap.probe").is_file())

    def test_bootstrap_result_with_missing_executable_is_rejected(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(self.root / "missing python")
        self.assert_failed(self.execute())

    def test_bootstrap_relative_path_is_rejected(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = "relative/python3"
        result = self.execute()
        self.assert_failed(result)
        self.assertIn("绝对", result.stderr)

    def test_bootstrap_empty_stdout_is_rejected(self):
        self.assert_failed(self.execute())

    def test_bootstrap_extra_stdout_is_not_executed(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = "unwanted progress\n" + shell_path(self.make_python("bootstrap"))
        self.assert_failed(self.execute("--json"))
        self.assertFalse((self.logs / "bootstrap.probe").exists())

    def test_bootstrap_absolute_multiline_stdout_is_rejected(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(self.make_python("bootstrap")) + "\nunwanted progress"
        result = self.execute()
        self.assert_failed(result)
        self.assertIn("多行", result.stderr)
        self.assertFalse((self.logs / "bootstrap.probe").exists())

    def test_bootstrap_failure_status_is_preserved(self):
        self.env["FAKE_BOOTSTRAP_EXIT"] = "23"
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(self.make_python("unused"))
        self.assert_failed(self.execute(), code=23)
        self.assertFalse((self.logs / "unused.probe").exists())

    def test_help_without_python_never_bootstraps(self):
        result = self.execute("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1.3.4-mac.1", result.stdout)
        self.assertIn("--codex-home", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assert_no_bootstrap()

    def test_short_help_without_python_never_bootstraps(self):
        result = self.execute("-h")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("用法", result.stdout)
        self.assert_no_bootstrap()

    def test_help_and_json_without_python_keep_wrapper_stdout_empty(self):
        result = self.execute("--help", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("用法", result.stderr)
        self.assert_no_bootstrap()

    def test_help_with_python_delegates_to_real_argument_parser(self):
        self.make_python("path", self.bin / "python3")
        result = self.execute("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_arguments("path"), ["-I", shell_path(self.macos / "run.py"), "--help"])
        self.assert_no_bootstrap()

    def test_json_stdout_contains_only_python_output_even_during_bootstrap(self):
        self.env["FAKE_BOOTSTRAP_PYTHON"] = shell_path(self.make_python("bootstrap"))
        self.env["FAKE_PYTHON_OUTPUT"] = '{"ok":true,"action":"install"}\n'
        self.env.pop("XIAOGUAI_NO_PAUSE")
        result = self.execute("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '{"ok":true,"action":"install"}\n')
        self.assertEqual(result.stderr, "bootstrap progress\n")

    def test_python_exit_status_and_stderr_are_preserved(self):
        self.make_python("path", self.bin / "python3")
        self.env["FAKE_PYTHON_EXIT"] = "37"
        self.env["FAKE_PYTHON_STDERR"] = "runtime failure\n"
        self.env.pop("XIAOGUAI_NO_PAUSE")
        result = self.execute("--json")
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "runtime failure\n")

    def test_noninteractive_non_json_never_pauses(self):
        self.make_python("path", self.bin / "python3")
        self.env.pop("XIAOGUAI_NO_PAUSE")
        result = self.execute("--status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_non_darwin_platform_exits_before_python_or_bootstrap(self):
        self.make_python("path", self.bin / "python3")
        self.env["FAKE_UNAME"] = "Linux"
        result = self.execute("--json")
        self.assert_failed(result)
        self.assertIn("macOS", result.stderr)
        self.assertFalse((self.logs / "path.probe").exists())
        self.assert_no_bootstrap()

    def test_uname_failure_exits_before_python_or_bootstrap(self):
        self.env["FAKE_UNAME_EXIT"] = "1"
        self.assert_failed(self.execute())
        self.assert_no_bootstrap()

    def test_missing_run_module_exits_without_bootstrap(self):
        (self.macos / "run.py").unlink()
        result = self.execute()
        self.assert_failed(result)
        self.assertIn("run.py", result.stderr)
        self.assert_no_bootstrap()

    def test_missing_bootstrap_script_reports_incomplete_package(self):
        (self.macos / "bootstrap-python.sh").unlink()
        result = self.execute()
        self.assert_failed(result)
        self.assertIn("bootstrap-python.sh", result.stderr)
        self.assert_no_bootstrap()


if __name__ == "__main__":
    unittest.main()
