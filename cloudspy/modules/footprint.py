import concurrent.futures
import re
from urllib.parse import urlparse

from rich.text import Text

from ..utils import http
from .base import Context, Module

_CDX = "https://web.archive.org/cdx/search/cdx"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9-]+)*\.[a-z]{2,}$", re.I)

_SITES = [
    ("Twitter", "twitter.com/{u}"),
    ("Instagram", "instagram.com/{u}"),
    ("GitHub", "github.com/{u}"),
    ("Reddit", "reddit.com/user/{u}"),
    ("TikTok", "tiktok.com/@{u}"),
    ("YouTube", "youtube.com/@{u}"),
    ("Facebook", "facebook.com/{u}"),
    ("Twitch", "twitch.tv/{u}"),
    ("SoundCloud", "soundcloud.com/{u}"),
    ("Steam", "steamcommunity.com/id/{u}"),
    ("Pinterest", "pinterest.com/{u}"),
    ("Medium", "medium.com/@{u}"),
    ("Telegram", "t.me/{u}"),
    ("Flickr", "flickr.com/people/{u}"),
    ("Keybase", "keybase.io/{u}"),
    ("VK", "vk.com/{u}"),
]


class FootprintModule(Module):
    name = "Footprint Timeline"
    slug = "footprint"
    description = "Reconstruct a target's historical and deleted presence from web archives."
    version = "0.1.0"

    request_timeout = 8
    max_workers = 16

    def run(self, ctx: Context) -> None:
        raw = ctx.ui.ask("username, email, or domain")
        if not raw:
            ctx.ui.notify_error("no target supplied")
            return

        kind, value = _classify(raw)
        if kind is None:
            ctx.ui.notify_error("could not read that target")
            return

        if kind == "domain":
            with ctx.ui.loader(f"mining web archives for {value}"):
                oldest, count, subdomains = self._domain(value)
            if not count:
                ctx.ui.notify_info(f"no archived captures found for {value}")
                return
            ctx.ui.result_panel(f"Footprint · {value}", self._domain_rows(value, oldest, count, subdomains))
            return

        note = " (from email)" if kind == "email" else ""
        with ctx.ui.loader(f"mining web archives for {value}{note}"):
            records = self._username(value)

        if not records:
            ctx.ui.notify_info(f"no archived footprint found for {value}")
            return

        ctx.ui.result_panel(f"Footprint · {value}", self._username_rows(value, records))

    def _username(self, username):
        def probe(site):
            name, template = site
            target = template.format(u=username)
            span = self._cdx(target)
            if not span:
                return None
            first, last, count = span
            url = "https://" + target
            state = self._live_state(url)
            return {
                "site": name,
                "url": url,
                "first": first,
                "last": last,
                "count": count,
                "state": state,
            }

        records = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for record in pool.map(probe, _SITES):
                if record:
                    records.append(record)
        records.sort(key=lambda r: r["first"])
        return records

    def _cdx(self, target):
        params = {
            "url": target,
            "output": "json",
            "fl": "timestamp,statuscode",
            "collapse": "timestamp:6",
            "limit": "120",
        }
        try:
            response = http.get(_CDX, params=params, timeout=self.request_timeout)
            rows = response.json()
        except Exception:
            return None
        if not isinstance(rows, list) or len(rows) < 2:
            return None
        stamps = [row[0] for row in rows[1:] if row and row[0]]
        if not stamps:
            return None
        return stamps[0], stamps[-1], len(stamps)

    def _live_state(self, url):
        try:
            response = http.get(
                url,
                client=http.session(http.BROWSER_AGENT),
                timeout=self.request_timeout,
                allow_redirects=True,
            )
        except Exception:
            return ""
        if response.status_code in (404, 410):
            return "deleted"
        if response.status_code == 200:
            return "live"
        return ""

    def _domain(self, domain):
        oldest = None
        try:
            response = http.get(
                _CDX,
                params={"url": domain, "matchType": "domain", "output": "json", "fl": "timestamp", "limit": "1"},
                timeout=self.request_timeout,
            )
            rows = response.json()
            if isinstance(rows, list) and len(rows) > 1:
                oldest = rows[1][0]
        except Exception:
            pass

        subdomains = []
        count = 0
        try:
            response = http.get(
                _CDX,
                params={
                    "url": domain, "matchType": "domain", "output": "json",
                    "fl": "original", "collapse": "urlkey", "limit": "1000",
                },
                timeout=self.request_timeout,
            )
            rows = response.json()
            if isinstance(rows, list) and len(rows) > 1:
                count = len(rows) - 1
                hosts = []
                for row in rows[1:]:
                    host = _host(row[0]) if row and row[0] else None
                    if host and host not in hosts:
                        hosts.append(host)
                subdomains = sorted(hosts)
        except Exception:
            pass

        return oldest, count, subdomains

    def _username_rows(self, username, records):
        oldest = min(r["first"] for r in records)
        total = sum(r["count"] for r in records)
        deleted = [r for r in records if r["state"] == "deleted"]

        rows = [
            ("target", Text(username, style="text")),
            ("online since", Text(_year(oldest), style="bold accent")),
            ("archived on", Text(f"{len(records)} platforms · {total} snapshots", style="muted")),
        ]
        if deleted:
            rows.append(("deleted", Text(f"{len(deleted)} profile(s) archived but now gone", style="error")))

        rows.append(("", Text("")))
        rows.append(("", Text("── timeline ──", style="primary.dim")))
        for record in records:
            head = Text(record["site"], style="bold accent")
            span = _year(record["first"])
            if _year(record["last"]) != span:
                span += f" → {_year(record['last'])}"
            head.append(f"  {span}  ·  {record['count']} snapshots", style="muted")
            if record["state"] == "deleted":
                head.append("  ·  deleted", style="error")
            elif record["state"] == "live":
                head.append("  ·  live", style="muted")
            rows.append(("", head))
            rows.append(("", Text(f"  {record['url']}", style="text")))

        return rows

    def _domain_rows(self, domain, oldest, count, subdomains):
        rows = [
            ("domain", Text(domain, style="text")),
            ("online since", Text(_year(oldest), style="bold accent")),
            ("archived urls", Text(str(count), style="accent")),
            ("subdomains", Text(str(len(subdomains)), style="accent")),
        ]
        if subdomains:
            rows.append(("", Text("")))
            rows.append(("", Text("── subdomains seen ──", style="primary.dim")))
            for host in subdomains[:20]:
                rows.append(("", Text(host, style="text")))
            hidden = len(subdomains) - min(len(subdomains), 20)
            if hidden:
                rows.append(("", Text(f"+ {hidden} more", style="muted")))
        return rows


def _classify(value):
    value = value.strip()
    if _EMAIL_RE.match(value):
        return "email", value.split("@")[0].lower()
    if _DOMAIN_RE.match(value) and " " not in value:
        return "domain", value.lower()
    handle = value.lstrip("@").strip()
    if handle and " " not in handle:
        return "username", handle
    return None, None


def _host(url):
    try:
        netloc = urlparse(url if "://" in url else "http://" + url).netloc
    except Exception:
        return None
    return netloc.split("@")[-1].split(":")[0].lower() or None


def _year(stamp):
    if stamp and len(stamp) >= 4:
        return stamp[:4]
    return "?"
