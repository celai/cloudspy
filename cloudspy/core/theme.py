from rich import box
from rich.theme import Theme

from . import terminal

terminal.setup()

PRIMARY = "#9C5641"
PRIMARY_DIM = "#9C5641"
ACCENT = "#E8A87C"
MUTED = "#8A8A8A"
TEXT = "#E6E6E6"
SUCCESS = "#7FB37F"
WARN = "#D6A25C"
ERROR = "#CF6679"

if terminal.UNICODE:
    CLOUD = "☁"
    DOT = "·"
    RING = "○"
    CHEVRON = "›"
    CROSS = "✗"
    RULE_CHAR = "─"
    BOX = box.ROUNDED
else:
    CLOUD = "*"
    DOT = "."
    RING = "o"
    CHEVRON = ">"
    CROSS = "x"
    RULE_CHAR = "-"
    BOX = box.ASCII

THEME = Theme(
    {
        "primary": PRIMARY,
        "primary.dim": PRIMARY_DIM,
        "accent": ACCENT,
        "muted": MUTED,
        "text": TEXT,
        "success": SUCCESS,
        "warn": WARN,
        "error": ERROR,
        "heading": f"bold {PRIMARY}",
        "border": PRIMARY,
        "spinner": PRIMARY,
        "index": f"bold {PRIMARY}",
    }
)
