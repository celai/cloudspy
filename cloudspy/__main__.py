import sys

from .core.app import App
from .core import ui


def main() -> int:
    try:
        App().run()
    except (KeyboardInterrupt, EOFError):
        ui.console.print()
        ui.render_farewell()
    return 0


if __name__ == "__main__":
    sys.exit(main())
