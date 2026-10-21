"""Windows wizard and optional frozen-EXE smoke tests, using temporary homes."""

import contextlib
import http.server
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import wb_agent_setup as setup
import wb_agents

EXE = None
if "--exe" in sys.argv:
    index = sys.argv.index("--exe")
    EXE = str(Path(sys.argv[index + 1]).resolve())
    del sys.argv[index:index + 2]
COMMAND = [EXE] if EXE else [sys.executable, str(ROOT / "wb_agent_setup.py")]
KEY = "sk-test-only-agent-setup"


class Gateway(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer " + KEY:
            self.send_error(401)
            return
        body = json.dumps({"data": [{"id": "model-one", "supports_vision": True,
                                      "context_length": 64000}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class SetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.gateway = "http://127.0.0.1:%d/v1" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(5)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-setup-")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "用户 home"
        self.home.mkdir()
        self.state = Path(self.tmp.name) / "state"
        env = os.environ.copy()
        for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "DSH_HOME",
                     "WB_PROXY_API_KEY", "PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        self.environment = patch.dict(os.environ, env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_cli(self, *args):
        env = os.environ.copy()
        if EXE:
            # Exercise the frozen app without python/py/pip on PATH.
            env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        return subprocess.run(COMMAND + ["--home", str(self.home), "--state-dir",
                                         str(self.state)] + list(args),
                              cwd=self.tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=45)

    def test_url_validation(self):
        self.assertEqual(setup.normalize_gateway(" https://example.test/root/ "),
                         "https://example.test/root/v1")
        self.assertEqual(setup.normalize_gateway(self.gateway), self.gateway)
        for bad in ("", "file:///tmp/x", "ftp://x", "http://user:secret@x",
                    "https://x?key=secret", "https://x/#secret", "http://x:99999",
                    "http://x\n/evil", "http://[broken"):
            with self.subTest(bad=bad), self.assertRaises(wb_agents.AgentConfigError):
                setup.normalize_gateway(bad)

    def test_all_six_clients_apply_and_restore_original_bytes(self):
        for client_id, client in wb_agents.CLIENTS.items():
            with self.subTest(client=client_id):
                originals = {}
                for path in client["files"](str(self.home)).values():
                    path = Path(path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.suffix == ".toml":
                        value = '# 用户注释\r\n[other]\r\nvalue = "keep"\r\n'
                    elif path.suffix in (".yaml", ".yml"):
                        value = "# original\r\nrefs:\r\n  KEEP: unchanged\r\n" if "credentials" in path.name else "# original\r\n"
                    elif client_id == "zcode":
                        value = '{"schemaVersion":1,"config":{"providerOrder":[],"providerConfigRules":{"providerRules":[]}},"keep":true}\r\n'
                    else:
                        value = '{"keep":"用户原配置"}\r\n'
                    originals[path] = value.encode("utf-8")
                    path.write_bytes(originals[path])
                result = self.run_cli("apply", "--client", client_id, "--base-url",
                                      self.gateway, "--key", KEY, "--model", "model-one")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(KEY, result.stdout)
                self.assertTrue(any(KEY in path.read_text(encoding="utf-8") for path in originals))
                result = self.run_cli("restore", "--client", client_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                for path, content in originals.items():
                    self.assertEqual(path.read_bytes(), content)

    def test_rejected_key_writes_nothing(self):
        result = self.run_cli("apply", "--client", "codex", "--base-url",
                              self.gateway, "--key", "wrong-test-key")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("401", result.stderr)
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertFalse(self.state.exists())

    def test_new_config_removed_on_restore(self):
        result = self.run_cli("apply", "--client", "claude-code", "--base-url",
                              self.gateway, "--key", KEY, "--model", "model-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        target = self.home / ".claude" / "settings.json"
        self.assertTrue(target.exists())
        result = self.run_cli("restore", "--client", "claude-code")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(target.exists())

    def test_wizard_confirmation_and_cancel(self):
        for answer, expected in (("n", False), ("y", True)):
            with self.subTest(answer=answer):
                output = io.StringIO()
                with patch("builtins.input", side_effect=["1", "1", self.gateway, "1", answer, "0"]), \
                        patch("getpass.getpass", return_value=KEY), contextlib.redirect_stdout(output):
                    self.assertEqual(setup.wizard(str(self.home), str(self.state)), 0)
                self.assertEqual((self.home / ".claude" / "settings.json").exists(), expected)
                self.assertNotIn(KEY, output.getvalue())

    def test_wizard_bad_key_stays_open_and_does_not_write(self):
        output = io.StringIO()
        with patch("builtins.input", side_effect=["1", "1", self.gateway, "0"]), \
                patch("getpass.getpass", return_value="wrong-test-key"), contextlib.redirect_stdout(output):
            self.assertEqual(setup.wizard(str(self.home), str(self.state)), 0)
        self.assertIn("401", output.getvalue())
        self.assertNotIn("wrong-test-key", output.getvalue())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_license_is_in_bundle(self):
        result = subprocess.run(COMMAND + ["--license"], cwd=self.tmp.name,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MIT License", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
