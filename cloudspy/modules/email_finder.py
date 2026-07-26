import concurrent.futures
import hashlib
import random
import re
import smtplib
import socket
import string
import unicodedata

from rich.text import Text

from ..utils import http
from .base import Context, Module
from .gravatar import GravatarModule

_DOH = "https://dns.google/resolve"

_PATTERNS = [
    "{first}",
    "{first}.{last}",
    "{first}{last}",
    "{first}_{last}",
    "{first}-{last}",
    "{f}{last}",
    "{f}.{last}",
    "{f}_{last}",
    "{first}{l}",
    "{first}.{l}",
    "{last}",
    "{last}{first}",
    "{last}.{first}",
    "{last}{f}",
    "{f}{l}",
    "{first}{m}{last}",
]

_FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
    "outlook.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com",
    "proton.me", "protonmail.com", "gmx.com", "gmx.net", "mail.com", "zoho.com",
    "yandex.com", "pm.me", "tutanota.com",
}


class EmailFinderModule(Module):
    name = "Email Finder"
    slug = "email"
    description = "Discover and verify a person's email from their name and a domain."
    version = "0.1.0"

    smtp_timeout = 6
    max_workers = 10

    def run(self, ctx: Context) -> None:
        raw_name = ctx.ui.ask("full name")
        if not raw_name:
            ctx.ui.notify_error("no name supplied")
            return

        parts = _name_parts(raw_name)
        if not parts:
            ctx.ui.notify_error("could not read that name")
            return

        raw_domain = ctx.ui.ask("domain")
        if not raw_domain:
            ctx.ui.notify_error("no domain supplied")
            return

        domain = _clean_domain(raw_domain)
        if not domain or "." not in domain:
            ctx.ui.notify_error("invalid domain")
            return

        candidates = _candidates(parts, domain)
        if not candidates:
            ctx.ui.notify_error("could not build candidates from that name")
            return

        with ctx.ui.loader(f"resolving mail servers for {domain}"):
            mx = _resolve_mx(domain)

        results, catch_all, mode = {}, False, "no-mx"
        if mx:
            with ctx.ui.loader(f"probing {len(candidates)} candidates via {mx[0]}"):
                catch_all, results, mode = self._smtp(mx[0], domain, candidates)

        with ctx.ui.loader("cross-checking gravatar"):
            gravatars = self._gravatar(candidates)

        identity = self._identity(gravatars)
        ctx.ui.result_panel(
            f"Email · {domain}",
            self._rows(domain, mx, candidates, results, catch_all, mode, gravatars, identity),
        )

    def _smtp(self, host, domain, candidates):
        try:
            server = smtplib.SMTP(timeout=self.smtp_timeout)
            server.connect(host, 25)
            server.helo(domain)
            server.mail(f"contact@{domain}")
        except (OSError, smtplib.SMTPException):
            return False, {}, "smtp-blocked"

        results = {}
        catch_all = False
        try:
            code, _ = server.rcpt(f"{_random_local()}@{domain}")
            if code in (250, 251):
                catch_all = True
        except smtplib.SMTPException:
            pass

        if not catch_all:
            for candidate in candidates:
                try:
                    code, _ = server.rcpt(candidate)
                except smtplib.SMTPException:
                    code = 0
                results[candidate] = code

        try:
            server.quit()
        except smtplib.SMTPException:
            pass
        return catch_all, results, "catch-all" if catch_all else "smtp"

    def _gravatar(self, candidates):
        client = http.session()

        def check(candidate):
            digest = hashlib.md5(candidate.lower().encode("utf-8")).hexdigest()
            try:
                response = http.get(
                    f"https://www.gravatar.com/avatar/{digest}",
                    client=client,
                    params={"d": "404"},
                    timeout=8,
                )
                return candidate, response.status_code == 200
            except Exception:
                return candidate, False

        hits = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for candidate, ok in pool.map(check, candidates):
                if ok:
                    hits[candidate] = True
        return hits

    def _identity(self, gravatars):
        for candidate in gravatars:
            digest = hashlib.md5(candidate.lower().encode("utf-8")).hexdigest()
            entry, _avatar, error = GravatarModule()._lookup(digest)
            if error or not isinstance(entry, dict):
                continue
            fields = []
            if entry.get("displayName"):
                fields.append(("name", entry["displayName"]))
            if entry.get("currentLocation"):
                fields.append(("location", entry["currentLocation"]))
            if entry.get("profileUrl"):
                fields.append(("gravatar", entry["profileUrl"]))
            if fields:
                return candidate, fields
        return None

    def _rows(self, domain, mx, candidates, results, catch_all, mode, gravatars, identity):
        rows = [("domain", Text(domain, style="text"))]
        if mx:
            rows.append(("mail server", Text(mx[0], style="muted")))

        if mode == "no-mx":
            rows.append(("status", Text("no MX record - this domain cannot receive mail", style="error")))
        elif mode == "smtp-blocked":
            rows.append(("status", Text("SMTP unreachable (port 25 blocked) - ranking by pattern + gravatar", style="warn")))
        elif catch_all:
            rows.append(("status", Text("catch-all domain - SMTP accepts every address, using gravatar", style="warn")))
        else:
            rows.append(("status", Text("SMTP verification active", style="accent")))

        ranked = _rank(candidates, results, gravatars, catch_all, mode)
        strong = [r for r in ranked if r[2] <= 1]
        weak = [r for r in ranked if r[2] == 2]
        rejected = [r for r in ranked if r[2] == 3]

        rows.append(("", Text("")))
        if strong:
            rows.append(("", Text("── best matches ──", style="primary.dim")))
            for email, verdict, _score, style in strong:
                line = Text(email, style=f"bold {style}")
                line.append(f"  {verdict}", style="muted")
                rows.append(("", line))
        else:
            rows.append(("", Text("no high-confidence match - candidates below by pattern", style="muted")))

        if weak:
            rows.append(("", Text("")))
            rows.append(("", Text("── possible ──", style="primary.dim")))
            for email, verdict, _score, style in weak:
                line = Text(email, style="text")
                line.append(f"  {verdict}", style="muted")
                rows.append(("", line))

        if rejected:
            rows.append(("", Text("")))
            rows.append(("rejected", Text(f"{len(rejected)} patterns refused by the mail server", style="muted")))

        if identity:
            email, fields = identity
            rows.append(("", Text("")))
            rows.append(("", Text("── identity ──", style="primary.dim")))
            rows.append(("email", Text(email, style="bold accent")))
            for label, value in fields:
                rows.append((label, Text(str(value), style="text")))

        return rows


def _name_parts(name):
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    tokens = [t for t in re.split(r"[^A-Za-z]+", text.lower()) if t]
    if not tokens:
        return None
    first = tokens[0]
    last = tokens[-1] if len(tokens) > 1 else ""
    middle = tokens[1] if len(tokens) > 2 else ""
    return {
        "first": first,
        "last": last,
        "f": first[0],
        "l": last[0] if last else "",
        "m": middle[0] if middle else "",
    }


def _candidates(parts, domain):
    seen = []
    out = []
    for pattern in _PATTERNS:
        try:
            local = pattern.format(**parts)
        except (KeyError, IndexError):
            continue
        local = re.sub(r"([._-])\1+", r"\1", local)
        local = local.strip("._-")
        if len(local) < 2 or "{" in local or local in seen:
            continue
        seen.append(local)
        out.append(f"{local}@{domain}")
    return out


def _clean_domain(value):
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/")[0].split("@")[-1]
    return value.strip(".")


def _resolve_mx(domain):
    try:
        response = http.get(_DOH, params={"name": domain, "type": "MX"}, timeout=8)
        data = response.json()
    except Exception:
        return []
    answers = data.get("Answer") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        return []
    hosts = []
    for answer in answers:
        if answer.get("type") != 15:
            continue
        parts = str(answer.get("data", "")).split()
        if len(parts) == 2:
            hosts.append((int(parts[0]), parts[1].rstrip(".")))
    hosts.sort()
    return [host for _pref, host in hosts]


def _random_local():
    return "zz" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))


def _rank(candidates, results, gravatars, catch_all, mode):
    ranked = []
    for candidate in candidates:
        if gravatars.get(candidate):
            ranked.append((candidate, "gravatar match", 0, "accent"))
            continue
        code = results.get(candidate)
        if mode == "smtp" and not catch_all and code:
            if code in (250, 251):
                ranked.append((candidate, "verified", 1, "accent"))
            elif code in (450, 451, 452, 421):
                ranked.append((candidate, "greylisted", 2, "text"))
            elif code:
                ranked.append((candidate, "rejected", 3, "muted"))
            continue
        if catch_all:
            ranked.append((candidate, "accepted (catch-all)", 2, "text"))
        else:
            ranked.append((candidate, "unverified", 2, "text"))
    ranked.sort(key=lambda r: r[2])
    return ranked
