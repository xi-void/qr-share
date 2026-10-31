# QR Share

Turn a web link into a QR code you can scan, copy, or save. A small GTK app for [Omarchy](https://omarchy.org), with a command-line interface for quick exports.

<img src="assets/screenshot.png" alt="QR Share showing a QR code for https://omarchy.org, with Copy image, Save PNG, and Save SVG buttons" width="520">

- Live preview as you type or paste a link.
- Copy the QR image into a chat or document, or export PNG and SVG.
- Launch directly from your Wayland clipboard with a keyboard shortcut.
- Follows the current Omarchy theme, including changes while the window is open.
- Generates codes locally. No account, server, or network connection needed.

## Install

Requires Python 3.11+, GTK 4.12+, libadwaita 1.4+, PyGObject, `qrencode`, and `wl-clipboard`. Omarchy may already have these packages installed.

```sh
omarchy pkg add python python-gobject gtk4 libadwaita qrencode wl-clipboard

git clone https://github.com/xi-void/qr-share.git
cd qr-share
python3 install.py
```

Open **QR Share** from your application launcher. To share a link already on your clipboard, press **Super+Ctrl+Shift+Q**.

The installer adds that shortcut on Omarchy installations using `hypr/bindings.lua`. It preserves an occupied shortcut, backs up your bindings, and validates the change with `hyprctl reload` and `hyprctl configerrors`. If validation fails, it restores the original bindings. If Hyprland is unavailable or already reports configuration errors, the app installs without the shortcut; rerun the installer from a working desktop session to add it.

```sh
python3 install.py --dry-run       # Preview the installation
python3 install.py --no-shortcut   # Install without changing keybindings
```

To try the app without installing it:

```sh
./qr-share
./qr-share 'https://example.com'
./qr-share --clipboard
```

## Use

Paste an HTTP or HTTPS link into the window. The QR code appears automatically. Scan it with your phone's camera, choose **Copy image**, or save a file.

Bare hostnames such as `example.com/docs` get `https://` added. Explicit HTTP links, ports, query strings, and fragments are preserved. International URLs and local hosts are supported. A local address still needs to be reachable from the device scanning it.

| Shortcut | Action |
| --- | --- |
| Super+Ctrl+Shift+Q | Open a QR code from the clipboard, when installed |
| Ctrl+L | Select the link |
| Ctrl+Shift+V | Paste a link from the clipboard |
| Ctrl+Shift+C | Copy the QR image |
| Ctrl+S | Save PNG |
| Esc or Ctrl+W | Close the window |

Standard text copy and paste work in the link field. The launcher also includes a **QR from Clipboard** action.

## Command line

```sh
# Export without opening a window
qr-share 'https://example.com' -o code.png
qr-share 'https://example.com' -o code.svg

# Turn the clipboard link into an image on the clipboard
qr-share --clipboard --copy

# Read a link from stdin
printf '%s' 'https://example.com' | qr-share - -o code.png

# Replace an existing export explicitly
qr-share 'https://example.com' -o code.png --force
```

Use `./qr-share` instead of `qr-share` when running from the checkout. Installed commands live in `~/.local/bin`; add that directory to your `PATH` if your shell does not already include it.

PNG and SVG exports work without a desktop display. Clipboard operations require a running Wayland session. Existing files are preserved unless `--force` is supplied.

## Omarchy integration

The installer copies the app into user-owned locations. It does not modify packaged Omarchy files or require root privileges.

| Default location | Contents |
| --- | --- |
| `~/.local/share/qr-share/` | Standalone application and uninstaller |
| `~/.local/bin/qr-share` | Command-line launcher |
| `~/.local/share/applications/` | Desktop launcher |
| `~/.local/share/icons/hicolor/scalable/apps/` | Application icon |
| `~/.config/hypr/bindings.lua` | Optional managed shortcut |

`XDG_DATA_HOME` and `XDG_CONFIG_HOME` are respected. The app reads Omarchy's generated palette from its state directory, with a fallback for older theme layouts. QR images stay black on white with a four-module quiet zone and medium error correction, regardless of the desktop theme.

Once installed, the app runs independently of the checkout. Keep the checkout if you want to pull updates:

```sh
git pull --ff-only
python3 install.py
```

## Remove

From the checkout:

```sh
python3 install.py --uninstall
```

Or use the installed copy:

```sh
python3 "${XDG_DATA_HOME:-$HOME/.local/share}/qr-share/install.py" --uninstall
```

Run this inside your Hyprland session so the managed shortcut can be removed and the configuration validated. Exported images and binding backups are retained.

## Privacy

QR Share does not visit, shorten, upload, or keep a history of your links. A QR code contains the link itself, including any query parameters. Copying uses the desktop clipboard, which your clipboard manager may retain.

## Development

The app uses system Python packages; there is no pip installation or build step. Tests cover link validation, real QR decoding, file overwrite protection, asynchronous preview state, and installer behavior.

```sh
# Additional tools for the full validation suite
omarchy pkg add zbar librsvg desktop-file-utils
python3 -m unittest discover -s tests -v
```

PNG round-trip tests use `zbarimg`; SVG tests also use `rsvg-convert`. Those tests are skipped if their decoding tools are absent.

To inspect an installation without changing your desktop:

```sh
qr_test_prefix=$(mktemp -d)
python3 install.py --prefix "$qr_test_prefix"
desktop-file-validate "$qr_test_prefix/share/applications/local.omarchy.QRShare.desktop"
python3 install.py --prefix "$qr_test_prefix" --uninstall
```
