import json
import os
import subprocess
import sys

from rich.text import Text

from .base import Context, Module

_ENGINE = os.path.join(os.path.dirname(__file__), "workers", "tiktok_worker.py")
_SOURCE = "omar-thing.site"

_FIELDS = [
    ("name", "nickname"),
    ("username", "username"),
    ("user id", "user_id"),
    ("language", "language"),
    ("region", "region"),
    ("locked region", "locked_region"),
]


class TikTokRegionModule(Module):
    name = "TikTok Country"
    slug = "tiktok"
    description = "TikTok username to country lookup."
    version = "0.1.0"

    hard_timeout = 90

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("tiktok username")
        if not target:
            ctx.ui.notify_error("no username supplied")
            return

        username = target.lstrip("@").strip()
        if not username:
            ctx.ui.notify_error("invalid username")
            return

        with ctx.ui.loader(f"resolving country for {username}"):
            data, error = self._search(username)

        if error:
            ctx.ui.notify_error(error)
            return

        if not data:
            ctx.ui.notify_info(f"no data found for {username}")
            return

        ctx.ui.result_panel(f"TikTok · {username}", self._rows(data))
        self._credit(ctx)

    def _search(self, username):
        if not self._engine_ready():
            return None, "search engine not installed - run: pip install -r requirements.txt"

        cmd = [sys.executable, _ENGINE, username]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.hard_timeout,
            )
        except subprocess.TimeoutExpired:
            return None, "lookup timed out, try again"
        except Exception as exc:
            return None, f"lookup failed: {exc}"

        try:
            data = json.loads(result.stdout or b"null")
        except ValueError:
            return None, "could not parse lookup results"

        if isinstance(data, dict) and data.get("error"):
            message = data["error"]
            if "Executable doesn't exist" in message or "playwright install" in message:
                return None, "browser not installed - run: playwright install chromium"
            return None, message

        return data, None

    def _engine_ready(self):
        try:
            __import__("playwright")
        except Exception:
            return False
        return True

    def _rows(self, data):
        rows = []
        for label, key in _FIELDS:
            value = data.get(key)
            if value:
                rows.append((label, Text(str(value), style="accent")))
        if not rows:
            rows.append(("status", Text("no fields returned", style="muted")))
        return rows

    def _credit(self, ctx: Context) -> None:
        line = Text()
        line.append("  credits to ", style="muted")
        line.append(_SOURCE, style="accent")
        line.append(" <3", style="primary")
        ctx.console.print(line)
