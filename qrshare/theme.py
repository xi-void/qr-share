"""Read Omarchy's generated palette, without modifying system theme files."""
import os
from pathlib import Path
import re
import tomllib


def theme_paths():
    # Quattro uses state; retain compatibility with earlier Omarchy installs.
    return [
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy/current/theme/colors.toml",
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "omarchy/current/theme/colors.toml",
    ]


def read_theme():
    for path in theme_paths():
        try:
            colors = tomllib.loads(path.read_text())
            return {key: value for key, value in colors.items() if isinstance(value, str) and (
                re.fullmatch(r"#[0-9a-fA-F]{6}", value) or key == "mode" and value in {"dark", "light"}
            )}
        except (OSError, ValueError):
            continue
    return {}


def theme_css(colors):
    mapping = {
        "background": ["window_bg_color", "headerbar_bg_color", "card_bg_color"],
        "foreground": ["window_fg_color", "view_fg_color", "headerbar_fg_color", "card_fg_color"],
        "dark_background": ["view_bg_color"],
        "accent": ["accent_bg_color", "accent_color"],
        "selection": ["headerbar_backdrop_color"],
    }
    rules = [f"@define-color {name} {colors[key]};" for key, names in mapping.items()
             if key in colors for name in names]
    if "accent" in colors:
        rgb = [int(colors["accent"][i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
        luminance = sum(c * w for c, w in zip(linear, [.2126, .7152, .0722]))
        rules.append(f"@define-color accent_fg_color {'#000000' if luminance > .179 else '#ffffff'};")
    return "\n".join(rules) + """
    .qr-stage { background: #ffffff; color: #222222; border-radius: 18px; padding: 14px; }
    .qr-stage .dim-label { color: #666666; opacity: 1; }
    .qr-heading { font-size: 27px; font-weight: 700; }
    .qr-input { padding: 9px; border-radius: 10px; }
    .qr-action { padding: 10px 14px; }
    .qr-status { font-size: 12px; }
    """
