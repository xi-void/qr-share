#!/usr/bin/env python3
"""Install QR Share into user-owned locations, with an optional Omarchy shortcut."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

APP_ID = "local.omarchy.QRShare"
BEGIN = "-- BEGIN QR Share (managed by qr-share installer)"
END = "-- END QR Share"
SHORTCUT = "SUPER + CTRL + SHIFT + Q"
ROOT = Path(__file__).resolve().parent


def run(command):
    return subprocess.run(command, capture_output=True, text=True, timeout=15)


def without_binding(text):
    return re.sub(r"(?m)^" + re.escape(BEGIN) + r"\n.*?^" + re.escape(END) + r"\n?", "", text, flags=re.S)


def binding_text(executable):
    # JSON string quoting is also valid Lua string quoting for these paths.
    command = shlex.quote(str(executable)) + " --clipboard"
    return f'{BEGIN}\no.bind("{SHORTCUT}", "Share link as QR", {{ launch = {json.dumps(command)} }})\n{END}\n'


def update_binding(executable, uninstall=False, dry_run=False):
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hypr/bindings.lua"
    if not config.is_file():
        print("Shortcut skipped: this installation does not have hypr/bindings.lua.")
        return
    original = config.read_text()
    owned = BEGIN in original and END in original
    if uninstall and not owned:
        return
    if not shutil.which("hyprctl"):
        print("Shortcut skipped: hyprctl is unavailable.")
        return
    try:
        errors = run(["hyprctl", "configerrors"])
        if errors.returncode or errors.stdout.strip():
            print("Shortcut skipped: Hyprland is unavailable or already reports config errors.")
            return
        if not uninstall:
            result = run(["hyprctl", "-j", "binds"])
            bindings = json.loads(result.stdout)
            conflicts = [b for b in bindings if b.get("modmask") == 69 and str(b.get("key", "")).lower() == "q"
                         and not (owned and b.get("description") == "Share link as QR")]
            if conflicts:
                print(f"Shortcut skipped: {SHORTCUT} is already assigned. Existing binding preserved.")
                return
        updated = without_binding(original)
        if not uninstall:
            updated = updated.rstrip("\n") + "\n\n" + binding_text(executable)
        if updated == original:
            print("Omarchy shortcut is already installed.")
            return
        if dry_run:
            print(f"Would {'remove' if uninstall else 'add'} {SHORTCUT} in {config}")
            return
        backup = config.with_name(config.name + ".qr-share.bak." + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        shutil.copy2(config, backup)
        config.write_text(updated)
        try:
            reload_result = run(["hyprctl", "reload"])
            checked = run(["hyprctl", "configerrors"])
            if reload_result.returncode or checked.returncode or checked.stdout.strip():
                raise RuntimeError("Hyprland rejected the new configuration")
        except Exception:
            config.write_text(original)
            run(["hyprctl", "reload"])
            restored = run(["hyprctl", "configerrors"])
            print("Shortcut change rolled back; your original bindings were restored.")
            if restored.stdout.strip():
                print(restored.stdout.strip())
            return
        print(f"Shortcut {'removed' if uninstall else 'installed'}: {SHORTCUT}")
        print(f"Bindings backup: {backup}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Shortcut skipped: {exc}")


def desktop_quote(path):
    value = str(path).replace("%", "%%")
    for old, new in [("\\", "\\\\"), ('"', '\\"'), ("`", "\\`"), ("$", "\\$")]:
        value = value.replace(old, new)
    # Desktop entry escaping is applied before Exec argument unquoting.
    return '"' + value.replace("\\", "\\\\") + '"'


def check_dependencies():
    missing = [name for name in ("qrencode", "wl-copy", "wl-paste") if not shutil.which(name)]
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
    except (ImportError, ValueError):
        missing.append("GTK 4 / libadwaita Python bindings")
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing) + "\nRun: omarchy pkg add qrencode wl-clipboard python-gobject gtk4 libadwaita")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, help="alternate installation prefix; skips desktop integration for staging")
    parser.add_argument("--no-shortcut", action="store_true", help="install the launcher without changing Hyprland bindings")
    parser.add_argument("--dry-run", action="store_true", help="show planned changes without writing")
    parser.add_argument("--uninstall", action="store_true", help="remove QR Share and its managed shortcut")
    args = parser.parse_args(argv)
    prefix = (args.prefix or Path.home() / ".local").expanduser().resolve()
    data = prefix / "share" if args.prefix else Path(os.environ.get("XDG_DATA_HOME", prefix / "share"))
    app_dir = data / "qr-share"
    executable = prefix / "bin/qr-share"
    desktop = data / f"applications/{APP_ID}.desktop"
    icon = data / f"icons/hicolor/scalable/apps/{APP_ID}.svg"
    marker = app_dir / ".qr-share-managed"
    targets = (app_dir, executable, desktop, icon)
    if args.uninstall:
        if not marker.is_file():
            raise RuntimeError(f"No managed QR Share installation at {app_dir}")
        if not args.prefix and not args.no_shortcut:
            update_binding(executable, uninstall=True, dry_run=args.dry_run)
        for target in targets:
            print(f"{'Would remove' if args.dry_run else 'Removing'} {target}")
            if not args.dry_run:
                if target == app_dir:
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
    else:
        check_dependencies()
        if not marker.is_file() and any(p.exists() or p.is_symlink() for p in targets):
            raise RuntimeError("An installation target already exists without QR Share's ownership marker. Refusing to overwrite it.")
        for target in targets:
            print(f"{'Would install' if args.dry_run else 'Installing'} {target}")
        if not args.dry_run:
            app_dir.mkdir(parents=True, exist_ok=True)
            for target in (executable, desktop, icon):
                target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT / "qrshare", app_dir / "qrshare", dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(ROOT / "qr-share", app_dir / "qr-share")
            shutil.copy2(ROOT / "install.py", app_dir / "install.py")
            shutil.copy2(ROOT / "assets" / f"{APP_ID}.svg", icon)
            executable.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(app_dir / "qr-share")) + ' "$@"\n')
            executable.chmod(0o755)
            desktop.write_text(f"""[Desktop Entry]
Type=Application
Name=QR Share
Comment=Turn a web link into a QR code
Exec={desktop_quote(executable)}
Icon={APP_ID}
Terminal=false
Categories=Utility;Graphics;
Keywords=QR;code;link;share;clipboard;
StartupNotify=true
StartupWMClass={APP_ID}
Actions=Clipboard;

[Desktop Action Clipboard]
Name=QR from Clipboard
Exec={desktop_quote(executable)} --clipboard
""")
            marker.write_text("QR Share user installation\n")
        if not args.prefix and not args.no_shortcut:
            update_binding(executable, dry_run=args.dry_run)
    if not args.dry_run and not args.prefix:
        for command in (["update-desktop-database", str(desktop.parent)], ["gtk-update-icon-cache", "-f", "-t", str(data / "icons/hicolor")]):
            if shutil.which(command[0]):
                result = run(command)
                if result.returncode:
                    print(f"Note: {command[0]} could not refresh its cache; the files are installed.")
    if not args.uninstall:
        print(f"{'Preview complete.' if args.dry_run else 'Ready.'} Launch: {executable}")
        print("Find QR Share in your application launcher.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Install failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
