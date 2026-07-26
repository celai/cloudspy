import hashlib
from collections import Counter

from rich.text import Text

from ..utils import http
from .base import Context, Module

_ANALYTICS = "https://api.xposedornot.com/v1/breach-analytics"
_CHECK = "https://api.xposedornot.com/v1/check-email/{email}"
_PWNED = "https://api.pwnedpasswords.com/range/{prefix}"


class BreachCheckModule(Module):
    name = "Breach Check"
    slug = "breach"
    description = "Where an email leaked and whether a password is compromised."
    version = "0.1.0"

    max_breaches = 18
    max_data_types = 10

    def run(self, ctx: Context) -> None:
        while True:
            ctx.ui.render_submenu("Breach Check", ["Email Exposure", "Password Check"])
            choice = (ctx.ui.ask("select") or "").strip().lower()
            if choice in ("1", "01", "email"):
                self._email_flow(ctx)
                return
            if choice in ("2", "02", "password", "pass"):
                self._password_flow(ctx)
                return
            if choice in ("b", "back", "q", ""):
                return


    def _email_flow(self, ctx):
        target = ctx.ui.ask("target email")
        if not target:
            ctx.ui.notify_error("no email supplied")
            return
        email = target.strip()
        if "@" not in email or " " in email or email.count("@") != 1:
            ctx.ui.notify_error("invalid email address")
            return

        with ctx.ui.loader(f"checking breaches for {email}"):
            details, metrics, error = self._analytics(email)

        if error:
            ctx.ui.notify_error(error)
            return

        if not details:
            ctx.ui.notify_info(f"no breaches found for {email}")
            return

        ctx.ui.result_panel(f"Breach · {email}", self._email_rows(details, metrics))

    def _analytics(self, email):
        client = http.session()
        try:
            response = http.get(_ANALYTICS, client=client, params={"email": email})
        except Exception as exc:
            return None, None, f"request failed: {exc}"

        if response.status_code == 404:
            return [], {}, None
        if response.status_code == 429:
            return None, None, "rate limited by breach service, try again later"
        if response.status_code != 200:
            return None, None, f"breach service returned status {response.status_code}"

        try:
            data = response.json()
        except ValueError:
            return None, None, "could not parse breach response"

        if not isinstance(data, dict):
            return [], {}, None

        exposed = data.get("ExposedBreaches") or {}
        details = exposed.get("breaches_details") if isinstance(exposed, dict) else None
        if not isinstance(details, list):
            details = []

        metrics = data.get("BreachMetrics") if isinstance(data.get("BreachMetrics"), dict) else {}
        return details, metrics, None

    def _email_rows(self, details, metrics):
        years = [self._year(b.get("xposed_date")) for b in details]
        years = [y for y in years if y]
        records = sum(int(b.get("xposed_records") or 0) for b in details)
        verified = sum(1 for b in details if str(b.get("verified", "")).lower() == "yes")

        data_counts = Counter()
        for b in details:
            for item in str(b.get("xposed_data") or "").split(";"):
                item = item.strip()
                if item:
                    data_counts[item] += 1

        rows = [("breaches", Text(str(len(details)), style="bold accent"))]

        risk = self._risk(metrics)
        if risk:
            label, score, style = risk
            rows.append(("risk", Text(f"{label} ({score}/100)", style=style)))

        if years:
            span = f"{min(years)} - {max(years)}" if min(years) != max(years) else str(max(years))
            rows.append(("span", span))
        if records:
            rows.append(("records", f"{records:,} exposed"))
        rows.append(("verified", f"{verified} of {len(details)} confirmed"))

        pw = self._password_strength(metrics)
        if pw:
            rows.append(("passwords", Text(pw, style="text")))

        if data_counts:
            top = ", ".join(name for name, _ in data_counts.most_common(self.max_data_types))
            rows.append(("data types", Text(top, style="muted")))

        rows.append(("", Text("")))
        ordered = sorted(
            details,
            key=lambda b: (self._year(b.get("xposed_date")) or 0, int(b.get("xposed_records") or 0)),
            reverse=True,
        )
        for b in ordered[: self.max_breaches]:
            name = b.get("breach") or b.get("domain") or "-"
            year = self._year(b.get("xposed_date"))
            rec = int(b.get("xposed_records") or 0)
            meta = []
            if year:
                meta.append(str(year))
            if rec:
                meta.append(f"{rec:,} recs")
            if str(b.get("verified", "")).lower() == "yes":
                meta.append("verified")
            head = Text(name, style="bold accent")
            if meta:
                head.append("  ·  " + " · ".join(meta), style="muted")
            rows.append(("", head))
            classes = _clip(str(b.get("xposed_data") or "").replace(";", ", "), 90)
            if classes and classes != "-":
                rows.append(("", Text(classes, style="text")))

        hidden = len(details) - min(len(details), self.max_breaches)
        if hidden:
            rows.append(("", Text(f"+ {hidden} more breaches", style="muted")))

        return rows

    def _risk(self, metrics):
        risk = metrics.get("risk") if metrics else None
        if isinstance(risk, list) and risk and isinstance(risk[0], dict):
            label = str(risk[0].get("risk_label") or "Unknown")
            score = risk[0].get("risk_score", "?")
            style = {
                "critical": "error",
                "high": "error",
                "medium": "accent",
                "low": "muted",
            }.get(label.lower(), "text")
            return label, score, style
        return None

    def _password_strength(self, metrics):
        strengths = metrics.get("passwords_strength") if metrics else None
        if isinstance(strengths, list) and strengths and isinstance(strengths[0], dict):
            s = strengths[0]
            parts = []
            for key, label in (
                ("PlainText", "plaintext"),
                ("EasyToCrack", "weak"),
                ("StrongHash", "strong-hash"),
            ):
                val = s.get(key)
                if val:
                    parts.append(f"{val} {label}")
            return " · ".join(parts) if parts else None
        return None

    def _year(self, value):
        try:
            return int(str(value)[:4])
        except (ValueError, TypeError):
            return None


    def _password_flow(self, ctx):
        secret = ctx.ui.ask("password to test")
        if not secret:
            ctx.ui.notify_error("no password supplied")
            return

        digest = hashlib.sha1(secret.encode("utf-8")).hexdigest().upper()
        prefix, suffix = digest[:5], digest[5:]

        with ctx.ui.loader("querying pwned passwords (only a hash prefix is sent)"):
            count, error = self._pwned(prefix, suffix)

        if error:
            ctx.ui.notify_error(error)
            return

        ctx.ui.result_panel("Breach · Password", self._password_rows(prefix, count))

    def _pwned(self, prefix, suffix):
        client = http.session()
        try:
            response = http.get(
                _PWNED.format(prefix=prefix),
                client=client,
                headers={"Add-Padding": "true"},
            )
        except Exception as exc:
            return None, f"request failed: {exc}"

        if response.status_code != 200:
            return None, f"pwned passwords returned status {response.status_code}"

        for line in response.text.splitlines():
            part, _, seen = line.partition(":")
            if part.strip().upper() == suffix:
                try:
                    return int(seen.strip()), None
                except ValueError:
                    return 0, None
        return 0, None

    def _password_rows(self, prefix, count):
        rows = [("hash prefix", Text(prefix + "…", style="muted"))]
        if count > 0:
            rows.append(("status", Text("COMPROMISED", style="error")))
            rows.append(("seen", Text(f"{count:,} times in known breaches", style="text")))
            rows.append(("", Text("do not use this password anywhere", style="error")))
        else:
            rows.append(("status", Text("not found in breach corpus", style="accent")))
            rows.append(("", Text("absence is not a guarantee of safety", style="muted")))
        return rows


def _clip(value, limit=160):
    if not value:
        return "-"
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
