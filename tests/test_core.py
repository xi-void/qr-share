import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from qrshare.core import QRError, encode, normalize_link, save_image

ROOT = Path(__file__).resolve().parents[1]


class LinkTests(unittest.TestCase):
    def test_normalization(self):
        cases = {
            "  example.com/a?b=1#c  ": "https://example.com/a?b=1#c",
            "localhost:3000/test": "https://localhost:3000/test",
            "http://192.168.0.1:8080/": "http://192.168.0.1:8080/",
            "https://[::1]:8080/path": "https://[::1]:8080/path",
            "https://例え.jp/道?q=✓": "https://例え.jp/道?q=✓",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_link(value), expected)

    def test_invalid_links(self):
        for value in ["", "  ", "https://", "hello world", "https://x.test/\nx", "https://x.test/\0",
                      "javascript:alert(1)", "mailto:a@b.com", "ftp://example.com", "http:example.com",
                      "https://x.test:99999", "https://x.test:port", "https://[invalid]/", "https://-bad.test",
                      "https://bad..test", "https://example.com\\@evil.test"]:
            with self.subTest(value=value):
                self.assertRaises(QRError, normalize_link, value)

    def test_capacity_counts_utf8_bytes(self):
        prefix = "https://example.com/"
        self.assertEqual(len(normalize_link(prefix + "a" * (2331 - len(prefix)))), 2331)
        self.assertRaises(QRError, normalize_link, prefix + "a" * 2332)
        self.assertRaises(QRError, normalize_link, prefix + "道" * 800)

    def test_missing_encoder_is_actionable(self):
        with patch("qrshare.core.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(QRError, "omarchy pkg add qrencode"):
                encode("example.com")

    def test_invalid_output_options(self):
        self.assertRaises(QRError, encode, "example.com", "jpg")
        self.assertRaises(QRError, encode, "example.com", "png", 0)


@unittest.skipUnless(shutil.which("qrencode") and shutil.which("zbarimg"), "requires qrencode and zbarimg")
class RoundTripTests(unittest.TestCase):
    def assert_decodes(self, payload, expected):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.png"
            path.write_bytes(payload)
            result = subprocess.run(["zbarimg", "--quiet", "--raw", str(path)], capture_output=True, check=True)
            self.assertEqual(result.stdout.decode("utf-8").rstrip("\n"), expected)

    def test_png_round_trips(self):
        for value in [
            "example.com",
            "https://example.com/path?first=one&second=two#fragment",
            "https://example.com/道?q=Grüße✓",
            "https://example.com/?literal=$(touch${IFS}/tmp/qr-share-injected)`id`",
            "https://example.com/" + "a" * 2000,
        ]:
            with self.subTest(value=value[:70]):
                png = encode(value)
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assert_decodes(png, normalize_link(value))

    @unittest.skipUnless(shutil.which("rsvg-convert"), "requires rsvg-convert")
    def test_svg_round_trip(self):
        link = "https://example.com/vector?x=1&y=2#anchor"
        svg = encode(link, "svg")
        png = subprocess.run(["rsvg-convert", "--format=png"], input=svg, capture_output=True, check=True).stdout
        self.assert_decodes(png, link)

    def test_maximum_capacity_encodes(self):
        prefix = "https://example.com/"
        self.assertTrue(encode(prefix + "a" * (2331 - len(prefix))).startswith(b"\x89PNG"))


class FileTests(unittest.TestCase):
    def test_existing_file_protected_and_force_replaces(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.png"
            save_image(path, b"first")
            self.assertRaises(QRError, save_image, path, b"second")
            self.assertEqual(path.read_bytes(), b"first")
            save_image(path, b"second", overwrite=True)
            self.assertEqual(path.read_bytes(), b"second")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_symlink_does_not_overwrite_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "original"
            target.write_bytes(b"preserve")
            link = Path(directory) / "qr.png"
            link.symlink_to(target)
            self.assertRaises(QRError, save_image, link, b"new")
            save_image(link, b"new", overwrite=True)
            self.assertEqual(target.read_bytes(), b"preserve")
            self.assertFalse(link.is_symlink())

    def test_missing_directory_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertRaises(QRError, save_image, Path(directory) / "missing/code.png", b"x")


class CLITests(unittest.TestCase):
    def cli(self, *args, input=None):
        env = dict(os.environ, DISPLAY="", WAYLAND_DISPLAY="")
        return subprocess.run([sys.executable, str(ROOT / "qr-share"), *args], input=input,
                              capture_output=True, text=True, env=env)

    @unittest.skipUnless(shutil.which("qrencode"), "requires qrencode")
    def test_headless_stdin_export_and_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "code.svg")
            result = self.cli("-", "-o", path, input="https://example.com?x=1&y=2")
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.cli("example.com", "-o", path)
            self.assertEqual(result.returncode, 1)
            self.assertIn("already exists", result.stderr)
            result = self.cli("example.com", "-o", path, "--force")
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_bad_arguments(self):
        for args in [("--copy",), ("--force",), ("example.com", "--clipboard"), ("example.com", "-o", "x.jpg")]:
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args).returncode, 2)

    def test_no_display_is_actionable(self):
        result = self.cli("example.com")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No desktop display", result.stderr)
        self.assertNotIn("CRITICAL", result.stderr)


if __name__ == "__main__":
    unittest.main()
