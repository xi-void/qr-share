"""Link validation, local QR encoding, and Wayland clipboard access."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit


class QRError(ValueError):
    """An actionable error suitable for the UI or command line."""


def normalize_link(value: str) -> str:
    link = value.strip()
    if not link:
        raise QRError("Paste a web link to get started.")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in link):
        raise QRError("Use one link without spaces or line breaks.")
    if "\\" in link:
        raise QRError("Use forward slashes in the link.")
    if "://" not in link:
        # A bare host with a port is useful for sharing local development URLs.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", link) and not re.match(
            r"^[^/:]+:\d+(?:[/?#]|$)", link
        ):
            raise QRError("Use an http:// or https:// web link.")
        link = "https://" + link
    try:
        parts = urlsplit(link)
        if parts.scheme.lower() not in {"http", "https"}:
            raise QRError("Use an http:// or https:// web link.")
        host = parts.hostname
        if not host:
            raise QRError("The link needs a hostname, such as example.com.")
        if ":" in host:
            ipaddress.IPv6Address(host)
        else:
            ascii_host = host.encode("idna").decode("ascii").rstrip(".")
            labels = ascii_host.split(".")
            if len(ascii_host) > 253 or any(
                not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in labels
            ):
                raise ValueError("invalid hostname")
        _ = parts.port  # Validate range and numeric syntax.
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, QRError):
            raise
        raise QRError("That link has an invalid hostname or port.") from exc
    if len(link.encode("utf-8")) > 2331:
        raise QRError("This link is too long for one QR code. Use a shorter link.")
    return link


def run_tool(command: list[str], data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=8, check=False,
        )
    except FileNotFoundError as exc:
        package = "qrencode" if command[0] == "qrencode" else "wl-clipboard"
        raise QRError(f"Install {package} with: omarchy pkg add {package}") from exc
    except subprocess.TimeoutExpired as exc:
        raise QRError(f"{command[0]} took too long. Please try again.") from exc
    if result.returncode:
        if command[0] == "qrencode":
            raise QRError("Could not encode this link. Try a shorter link.")
        raise QRError("Clipboard unavailable. Run QR Share in your Wayland desktop.")
    return result.stdout


def encode(link: str, image_format: str = "png", scale: int = 10) -> bytes:
    link = normalize_link(link)
    if image_format not in {"png", "svg"}:
        raise QRError("Choose PNG or SVG output.")
    if not 1 <= scale <= 32:
        raise QRError("Module size must be between 1 and 32 pixels.")
    # Pass the URL on stdin: never treat its characters as shell syntax/options.
    return run_tool(
        ["qrencode", "-8", "-l", "M", "-m", "4", "-s", str(scale),
         "-t", image_format.upper(), "-o", "-"],
        link.encode("utf-8"),
    )


def read_clipboard() -> str:
    data = run_tool(["wl-paste", "--no-newline", "--type", "text"])
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise QRError("The clipboard does not contain a text link.") from exc


def copy_image(png: bytes) -> None:
    # wl-copy owns the selection after this application exits.
    run_tool(["wl-copy", "--type", "image/png"], png)


def save_image(path: Path, data: bytes, overwrite: bool = False) -> None:
    """Publish a complete file atomically, without clobbering by default."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".qr-share-", delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    except FileExistsError as exc:
        raise QRError(f"File already exists: {path}. Use --force to replace it.") from exc
    except OSError as exc:
        raise QRError(f"Could not save {path}: {exc.strerror}") from exc
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
