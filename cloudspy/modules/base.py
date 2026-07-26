from abc import ABC, abstractmethod
from dataclasses import dataclass

from rich.console import Console


@dataclass
class Context:
    console: Console
    ui: object


class Module(ABC):
    name = "module"
    slug = "module"
    description = ""
    version = "0.1.0"

    @abstractmethod
    def run(self, ctx: Context) -> None:
        ...
