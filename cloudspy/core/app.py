from rich.prompt import Prompt

from . import ui
from .registry import Registry
from ..modules import load_modules
from ..modules.base import Context

_QUIT = {"q", "quit", "exit"}
_HELP = {"h", "help"}


class App:
    def __init__(self):
        self.console = ui.console
        self.registry = Registry()
        self.registry.extend(load_modules())
        self._notice = None

    def run(self):
        while True:
            ui.render_menu(self.registry.all(), self._notice)
            self._notice = None
            selection = self._prompt()
            if selection is None:
                continue
            if selection == "quit":
                ui.clear()
                ui.render_farewell()
                return
            if selection == "help":
                self._show_help()
                continue
            self._launch(self.registry.get(selection))

    def _prompt(self):
        raw = Prompt.ask(
            ui.prompt_text(),
            console=self.console,
            default="",
            show_default=False,
        ).strip().lower()
        if not raw:
            return None
        if raw in _QUIT:
            return "quit"
        if raw in _HELP:
            return "help"
        if not raw.isdigit():
            self._notice = f"unknown selection: {raw}"
            return None
        position = int(raw)
        if not self.registry.valid(position):
            self._notice = f"no module at position {position}"
            return None
        return position

    def _show_help(self):
        ui.render_help(self.registry.all())
        ui.back_prompt()

    def _launch(self, module):
        ui.enter_module(module)
        module.run(Context(console=self.console, ui=ui))
        ui.pause()
