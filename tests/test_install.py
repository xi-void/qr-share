import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / "hypr/bindings.lua"
        self.config.parent.mkdir()
        self.original = '-- My custom bindings\no.bind("SUPER + X", "Custom", "custom")\n'
        self.config.write_text(self.original)
        self.command = Path("/home/test/.local/bin/qr-share")
        self.env = patch.dict("os.environ", {"XDG_CONFIG_HOME": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_update(self, command_results, **kwargs):
        calls = []
        def fake_run(command):
            calls.append(command)
            return command_results(command)
        with patch("install.shutil.which", return_value="/usr/bin/hyprctl"), patch("install.run", side_effect=fake_run), contextlib.redirect_stdout(io.StringIO()):
            install.update_binding(self.command, **kwargs)
        return calls

    @staticmethod
    def healthy(command):
        return subprocess.CompletedProcess(command, 0, "[]" if "binds" in command else "", "")

    def test_idempotent_and_removes_only_own_block(self):
        self.run_update(self.healthy)
        first = self.config.read_text()
        self.assertTrue(first.startswith(self.original))
        self.run_update(self.healthy)
        self.assertEqual(self.config.read_text(), first)
        self.assertEqual(first.count(install.BEGIN), 1)
        self.run_update(self.healthy, uninstall=True)
        self.assertEqual(self.config.read_text().rstrip(), self.original.rstrip())
        self.assertTrue(list(self.config.parent.glob("*.bak.*")))

    def test_conflicting_shortcut_is_preserved(self):
        def conflict(command):
            result = self.healthy(command)
            if "binds" in command:
                result.stdout = json.dumps([{"modmask": 69, "key": "Q", "description": "Existing"}])
            return result
        self.run_update(conflict)
        self.assertEqual(self.config.read_text(), self.original)

    def test_failed_reload_restores_original_and_validates(self):
        reloads = 0
        def fails_once(command):
            nonlocal reloads
            result = self.healthy(command)
            if "reload" in command:
                reloads += 1
                result.returncode = 1 if reloads == 1 else 0
            return result
        calls = self.run_update(fails_once)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(reloads, 2)
        self.assertEqual(calls[-1], ["hyprctl", "configerrors"])

    def test_dry_run_does_not_write(self):
        self.run_update(self.healthy, dry_run=True)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.config.parent.iterdir()), [self.config])


class InstallTests(unittest.TestCase):
    def test_staged_install_upgrade_and_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="qr-share space ") as directory:
            args = ["--prefix", directory]
            with contextlib.redirect_stdout(io.StringIO()):
                install.main(args)
                install.main(args)
            root = Path(directory)
            executable = root / "bin/qr-share"
            desktop = root / "share/applications/local.omarchy.QRShare.desktop"
            result = subprocess.run([str(executable), "--help"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run(["desktop-file-validate", str(desktop)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with contextlib.redirect_stdout(io.StringIO()):
                install.main(args + ["--uninstall"])
            self.assertFalse(executable.exists())
            self.assertFalse(desktop.exists())
            self.assertFalse((root / "share/qr-share").exists())

    def test_unmanaged_command_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "bin/qr-share"
            executable.parent.mkdir()
            executable.write_text("user-owned")
            with self.assertRaisesRegex(RuntimeError, "Refusing to overwrite"):
                install.main(["--prefix", directory])
            self.assertEqual(executable.read_text(), "user-owned")


if __name__ == "__main__":
    unittest.main()
