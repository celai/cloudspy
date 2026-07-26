import glob
import json
import os
import subprocess
import sys
import tempfile

from rich.text import Text

from .base import Context, Module

_DETAIL_FIELDS = [
    ("name", ("fullname", "name")),
    ("bio", ("bio", "description")),
    ("location", ("location",)),
    ("followers", ("follower_count",)),
    ("created", ("created_at",)),
    ("url", ("website", "blog_url", "url")),
]


class UsernameSearchModule(Module):
    name = "Username Search"
    slug = "username"
    description = "Trace a username across thousands of sites and networks."
    version = "0.1.0"

    top_sites = 500
    request_timeout = 10
    hard_timeout = 300
    max_results = 40
    max_details = 4

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("username")
        if not target:
            ctx.ui.notify_error("no username supplied")
            return

        username = target.lstrip("@").strip()
        if not username:
            ctx.ui.notify_error("invalid username")
            return

        with ctx.ui.loader(f"searching for {username} across the web"):
            accounts, error = self._search(username)

        if error:
            ctx.ui.notify_error(error)
            return

        if not accounts:
            ctx.ui.notify_info(f"no accounts found for {username}")
            return

        ctx.ui.result_panel(f"Username · {username}", self._rows(username, accounts))

    def _search(self, username):
        if not self._engine_ready():
            return None, "search engine not installed - run: pip install -r requirements.txt"

        with tempfile.TemporaryDirectory(prefix="cloudspy_") as folder:
            cmd = [
                sys.executable, "-m", "maigret", username,
                "--top-sites", str(self.top_sites),
                "--timeout", str(self.request_timeout),
                "--no-recursion",
                "--no-progressbar",
                "--no-color",
                "-J", "ndjson",
                "-fo", folder,
            ]
            try:
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.hard_timeout,
                )
            except subprocess.TimeoutExpired:
                return None, "search timed out, try a narrower scan"
            except Exception as exc:
                return None, f"search failed: {exc}"

            report = self._report_path(folder, username)
            if report is None:
                return None, "search produced no report"

            try:
                return self._parse(report), None
            except (OSError, ValueError):
                return None, "could not parse search results"

    def _engine_ready(self):
        try:
            __import__("maigret")
        except Exception:
            return False
        return True

    def _report_path(self, folder, username):
        expected = os.path.join(folder, f"report_{username}_ndjson.json")
        if os.path.isfile(expected):
            return expected
        matches = glob.glob(os.path.join(folder, "report_*_ndjson.json"))
        return matches[0] if matches else None

    def _parse(self, report):
        accounts = []
        with open(report, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                status = record.get("status") or {}
                if status.get("status") != "Claimed":
                    continue
                accounts.append(status)
        accounts.sort(key=lambda s: str(s.get("site_name", "")).lower())
        return accounts

    def _rows(self, username, accounts):
        shown = accounts[: self.max_results]
        rows = [("accounts", str(len(accounts)))]

        for status in shown:
            site = status.get("site_name") or "-"
            url = status.get("url") or ""
            rows.append(("", Text(site, style="bold accent")))
            if url:
                rows.append(("", Text(f"  {url}", style="muted")))
            for detail_label, detail in self._details(status.get("ids") or {}):
                rows.append((detail_label, Text(detail, style="text")))

        hidden = len(accounts) - len(shown)
        if hidden:
            rows.append(("", Text(f"+ {hidden} more accounts", style="muted")))

        return rows

    def _details(self, ids):
        out = []
        for label, keys in _DETAIL_FIELDS:
            if len(out) >= self.max_details:
                break
            for key in keys:
                value = ids.get(key)
                if value:
                    out.append((label, _clip(str(value))))
                    break
        return out


def _clip(value, limit=120):
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
