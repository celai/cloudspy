import asyncio
import contextlib
import json
import re
import sys

_FLAGS = re.compile(r"[\U0001F1E6-\U0001F1FF]")
_SOURCE = "https://omar-thing.site/"


def _clean(text, prefix=None):
    if prefix and text.startswith(prefix):
        text = text[len(prefix):]
    return _FLAGS.sub("", text).strip()


def _run(coro):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(coro)


async def _dismiss_consent(page):
    for selector in (
        ".fc-cta-consent",
        "button.fc-cta-consent",
        ".fc-consent-root .fc-button",
    ):
        try:
            await page.click(selector, timeout=2000)
            break
        except Exception:
            continue

    with contextlib.suppress(Exception):
        await page.evaluate(
            """() => {
                document
                    .querySelectorAll('.fc-consent-root, .fc-dialog-overlay')
                    .forEach((el) => el.remove());
            }"""
        )


async def _lookup(username):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            page = await context.new_page()
            await page.goto(_SOURCE, wait_until="networkidle")

            await page.wait_for_selector("#usernameInput", timeout=10000)
            await _dismiss_consent(page)
            await page.fill("#usernameInput", username)
            try:
                await page.click("#fetchButton", timeout=8000)
            except Exception:
                await _dismiss_consent(page)
                await page.eval_on_selector("#fetchButton", "(el) => el.click()")

            try:
                await page.wait_for_selector("#resultsContent", timeout=15000)
            except Exception:
                try:
                    error = await page.inner_text("#errorText", timeout=2000)
                    return {"error": error.strip()}
                except Exception:
                    return None

            try:
                await page.wait_for_function(
                    """(selector) => {
                        const el = document.querySelector(selector);
                        if (!el) return false;
                        const text = el.innerText.trim();
                        return text && text !== '...' && text !== 'Region: ...';
                    }""",
                    arg="#resultRegion",
                    timeout=10000,
                )
            except Exception:
                pass

            async def field(selector):
                try:
                    return (await page.inner_text(selector, timeout=1000)).strip()
                except Exception:
                    return ""

            region = _clean(await field("#resultRegion"), "Region:")
            locked = _clean(await field("#resultLockedRegionText"), "Locked Region:")
            if not region or region == "...":
                region = locked

            return {
                "nickname": await field("#resultNickname"),
                "username": await field("#resultUsername"),
                "user_id": await field("#resultUserId"),
                "language": await field("#resultLanguage"),
                "region": region,
                "locked_region": locked,
            }
        finally:
            await browser.close()


def main(argv):
    if len(argv) < 2 or not argv[1].strip():
        json.dump(None, sys.stdout)
        return 1

    real_stdout = sys.stdout
    try:
        with contextlib.redirect_stdout(sys.stderr):
            data = _run(_lookup(argv[1].strip()))
    except Exception as exc:
        json.dump({"error": f"engine failure: {exc}"}, real_stdout)
        return 0

    json.dump(data, real_stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
