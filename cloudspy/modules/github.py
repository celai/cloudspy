from datetime import datetime

from rich.text import Text

from ..utils import http
from .base import Context, Module

_NOREPLY = "noreply.github.com"


class GitHubModule(Module):
    name = "GitHub Recon"
    slug = "github"
    description = "Profile lookup and public commit email harvesting."
    version = "0.1.0"
    max_repos = 25
    max_emails = 15

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("name")
        if not target:
            ctx.ui.notify_error("no target supplied")
            return

        username = target.lstrip("@").strip()
        if not username:
            ctx.ui.notify_error("invalid username")
            return

        with ctx.ui.loader(f"querying github for {username}"):
            profile, error = self._profile(username)

        if error:
            ctx.ui.notify_error(error)
            return

        with ctx.ui.loader("harvesting public commit emails"):
            emails = self._emails(username)

        ctx.ui.result_panel(f"GitHub · {profile.get('login', username)}", self._rows(profile, emails))

    def _profile(self, username):
        try:
            response = http.get(f"https://api.github.com/users/{username}")
        except Exception as exc:
            return None, f"request failed: {exc}"

        if response.status_code == 404:
            return None, f"user '{username}' not found"
        if response.status_code == 403:
            return None, "github rate limit reached, try again later"
        if response.status_code != 200:
            return None, f"github returned status {response.status_code}"

        try:
            return response.json(), None
        except ValueError:
            return None, "could not parse github response"

    def _emails(self, username):
        client = http.session()
        emails = set()

        try:
            response = http.get(
                f"https://api.github.com/users/{username}/repos?per_page=100&sort=pushed",
                client=client,
            )
            repos = response.json()
        except Exception:
            return emails

        if not isinstance(repos, list):
            return emails

        for repo in repos[: self.max_repos]:
            name = repo.get("name")
            if not name:
                continue
            try:
                response = http.get(
                    f"https://api.github.com/repos/{username}/{name}/commits?per_page=100",
                    client=client,
                )
                commits = response.json()
            except Exception:
                continue

            if not isinstance(commits, list):
                continue

            for commit in commits:
                author = commit.get("commit", {}).get("author", {}) or {}
                email = author.get("email")
                if email and _NOREPLY not in email:
                    emails.add(email)

        return emails

    def _rows(self, profile, emails):
        rows = [
            ("id", str(profile.get("id", "-"))),
            ("name", _text(profile.get("name"))),
            ("bio", _clip(profile.get("bio"))),
            ("created", _date(profile.get("created_at"))),
            ("profile", _text(profile.get("html_url"))),
        ]

        if emails:
            ordered = sorted(emails)
            shown = ordered[: self.max_emails]
            for email in shown:
                rows.append(("email", Text(email, style="accent")))
            hidden = len(ordered) - len(shown)
            if hidden:
                rows.append(("", Text(f"+ {hidden} more emails", style="muted")))
        else:
            rows.append(("email", Text("none found", style="muted")))

        return rows


def _text(value):
    value = value.strip() if isinstance(value, str) else value
    return value if value else "-"


def _clip(value, limit=160):
    if not value:
        return "-"
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _date(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return str(value)
