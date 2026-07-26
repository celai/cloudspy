import threading
import time

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text
from rich.table import Table

from .. import __version__
from . import terminal
from .theme import BOX, CHEVRON, CLOUD, CROSS, DOT, PRIMARY, RING, RULE_CHAR, THEME

terminal.setup()

console = Console(theme=THEME, highlight=False)

FRAME = PRIMARY
_MIN_WIDTH = 30
_MAX_WIDTH = 70

_GLOW = ["#F2D3C2", "#E3A588", PRIMARY]

_TITLE_A = "#8A4A38"
_TITLE_B = "#E0A985"
_NAME = "#EAD7CC"
_DESC = "#A2897E"
_LABEL = "#8A5140"
_RULE = "#573024"
_CHEV = "#7A4636"
_KEY = "#DDA582"

_CLOUD_ART_UNICODE = (
    "⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⣤⣄⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀\n"
    "⠀⠀⠀⠀⠀⠀⠀⢀⡴⠛⠉⠀⠀⠈⠉⠻⢦⣀⣤⣀⠀⠀⠀⠀\n"
    "⠀⠀⠀⠀⢀⣀⣠⡟⠀⠀⠀⠀⠀⠀⠀⢀⡼⠋⠀⠈⠳⢦⡀⠀\n"
    "⠀⠀⠀⣴⠋⠁⠈⠁⠀⣠⡶⠟⠛⢷⣄⠘⢧⣤⣤⣤⣤⣼⡃⠀\n"
    "⠀⣠⠶⠟⠀⠀⠀⠀⢰⡟⠀⠀⠀⠀⢹⡆⠀⠀⠀⠀⠀⠈⠻⣄\n"
    "⣼⠃⠀⠀⠀⠀⠀⠀⠈⢿⣄⠀⠀⣠⣾⡁⠀⠀⠀⠀⠀⠀⠀⣿\n"
    "⢹⣆⠀⠀⠀⠀⠀⠀⠀⠀⠙⠛⠛⠋⠻⣿⣦⡀⠀⠀⠀⢀⣰⠋\n"
    "⠀⠉⠛⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠒⠚⠛⠃⠒⠒⠚⠋⠁⠀"
)

_CLOUD_ART_ASCII = (
    "        .-~~~~~-.\n"
    "     .-~         ~-.\n"
    "   .~               ~.\n"
    "  /                   \\\n"
    " (                     )\n"
    "  \\                   /\n"
    "   `~-.           .-~'\n"
    "      `~-.._____.-~'"
)

CLOUD_ART = _CLOUD_ART_UNICODE if terminal.UNICODE else _CLOUD_ART_ASCII
_ART_W = max(len(line) for line in CLOUD_ART.split("\n"))
_SIDE_MIN = _ART_W + 30


def _width():
    return max(_MIN_WIDTH, min(_MAX_WIDTH, console.size.width - 2))


def _rule():
    return Rule(style=_RULE, characters=RULE_CHAR)


def clear() -> None:
    terminal.clear(console)


def _titled(renderable, title, width=None):
    panel = Panel(
        renderable,
        title=Text.assemble((f"{CLOUD} ", "primary"), (title, "heading")),
        title_align="left",
        border_style=FRAME,
        box=BOX,
        padding=(1, 2),
    )
    panel.width = width if width is not None else _width()
    return panel


def _wordmark(modules):
    tagline = Text()
    tagline.append("osint toolkit", style=_LABEL)
    tagline.append(f"   {DOT}   ", style=_RULE)
    tagline.append(f"v{__version__}", style=_LABEL)

    author = Text()
    author.append("by ", style=_DESC)
    author.append("celai", style=f"bold {_NAME}")
    author.append(f"   {DOT}   ", style=_RULE)
    author.append("github.com/celai", style=_LABEL)

    return Group(
        Text("cloudspy", style=f"bold {_TITLE_B}"),
        tagline,
        author,
        Text(),
        Text(f"{len(modules)} modules loaded", style=_DESC),
    )


def _module_cell(index, module):
    cell = Table.grid(expand=True, padding=(0, 1))
    cell.add_column(width=3, justify="right")
    cell.add_column(ratio=1)
    cell.add_column(width=1, justify="right")

    number = Text(f"{index:02d}", style=f"bold {_KEY}")
    name = Text(module.name, style=f"bold {_NAME}")
    chevron = Text(CHEVRON, style=_CHEV)

    cell.add_row(number, name, chevron)
    return cell


def _module_table(modules):
    table = Table.grid(expand=True, padding=(0, 2))
    table.add_column(ratio=1)
    table.add_column(ratio=1)

    items = list(enumerate(modules, start=1))
    for row in range(0, len(items), 2):
        left = _module_cell(*items[row])
        right = _module_cell(*items[row + 1]) if row + 1 < len(items) else Text("")
        table.add_row(left, right)
    return table


def _help_list(modules):
    table = Table.grid(padding=(0, 1))
    table.add_column(width=3, justify="right")
    table.add_column(ratio=1)

    last = len(modules)
    for index, module in enumerate(modules, start=1):
        number = Text(f"{index:02d}", style=f"bold {_KEY}")
        cell = Text()
        cell.append(module.name, style=f"bold {_NAME}")
        cell.append("\n")
        cell.append(module.description, style=_DESC)
        table.add_row(number, cell)
        if index != last:
            table.add_row("", "")
    return table


def _footer(modules):
    footer = Text()
    footer.append("1", style=f"bold {_KEY}")
    footer.append(f"-{len(modules)}", style=_KEY)
    footer.append("  select a module", style=_DESC)
    footer.append("      ", style=_DESC)
    footer.append("h", style=f"bold {_KEY}")
    footer.append("  help", style=_DESC)
    footer.append("      ", style=_DESC)
    footer.append("q", style=f"bold {_KEY}")
    footer.append("  quit", style=_DESC)
    return footer


def render_menu(modules, notice=None) -> None:
    clear()
    total = _width()
    art = Text(CLOUD_ART, style=_TITLE_A)

    if total >= _SIDE_MIN:
        head = Table.grid(padding=(0, 0))
        head.add_column(width=_ART_W, no_wrap=True)
        head.add_column(ratio=1)
        head.add_row(art, Padding(_wordmark(modules), (2, 0, 0, 3)))
    else:
        head = Group(Align.center(art), Text(), Align.center(_wordmark(modules)))

    body = Group(
        head,
        Text(),
        _rule(),
        Text(),
        Text("MODULES", style=f"bold {_LABEL}"),
        Text(),
        _module_table(modules),
        Text(),
        _rule(),
        _footer(modules),
    )

    console.print(Panel(body, border_style=FRAME, box=BOX, padding=(1, 3), width=total))

    if notice:
        line = Text()
        line.append(f"  {CROSS} ", style="error")
        line.append(notice, style="text")
        console.print(line)


def render_help(modules) -> None:
    clear()
    total = _width()

    footer = Text()
    footer.append("b", style=f"bold {_KEY}")
    footer.append("  back", style=_DESC)

    body = Group(
        Text.assemble((f"{CLOUD} ", "primary"), ("HELP", "heading")),
        Text("what each module does", style=_DESC),
        Text(),
        _rule(),
        Text(),
        _help_list(modules),
        Text(),
        _rule(),
        footer,
    )

    console.print(Panel(body, border_style=FRAME, box=BOX, padding=(1, 3), width=total))


def back_prompt() -> None:
    text = Text()
    text.append(f"\n{CLOUD} ", style="primary")
    text.append("press enter to go back", style="muted")
    Prompt.ask(text, console=console, default="", show_default=False)


def render_submenu(heading, options) -> None:
    clear()
    total = _width()

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=3, justify="right")
    table.add_column(ratio=1)
    table.add_column(width=1, justify="right")

    last = len(options)
    for index, label in enumerate(options, start=1):
        number = Text(f"{index:02d}", style=f"bold {_KEY}")
        name = Text(label, style=f"bold {_NAME}")
        chevron = Text(CHEVRON, style=_CHEV)
        table.add_row(number, name, chevron)
        if index != last:
            table.add_row("", "", "")

    footer = Text()
    footer.append("1", style=f"bold {_KEY}")
    footer.append(f"-{len(options)}", style=_KEY)
    footer.append("  select", style=_DESC)
    footer.append("      ", style=_DESC)
    footer.append("b", style=f"bold {_KEY}")
    footer.append("  back", style=_DESC)

    body = Group(
        Text.assemble((f"{CLOUD} ", "primary"), (heading, "heading")),
        Text(),
        _rule(),
        Text(),
        Text("CHOOSE", style=f"bold {_LABEL}"),
        Text(),
        table,
        Text(),
        _rule(),
        footer,
    )

    console.print(Panel(body, border_style=FRAME, box=BOX, padding=(1, 3), width=total))


def enter_module(module) -> None:
    clear()
    with loader(f"launching {module.name}"):
        time.sleep(0.6)

    title = Text()
    title.append(f"{CLOUD} ", style="primary")
    title.append(module.name, style="bold primary")
    header = Panel(
        Group(title, Text(module.description, style="muted")),
        border_style=FRAME,
        box=BOX,
        width=_width(),
        padding=(1, 2),
    )
    console.print(header)
    console.print()


def pause() -> None:
    console.print()
    text = Text()
    text.append(f"{CLOUD} ", style="primary")
    text.append("press enter to return", style="muted")
    Prompt.ask(text, console=console, default="", show_default=False)


def prompt_text() -> Text:
    text = Text()
    text.append(f"\n{CLOUD} ", style="primary")
    text.append("cloudspy", style="primary.dim")
    text.append(f" {CHEVRON}", style="primary")
    return text


def ask(label, default="") -> str:
    text = Text()
    text.append(f"{CLOUD} ", style="primary")
    text.append(label, style="text")
    text.append(f" {CHEVRON}", style="primary")
    return Prompt.ask(text, console=console, default=default, show_default=False).strip()


def _shimmer_frame(message, step):
    text = Text()
    span = len(message) + len(_GLOW) + 3
    head = step % span
    for index, char in enumerate(message):
        if char == " ":
            text.append(char)
            continue
        distance = head - index
        if 0 <= distance < len(_GLOW):
            color = _GLOW[distance]
            text.append(char, style=f"bold {color}" if distance == 0 else color)
        else:
            text.append(char, style="primary")
    return text


class _Shimmer:
    interval = 0.05

    def __init__(self, message):
        self.message = message
        self._step = 0
        self._stop = threading.Event()
        self._live = Live(self._frame(), console=console, refresh_per_second=24, transient=True)
        self._worker = threading.Thread(target=self._animate, daemon=True)

    def _frame(self):
        line = Text()
        line.append(f"{CLOUD} ", style="primary")
        line.append_text(_shimmer_frame(self.message, self._step))
        return line

    def _animate(self):
        while not self._stop.is_set():
            self._step += 1
            self._live.update(self._frame())
            time.sleep(self.interval)

    def __enter__(self):
        self._live.start()
        self._worker.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._worker.join()
        self._live.stop()
        return False


def loader(message):
    return _Shimmer(message)


def notify_error(message) -> None:
    text = Text()
    text.append(f"  {CROSS} ", style="error")
    text.append(message, style="text")
    console.print(text)


def notify_info(message) -> None:
    text = Text()
    text.append(f"  {DOT} ", style="primary")
    text.append(message, style="muted")
    console.print(text)


def result_panel(title, rows) -> None:
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="primary.dim", justify="right", no_wrap=True)
    table.add_column(style="text", overflow="fold")
    for key, value in rows:
        table.add_row(key, value)
    console.print(_titled(table, title))


def pending_panel(title, note, steps=None) -> None:
    body = [Text(note, style="text")]
    if steps:
        body.append(Text())
        body.append(Text("planned", style="primary.dim"))
        for step in steps:
            line = Text()
            line.append(f"  {RING} ", style="primary")
            line.append(step, style="muted")
            body.append(line)
    console.print(_titled(Group(*body), title))


def render_farewell() -> None:
    text = Text()
    text.append(f"{CLOUD} ", style="primary")
    text.append("session closed", style="muted")
    console.print(text)
