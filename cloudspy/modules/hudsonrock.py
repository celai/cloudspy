from rich.text import Text

from ..utils import http
from .base import Context, Module

_EMAIL_URL = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-email"
_USERNAME_URL = "https://cavalier.hudsonrock.com/api/json/v2/osint-tools/search-by-username"

_FIELDS = [
    ("computer", "computer_name"),
    ("ip", "ip"),
    ("os", "operating_system"),
    ("malware", "malware_path"),
    ("antivirus", "antiviruses"),
    ("compromised", "date_compromised"),
    ("passwords", "top_passwords"),
    ("logins", "top_logins"),
]


class HudsonRockModule(Module):
    name = "Hudson Rock"
    slug = "hudson"
    description = "Infostealer infection lookup by email or username."
    version = "0.1.0"
    max_stealers = 5

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("email or username")
        if not target:
            ctx.ui.notify_error("no target supplied")
            return

        value = target.strip()
        if not value:
            ctx.ui.notify_error("invalid target")
            return

        email = "@" in value
        url = _EMAIL_URL if email else _USERNAME_URL
        param = "email" if email else "username"

        with ctx.ui.loader(f"querying hudson rock for {value}"):
            data, error = self._search(url, param, value)

        if error:
            ctx.ui.notify_error(error)
            return

        ctx.ui.result_panel(f"Hudson Rock · {value}", self._rows(data))

    def _search(self, url, param, value):
        try:
            response = http.get(url, params={param: value})
        except Exception as exc:
            return None, f"request failed: {exc}"

        if response.status_code != 200:
            return None, f"hudson rock returned status {response.status_code}"

        try:
            return response.json(), None
        except ValueError:
            return None, "could not parse hudson rock response"

    def _rows(self, data):
        stealers = data.get("stealers") or []

        if not stealers:
            return [("status", Text(_message(data), style="muted"))]

        shown = stealers[: self.max_stealers]
        rows = [("infections", str(len(stealers)))]

        for index, stealer in enumerate(shown, start=1):
            rows.append(("", Text(f"- stealer {index} -", style="primary.dim")))
            for label, key in _FIELDS:
                value = stealer.get(key)
                if value is not None:
                    rows.append((label, Text(_value(value), style="accent")))

        hidden = len(stealers) - len(shown)
        if hidden:
            rows.append(("", Text(f"+ {hidden} more infections", style="muted")))

        return rows


def _message(data):
    message = data.get("message")
    if not message:
        return "no infections found"
    return message.split(" Visit")[0].strip()


def _value(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "-"
    return str(value)
