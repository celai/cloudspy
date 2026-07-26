import contextlib
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _here]


async def _launch(module, phone, country_code, client, out):
    try:
        await module(phone, country_code, client, out)
    except Exception:
        pass


async def _run(phone, country_code, timeout, out):
    import httpx
    import trio
    from ignorant.core import get_functions, import_submodules

    modules = import_submodules("ignorant.modules")
    websites = get_functions(modules)
    client = httpx.AsyncClient(timeout=timeout)
    try:
        async with trio.open_nursery() as nursery:
            for website in websites:
                nursery.start_soon(_launch, website, phone, country_code, client, out)
    finally:
        await client.aclose()


def main(argv):
    if len(argv) < 3:
        json.dump([], sys.stdout)
        return 1

    country_code = argv[1]
    phone = argv[2]
    try:
        timeout = float(argv[3]) if len(argv) > 3 else 10.0
    except ValueError:
        timeout = 10.0

    import trio

    out = []
    real_stdout = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        trio.run(_run, phone, country_code, timeout, out)

    records = [
        {
            "name": item.get("name"),
            "domain": item.get("domain"),
            "exists": bool(item.get("exists")),
            "rateLimit": bool(item.get("rateLimit")),
        }
        for item in out
    ]
    json.dump(records, real_stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
