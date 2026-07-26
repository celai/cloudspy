import json
import os
import re
import subprocess
import sys

from rich.text import Text

from .base import Context, Module

_WORKERS_DIR = os.path.join(os.path.dirname(__file__), "workers")
_EMAIL_ENGINE = os.path.join(_WORKERS_DIR, "holehe_worker.py")
_PHONE_ENGINE = os.path.join(_WORKERS_DIR, "ignorant_worker.py")


class AccountFinderModule(Module):
    name = "Account Finder"
    slug = "account"
    description = "Find accounts linked to an email or phone number."
    version = "0.1.0"

    request_timeout = 10
    hard_timeout = 180
    max_results = 60

    def run(self, ctx: Context) -> None:
        while True:
            ctx.ui.render_submenu("Account Finder", ["Email Lookup", "Phone Lookup"])
            choice = (ctx.ui.ask("select") or "").strip().lower()
            if choice in ("1", "01", "email"):
                self._email_flow(ctx)
                return
            if choice in ("2", "02", "phone"):
                self._phone_flow(ctx)
                return
            if choice in ("b", "back", "q", ""):
                return


    def _email_flow(self, ctx):
        if not self._ensure(ctx, "holehe"):
            ctx.ui.notify_error("search engine not installed - run: pip install -r requirements.txt")
            return

        target = ctx.ui.ask("target email")
        if not target:
            ctx.ui.notify_error("no email supplied")
            return
        email = target.strip()
        if "@" not in email or " " in email:
            ctx.ui.notify_error("invalid email address")
            return

        with ctx.ui.loader(f"searching where {email} is registered"):
            records, error = self._run_engine(_EMAIL_ENGINE, [email, str(self.request_timeout)])

        if error:
            ctx.ui.notify_error(error)
            return

        found = [r for r in records if r.get("exists")]
        if not found:
            checked = sum(1 for r in records if not r.get("rateLimit"))
            ctx.ui.notify_info(f"no registrations found for {email} across {checked} sites")
            return

        ctx.ui.result_panel(f"Email · {email}", self._email_rows(records, found))

    def _email_rows(self, records, found):
        found.sort(key=lambda r: str(r.get("domain") or r.get("name") or "").lower())
        shown = found[: self.max_results]

        rate_limited = sum(1 for r in records if r.get("rateLimit"))
        rows = [("registered", str(len(found)))]
        if rate_limited:
            rows.append(("skipped", Text(f"{rate_limited} sites rate-limited", style="muted")))

        for record in shown:
            site = record.get("domain") or record.get("name") or "-"
            rows.append(("", Text(site, style="bold accent")))
            recovery = _hint(record.get("emailrecovery"))
            if recovery:
                rows.append(("recovery", Text(recovery, style="text")))
            phone = _hint(record.get("phoneNumber"))
            if phone:
                rows.append(("phone", Text(phone, style="text")))

        hidden = len(found) - len(shown)
        if hidden:
            rows.append(("", Text(f"+ {hidden} more sites", style="muted")))

        return rows


    def _phone_flow(self, ctx):
        if not self._ensure(ctx, "ignorant"):
            ctx.ui.notify_error("search engine not installed - run: pip install -r requirements.txt")
            return

        target = ctx.ui.ask("target phone")
        if not target:
            ctx.ui.notify_error("no phone supplied")
            return

        country_code, national = self._split_phone(target)
        if not country_code:
            ctx.ui.notify_error("invalid phone - include country code, e.g. +33612345678")
            return

        pretty = f"+{country_code} {national}"
        with ctx.ui.loader(f"searching where {pretty} is registered"):
            records, error = self._run_engine(
                _PHONE_ENGINE, [country_code, national, str(self.request_timeout)]
            )

        if error:
            ctx.ui.notify_error(error)
            return

        found = [r for r in records if r.get("exists")]
        if not found:
            checked = sum(1 for r in records if not r.get("rateLimit"))
            ctx.ui.notify_info(f"no registrations found for {pretty} across {checked} sites")
            return

        ctx.ui.result_panel(f"Phone · {pretty}", self._phone_rows(records, found))

    def _phone_rows(self, records, found):
        found.sort(key=lambda r: str(r.get("domain") or r.get("name") or "").lower())

        rate_limited = sum(1 for r in records if r.get("rateLimit"))
        rows = [("registered", str(len(found)))]
        if rate_limited:
            rows.append(("skipped", Text(f"{rate_limited} sites rate-limited", style="muted")))

        for record in found:
            site = record.get("domain") or record.get("name") or "-"
            rows.append(("", Text(site, style="bold accent")))

        return rows

    def _split_phone(self, raw):
        raw = raw.strip()
        if not raw:
            return None, None
        candidate = raw if raw.startswith("+") else "+" + re.sub(r"[^0-9]", "", raw)
        try:
            import phonenumbers

            number = phonenumbers.parse(candidate, None)
            if phonenumbers.is_possible_number(number):
                return str(number.country_code), str(number.national_number)
        except Exception:
            pass
        return None, None


    def _run_engine(self, engine, args):
        cmd = [sys.executable, engine, *args]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.hard_timeout,
            )
        except subprocess.TimeoutExpired:
            return None, "search timed out, try again"
        except Exception as exc:
            return None, f"search failed: {exc}"

        try:
            return json.loads(result.stdout or b"[]"), None
        except ValueError:
            return None, "could not parse search results"

    def _ensure(self, ctx, package):
        if self._importable(package):
            return True
        with ctx.ui.loader("preparing search engine"):
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--quiet",
                     "--disable-pip-version-check", package],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=180,
                )
            except Exception:
                return False
        return self._importable(package)

    def _importable(self, package):
        try:
            __import__(package)
            return True
        except Exception:
            return False


def _hint(value):
    if not value:
        return None
    value = " ".join(str(value).split())
    return value or None
