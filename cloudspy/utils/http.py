import requests

DEFAULT_TIMEOUT = 12
API_AGENT = "cloudspy/0.1"
BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def session(agent=API_AGENT):
    client = requests.Session()
    client.headers.update({"User-Agent": agent})
    return client


def get(url, client=None, **kwargs):
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    caller = client or session()
    return caller.get(url, **kwargs)
