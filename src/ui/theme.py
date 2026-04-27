"""
Color themes shared between the touchscreen UI and web interface.

The active theme is stored in config.yaml under ui.theme.
Changing the theme on the touchscreen requires a restart to take effect;
the web interface picks up the new theme on the next page load.
"""
from __future__ import annotations

THEMES: dict[str, dict] = {
    "dark_blue": {
        "label":  "Dark Blue",
        "bg":     "#1a1a2e",
        "card":   "#16213e",
        "accent": "#e94560",
        "text":   "#eaeaea",
        "muted":  "#8888aa",
        "ok":     "#2ecc71",
        "warn":   "#e67e22",
        "err":    "#e74c3c",
        "border": "#2a2a4e",
        "deep":   "#0f0f23",
    },
    "dark_green": {
        "label":  "Dark Green",
        "bg":     "#0d1a0f",
        "card":   "#112414",
        "accent": "#27ae60",
        "text":   "#eaeaea",
        "muted":  "#7aaa84",
        "ok":     "#2ecc71",
        "warn":   "#e67e22",
        "err":    "#e74c3c",
        "border": "#1e3a24",
        "deep":   "#070e08",
    },
    "dark_purple": {
        "label":  "Dark Purple",
        "bg":     "#170d24",
        "card":   "#1f1033",
        "accent": "#9b59b6",
        "text":   "#eaeaea",
        "muted":  "#998aaa",
        "ok":     "#2ecc71",
        "warn":   "#e67e22",
        "err":    "#e74c3c",
        "border": "#2e1a44",
        "deep":   "#0d0718",
    },
    "high_contrast": {
        "label":  "High Contrast",
        "bg":     "#000000",
        "card":   "#111111",
        "accent": "#f1c40f",
        "text":   "#ffffff",
        "muted":  "#bbbbbb",
        "ok":     "#2ecc71",
        "warn":   "#e67e22",
        "err":    "#e74c3c",
        "border": "#333333",
        "deep":   "#000000",
    },
}

_DEFAULT = "dark_blue"


def get(config: dict) -> dict:
    """Return the active theme color dict for the given config."""
    name = config.get("ui", {}).get("theme", _DEFAULT)
    return THEMES.get(name, THEMES[_DEFAULT])


def site_name(config: dict) -> str:
    """Return the configured kegerator name."""
    return config.get("ui", {}).get("name", "SmartKegerator")


def css_vars(config: dict) -> str:
    """Return a CSS :root block body for the active theme (used by web templates)."""
    c = get(config)
    return (
        f"--sk-accent:{c['accent']};"
        f"--sk-bg:{c['bg']};"
        f"--sk-card:{c['card']};"
        f"--sk-muted:{c['muted']};"
        f"--sk-green:{c['ok']};"
        f"--sk-orange:{c['warn']};"
        f"--sk-text:{c['text']};"
        f"--sk-border:{c['border']};"
    )
