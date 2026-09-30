import asyncio
import base64
from pathlib import Path
from typing import Any

from ...utils.logger import logger


DEVICE_SCALE_FACTORS = {
    "normal": 1.0,
    "high": 1.3,
    "ultra": 1.8,
}


class LocalBrowserRenderer:
    """Render report HTML to an image with a local Playwright browser."""

    IDLE_TIMEOUT = 120
    """Seconds without renders before Chromium exits to free memory."""

    def __init__(self, config_manager: Any, data_dir: str | Path):
        self.config_manager = config_manager
        self.data_dir = Path(data_dir)
        self._playwright = None
        self._browser = None
        self._launch_lock = asyncio.Lock()
        self._active = 0
        self._idle_task: asyncio.Task | None = None

    async def render(
        self,
        html_content: str,
        data: dict | None = None,
        return_url: bool = False,
        image_options: dict | None = None,
    ) -> bytes | str:
        self._active += 1
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None
        try:
            return await self._render(html_content, return_url, image_options)
        finally:
            self._active -= 1
            if not self._active and self._browser:
                self._idle_task = asyncio.create_task(self._close_when_idle())

    async def _render(
        self, html_content: str, return_url: bool, image_options: dict | None
    ) -> bytes | str:
        if not html_content:
            raise ValueError("local browser render received empty HTML")

        options = dict(image_options or {})
        timeout_ms = self._get_timeout_ms(options)
        image_type = self._get_image_type(options)

        browser = await self._ensure_browser(timeout_ms)
        context = None
        page = None

        try:
            context = await browser.new_context(
                viewport={
                    "width": self.config_manager.get_local_browser_viewport_width(),
                    "height": self.config_manager.get_local_browser_viewport_height(),
                },
                device_scale_factor=self._get_device_scale_factor(options),
                ignore_https_errors=True,
                bypass_csp=True,
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)

            await page.set_content(
                html_content,
                wait_until=self.config_manager.get_local_browser_wait_until(),
                timeout=timeout_ms,
            )
            await self._wait_for_fonts(page, timeout_ms)
            await self._wait_extra(page)

            screenshot_options: dict[str, Any] = {
                "type": image_type,
                "full_page": bool(options.get("full_page", True)),
                "timeout": timeout_ms,
                "animations": "disabled",
            }
            if image_type == "jpeg":
                screenshot_options["quality"] = self._get_quality(options)

            image_bytes = await page.screenshot(**screenshot_options)
            logger.info(
                f"[LocalBrowserT2I] Rendered {image_type.upper()} image locally "
                f"({len(image_bytes)} bytes)"
            )

            if return_url:
                encoded = base64.b64encode(image_bytes).decode("ascii")
                return f"base64://{encoded}"
            return image_bytes
        finally:
            if page:
                await page.close()
            if context:
                await context.close()

    async def _close_when_idle(self):
        await asyncio.sleep(self.IDLE_TIMEOUT)
        async with self._launch_lock:
            if self._active:
                return
            # Once shutdown starts, new renders wait for the lock and relaunch.
            self._idle_task = None
            await self._shutdown()
        logger.info("[LocalBrowserT2I] Chromium closed after being idle")

    async def close(self):
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None
        async with self._launch_lock:
            await self._shutdown()

    async def _shutdown(self):
        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._playwright = None

        if browser:
            try:
                await browser.close()
            except Exception as e:
                logger.debug(f"[LocalBrowserT2I] Browser close failed: {e}")
        if playwright:
            try:
                await playwright.stop()
            except Exception as e:
                logger.debug(f"[LocalBrowserT2I] Playwright stop failed: {e}")

    async def _ensure_browser(self, timeout_ms: int):
        async with self._launch_lock:
            if self._browser and self._browser.is_connected():
                return self._browser

            try:
                from playwright.async_api import async_playwright
            except Exception as e:
                raise RuntimeError(
                    "Playwright is not available. Install playwright and the "
                    "Chromium browser, or switch t2i_render_backend back to astrbot."
                ) from e

            if self._playwright is None:
                self._playwright = await async_playwright().start()

            launch_args = ["--disable-dev-shm-usage"]
            if self.config_manager.get_local_browser_no_sandbox():
                launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox"])

            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
                timeout=timeout_ms,
            )
            logger.info("[LocalBrowserT2I] Chromium launched for local rendering")
            return self._browser

    async def _wait_for_fonts(self, page: Any, timeout_ms: int):
        try:
            await asyncio.wait_for(
                page.evaluate(
                    "() => document.fonts ? document.fonts.ready : Promise.resolve()"
                ),
                timeout=max(1, timeout_ms / 1000),
            )
        except Exception as e:
            logger.debug(f"[LocalBrowserT2I] Font readiness wait skipped: {e}")

    async def _wait_extra(self, page: Any):
        wait_ms = self.config_manager.get_local_browser_extra_wait_ms()
        if wait_ms > 0:
            await page.wait_for_timeout(wait_ms)

    @staticmethod
    def _get_timeout_ms(options: dict) -> int:
        try:
            return max(1000, int(options.get("timeout", 60000)))
        except Exception:
            return 60000

    @staticmethod
    def _get_image_type(options: dict) -> str:
        image_type = str(options.get("type", "png")).lower()
        return "jpeg" if image_type in ("jpg", "jpeg") else "png"

    @staticmethod
    def _get_quality(options: dict) -> int:
        try:
            return min(100, max(1, int(options.get("quality", 80))))
        except Exception:
            return 80

    @staticmethod
    def _get_device_scale_factor(options: dict) -> float:
        level = str(options.get("device_scale_factor_level", "normal")).lower()
        return DEVICE_SCALE_FACTORS.get(level, 1.0)
