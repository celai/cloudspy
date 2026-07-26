import concurrent.futures
import hashlib
import html
import re
import time
from collections import deque

from rich.text import Text

from ..utils import http
from .base import Context, Module

from .accounts import AccountFinderModule, _EMAIL_ENGINE
from .breach import BreachCheckModule
from .github import GitHubModule, _NOREPLY
from .gravatar import GravatarModule
from .hudsonrock import HudsonRockModule, _EMAIL_URL, _USERNAME_URL
from .username import UsernameSearchModule

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{1,38})$")
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
_INLINE_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

_SITES = [
    ("SoundCloud",   "https://soundcloud.com/{u}",            None,                          "code",   None),
    ("Snapchat",     "https://www.snapchat.com/add/{u}",      None,                          "code",   None),
    ("Lichess",      "https://lichess.org/@/{u}",             None,                          "code",   None),
    ("Dribbble",     "https://dribbble.com/{u}",              None,                          "code",   None),
    ("Behance",      "https://www.behance.net/{u}",           None,                          "code",   None),
    ("Flickr",       "https://www.flickr.com/people/{u}",     None,                          "code",   None),
    ("Product Hunt", "https://www.producthunt.com/@{u}",      None,                          "code",   None),
    ("Linktree",     "https://linktr.ee/{u}",                 None,                          "code",   None),
    ("Last.fm",      "https://www.last.fm/user/{u}",          None,                          "code",   None),
    ("Letterboxd",   "https://letterboxd.com/{u}/",           None,                          "code",   None),
    ("Genius",       "https://genius.com/{u}",                None,                          "code",   None),
    ("Speaker Deck", "https://speakerdeck.com/{u}",           None,                          "code",   None),
    ("Gumroad",      "https://{u}.gumroad.com",               None,                          "code",   None),
    ("Docker Hub",   "https://hub.docker.com/v2/users/{u}/",  "https://hub.docker.com/u/{u}", "code",   None),
    ("Wattpad",      "https://www.wattpad.com/user/{u}",      None,                          "code",   None),
    ("Steam",        "https://steamcommunity.com/id/{u}",     None,                          "absent", "The specified profile could not be found"),
    ("Roblox",       "https://www.roblox.com/user.aspx?username={u}", None,                  "code",   None),
    ("Twitch",       "https://twitchtracker.com/{u}",         "https://www.twitch.tv/{u}",    "absent", "User not found"),
    ("Scratch",      "https://api.scratch.mit.edu/users/{u}", "https://scratch.mit.edu/users/{u}", "code", None),
    ("osu!",         "https://osu.ppy.sh/users/{u}",          None,                          "code",   None),
    ("Speedrun",     "https://www.speedrun.com/api/v1/users?name={u}", "https://www.speedrun.com/user/{u}", "json", "data"),
    ("Newgrounds",   "https://{u}.newgrounds.com",            None,                          "code",   None),
]

_STEALER_FIELDS = [
    ("family", "stealer_family"),
    ("computer", "computer_name"),
    ("os", "operating_system"),
    ("ip", "ip"),
    ("date", "date_compromised"),
    ("malware", "malware_path"),
    ("antivirus", "antiviruses"),
    ("logins", "top_logins"),
    ("passwords", "top_passwords"),
]


class OrderedSet:

    def __init__(self):
        self._items = {}

    def add(self, value):
        if not isinstance(value, str):
            if value is None:
                return
            value = str(value)
        value = value.strip()
        if value:
            self._items.setdefault(value, None)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __bool__(self):
        return bool(self._items)


class Dossier:

    def __init__(self, seed, kind):
        self.seed = seed
        self.kind = kind
        self.usernames = OrderedSet()
        self.emails = OrderedSet()
        self.names = OrderedSet()
        self.locations = OrderedSet()
        self.roles = OrderedSet()
        self.bios = OrderedSet()
        self.faces = {}
        self.profiles = {}
        self.links = {}
        self.breaches = []
        self.breach_metrics = {}
        self.registrations = []
        self.stealers = []
        self.reputation = {}
        self.footprint = {}
        self.verified = set()
        self.sources = OrderedSet()
        self.trail = []
        self.waves = 0
        self.elapsed = 0.0

    def merge(self, payload):
        if not payload:
            return
        source = payload.get("source")
        if source:
            self.sources.add(source)
        for value in payload.get("usernames", ()):
            self.usernames.add(value)
        for value in payload.get("emails", ()):
            self.emails.add(value.lower())
        for value in payload.get("names", ()):
            self.names.add(value)
        for value in payload.get("locations", ()):
            self.locations.add(value)
        for value in payload.get("roles", ()):
            self.roles.add(value)
        for value in payload.get("bios", ()):
            self.bios.add(_clip(value, 180))
        for url in payload.get("faces", ()):
            if url:
                self.faces.setdefault(url, source)
        for site, url in payload.get("profiles", ()):
            if url:
                self.profiles.setdefault(url, site)
        for label, url in payload.get("links", ()):
            if url:
                self.links.setdefault(url, label)
        if payload.get("breaches"):
            self.breaches = payload["breaches"]
            self.breach_metrics = payload.get("metrics") or {}
        if payload.get("registrations"):
            self.registrations = payload["registrations"]
        for hit in payload.get("stealers", ()):
            self.stealers.append(hit)
        if payload.get("reputation") and not self.reputation:
            self.reputation = payload["reputation"]
        if payload.get("footprint") and not self.footprint:
            self.footprint = payload["footprint"]


class TargetDossierModule(Module):
    name = "Target Dossier"
    slug = "dossier"
    description = "Recursive OSINT crawler - build a full identity from one email or username."
    version = "0.1.0"

    max_depth = 3
    max_waves = 5
    max_usernames = 12
    max_emails = 10
    time_budget = 200
    max_workers = 10
    site_workers = 16
    req_timeout = 8

    site_max_depth = 1
    max_faces_verified = 8

    use_maigret = False
    spread_sites = 500
    spread_timeout = 300

    def run(self, ctx: Context) -> None:
        raw = ctx.ui.ask("target (email or username)")
        if not raw:
            ctx.ui.notify_error("no target supplied")
            return

        seed = raw.strip()
        kind = self._classify(seed)
        if kind is None:
            ctx.ui.notify_error("could not read target - give an email or a username")
            return

        seed = seed.lower() if kind == "email" else seed.lstrip("@").strip()
        dossier = Dossier(seed, kind)
        getattr(dossier, "emails" if kind == "email" else "usernames").add(seed)

        self._crawl(ctx, dossier)

        if dossier.faces:
            with ctx.ui.loader("confirming faces"):
                self._verify_faces(dossier)

        ctx.ui.result_panel(f"Dossier · {seed}", self._rows(dossier))


    def _classify(self, value):
        value = value.strip()
        if _EMAIL_RE.match(value):
            return "email"
        handle = value.lstrip("@").strip()
        if _HANDLE_RE.match(handle):
            return "username"
        return None


    def _crawl(self, ctx, dossier):
        start = time.time()
        seen = set()
        counts = {"username": 0, "email": 0}
        queue = deque()

        def enqueue(kind, value, depth, via):
            value = value.lower() if kind == "email" else _clean_handle(value)
            if not value:
                return
            key = (kind, value.lower())
            if key in seen or depth > self.max_depth:
                return
            if counts[kind] >= (self.max_usernames if kind == "username" else self.max_emails):
                return
            seen.add(key)
            counts[kind] += 1
            queue.append((kind, value, depth))
            dossier.trail.append((depth, kind, value, via))

        enqueue(dossier.kind, dossier.seed, 0, "seed")

        wave = 0
        while queue and (time.time() - start) < self.time_budget and wave < self.max_waves:
            wave += 1
            level = list(queue)
            queue.clear()
            depth = level[0][2]

            jobs = []
            for kind, value, _depth in level:
                for fn in self._collectors(kind, depth):
                    jobs.append((fn, value))

            targets = ", ".join(v for _k, v, _d in level[:3])
            if len(level) > 3:
                targets += f" +{len(level) - 3}"
            message = f"wave {wave} · crawling {len(level)} identifier(s) [{targets}] via {len(jobs)} sources"

            with ctx.ui.loader(message):
                results = self._run(jobs)

            for payload in results:
                if not payload:
                    continue
                dossier.merge(payload)
                via = payload.get("source", "?")
                for value in payload.get("usernames", ()):
                    enqueue("username", value, depth + 1, via)
                for value in payload.get("emails", ()):
                    enqueue("email", value, depth + 1, via)

        dossier.waves = wave
        dossier.elapsed = round(time.time() - start, 1)

    def _collectors(self, kind, depth):
        if kind == "email":
            collectors = [
                self._c_gravatar,
                self._c_breach,
                self._c_hudson_email,
                self._c_emailrep,
            ]
            if depth == 0:
                collectors.append(self._c_holehe)
            return collectors

        collectors = [
            self._c_github,
            self._c_keybase,
            self._c_reddit,
            self._c_hackernews,
            self._c_gitlab,
            self._c_chess,
            self._c_hudson_user,
        ]
        if depth <= self.site_max_depth:
            collectors.append(self._c_sites)
        if depth == 0:
            collectors.append(self._c_github_emails)
            collectors.append(self._c_footprint)
            if self.use_maigret:
                collectors.append(self._c_spread)
        return collectors

    def _run(self, jobs):
        if not jobs:
            return []
        workers = min(self.max_workers, len(jobs))
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._safe, fn, arg) for fn, arg in jobs]
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        return results

    def _safe(self, fn, arg):
        try:
            return fn(arg)
        except Exception:
            return {}


    def _c_sites(self, username):
        client = http.session(http.BROWSER_AGENT)
        found = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.site_workers) as pool:
            for hit in pool.map(lambda site: self._check_site(client, username, site), _SITES):
                if hit:
                    found.append(hit)
        if not found:
            return {}
        return {"source": "sites", "profiles": found}

    def _check_site(self, client, username, site):
        name, check_tpl, profile_tpl, method, marker = site
        try:
            response = client.get(
                check_tpl.format(u=username), timeout=self.req_timeout, allow_redirects=True
            )
        except Exception:
            return None
        if response.status_code != 200:
            return None
        if method == "absent" and marker and marker in response.text:
            return None
        if method == "json":
            try:
                if not (response.json() or {}).get(marker):
                    return None
            except Exception:
                return None
        url = (profile_tpl or check_tpl).format(u=username)
        return (name, url)


    def _c_github(self, username):
        gh = GitHubModule()
        profile, error = gh._profile(username)
        if error or not isinstance(profile, dict):
            return {}
        login = profile.get("login") or username
        payload = {"source": "github", "usernames": [login]}
        _push(payload, "names", profile.get("name"))
        _push(payload, "locations", profile.get("location"))
        _push(payload, "bios", profile.get("bio"))
        _push(payload, "faces", profile.get("avatar_url"))
        if profile.get("company"):
            payload.setdefault("roles", []).append(str(profile["company"]).strip())
        if profile.get("html_url"):
            payload["profiles"] = [("GitHub", profile["html_url"])]
        blog = (profile.get("blog") or "").strip()
        if blog:
            payload.setdefault("links", []).append(("website", _normalize_url(blog)))
        twitter = (profile.get("twitter_username") or "").strip()
        if twitter:
            payload["usernames"].append(twitter)
            payload.setdefault("links", []).append(("twitter", f"https://twitter.com/{twitter}"))
        if profile.get("email"):
            payload.setdefault("emails", []).append(str(profile["email"]))
        return payload

    def _c_github_emails(self, username):
        emails = {e for e in GitHubModule()._emails(username) if _NOREPLY not in e}
        if not emails:
            return {}
        return {"source": "github", "emails": list(emails)}

    def _c_keybase(self, username):
        url = "https://keybase.io/_/api/1.0/user/lookup.json"
        params = {"usernames": username, "fields": "basics,profile,pictures,proofs_summary"}
        response = http.get(url, params=params, timeout=self.req_timeout)
        data = response.json() if response.status_code == 200 else {}
        them = data.get("them") if isinstance(data, dict) else None
        if not isinstance(them, list) or not them or not isinstance(them[0], dict):
            return {}
        entry = them[0]
        payload = {"source": "keybase"}
        profile = entry.get("profile") or {}
        _push(payload, "names", profile.get("full_name"))
        _push(payload, "locations", profile.get("location"))
        _push(payload, "bios", profile.get("bio"))
        pictures = entry.get("pictures") or {}
        primary = pictures.get("primary") if isinstance(pictures, dict) else None
        if isinstance(primary, dict):
            _push(payload, "faces", primary.get("url"))
        basics = entry.get("basics") or {}
        if basics.get("username"):
            payload["profiles"] = [("Keybase", f"https://keybase.io/{basics['username']}")]
        proofs = (entry.get("proofs_summary") or {}).get("all") or []
        for proof in proofs:
            if not isinstance(proof, dict):
                continue
            service = proof.get("proof_type")
            handle = proof.get("nametag")
            link = proof.get("service_url")
            if link:
                payload.setdefault("links", []).append((service or "proof", link))
            if handle and service in ("twitter", "github", "reddit", "hackernews", "mastodon"):
                payload.setdefault("usernames", []).append(handle)
        return payload

    def _c_reddit(self, username):
        client = http.session(http.BROWSER_AGENT)
        url = f"https://www.reddit.com/user/{username}/about.json"
        response = http.get(url, client=client, timeout=self.req_timeout)
        if response.status_code != 200:
            return {}
        data = (response.json() or {}).get("data") or {}
        if not data:
            return {}
        payload = {"source": "reddit", "profiles": [("Reddit", f"https://reddit.com/user/{username}")]}
        face = data.get("snoovatar_img") or data.get("icon_img")
        if face:
            _push(payload, "faces", html.unescape(face.split("?")[0]))
        sub = data.get("subreddit") or {}
        _push(payload, "names", sub.get("title"))
        _push(payload, "bios", sub.get("public_description"))
        return payload

    def _c_hackernews(self, username):
        url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
        response = http.get(url, timeout=self.req_timeout)
        data = response.json() if response.status_code == 200 else None
        if not isinstance(data, dict) or not data.get("id"):
            return {}
        payload = {
            "source": "hackernews",
            "profiles": [("Hacker News", f"https://news.ycombinator.com/user?id={username}")],
        }
        about = html.unescape(data.get("about") or "")
        if about:
            for match in _INLINE_EMAIL_RE.findall(about):
                payload.setdefault("emails", []).append(match)
            for match in _URL_RE.findall(about):
                payload.setdefault("links", []).append(("hn-link", match))
        return payload

    def _c_gitlab(self, username):
        url = "https://gitlab.com/api/v4/users"
        response = http.get(url, params={"username": username}, timeout=self.req_timeout)
        data = response.json() if response.status_code == 200 else None
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return {}
        user = data[0]
        payload = {"source": "gitlab", "usernames": [user.get("username") or username]}
        _push(payload, "names", user.get("name"))
        _push(payload, "locations", user.get("location"))
        _push(payload, "bios", user.get("bio"))
        _push(payload, "faces", user.get("avatar_url"))
        if user.get("organization"):
            payload.setdefault("roles", []).append(str(user["organization"]).strip())
        if user.get("web_url"):
            payload["profiles"] = [("GitLab", user["web_url"])]
        if user.get("public_email"):
            payload.setdefault("emails", []).append(str(user["public_email"]))
        twitter = (user.get("twitter") or "").strip().lstrip("@")
        if twitter:
            payload.setdefault("usernames", []).append(twitter)
        return payload

    def _c_chess(self, username):
        url = f"https://api.chess.com/pub/player/{username}"
        response = http.get(url, timeout=self.req_timeout)
        data = response.json() if response.status_code == 200 else None
        if not isinstance(data, dict) or not data.get("player_id"):
            return {}
        payload = {"source": "chess.com", "profiles": [("Chess.com", data.get("url") or url)]}
        _push(payload, "names", data.get("name"))
        _push(payload, "locations", data.get("location"))
        _push(payload, "faces", data.get("avatar"))
        return payload

    def _c_hudson_user(self, username):
        return self._hudson(_USERNAME_URL, "username", username, f"username:{username}")

    def _c_footprint(self, username):
        from .footprint import FootprintModule, _SITES, _year

        finder = FootprintModule()
        finder.request_timeout = 14
        oldest = None
        captures = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            spans = pool.map(lambda s: finder._cdx(s[1].format(u=username)), _SITES[:6])
            for span in spans:
                if not span:
                    continue
                first, _last, count = span
                captures += count
                if oldest is None or first < oldest:
                    oldest = first
        if not oldest:
            return {}
        return {"source": "archive", "footprint": {"since": _year(oldest), "captures": captures}}

    def _c_spread(self, username):
        finder = UsernameSearchModule()
        finder.top_sites = self.spread_sites
        finder.hard_timeout = self.spread_timeout
        accounts, error = finder._search(username)
        if error or not accounts:
            return {}
        profiles = [
            (a.get("site_name") or "site", a.get("url"))
            for a in accounts
            if a.get("url")
        ]
        return {"source": "maigret", "profiles": profiles}


    def _c_gravatar(self, email):
        digest = hashlib.md5(email.encode("utf-8")).hexdigest()
        entry, _has_avatar, error = GravatarModule()._lookup(digest)
        if error or not isinstance(entry, dict):
            return {}
        payload = {"source": "gravatar"}
        _push(payload, "names", entry.get("displayName"))
        _push(payload, "locations", entry.get("currentLocation"))
        _push(payload, "bios", entry.get("aboutMe"))
        if entry.get("preferredUsername"):
            payload.setdefault("usernames", []).append(str(entry["preferredUsername"]))
        photo = _first_photo(entry.get("photos"))
        if photo:
            _push(payload, "faces", photo)
        if entry.get("profileUrl"):
            payload["profiles"] = [("Gravatar", entry["profileUrl"])]
        title = (entry.get("job_title") or "").strip()
        company = (entry.get("company") or "").strip()
        role = " @ ".join(p for p in (title, company) if p)
        if role:
            payload.setdefault("roles", []).append(role)
        for mail in entry.get("emails") or []:
            if isinstance(mail, dict) and mail.get("value"):
                payload.setdefault("emails", []).append(str(mail["value"]))
        for account in entry.get("accounts") or []:
            if isinstance(account, dict):
                label = account.get("shortname") or account.get("name") or "link"
                if account.get("url"):
                    payload.setdefault("links", []).append((label, account["url"]))
                if account.get("username"):
                    payload.setdefault("usernames", []).append(str(account["username"]))
        return payload

    def _c_breach(self, email):
        details, metrics, error = BreachCheckModule()._analytics(email)
        if error or not details:
            return {}
        return {"source": "breach", "breaches": details, "metrics": metrics or {}}

    def _c_hudson_email(self, email):
        return self._hudson(_EMAIL_URL, "email", email, f"email:{email}")

    def _c_holehe(self, email):
        records, error = AccountFinderModule()._run_engine(_EMAIL_ENGINE, [email, "10"])
        if error or not records:
            return {}
        found = [r for r in records if r.get("exists")]
        if not found:
            return {}
        registrations = sorted(
            {(r.get("domain") or r.get("name") or "").lower() for r in found} - {""}
        )
        payload = {"source": "accounts", "registrations": registrations}
        for record in found:
            recovery = record.get("emailrecovery")
            if isinstance(recovery, str):
                clean = _deobfuscate(recovery)
                if clean:
                    payload.setdefault("emails", []).append(clean)
        return payload

    def _c_emailrep(self, email):
        client = http.session(http.BROWSER_AGENT)
        response = http.get(f"https://emailrep.io/{email}", client=client, timeout=self.req_timeout)
        if response.status_code != 200:
            return {}
        data = response.json()
        if not isinstance(data, dict) or "reputation" not in data:
            return {}
        details = data.get("details") or {}
        summary = {
            "reputation": data.get("reputation"),
            "suspicious": data.get("suspicious"),
            "credentials_leaked": details.get("credentials_leaked"),
            "data_breach": details.get("data_breach"),
            "deliverable": details.get("deliverable"),
            "last_seen": details.get("last_seen"),
            "profiles": details.get("profiles") or [],
        }
        payload = {"source": "emailrep", "reputation": summary}
        for profile in summary["profiles"]:
            payload.setdefault("links", []).append((str(profile), f"({profile} linked to email)"))
        return payload


    def _hudson(self, url, param, value, origin):
        data, error = HudsonRockModule()._search(url, param, value)
        if error or not isinstance(data, dict):
            return {}
        stealers = data.get("stealers") or []
        if not stealers:
            return {}
        payload = {"source": "hudson", "stealers": [(s, origin) for s in stealers]}
        for stealer in stealers:
            for login in stealer.get("top_logins") or []:
                login = str(login).strip()
                if not login or "*" in login:
                    continue
                if _EMAIL_RE.match(login):
                    payload.setdefault("emails", []).append(login.lower())
                elif _HANDLE_RE.match(login):
                    payload.setdefault("usernames", []).append(login)
        return payload

    def _verify_faces(self, dossier):
        urls = [u for u in dossier.faces if u.startswith("http")][: self.max_faces_verified]
        if not urls:
            return
        client = http.session(http.BROWSER_AGENT)

        def check(url):
            try:
                resp = client.get(url, timeout=self.req_timeout, stream=True)
                ok = resp.status_code == 200 and "image" in resp.headers.get("content-type", "")
                resp.close()
                return url, ok
            except Exception:
                return url, False

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(self.max_workers, len(urls))) as pool:
            for url, ok in pool.map(check, urls):
                if ok:
                    dossier.verified.add(url)


    def _rows(self, dossier):
        score, label, style, total = self._signal(dossier)
        rows = [
            ("seed", Text(f"{dossier.seed}  ({dossier.kind})", style="text")),
            ("signal", Text.assemble((_meter(score, total), style), ("  " + label, style))),
            ("reach", Text(self._reach_line(dossier), style="muted")),
            ("sources", Text(", ".join(dossier.sources) or "none responded", style="muted")),
        ]
        if dossier.footprint:
            fp = dossier.footprint
            rows.append(("archived", Text(f"online since {fp.get('since', '?')} · {fp.get('captures', 0)} captures", style="muted")))
        rows += self._identity_rows(dossier)
        rows += self._profiles_rows(dossier)
        rows += self._faces_rows(dossier)
        rows += self._links_rows(dossier)
        rows += self._exposure_rows(dossier)
        rows += self._trail_rows(dossier)
        return rows

    def _reach_line(self, dossier):
        return (
            f"{len(dossier.profiles)} profiles · {len(dossier.usernames)} usernames · "
            f"{len(dossier.emails)} emails · {dossier.waves} waves · {dossier.elapsed}s"
        )

    def _identity_rows(self, dossier):
        rows = [("", Text("")), ("", Text("── identity ──", style="primary.dim"))]
        empty = True
        for name in list(dossier.names)[:4]:
            rows.append(("name", Text(name, style="bold accent")))
            empty = False
        for role in list(dossier.roles)[:3]:
            rows.append(("role", Text(role, style="text")))
            empty = False
        for location in list(dossier.locations)[:3]:
            rows.append(("location", Text(location, style="text")))
            empty = False
        bios = list(dossier.bios)
        if bios:
            rows.append(("bio", Text(_clip(bios[0], 160), style="text")))
            empty = False
        for username in list(dossier.usernames)[:8]:
            tag = "  (seed)" if username.lower() == dossier.seed.lower() else ""
            rows.append(("username", Text(username + tag, style="text")))
            empty = False
        for email in list(dossier.emails)[:8]:
            tag = "  (seed)" if email == dossier.seed else ""
            rows.append(("email", Text(email + tag, style="accent" if not tag else "muted")))
            empty = False
        if empty:
            rows.append(("", Text("no identity correlated", style="muted")))
        return rows

    def _profiles_rows(self, dossier):
        if not dossier.profiles:
            return []
        items = list(dossier.profiles.items())
        rows = [("", Text("")), ("", Text(f"── profiles · {len(items)} confirmed ──", style="primary.dim"))]
        for url, site in items[:26]:
            line = Text(site, style="bold accent")
            line.append(f"  {url}", style="text")
            rows.append(("", line))
        hidden = len(items) - min(len(items), 26)
        if hidden:
            rows.append(("", Text(f"+ {hidden} more profiles", style="muted")))
        return rows

    def _faces_rows(self, dossier):
        if not dossier.faces:
            return []
        rows = [("", Text("")), ("", Text("── faces ──", style="primary.dim"))]
        for url, source in list(dossier.faces.items())[:8]:
            mark = " ✓" if url in dossier.verified else ""
            line = Text(url, style="accent")
            line.append(f"  ({source}{mark})", style="muted")
            rows.append(("face", line))
        return rows

    def _links_rows(self, dossier):
        if not dossier.links:
            return []
        rows = [("", Text("")), ("", Text("── linked accounts ──", style="primary.dim"))]
        for url, label in list(dossier.links.items())[:12]:
            line = Text(f"{label}", style="bold accent")
            line.append(f"  {url}", style="text")
            rows.append(("", line))
        return rows

    def _exposure_rows(self, dossier):
        has_exposure = (
            dossier.breaches or dossier.stealers
            or dossier.registrations or dossier.reputation
        )
        if not has_exposure:
            return []
        rows = [("", Text("")), ("", Text("── exposure ──", style="primary.dim"))]

        if dossier.breaches:
            head = Text(f"{len(dossier.breaches)} breaches", style="bold error")
            risk = self._risk_label(dossier.breach_metrics)
            if risk:
                head.append(f"  ·  {risk}", style="muted")
            rows.append(("breaches", head))
            top = ", ".join(
                str(b.get("breach") or b.get("domain") or "?") for b in dossier.breaches[:8]
            )
            rows.append(("", Text(_clip(top), style="text")))

        for record, origin in dossier.stealers[:2]:
            rows.append(("", Text("")))
            rows.append(("stealer", Text(f"infostealer · {origin}", style="bold error")))
            for label, key in _STEALER_FIELDS:
                value = record.get(key)
                if value in (None, "", []):
                    continue
                rendered = _clip(_stealer_value(value), 100)
                rows.append((label, Text(rendered, style="text" if label not in ("logins", "passwords") else "accent")))

        if dossier.reputation:
            rep = dossier.reputation
            bits = [f"reputation {rep.get('reputation', '?')}"]
            if rep.get("credentials_leaked"):
                bits.append("credentials leaked")
            if rep.get("data_breach"):
                bits.append("in data breach")
            if rep.get("suspicious"):
                bits.append("suspicious")
            rows.append(("", Text("")))
            rows.append(("emailrep", Text(" · ".join(bits), style="text")))

        if dossier.registrations:
            rows.append(("", Text("")))
            rows.append(("registered", Text(f"{len(dossier.registrations)} sites", style="accent")))
            rows.append(("", Text(_clip(", ".join(dossier.registrations[:12])), style="muted")))

        return rows

    def _trail_rows(self, dossier):
        pivots = [t for t in dossier.trail if t[3] != "seed"]
        if not pivots:
            return []
        rows = [("", Text("")), ("", Text("── pivot trail ──", style="primary.dim"))]
        for depth, kind, value, via in pivots[:12]:
            arrow = "  " * depth + "↳"
            line = Text(f"{arrow} {value}", style="text")
            line.append(f"  ({kind} via {via})", style="muted")
            rows.append(("", line))
        return rows


    def _signal(self, dossier):
        total = 6
        score = 0
        if dossier.names or dossier.profiles:
            score += 1
        if len(dossier.profiles) >= 3:
            score += 1
        if len(dossier.names) >= 1 and len(dossier.sources) >= 3:
            score += 1
        if dossier.faces:
            score += 1
        bridged = (
            (dossier.kind == "username" and any(e != dossier.seed for e in dossier.emails))
            or (dossier.kind == "email" and len(dossier.usernames) >= 1)
        )
        if bridged:
            score += 1
        if dossier.breaches or dossier.stealers or dossier.reputation.get("credentials_leaked"):
            score += 1
        score = max(0, min(total, score))

        label, style = {
            0: ("no signal", "muted"),
            1: ("faint", "muted"),
            2: ("low", "warn"),
            3: ("moderate", "warn"),
            4: ("strong", "accent"),
            5: ("high", "accent"),
            6: ("full identity", "error"),
        }[score]
        return score, label, style, total

    def _risk_label(self, metrics):
        risk = metrics.get("risk") if metrics else None
        if isinstance(risk, list) and risk and isinstance(risk[0], dict):
            label = risk[0].get("risk_label")
            score = risk[0].get("risk_score")
            if label:
                return f"{label} ({score}/100)" if score is not None else str(label)
        return None


def _push(payload, key, value):
    if isinstance(value, str):
        value = value.strip()
    if value:
        payload.setdefault(key, []).append(value)


def _clean_handle(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lstrip("@").strip()
    return value if _HANDLE_RE.match(value) else None


def _deobfuscate(masked):
    masked = (masked or "").strip()
    if "*" in masked or not _EMAIL_RE.match(masked):
        return None
    return masked.lower()


def _normalize_url(url):
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _first_photo(items):
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("value"):
                return str(item["value"])
    return None


def _stealer_value(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip())
    return str(value)


def _meter(score, total=6):
    return "".join("●" if i < score else "○" for i in range(total))


def _clip(value, limit=110):
    if not value:
        return "-"
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1] + "…"
