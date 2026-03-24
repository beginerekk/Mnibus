import asyncio
from playwright.async_api import async_playwright

target_url = input("Podaj adres z royalcams: ")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--mute-audio",
                "--window-position=-10000,-10000",  # przesuń okno poza ekran
                "--window-size=1280,720",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            extra_http_headers={
                "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

        await context.grant_permissions(["camera", "microphone"])
        page = await context.new_page()
        found = set()

        def on_request(req):
            url = req.url
            if "bcvcdn.com" in url and "chunks.m3u8" in url and url not in found and not ".ts" in url:
                found.add(url)
                print(url)

        page.on("request", on_request)

        try:
            await page.goto(target_url, wait_until="commit")
        except Exception:
            pass

        for _ in range(30):
            await asyncio.sleep(1)
            if found:
                break

        await browser.close()

asyncio.run(main())