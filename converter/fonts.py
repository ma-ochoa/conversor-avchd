"""Localiza fuentes del sistema (macOS) utilizables por el filtro drawtext de ffmpeg."""

from pathlib import Path

_FONT_DIRS = [
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
]

_FONT_EXTS = {".ttf", ".ttc", ".otf"}

# Fuentes conocidas y legibles primero; el resto del sistema se añade después.
_PREFERRED_ORDER = [
    "Helvetica", "Helvetica Neue", "Arial", "Avenir", "Avenir Next",
    "Futura", "Georgia", "Times New Roman", "Verdana", "Menlo", "Courier New",
]


def list_system_fonts() -> list[dict]:
    found = {}
    for directory in _FONT_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.suffix.lower() not in _FONT_EXTS or path.name.startswith("."):
                continue
            name = path.stem
            if name not in found:
                found[name] = str(path)

    def sort_key(name):
        try:
            return (0, _PREFERRED_ORDER.index(name))
        except ValueError:
            return (1, name.lower())

    return [{"name": name, "path": found[name]} for name in sorted(found, key=sort_key)]


def default_font_path() -> str | None:
    fonts = list_system_fonts()
    return fonts[0]["path"] if fonts else None
