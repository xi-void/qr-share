"""A small GTK 4 / libadwaita window for turning links into shareable images."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from urllib.parse import urlsplit

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .core import QRError, copy_image, encode, normalize_link
from .theme import read_theme, theme_css

APP_ID = "local.omarchy.QRShare"


class QRApplication(Adw.Application):
    def __init__(self, link=None, from_clipboard=False):
        # Each invocation keeps its own input; never discard a new CLI link.
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.initial_link = link
        self.from_clipboard = from_clipboard

    def do_activate(self):
        if not Gdk.Display.get_default():
            self.quit()
            return
        window = QRWindow(self)
        window.present()
        if self.initial_link is not None:
            window.entry.set_text(self.initial_link)
        elif self.from_clipboard:
            window.paste()


class QRWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="QR Share", default_width=520, default_height=760)
        self.set_icon_name(APP_ID)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="qr-share")
        self.revision = 0
        self.pending = 0
        self.closed = False
        self.link = None
        self.png = None
        self.colors = None
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(self.get_display(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.refresh_theme()
        self.theme_timer = GLib.timeout_add_seconds(2, self.refresh_theme)
        self.connect("close-request", self.on_close)

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="QR Share", subtitle=""))
        toolbar.add_top_bar(header)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=480, tightening_threshold=420)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                          margin_start=24, margin_end=24, margin_top=20, margin_bottom=24)
        clamp.set_child(content)
        scroller.set_child(clamp)
        toolbar.set_content(scroller)
        self.toast_overlay.set_child(toolbar)
        self.set_content(self.toast_overlay)

        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        intro.append(Gtk.Label(label="Share a link", xalign=0, css_classes=["qr-heading"]))
        intro.append(Gtk.Label(label="Scan it on a phone. Send it to anyone.", xalign=0, wrap=True,
                               css_classes=["dim-label"]))
        content.append(intro)

        input_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        label = Gtk.Label(label="_Web link", use_underline=True, xalign=0, css_classes=["heading"])
        input_box.append(label)
        row = Gtk.Box(spacing=8)
        self.entry = Gtk.Entry(placeholder_text="https://example.com", hexpand=True,
                               input_purpose=Gtk.InputPurpose.URL, css_classes=["qr-input"])
        self.entry.set_max_length(8192)
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], ["Web link"])
        label.set_mnemonic_widget(self.entry)
        self.entry.connect("changed", self.on_changed)
        self.entry.connect("activate", lambda *_: self.generate_now())
        row.append(self.entry)
        paste = Gtk.Button(icon_name="edit-paste-symbolic", tooltip_text="Paste link from clipboard")
        paste.connect("clicked", lambda *_: self.paste())
        row.append(paste)
        input_box.append(row)
        self.status = Gtk.Label(label="Paste a link. Your QR code appears automatically.", xalign=0,
                                wrap=True, css_classes=["dim-label", "qr-status"])
        input_box.append(self.status)
        content.append(input_box)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               css_classes=["qr-stage"], halign=Gtk.Align.CENTER)
        self.stack.set_size_request(316, 316)
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("view-grid-symbolic")
        icon.set_pixel_size(64)
        icon.add_css_class("dim-label")
        empty.append(icon)
        empty.append(Gtk.Label(label="Your link, ready to scan", css_classes=["heading"]))
        empty.append(Gtk.Label(label="Start with a link above", css_classes=["dim-label"]))
        self.stack.add_named(empty, "empty")
        self.picture = Gtk.Picture(can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN)
        self.picture.set_size_request(288, 288)
        self.picture.update_property([Gtk.AccessibleProperty.LABEL], ["QR code for the web link"])
        self.stack.add_named(self.picture, "qr")
        content.append(self.stack)

        self.caption = Gtk.Label(label="Point your phone’s camera at the code", wrap=True,
                                 justify=Gtk.Justification.CENTER, css_classes=["dim-label", "qr-status"])
        self.caption.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.caption.set_max_width_chars(44)
        content.append(self.caption)

        self.copy_button = Gtk.Button(label="Copy image", css_classes=["suggested-action", "qr-action"])
        self.copy_button.connect("clicked", lambda *_: self.copy())
        content.append(self.copy_button)
        saves = Gtk.Box(spacing=10, homogeneous=True)
        self.png_button = Gtk.Button(label="Save PNG", css_classes=["qr-action"])
        self.svg_button = Gtk.Button(label="Save SVG", css_classes=["qr-action"])
        self.png_button.connect("clicked", lambda *_: self.save("png"))
        self.svg_button.connect("clicked", lambda *_: self.save("svg"))
        saves.append(self.png_button)
        saves.append(self.svg_button)
        content.append(saves)
        content.append(Gtk.Label(label="Made on your device · Works offline", css_classes=["dim-label", "qr-status"]))
        self.enable_actions(False)

        for name, callback, keys in [
            ("paste-link", self.paste, ["<Control><Shift>v"]),
            ("copy-image", self.copy, ["<Control><Shift>c"]),
            ("save-png", lambda: self.save("png"), ["<Control>s"]),
            ("focus-link", self.focus_link, ["<Control>l"]),
            ("close", self.close, ["Escape", "<Control>w"]),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", keys)
        self.entry.grab_focus()

    def refresh_theme(self):
        colors = read_theme()
        if colors != self.colors:
            self.colors = colors
            mode = {"dark": Adw.ColorScheme.FORCE_DARK, "light": Adw.ColorScheme.FORCE_LIGHT}
            Adw.StyleManager.get_default().set_color_scheme(mode.get(colors.get("mode"), Adw.ColorScheme.DEFAULT))
            self.css.load_from_string(theme_css(colors))
        return GLib.SOURCE_CONTINUE

    def focus_link(self):
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def enable_actions(self, enabled):
        for button in (self.copy_button, self.png_button, self.svg_button):
            button.set_sensitive(enabled)

    def toast(self, message):
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=4, use_markup=False))

    def work(self, function, callback):
        future = self.executor.submit(function)
        def done(completed):
            try:
                result, error = completed.result(), None
            except Exception as exc:
                result, error = None, exc
            GLib.idle_add(deliver, result, error)
        def deliver(result, error):
            if not self.closed:
                callback(result, error)
            return GLib.SOURCE_REMOVE
        future.add_done_callback(done)

    def on_changed(self, *_):
        self.revision += 1
        self.link = self.png = None
        self.enable_actions(False)
        self.stack.set_visible_child_name("empty")
        self.caption.set_label("Point your phone’s camera at the code")
        self.caption.set_tooltip_text(None)
        self.entry.remove_css_class("error")
        if self.pending:
            GLib.source_remove(self.pending)
        self.status.set_label("Preparing QR code…" if self.entry.get_text().strip() else "Paste a link. Your QR code appears automatically.")
        self.pending = GLib.timeout_add(300, self.generate)

    def generate_now(self):
        if self.pending:
            GLib.source_remove(self.pending)
            self.pending = 0
        self.generate()

    def generate(self):
        self.pending = 0
        value = self.entry.get_text()
        if not value.strip():
            return GLib.SOURCE_REMOVE
        revision = self.revision
        try:
            link = normalize_link(value)
        except QRError as exc:
            self.status.set_label(str(exc))
            self.entry.add_css_class("error")
            return GLib.SOURCE_REMOVE
        def rendered(png, error):
            if revision != self.revision:
                return  # Never show or share an older input's QR code.
            if error:
                self.status.set_label(str(error))
                return
            self.link, self.png = link, png
            self.picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(png)))
            self.stack.set_visible_child_name("qr")
            self.caption.set_label(link)
            self.caption.set_tooltip_text(link)
            self.status.set_label("Ready to share · Added https://" if link != value.strip() else "Ready to share · Scan with your camera")
            self.enable_actions(True)
        self.work(lambda: encode(link), rendered)
        return GLib.SOURCE_REMOVE

    def paste(self):
        revision = self.revision
        def received(clipboard, result):
            if self.closed or revision != self.revision:
                return
            try:
                value = clipboard.read_text_finish(result)
                if not value or not value.strip():
                    self.toast("Copy a web link first.")
                    return
                # Validate before Gtk.Entry can strip newlines/truncate content.
                self.entry.set_text(normalize_link(value))
                self.entry.set_position(-1)
            except (GLib.Error, QRError) as exc:
                self.toast(str(exc) if isinstance(exc, QRError) else "Could not read a link from the clipboard.")
        self.get_clipboard().read_text_async(None, received)

    def copy(self):
        if not self.png:
            return
        png = self.png
        self.work(lambda: copy_image(png), lambda _result, error: self.toast(str(error) if error else "QR image copied. Paste it into a chat or document."))

    def save(self, image_format):
        if not self.link:
            return
        link, png = self.link, self.png
        host = re.sub(r"[^a-zA-Z0-9.-]", "-", urlsplit(link).hostname or "link")[:70]
        dialog = Gtk.FileDialog(title=f"Save QR code as {image_format.upper()}", initial_name=f"qr-{host}.{image_format}")
        file_filter = Gtk.FileFilter()
        file_filter.set_name(f"{image_format.upper()} image")
        file_filter.add_pattern(f"*.{image_format}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(file_filter)
        pictures = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES)
        if pictures and Path(pictures).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(pictures))
        def selected(source, result):
            try:
                destination = source.save_finish(result)
            except GLib.Error as exc:
                if not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.DISMISSED) and not exc.matches(Gtk.DialogError.quark(), Gtk.DialogError.CANCELLED):
                    self.toast("Could not open the save dialog.")
                return
            if self.closed:
                return
            # Do not change the selected filename after the chooser checks overwrites.
            def write():
                data = png if image_format == "png" else encode(link, "svg")
                destination.replace_contents(data, None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
            self.work(write, lambda _result, error: self.toast("Could not save the image. Check folder permissions." if error else f"Saved {destination.get_basename()}"))
        dialog.save(self, None, selected)

    def on_close(self, *_):
        self.closed = True
        if self.pending:
            GLib.source_remove(self.pending)
        GLib.source_remove(self.theme_timer)
        Gtk.StyleContext.remove_provider_for_display(self.get_display(), self.css)
        self.executor.shutdown(wait=False, cancel_futures=True)
        return False
