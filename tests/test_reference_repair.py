from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
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


class ReferenceRepairTests(unittest.TestCase):
    """All configuration and recovery files live below an isolated temporary root."""

    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="reference-repair-中文 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.expected_parent = Path(parent or tempfile.gettempdir()).resolve()
        if self.root.parent != self.expected_parent:
            raise RuntimeError("Test directory is outside the intended test root.")
        self.home = self.root / "isolated 配置"
        self.home.mkdir()
        self.store = app.ActivationStore(self.home)
        self.history_root = self.store.managed_dir / "history"

    def tearDown(self):
        if (self.root.resolve().parent != self.expected_parent
                or not self.root.name.startswith("reference-repair-中文 空格-")):
            raise RuntimeError("Refusing to clean a directory outside the test root.")
        self.temp.cleanup()

    def config_bytes(self, reference, settings="model = 'fake-model-before'\n", *, bom=False):
        text = "# isolated test configuration\n"
        if reference is not None:
            value = reference.as_posix() if isinstance(reference, Path) else reference
            text += engine.KEY + " = " + json.dumps(value, ensure_ascii=False) + " # selected reference\n"
        raw = (text + settings).replace("\n", "\r\n").encode("utf-8")
        return (engine.BOM if bom else b"") + raw

    def write_reference(self, reference, settings="model = 'fake-model-before'\n", *, bom=False):
        raw = self.config_bytes(reference, settings, bom=bom)
        self.store.config_path.write_bytes(raw)
        return raw

    def seed_install(self, *, config_existed=True, bom=False):
        self.initial_source = self.home / "initial 指令.md"
        self.initial_source.write_bytes("initial-source-sentinel\n保留初始源文件。\n".encode("utf-8"))
        if config_existed:
            self.initial_config = self.write_reference(self.initial_source, bom=bom)
        else:
            self.initial_config = None
        result = self.store.activate()
        self.assertFalse(result["reference_repaired"])
        self.assertIsNone(result["recovery_path"])
        self.assertFalse(result["model_reply_verified"])
        self.initial_target = Path(result["prompt_path"])
        return result

    def detached_source(self, name="external 指令.md", body="external-source-sentinel\n保留外部源文件。\n",
                        *, relative=False, outside_home=False):
        source = (self.root if outside_home else self.home) / name
        source.write_bytes(body.encode("utf-8"))
        reference = os.path.relpath(source, self.home).replace("\\", "/") if relative else source
        self.write_reference(reference)
        return source

    def snapshot(self, *, with_times=False):
        result = {}
        for path in self.root.rglob("*"):
            if path.is_file():
                value = path.read_bytes()
                if with_times:
                    value = (value, path.stat().st_mtime_ns)
                result[path.relative_to(self.root).as_posix()] = value
        return result

    def archive_snapshot(self, archive):
        return {path.relative_to(archive).as_posix(): path.read_bytes()
                for path in archive.rglob("*") if path.is_file()}

    def repair_baseline(self):
        state = self.store.read_state()
        owned = {Path(name): Path(name).read_bytes() for name in state["owned_prompts"]}
        return {
            "state_raw": self.store.state_path.read_bytes(),
            "config_raw": engine._bytes(self.store.config_path),
            "backup_raw": engine._bytes(self.store.backup_path),
            "backup_time": self.store.backup_path.stat().st_mtime_ns if self.store.backup_path.exists() else None,
            "owned": owned,
            "owned_times": {path: path.stat().st_mtime_ns for path in owned},
        }

    def assert_repair(self, result, baseline):
        self.assertTrue(result["reference_repaired"])
        self.assertFalse(result["unchanged"])
        self.assertEqual(result["version"], "1.3.4")
        self.assertIsInstance(result["recovery_path"], str)
        archive = Path(result["recovery_path"])
        self.assertTrue(archive.is_absolute())
        self.assertTrue(archive.is_dir())
        self.assertEqual(archive.parent, self.history_root)
        self.assertEqual((archive / "install-state.json").read_bytes(), baseline["state_raw"])
        self.assertEqual(engine._bytes(archive / "config-before-repair.toml"), baseline["config_raw"])
        self.assertEqual(engine._bytes(archive / "config-before-first-install.bak"), baseline["backup_raw"])
        for path, raw in baseline["owned"].items():
            self.assertEqual((archive / "prompts" / path.name).read_bytes(), raw)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, baseline["owned_times"][path])
        self.assertEqual(engine._bytes(self.store.backup_path), baseline["backup_raw"])
        if baseline["backup_time"] is not None:
            self.assertEqual(self.store.backup_path.stat().st_mtime_ns, baseline["backup_time"])
        state = self.store.read_state()
        before = engine.ConfigDocument(baseline["config_raw"])
        self.assertEqual(state["previous_line"], before.line)
        self.assertEqual(state["had_line"], before.line is not None)
        self.assertEqual(state["config_existed"], baseline["config_raw"] is not None)
        self.assertEqual(state["recovery_path"], str(archive))
        target = Path(result["prompt_path"])
        self.assertEqual(target, Path(state["prompt_path"]))
        self.assertEqual(target.parent, self.store.managed_dir)
        self.assertNotIn(target, baseline["owned"])
        self.assertEqual(state["owned_prompts"], {str(target): hashlib.sha256(target.read_bytes()).hexdigest()})
        installed = tomllib.loads(self.store.config_path.read_text("utf-8-sig"))
        self.assertEqual(Path(installed[engine.KEY]), target)
        self.assertEqual({key: value for key, value in installed.items() if key != engine.KEY},
                         {key: value for key, value in before.data.items() if key != engine.KEY})
        return archive, target

    def assert_sources_and_history_survive_restore(self, baseline, archive, target):
        archived_before = self.archive_snapshot(archive)
        self.assertTrue(self.store.restore())
        self.assertEqual(engine._bytes(self.store.config_path), baseline["config_raw"])
        self.assertFalse(target.exists())
        self.assertFalse(self.store.state_path.exists())
        self.assertEqual(self.archive_snapshot(archive), archived_before)
        for path, raw in baseline["owned"].items():
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(path.stat().st_mtime_ns, baseline["owned_times"][path])

    def test_valid_external_reference_repairs_to_current_source_with_exact_recovery_snapshots(self):
        self.seed_install(bom=True)
        source = self.detached_source()
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        baseline = self.repair_baseline()
        with patch.object(self.store, "install_content", wraps=self.store.install_content) as installer:
            result = self.store.activate()
        self.assertTrue(installer.call_args.kwargs["rebase_current"])
        archive, target = self.assert_repair(result, baseline)
        content = target.read_text("utf-8")
        self.assertIn("external-source-sentinel", content)
        self.assertNotIn("initial-source-sentinel", content)
        self.assertEqual(content.count(app.BEGIN), 1)
        self.assertEqual(content.count(app.GREETING_REPLY), 1)
        self.assertEqual(content.count(app.REPLY), 1)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)
        self.assert_sources_and_history_survive_restore(baseline, archive, target)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)

    def test_engine_install_default_and_restore_remain_strict_when_reference_is_detached(self):
        self.seed_install()
        self.detached_source()
        before = self.snapshot(with_times=True)
        with self.assertRaises(engine.ConfigConflictError):
            engine.ConfigStore.install_content(self.store, "new content", "new.md", "test")
        self.assertEqual(self.snapshot(with_times=True), before)
        with self.assertRaises(engine.ConfigConflictError):
            self.store.restore()
        self.assertEqual(self.snapshot(with_times=True), before)

    def test_missing_empty_or_deleted_reference_uses_default_and_rebases_restore_correctly(self):
        for kind in ("missing-key", "empty-reference", "empty-config", "deleted-config"):
            with self.subTest(kind=kind):
                # Every case starts from a separate valid installation, not a repaired state.
                child = self.home / kind
                child.mkdir()
                previous = self.store
                previous_history = self.history_root
                self.store = app.ActivationStore(child)
                self.history_root = self.store.managed_dir / "history"
                original_source = child / "original.md"
                original_source.write_bytes(b"old prompt sentinel\n")
                self.store.config_path.write_bytes(self.config_bytes(original_source))
                self.store.activate()
                if kind == "missing-key":
                    self.store.config_path.write_bytes(self.config_bytes(None))
                elif kind == "empty-reference":
                    self.store.config_path.write_bytes(self.config_bytes(""))
                elif kind == "empty-config":
                    self.store.config_path.write_bytes(b"")
                else:
                    self.store.config_path.unlink()
                try:
                    baseline = self.repair_baseline()
                    result = self.store.activate()
                    archive, target = self.assert_repair(result, baseline)
                    content = target.read_text("utf-8")
                    self.assertIn(app.DEFAULT_PROMPT, content)
                    self.assertNotIn("old prompt sentinel", content)
                    self.assertEqual(original_source.read_bytes(), b"old prompt sentinel\n")
                    self.assert_sources_and_history_survive_restore(baseline, archive, target)
                finally:
                    self.store = previous
                    self.history_root = previous_history

    def test_same_managed_target_in_relative_notation_does_not_rebase_or_write(self):
        self.seed_install()
        state_before = self.store.state_path.read_bytes()
        backup_before = self.store.backup_path.read_bytes()
        relative = self.initial_target.relative_to(self.home).as_posix()
        for reference in (relative, "./" + relative):
            with self.subTest(reference=reference):
                current = engine.ConfigDocument(self.store.config_path.read_bytes())
                replacement = engine.KEY + " = " + json.dumps(reference) + " # equivalent target\r\n"
                self.store.config_path.write_bytes(current.replace(replacement))
                before = self.snapshot(with_times=True)
                result = self.store.activate()
                self.assertFalse(result["reference_repaired"])
                self.assertTrue(result["unchanged"])
                self.assertIsNone(result["recovery_path"])
                self.assertEqual(self.snapshot(with_times=True), before)
                self.assertEqual(self.store.state_path.read_bytes(), state_before)
                self.assertEqual(self.store.backup_path.read_bytes(), backup_before)
                self.assertEqual(Path(result["prompt_path"]), self.initial_target)
        self.assertFalse(self.history_root.exists())
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), self.initial_config)

    def test_relative_external_reference_resolves_from_codex_home_not_process_directory(self):
        self.seed_install()
        source = self.detached_source(name="outside-home.md", relative=True, outside_home=True)
        source_before = (source.read_bytes(), source.stat().st_mtime_ns)
        baseline = self.repair_baseline()
        original_reference = engine.ConfigDocument(baseline["config_raw"]).data[engine.KEY]
        self.assertTrue(original_reference.startswith("../"))
        archive, target = self.assert_repair(self.store.activate(), baseline)
        self.assertIn("external-source-sentinel", target.read_text("utf-8"))
        self.assert_sources_and_history_survive_restore(baseline, archive, target)
        self.assertEqual(engine.ConfigDocument(self.store.config_path.read_bytes()).data[engine.KEY],
                         original_reference)
        self.assertEqual((source.read_bytes(), source.stat().st_mtime_ns), source_before)

    def test_reference_to_another_old_owned_prompt_is_never_deleted_on_restore(self):
        self.seed_install()
        original_prompt = self.initial_target
        original_prompt.write_bytes(b"manual old prompt prefix\n" + original_prompt.read_bytes())
        second = self.store.activate()
        second_prompt = Path(second["prompt_path"])
        self.assertNotEqual(original_prompt, second_prompt)
        self.assertEqual(set(self.store.read_state()["owned_prompts"]),
                         {str(original_prompt), str(second_prompt)})
        self.write_reference(original_prompt)
        baseline = self.repair_baseline()
        archive, target = self.assert_repair(self.store.activate(), baseline)
        self.assertNotEqual(target, original_prompt)
        self.assertNotEqual(target, second_prompt)
        self.assertIn("manual old prompt prefix", target.read_text("utf-8"))
        self.assert_sources_and_history_survive_restore(baseline, archive, target)
        restored = tomllib.loads(self.store.config_path.read_text("utf-8"))
        self.assertEqual(Path(restored[engine.KEY]), original_prompt)
        self.assertTrue(original_prompt.is_file())
        self.assertTrue(second_prompt.is_file())

    def test_repeated_repairs_have_unique_archives_and_repeated_activation_is_write_free(self):
        self.seed_install()
        first_source = self.detached_source(name="external-one.md")
        first_baseline = self.repair_baseline()
        first_archive, first_target = self.assert_repair(self.store.activate(), first_baseline)
        first_archive_before = self.archive_snapshot(first_archive)
        second_source = self.detached_source(name="external-two.md", body="second external sentinel\n")
        second_baseline = self.repair_baseline()
        second_archive, second_target = self.assert_repair(self.store.activate(), second_baseline)
        self.assertNotEqual(first_archive, second_archive)
        self.assertNotEqual(first_target, second_target)
        self.assertEqual(self.archive_snapshot(first_archive), first_archive_before)
        before = self.snapshot(with_times=True)
        with patch.object(self.store, "install_content", wraps=self.store.install_content) as installer:
            repeated = self.store.activate()
        installer.assert_not_called()
        self.assertFalse(repeated["reference_repaired"])
        self.assertTrue(repeated["unchanged"])
        if repeated["recovery_path"] is not None:
            self.assertEqual(Path(repeated["recovery_path"]), second_archive)
        self.assertEqual(self.snapshot(with_times=True), before)
        self.assertEqual(self.store.read_state()["recovery_path"], str(second_archive))
        self.assert_sources_and_history_survive_restore(second_baseline, second_archive, second_target)
        self.assertEqual(self.archive_snapshot(first_archive), first_archive_before)
        self.assertTrue(first_target.exists())
        self.assertTrue(self.initial_target.exists())
        self.assertTrue(first_source.exists())
        self.assertTrue(second_source.exists())

    def test_restore_preserves_later_model_and_fake_api_settings_after_repair(self):
        self.seed_install()
        source = self.detached_source()
        baseline = self.repair_baseline()
        archive, target = self.assert_repair(self.store.activate(), baseline)
        archived_before = self.archive_snapshot(archive)
        extra = (
            "model_reasoning_effort = 'high'\r\n"
            "model_provider = 'unit-test-fake'\r\n"
            "[model_providers.unit-test-fake]\r\n"
            "name = 'Fake API for unit tests'\r\n"
            "base_url = 'https://api.example.invalid/v1'\r\n"
            "env_key = 'UNIT_TEST_FAKE_API_KEY'\r\n"
        ).encode("utf-8")
        current = self.store.config_path.read_bytes().replace(b"fake-model-before", b"fake-model-after") + extra
        self.store.config_path.write_bytes(current)
        expected = baseline["config_raw"].replace(b"fake-model-before", b"fake-model-after") + extra
        self.assertTrue(self.store.restore())
        self.assertEqual(self.store.config_path.read_bytes(), expected)
        parsed = tomllib.loads(expected.decode("utf-8"))
        self.assertEqual(Path(parsed[engine.KEY]), source)
        self.assertEqual(parsed["model"], "fake-model-after")
        self.assertEqual(parsed["model_providers"]["unit-test-fake"]["base_url"],
                         "https://api.example.invalid/v1")
        self.assertEqual(self.archive_snapshot(archive), archived_before)
        self.assertFalse(target.exists())
        self.assertTrue(self.initial_target.exists())

    def test_repair_after_initially_absent_config_does_not_invent_a_first_backup(self):
        self.seed_install(config_existed=False)
        self.assertFalse(self.store.backup_path.exists())
        source = self.detached_source()
        baseline = self.repair_baseline()
        archive, target = self.assert_repair(self.store.activate(), baseline)
        self.assertFalse((archive / "config-before-first-install.bak").exists())
        self.assertFalse(self.store.backup_path.exists())
        self.assert_sources_and_history_survive_restore(baseline, archive, target)
        self.assertEqual(Path(engine.ConfigDocument(self.store.config_path.read_bytes()).data[engine.KEY]), source)

    def test_missing_empty_or_invalid_utf8_source_stops_repair_without_changes(self):
        self.seed_install()
        for index, raw in enumerate((None, b"", b" \r\n\t", engine.BOM, b"\xff\xfeinvalid")):
            with self.subTest(raw=raw):
                source = self.home / f"invalid-source-{index}.md"
                if raw is not None:
                    source.write_bytes(raw)
                self.write_reference(source)
                before = self.snapshot(with_times=True)
                with self.assertRaises(engine.ConfigError):
                    self.store.activate()
                self.assertEqual(self.snapshot(with_times=True), before)
        self.assertFalse(self.history_root.exists())

    def test_invalid_toml_or_non_string_reference_stops_repair_without_changes(self):
        self.seed_install()
        for raw in (b"broken = [", b"\xffnot-utf8", b"model_instructions_file = 42\n"):
            with self.subTest(raw=raw):
                self.store.config_path.write_bytes(raw)
                before = self.snapshot(with_times=True)
                with self.assertRaises(engine.ConfigError):
                    self.store.activate()
                self.assertEqual(self.snapshot(with_times=True), before)
        self.assertFalse(self.history_root.exists())

    def test_damaged_install_state_stops_repair_without_changes(self):
        self.seed_install()
        self.detached_source()
        state = self.store.read_state()
        wrong_digest = dict(state, owned_prompts={state["prompt_path"]: "invalid"})
        invalid_states = (b"{not-json", b"[]", b'{"version":999}',
                          (json.dumps(wrong_digest, ensure_ascii=False) + "\n").encode("utf-8"))
        for raw in invalid_states:
            with self.subTest(raw=raw):
                self.store.state_path.write_bytes(raw)
                before = self.snapshot(with_times=True)
                with self.assertRaises(engine.ConfigError):
                    self.store.activate()
                self.assertEqual(self.snapshot(with_times=True), before)
        self.assertFalse(self.history_root.exists())

    def test_active_profile_override_is_not_repaired_or_overwritten(self):
        self.seed_install()
        source = self.detached_source()
        raw = ("profile = 'isolated-test'\r\n".encode("utf-8") + self.config_bytes(source)
               + b"[profiles.isolated-test]\r\nmodel_instructions_file = 'profile-only.md'\r\n")
        self.store.config_path.write_bytes(raw)
        before = self.snapshot(with_times=True)
        with self.assertRaisesRegex(engine.ConfigError, "profile"):
            self.store.activate()
        self.assertEqual(self.snapshot(with_times=True), before)
        self.assertFalse(self.history_root.exists())

    def test_history_symlink_or_junction_is_rejected_before_any_repair_writes(self):
        self.seed_install()
        self.detached_source()
        before = self.snapshot(with_times=True)
        real_check = engine._is_link
        with patch.object(engine, "_is_link",
                          side_effect=lambda path: Path(path) == self.history_root or real_check(path)):
            with self.assertRaises(engine.ConfigError):
                self.store.activate()
        self.assertEqual(self.snapshot(with_times=True), before)

    def test_control_file_references_are_rejected_before_source_reads_or_writes(self):
        original_store, original_history = self.store, self.history_root
        for installed in (False, True):
            child = self.home / ("installed-controls" if installed else "fresh-controls")
            child.mkdir()
            self.store = app.ActivationStore(child)
            self.history_root = self.store.managed_dir / "history"
            try:
                if installed:
                    self.seed_install()
                controls = (self.store.config_path, self.store.state_path, self.store.backup_path,
                            self.store.managed_dir / "install.lock")
                for control in controls:
                    relative = control.relative_to(self.store.codex_home).as_posix()
                    for reference in (control.as_posix(), relative, "./" + relative):
                        with self.subTest(installed=installed, control=control.name, reference=reference):
                            self.write_reference(reference)
                            before = self.snapshot(with_times=True)
                            with (patch.object(app, "_bytes", wraps=app._bytes) as reads,
                                  patch.object(app, "compose_prompt", wraps=app.compose_prompt) as composer,
                                  patch.object(self.store, "install_content",
                                               wraps=self.store.install_content) as installer):
                                with self.assertRaisesRegex(engine.ConfigError, "配置、状态、备份或锁文件"):
                                    self.store.activate()
                            composer.assert_not_called()
                            installer.assert_not_called()
                            # Config and state each have one necessary metadata read;
                            # neither may be read again as an instruction source.
                            source_reads = sum(Path(call.args[0]).resolve() == control.resolve()
                                               for call in reads.call_args_list)
                            allowed = 1 if control in (self.store.config_path, self.store.state_path) else 0
                            self.assertLessEqual(source_reads, allowed)
                            self.assertEqual(self.snapshot(with_times=True), before)
                            self.assertFalse(self.history_root.exists())
            finally:
                self.store, self.history_root = original_store, original_history

    def test_source_change_before_install_is_detected_without_partial_repair(self):
        self.seed_install()
        source = self.detached_source()
        before = self.snapshot()
        original_install = self.store.install_content
        changed = b"concurrent external source change\n"

        def change_then_install(*args, **kwargs):
            source.write_bytes(changed)
            return original_install(*args, **kwargs)

        with patch.object(self.store, "install_content", side_effect=change_then_install):
            with self.assertRaises(engine.ConfigConflictError):
                self.store.activate()
        before[source.relative_to(self.root).as_posix()] = changed
        self.assertEqual(self.snapshot(), before)

    def test_source_change_at_transaction_entry_is_detected_without_partial_repair(self):
        self.seed_install()
        source = self.detached_source()
        before = self.snapshot()
        original_transaction = engine._transaction
        changed = b"late concurrent source change\n"

        def change_then_commit(updates, expected):
            source.write_bytes(changed)
            return original_transaction(updates, expected)

        with patch.object(engine, "_transaction", side_effect=change_then_commit):
            with self.assertRaises(engine.ConfigConflictError):
                self.store.activate()
        before[source.relative_to(self.root).as_posix()] = changed
        self.assertEqual(self.snapshot(), before)

    def test_source_change_during_writes_rolls_back_without_discarding_external_edit(self):
        self.seed_install()
        source = self.detached_source()
        original_write = engine._atomic_write
        for stage in ("after-first-history-write", "after-final-config-write"):
            with self.subTest(stage=stage):
                before = self.snapshot()
                changed = ("external edit at " + stage + "\n").encode("utf-8")
                injected = {"done": False}

                def write_then_change_source(path, data):
                    original_write(path, data)
                    matches = (
                        self.history_root in Path(path).parents and Path(path).name == "install-state.json"
                        if stage == "after-first-history-write" else Path(path) == self.store.config_path
                    )
                    if data is not None and matches and not injected["done"]:
                        injected["done"] = True
                        source.write_bytes(changed)

                with patch.object(engine, "_atomic_write", side_effect=write_then_change_source):
                    with self.assertRaises(engine.ConfigConflictError):
                        self.store.activate()
                self.assertTrue(injected["done"])
                before[source.relative_to(self.root).as_posix()] = changed
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(source.read_bytes(), changed)

    def test_source_and_final_config_edits_retain_a_consistent_non_dangling_installation(self):
        outer_home, outer_store, outer_history = self.home, self.store, self.history_root
        for mode in ("final-cas-conflict", "partially-completed-write"):
            self.home = outer_home / mode
            self.home.mkdir()
            self.store = app.ActivationStore(self.home)
            self.history_root = self.store.managed_dir / "history"
            try:
                with self.subTest(mode=mode):
                    self.seed_install()
                    source = self.detached_source()
                    source_before = source.read_bytes()
                    baseline = self.repair_baseline()
                    changed_source = b"external source edit after the final config write\n"
                    added_setting = b"external_setting_after_repair = 'preserve-this-value'\r\n"
                    original_write = engine._atomic_write
                    injected = {"done": False}

                    def write_then_modify_both(path, data):
                        original_write(path, data)
                        if Path(path) == self.store.config_path and data is not None and not injected["done"]:
                            injected["done"] = True
                            injected["config_raw"] = data + added_setting
                            self.store.config_path.write_bytes(injected["config_raw"])
                            source.write_bytes(changed_source)
                            injected["state_raw"] = self.store.state_path.read_bytes()
                            staged_state = json.loads(injected["state_raw"].decode("utf-8"))
                            injected["archive"] = Path(staged_state["recovery_path"])
                            injected["archive_files"] = self.archive_snapshot(injected["archive"])
                            if mode == "partially-completed-write":
                                raise OSError("simulated failure after the config write completed")

                    with patch.object(engine, "_atomic_write", side_effect=write_then_modify_both):
                        with self.assertRaises(engine.ConfigError):
                            self.store.activate()
                    self.assertTrue(injected["done"])
                    self.assertEqual(source.read_bytes(), changed_source)
                    self.assertEqual(self.store.config_path.read_bytes(), injected["config_raw"])
                    self.assertEqual(self.store.state_path.read_bytes(), injected["state_raw"])
                    config = tomllib.loads(self.store.config_path.read_text("utf-8"))
                    self.assertEqual(config["external_setting_after_repair"], "preserve-this-value")
                    target = Path(config[engine.KEY])
                    self.assertTrue(target.is_file(), "Retained config must never point to a removed prompt.")
                    self.assertNotIn(target, baseline["owned"])
                    self.assertEqual(target.read_bytes(), app.compose_prompt(source_before.decode("utf-8")).encode("utf-8"))
                    state = self.store.read_state()
                    self.assertEqual(Path(state["prompt_path"]), target)
                    self.assertEqual(state["previous_line"], engine.ConfigDocument(baseline["config_raw"]).line)
                    self.assertEqual(state["owned_prompts"], {str(target): hashlib.sha256(target.read_bytes()).hexdigest()})
                    self.assertIsNotNone(self.store.current_profile())
                    archive = Path(state["recovery_path"])
                    self.assertEqual(archive, injected["archive"])
                    self.assertEqual(self.archive_snapshot(archive), injected["archive_files"])
                    self.assertEqual((archive / "install-state.json").read_bytes(), baseline["state_raw"])
                    self.assertEqual((archive / "config-before-repair.toml").read_bytes(), baseline["config_raw"])
                    self.assertEqual((archive / "config-before-first-install.bak").read_bytes(), baseline["backup_raw"])
                    self.assertEqual(self.store.backup_path.read_bytes(), baseline["backup_raw"])
                    self.assertEqual(self.store.backup_path.stat().st_mtime_ns, baseline["backup_time"])
                    for old_path, old_raw in baseline["owned"].items():
                        self.assertEqual(old_path.read_bytes(), old_raw)
                        self.assertEqual((archive / "prompts" / old_path.name).read_bytes(), old_raw)
                    self.assertFalse((self.store.managed_dir / "install.lock").exists())
            finally:
                self.home, self.store, self.history_root = outer_home, outer_store, outer_history

    def test_atomic_failure_rolls_back_history_prompt_state_and_config(self):
        self.seed_install()
        self.detached_source()
        original_write = engine._atomic_write
        old_target = self.initial_target

        def matches(stage, path):
            path = Path(path)
            if stage == "history-state":
                return self.history_root in path.parents and path.name == "install-state.json"
            if stage == "history-prompt":
                return self.history_root in path.parents and path.parent.name == "prompts"
            if stage == "new-prompt":
                return path.parent == self.store.managed_dir and path.suffix == ".md" and path != old_target
            if stage == "state":
                return path == self.store.state_path
            return path == self.store.config_path

        for stage in ("history-state", "history-prompt", "new-prompt", "state", "config"):
            with self.subTest(stage=stage):
                before = self.snapshot()
                backup_before = (self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns)
                fault = {"hit": False}

                def fail_once(path, data):
                    if data is not None and not fault["hit"] and matches(stage, path):
                        fault["hit"] = True
                        raise OSError("simulated repair write failure")
                    return original_write(path, data)

                with patch.object(engine, "_atomic_write", side_effect=fail_once):
                    with self.assertRaises(OSError):
                        self.store.activate()
                self.assertTrue(fault["hit"])
                self.assertEqual(self.snapshot(), before)
                self.assertEqual((self.store.backup_path.read_bytes(), self.store.backup_path.stat().st_mtime_ns),
                                 backup_before)
                self.assertFalse((self.store.managed_dir / "install.lock").exists())

    def test_no_open_cli_reports_successful_reference_repair_as_json(self):
        self.seed_install()
        self.detached_source()
        baseline = self.repair_baseline()
        out = io.StringIO()
        with patch.object(app.os, "startfile", create=True) as opener, contextlib.redirect_stdout(out):
            rc = app.main(["--codex-home", str(self.home), "--install", "--no-open", "--json"])
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        self.assertTrue(result["reference_repaired"])
        self.assertFalse(result["codex_open_requested"])
        self.assertFalse(result["model_reply_verified"])
        self.assertEqual(result["assistant_name"], "小怪")
        self.assertEqual(result["expected_greeting"], "「你好」\n小怪在。👋")
        self.assert_repair(result, baseline)
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
