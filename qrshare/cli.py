"""CLI entry point; GTK is only imported for the interactive window."""
import argparse
from pathlib import Path
import sys

from .core import QRError, copy_image, encode, normalize_link, read_clipboard, save_image


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Turn a web link into an offline QR code.")
    parser.add_argument("link", nargs="?", help="web link; use - to read from stdin")
    parser.add_argument("--clipboard", action="store_true", help="read a link from the Wayland clipboard")
    parser.add_argument("-o", "--output", type=Path, help="save directly to a .png or .svg file")
    parser.add_argument("--copy", action="store_true", help="copy the PNG directly, without opening a window")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    if args.link is not None and args.clipboard:
        parser.error("choose a link argument or --clipboard")
    if args.force and not args.output:
        parser.error("--force requires --output")
    if args.output and args.output.suffix.lower() not in {".png", ".svg"}:
        parser.error("output filename must end in .png or .svg")
    try:
        if args.link == "-":
            link = sys.stdin.read(16384)
        else:
            link = args.link
        if args.output or args.copy:
            if args.clipboard:
                link = read_clipboard()
            if link is None:
                parser.error("supply a link or --clipboard for --output/--copy")
            link = normalize_link(link)
            if args.output:
                save_image(args.output, encode(link, args.output.suffix[1:].lower()), args.force)
                print(f"Saved {args.output}")
            if args.copy:
                copy_image(encode(link))
                print("QR image copied.")
            return 0
        try:
            from .gui import Adw, Gdk, Gtk, QRApplication
        except (ImportError, ValueError) as exc:
            raise QRError("Install desktop dependencies: omarchy pkg add python-gobject gtk4 libadwaita") from exc
        if Gtk.check_version(4, 12, 0) or (Adw.get_major_version(), Adw.get_minor_version()) < (1, 4):
            raise QRError("The window requires GTK 4.12+ and libadwaita 1.4+.")
        if not Gdk.Display.get_default():
            raise QRError("No desktop display is available. Run in your desktop session, or use --output code.png.")
        return QRApplication(link, args.clipboard).run(["qr-share"])
    except QRError as exc:
        print(f"qr-share: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
