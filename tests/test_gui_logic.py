"""Exercise async UI state without a display or real clipboard mutation."""
import unittest
from unittest.mock import Mock, patch

from qrshare.gui import QRWindow, Gtk
from qrshare.theme import read_theme, theme_css


class PreviewTests(unittest.TestCase):
    def window_state(self):
        state = Mock()
        state.entry.get_text.return_value = "https://example.com/first"
        state.revision = 1
        state.png = state.link = None
        state.callbacks = []
        state.work.side_effect = lambda fn, callback: state.callbacks.append(callback)
        return state

    def test_old_render_cannot_replace_new_input(self):
        state = self.window_state()
        QRWindow.generate(state)
        state.revision = 2
        state.callbacks[0](b"old image", None)
        state.picture.set_paintable.assert_not_called()
        state.enable_actions.assert_not_called()
        self.assertIsNone(state.png)

    def test_current_render_enables_sharing(self):
        state = self.window_state()
        QRWindow.generate(state)
        with patch("qrshare.gui.Gdk.Texture.new_from_bytes", return_value=Mock()):
            state.callbacks[0](b"new image", None)
        self.assertEqual(state.png, b"new image")
        self.assertEqual(state.link, "https://example.com/first")
        state.enable_actions.assert_called_once_with(True)

    def test_invalid_input_never_starts_encoder(self):
        state = self.window_state()
        state.entry.get_text.return_value = "not a link"
        QRWindow.generate(state)
        state.work.assert_not_called()
        state.entry.add_css_class.assert_called_once_with("error")

    def test_render_error_does_not_enable_sharing(self):
        state = self.window_state()
        QRWindow.generate(state)
        state.callbacks[0](None, ValueError("encoder missing"))
        state.enable_actions.assert_not_called()
        state.status.set_label.assert_called_once_with("encoder missing")

    def test_theme_css_parses(self):
        provider = Gtk.CssProvider()
        errors = []
        provider.connect("parsing-error", lambda _p, _s, error: errors.append(str(error)))
        for colors in [read_theme(), {}, {"mode": "light", "background": "#eeeeee", "accent": "#0055aa"}]:
            provider.load_from_string(theme_css(colors))
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
