from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import privacy_check as app


class PrivacyCheckTests(unittest.TestCase):
    def setUp(self):
        parent = os.environ.get("XIAOGUAI_TEST_ROOT")
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        self.parent = Path(parent or tempfile.gettempdir()).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix="privacy-中文 空格-", dir=parent)
        self.root = Path(self.temp.name).resolve()
        self.assertEqual(self.root.parent, self.parent)
        self.home = self.root / "private home"

    def tearDown(self):
        if self.root.parent != self.parent or not self.root.name.startswith("privacy-中文 空格-"):
            raise RuntimeError("Refusing cleanup outside the intended test root")
        self.temp.cleanup()

    def configure(self, text):
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.home / "config.toml"
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path

    def check(self, environ=None):
        return app.check_privacy(self.home, {} if environ is None else environ)

    def test_missing_home_is_read_only_and_never_reported_as_safe(self):
        result = self.check()
        self.assertTrue(result["ok"])
        self.assertEqual(result["configuration_status"], "missing")
        self.assertFalse(self.home.exists())
        self.assertEqual(result["interception_status"], "not_tested")
        self.assertFalse(result["prevents_local_or_proxy_extraction"])
        self.assertFalse(result["network_probes_performed"])

    def test_reads_only_config_never_prompt_credentials_or_referenced_network_path(self):
        self.configure("model_instructions_file = '\\\\server\\share\\secret-prompt.md'\n")
        (self.home / "auth.json").write_text("PRIVATE_AUTH_SENTINEL", encoding="utf-8")
        (self.home / "secret-prompt.md").write_text("PRIVATE_PROMPT_SENTINEL", encoding="utf-8")
        original = Path.open
        opened = []

        def tracked(path, *args, **kwargs):
            opened.append(path)
            if path != self.home / "config.toml":
                raise AssertionError("Unexpected content read")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", tracked):
            result = self.check()
        self.assertEqual(opened, [self.home / "config.toml"])
        self.assertTrue(result["instruction_reference_configured"])
        self.assertFalse(result["prompt_contents_read"])
        self.assertFalse(result["credentials_files_read"])
        self.assertNotIn("SENTINEL", json.dumps(result))

    def test_valid_config_bytes_and_mtime_unchanged(self):
        path = self.configure(b"\xef\xbb\xbfmodel = 'test'\r\n# keep me\r\n")
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        result = self.check()
        self.assertEqual(result["configuration_status"], "valid")
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(list(self.home.iterdir()), [path])

    def test_invalid_config_does_not_echo_private_parser_input(self):
        self.configure("PRIVATE_CONFIG_SENTINEL = [broken")
        result = self.check()
        self.assertFalse(result["ok"])
        self.assertEqual(result["configuration_status"], "invalid")
        self.assertNotIn("PRIVATE_CONFIG_SENTINEL", json.dumps(result) + app.format_privacy_report(result))

    def test_invalid_utf8_has_sanitized_error(self):
        self.configure(b"\xff\xfePRIVATE_SENTINEL")
        result = self.check()
        self.assertEqual(result["configuration_status"], "invalid")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_large_config_is_not_opened(self):
        self.configure(b"#" * (app.MAX_CONFIG_BYTES + 1))
        with patch.object(Path, "open", side_effect=AssertionError("Too large file was opened")):
            result = self.check()
        self.assertEqual(result["configuration_status"], "too_large")

    def test_directory_config_is_not_read(self):
        (self.home / "config.toml").mkdir(parents=True)
        self.assertEqual(self.check()["configuration_status"], "not_regular")

    def test_symbolic_config_is_not_read(self):
        with patch.object(Path, "is_symlink", return_value=True), patch.object(Path, "open", side_effect=AssertionError):
            self.assertEqual(self.check()["configuration_status"], "linked")

    def test_unreadable_config_error_is_redacted(self):
        self.configure("model = 'test'\n")
        with patch.object(Path, "open", side_effect=PermissionError("PRIVATE_PATH_SENTINEL")):
            result = self.check()
        self.assertEqual(result["configuration_status"], "unreadable")
        self.assertNotIn("PRIVATE_PATH_SENTINEL", json.dumps(result))

    def test_only_fixed_environment_names_and_no_values_are_returned(self):
        result = self.check({
            "https_proxy": "http://PRIVATE_USER:PRIVATE_PASSWORD@PRIVATE_HOST:3210",
            "HTTPS_PROXY": "http://OTHER_PRIVATE_HOST",
            "ALL_PROXY": "socks5://SECRET_PROXY",
            "HTTP_PROXY": "  ",
            "SSL_CERT_FILE": "PRIVATE_CERT_PATH",
            "NODE_EXTRA_CA_CERTS": "PRIVATE_NODE_CA_PATH",
            "OPENAI_API_KEY": "PRIVATE_API_KEY",
            "RANDOM_PRIVATE_ENV_KEY": "PRIVATE_ENV_VALUE",
        })
        self.assertEqual(result["proxy_environment_names"], ["HTTPS_PROXY", "ALL_PROXY"])
        self.assertEqual(result["certificate_environment_names"], ["SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS"])
        output = json.dumps(result) + app.format_privacy_report(result)
        self.assertNotIn("PRIVATE_", output)
        self.assertNotIn("SECRET_PROXY", output)

    def test_active_profile_is_used_without_disclosing_profile_or_provider_name(self):
        self.configure("""profile = 'PRIVATE_PROFILE'
model_provider = 'old'
model_instructions_file = 'PRIVATE_PROMPT_PATH'
[profiles.PRIVATE_PROFILE]
model_provider = 'PRIVATE_PROVIDER'
[model_providers.old]
base_url = 'https://api.openai.com/v1'
[model_providers.PRIVATE_PROVIDER]
base_url = 'http://PRIVATE_USER:PRIVATE_PASS@localhost:3210/PRIVATE_PATH?token=PRIVATE_QUERY#PRIVATE_FRAGMENT'
api_key = 'PRIVATE_API_KEY'
""")
        result = self.check()
        endpoint = result["configured_provider_endpoint"]
        self.assertEqual(result["profile_resolution"], "selected")
        self.assertEqual(endpoint["scheme"], "http")
        self.assertEqual(endpoint["destination_class"], "loopback_hostname")
        self.assertTrue(endpoint["credentials_in_url"])
        self.assertTrue(endpoint["query_or_fragment_present"])
        self.assertNotIn("PRIVATE_", json.dumps(result) + app.format_privacy_report(result))

    def test_unknown_profile_or_provider_never_asserts_a_known_route(self):
        for text in ("profile = 'not found'", "model_provider = 'not found'", "profile = ['bad']", "model_provider = ['bad']"):
            with self.subTest(text=text):
                self.configure(text)
                result = self.check()
                self.assertIn("ROUTE_UNRESOLVED", [x["code"] for x in result["findings"]])
                self.assertEqual(result["interception_status"], "not_tested")

    def test_environment_endpoint_is_a_hint_not_a_confirmed_route(self):
        result = self.check({"OPENAI_BASE_URL": "http://PRIVATE_USER:PRIVATE_PASS@[::1]:3210/PRIVATE_PATH?PRIVATE_QUERY"})
        self.assertEqual(result["environment_endpoint_hint"]["destination_class"], "loopback_address")
        self.assertEqual(result["configured_provider_endpoint"]["scheme"], "not_configured")
        self.assertIn("ENDPOINT_ENV_HINT", [x["code"] for x in result["findings"]])
        self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_endpoint_classification_is_strict_without_echoing_addresses(self):
        cases = [
            ("https://api.openai.com/v1", "https", "openai_api_hostname"),
            ("https://API.OPENAI.COM./v1", "https", "openai_api_hostname"),
            ("https://api.openai.com.attacker.example/v1", "https", "other_destination"),
            ("http://127.0.0.1:3210", "http", "loopback_address"),
            ("https://[::1]:3210", "https", "loopback_address"),
            ("https://10.0.0.2", "https", "other_destination"),
            ("https://sub.localhost", "https", "loopback_hostname"),
            ("file://somehost/path", "other", "other_destination"),
        ]
        for value, scheme, kind in cases:
            with self.subTest(value=value):
                result = app._endpoint_summary(value)
                self.assertEqual(result["scheme"], scheme)
                self.assertEqual(result["destination_class"], kind)
                self.assertNotIn(value, json.dumps(result))

    def test_malformed_endpoint_types_and_ports_are_not_echoed(self):
        for value in ([], {}, 123, "", "PRIVATE_SENTINEL", "https://[bad", "https://host:99999", "https://host:bad", "X" * 16385):
            with self.subTest(value_type=type(value).__name__):
                result = app._endpoint_summary(value)
                self.assertEqual(result["scheme"], "invalid")
                self.assertEqual(result["destination_class"], "unknown")
                self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_public_api_hostname_does_not_imply_interception_protection(self):
        self.configure("model_provider = 'test'\n[model_providers.test]\nbase_url = 'https://api.openai.com/v1'\n")
        result = self.check()
        self.assertEqual(result["configured_provider_endpoint"]["destination_class"], "openai_api_hostname")
        self.assertFalse(result["prevents_local_or_proxy_extraction"])
        self.assertEqual(result["interception_status"], "not_tested")

    def test_unparseable_endpoint_has_visible_redacted_finding(self):
        self.configure("model_provider = 'test'\n[model_providers.test]\nbase_url = 'PRIVATE_BAD_ENDPOINT'\n")
        result = self.check()
        self.assertIn("ENDPOINT_UNRESOLVED", [x["code"] for x in result["findings"]])
        self.assertNotIn("PRIVATE_BAD_ENDPOINT", app.format_privacy_report(result))

    def test_report_includes_limits_not_a_claim_to_detect_all_proxies(self):
        output = app.format_privacy_report(self.check())
        for required in ("不是防抓包功能", "未发现代理提示也不代表安全", "系统代理", "未更改代理"):
            self.assertIn(required, output)
        self.assertNotIn(str(self.home), output)


if __name__ == "__main__":
    unittest.main()
