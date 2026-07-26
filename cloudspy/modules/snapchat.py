import asyncio
import random
import re
import sys

from playwright.async_api import async_playwright
from rich.text import Text

from .base import Context, Module


def _run(coro):
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(coro)


class SnapchatModule(Module):
    name = "Snapchat"
    slug = "snapchat"
    description = "Retrieve masked email or phone number from Snapchat password reset. (Using a VPN is highly recommended)"
    version = "0.1.0"

    max_related = 12

    def run(self, ctx: Context) -> None:
        target = ctx.ui.ask("snapchat username")
        if not target:
            ctx.ui.notify_error("no username supplied")
            return

        username = target.lstrip("@").strip()
        if not username or " " in username:
            ctx.ui.notify_error("invalid username")
            return

        with ctx.ui.loader(f"resolving snapchat profile for {username}"):
            masked_email, error = _run(self._get_masked_email(username))

        if error:
            ctx.ui.notify_error(error)
            return

        if masked_email:
            ctx.ui.result_panel(f"Snapchat · {username}", self._format_results(masked_email))
        else:
            ctx.ui.notify_info(f"no masked email found for {username}")

    async def _get_masked_email(self, username):
        async with async_playwright() as p:
            browser = await p.firefox.launch(
                headless=True,
                firefox_user_prefs={
                    'dom.webdriver.enabled': False,
                    'useAutomationExtension': False,
                    'general.platform.override': 'Win32',
                    'general.useragent.override': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
                }
            )

            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
                viewport={"width": 1920, "height": 1080},
                locale='en-US',
                timezone_id='America/New_York',
                permissions=['geolocation'],
                color_scheme='light',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            )

            page = await context.new_page()

            await page.goto("https://accounts.snapchat.com/accounts/password_reset_request", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 4))
            await self._move_mouse_randomly(page)
            await page.mouse.wheel(0, random.randint(50, 150))
            await asyncio.sleep(random.uniform(1, 2))

            try:
                await page.click('button:has-text("Accept All")', timeout=5000)
                await asyncio.sleep(random.uniform(1, 2))
            except:
                pass

            await self._move_mouse_randomly(page)

            recover_selectors = [
                'button:has-text("Recover your account")',
                'button:has-text("Recover")',
            ]

            for sel in recover_selectors:
                try:
                    element = await page.query_selector(sel)
                    if element:
                        box = await element.bounding_box()
                        if box:
                            await page.mouse.move(
                                box['x'] + box['width']/2 + random.randint(-5, 5),
                                box['y'] + box['height']/2 + random.randint(-5, 5),
                                steps=random.randint(15, 25)
                            )
                            await asyncio.sleep(random.uniform(0.5, 1))

                    await page.click(sel, timeout=5000)
                    await asyncio.sleep(random.uniform(3, 5))
                    break
                except:
                    continue

            await self._move_mouse_randomly(page)
            await asyncio.sleep(random.uniform(0.5, 1.5))

            input_selectors = [
                'input[id*="username"]',
                'input[name="username"]',
                'input[type="text"]',
            ]

            filled = False
            for sel in input_selectors:
                try:
                    await page.wait_for_selector(sel, state="visible", timeout=10000)

                    element = await page.query_selector(sel)
                    if element:
                        box = await element.bounding_box()
                        if box:
                            await page.mouse.move(
                                box['x'] + box['width']/2,
                                box['y'] + box['height']/2,
                                steps=random.randint(15, 25)
                            )

                    await asyncio.sleep(random.uniform(0.3, 0.8))
                    await page.click(sel)
                    await asyncio.sleep(random.uniform(0.4, 0.9))

                    for char in username:
                        await page.keyboard.type(char)
                        await asyncio.sleep(random.uniform(0.1, 0.25))

                    filled = True
                    await asyncio.sleep(random.uniform(1, 2))
                    break
                except:
                    continue

            if not filled:
                await browser.close()
                return None, "Could not find input"

            await self._move_mouse_randomly(page)
            await asyncio.sleep(random.uniform(0.5, 1))

            submit_selectors = [
                'button[type="submit"]',
                'button:has-text("Next")',
            ]

            for sel in submit_selectors:
                try:
                    element = await page.query_selector(sel)
                    if element:
                        box = await element.bounding_box()
                        if box:
                            await page.mouse.move(
                                box['x'] + box['width']/2 + random.randint(-3, 3),
                                box['y'] + box['height']/2 + random.randint(-3, 3),
                                steps=random.randint(15, 25)
                            )
                            await asyncio.sleep(random.uniform(0.3, 0.7))

                    await page.click(sel)
                    break
                except:
                    continue

            for attempt in range(25):
                await asyncio.sleep(4)
                await self._move_mouse_randomly(page)

                current_url = page.url

                if 'security-question' in current_url.lower() or 'reset' in current_url.lower():
                    break

                if 'captcha' not in current_url.lower() and 'verify' not in current_url.lower():
                    break

            await asyncio.sleep(3)

            body_text = await page.inner_text('body')

            email_match = re.search(r'([a-zA-Z0-9]+\.{2,}[a-zA-Z0-9]*@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', body_text)
            if email_match:
                await browser.close()
                return email_match.group(1), None

            phone_match = re.search(r'(\+\d{1,3}\s?\.{2,}\s?\d{2,4})', body_text)
            if phone_match:
                await browser.close()
                return phone_match.group(1), None

            await browser.close()
            return None, "Not found"

    async def _move_mouse_randomly(self, page):
        try:
            viewport = page.viewport_size
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, viewport['width'] - 100)
                y = random.randint(100, viewport['height'] - 100)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.1, 0.3))
        except:
            pass

    def _format_results(self, masked_email):
        rows = []
        rows.append(("username", Text("snapchat", style="bold accent")))
        rows.append(("masked_email", Text(str(masked_email), style="text")))
        return rows
