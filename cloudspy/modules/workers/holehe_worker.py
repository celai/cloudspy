import contextlib
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]


async def _launch(module, email, client, out):
    try:
        await module(email, client, out)
    except Exception:
        pass


async def _run(email, timeout, out):
    import httpx
    import trio
    from holehe.core import get_functions, import_submodules

    modules = import_submodules("holehe.modules")
    websites = get_functions(modules)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        async with trio.open_nursery() as nursery:
            for website in websites:
                nursery.start_soon(_launch, website, email, client, out)
    finally:
        await client.aclose()


def main(argv):
    if len(argv) < 2:
        json.dump([], sys.stdout)
        return 1

    email = argv[1]
    try:
        timeout = float(argv[2]) if len(argv) > 2 else 10.0
    except ValueError:
        timeout = 10.0

    import trio

    out = []
    real_stdout = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        trio.run(_run, email, timeout, out)

    records = [
        {
            "name": item.get("name"),
            "domain": item.get("domain"),
            "exists": bool(item.get("exists")),
            "rateLimit": bool(item.get("rateLimit")),
            "emailrecovery": item.get("emailrecovery"),
            "phoneNumber": item.get("phoneNumber"),
        }
        for item in out
    ]
    json.dump(records, real_stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
