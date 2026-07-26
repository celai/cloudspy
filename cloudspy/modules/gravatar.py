import hashlib

from rich.text import Text

from ..utils import http
from .base import Context, Module

_PROFILE = "https://en.gravatar.com/{hash}.json"
_AVATAR = "https://www.gravatar.com/avatar/{hash}"


class GravatarModule(Module):
    name = "Gravatar Lookup"
    slug = "gravatar"
    description = "Resolve an email to a public Gravatar identity and linked accounts."
    version = "0.1.0"

    max_accounts = 20

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("target email")
        if not target:
            ctx.ui.notify_error("no email supplied")
            return

        email = target.strip().lower()
        if "@" not in email or " " in email or email.count("@") != 1:
            ctx.ui.notify_error("invalid email address")
            return

        digest = hashlib.md5(email.encode("utf-8")).hexdigest()

        with ctx.ui.loader(f"resolving gravatar for {email}"):
            entry, has_avatar, error = self._lookup(digest)

        if error:
            ctx.ui.notify_error(error)
            return

        if entry is None:
            if has_avatar:
                ctx.ui.result_panel(
                    f"Gravatar · {email}",
                    [
                        ("hash", Text(digest, style="muted")),
                        ("profile", Text("no public profile", style="muted")),
                        ("avatar", Text(_AVATAR.format(hash=digest), style="accent")),
                        ("", Text("custom avatar set, but profile is private/empty", style="muted")),
                    ],
                )
            else:
                ctx.ui.notify_info(f"no gravatar registered for {email}")
            return

        ctx.ui.result_panel(f"Gravatar · {email}", self._rows(entry, digest, has_avatar))

    def _lookup(self, digest):
        client = http.session()

        try:
            response = http.get(_PROFILE.format(hash=digest), client=client)
        except Exception as exc:
            return None, False, f"request failed: {exc}"

        has_avatar = self._avatar_exists(digest, client)

        if response.status_code == 404:
            return None, has_avatar, None
        if response.status_code == 429:
            return None, has_avatar, "rate limited by gravatar, try again later"
        if response.status_code != 200:
            return None, has_avatar, f"gravatar returned status {response.status_code}"

        try:
            data = response.json()
        except ValueError:
            return None, has_avatar, "could not parse gravatar response"

        entries = data.get("entry") if isinstance(data, dict) else None
        if not isinstance(entries, list) or not entries:
            return None, has_avatar, None

        return entries[0], has_avatar, None

    def _avatar_exists(self, digest, client):
        try:
            response = http.get(
                _AVATAR.format(hash=digest), client=client, params={"d": "404"}
            )
            return response.status_code == 200
        except Exception:
            return False

    def _rows(self, entry, digest, has_avatar):
        rows = [("hash", Text(digest, style="muted"))]

        profile_url = entry.get("profileUrl")
        if profile_url:
            rows.append(("profile", Text(profile_url, style="accent")))

        rows.append(("name", _text(entry.get("displayName"))))
        username = entry.get("preferredUsername")
        if username:
            rows.append(("username", Text(str(username), style="text")))
        if entry.get("pronouns"):
            rows.append(("pronouns", _text(entry.get("pronouns"))))

        role = self._role(entry)
        if role:
            rows.append(("role", Text(role, style="text")))
        if entry.get("currentLocation"):
            rows.append(("location", _text(entry.get("currentLocation"))))
        if entry.get("aboutMe"):
            rows.append(("bio", _clip(entry.get("aboutMe"))))

        avatar = _first_value(entry.get("photos")) or _AVATAR.format(hash=digest)
        rows.append(("avatar", Text(avatar, style="accent" if has_avatar else "muted")))

        emails = self._values(entry.get("emails"))
        for mail in emails:
            rows.append(("email", Text(mail, style="text")))

        contacts = self._values(entry.get("contactInfo"))
        for contact in contacts:
            rows.append(("contact", Text(contact, style="text")))

        accounts = entry.get("accounts")
        if isinstance(accounts, list) and accounts:
            rows.append(("", Text("")))
            rows.append(("accounts", Text(str(len(accounts)), style="bold accent")))
            for account in accounts[: self.max_accounts]:
                if not isinstance(account, dict):
                    continue
                label = account.get("name") or account.get("domain") or "link"
                url = account.get("url") or account.get("display") or ""
                mark = " ✓" if account.get("verified") else ""
                line = Text(f"{label}{mark}", style="bold accent")
                if url:
                    line.append(f"  {url}", style="text")
                rows.append(("", line))
            hidden = len(accounts) - min(len(accounts), self.max_accounts)
            if hidden:
                rows.append(("", Text(f"+ {hidden} more accounts", style="muted")))

        return rows

    def _role(self, entry):
        title = (entry.get("job_title") or "").strip()
        company = (entry.get("company") or "").strip()
        if title and company:
            return f"{title} @ {company}"
        return title or company or None

    def _values(self, items):
        out = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    value = item.get("value")
                    if value:
                        out.append(str(value).strip())
        return out


def _first_value(items):
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("value"):
                return str(item["value"])
    return None


def _text(value):
    value = value.strip() if isinstance(value, str) else value
    return value if value else "-"


def _clip(value, limit=200):
    if not value:
        return "-"
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
