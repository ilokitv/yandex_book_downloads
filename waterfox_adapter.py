"""Small Playwright-shaped adapter for the user's Waterfox window via Selenium."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

PORT = 2828
WATERFOX_HOME = Path(__file__).resolve().parent.parent / "waterfox-selenium-chatgpt" / "scripts"

class WaterfoxElement:
    def __init__(self, driver, element):
        self.driver, self.element = driver, element

    async def is_visible(self):
        try:
            return self.element.is_displayed()
        except Exception:
            return False

    async def is_enabled(self):
        return self.element.is_enabled()

    async def get_attribute(self, name):
        return self.element.get_attribute(name)

    async def inner_text(self):
        return self.element.text

    async def click(self, force=False, timeout=2000):
        if force:
            self.driver.execute_script("arguments[0].click()", self.element)
        else:
            self.element.click()

    async def scroll_into_view_if_needed(self):
        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'})", self.element)


class WaterfoxLocator:
    def __init__(self, driver, selector, index=0):
        self.driver, self.selector, self.index = driver, selector, index

    @property
    def first(self):
        return WaterfoxLocator(self.driver, self.selector, 0)

    def _elements(self):
        return self.driver.find_elements("css selector", self.selector)

    async def count(self):
        return len(self._elements())

    async def is_visible(self):
        items = self._elements()
        return self.index < len(items) and items[self.index].is_displayed()

    async def click(self, force=False, timeout=2000):
        items = self._elements()
        if self.index >= len(items):
            raise LookupError(f"Элемент не найден: {self.selector}")
        await WaterfoxElement(self.driver, items[self.index]).click(force=force, timeout=timeout)

    async def bounding_box(self):
        items = self._elements()
        if self.index >= len(items):
            return None
        rect = self.driver.execute_script(
            "const r=arguments[0].getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}",
            items[self.index],
        )
        return rect


class WaterfoxMouse:
    def __init__(self, driver):
        self.driver = driver
        self.x = self.y = 0

    def _move(self, x, y, steps=1):
        from selenium.webdriver import ActionChains
        x, y = int(x), int(y)
        dx, dy = x - self.x, y - self.y
        chain = ActionChains(self.driver)
        if steps > 1:
            for i in range(1, steps + 1):
                chain.move_by_offset(round(dx / steps), round(dy / steps))
        else:
            chain.move_by_offset(dx, dy)
        chain.perform()
        self.x, self.y = x, y

    async def move(self, x, y, steps=1):
        self._move(x, y, steps)

    async def click(self, x, y):
        from selenium.webdriver import ActionChains
        self._move(x, y)
        ActionChains(self.driver).click().perform()

    async def down(self):
        from selenium.webdriver import ActionChains
        from selenium.webdriver.common.actions import interaction
        ActionChains(self.driver).click_and_hold().perform()

    async def up(self):
        from selenium.webdriver import ActionChains
        ActionChains(self.driver).release().perform()


class WaterfoxPage:
    def __init__(self, driver):
        self.driver = driver
        self.keyboard = self
        self.mouse = WaterfoxMouse(driver)

    @property
    def url(self):
        return self.driver.current_url

    @property
    def viewport_size(self):
        return self.driver.execute_script("return {width:innerWidth,height:innerHeight}")

    def is_closed(self):
        try:
            return not self.driver.window_handles
        except Exception:
            return True

    async def goto(self, url, wait_until="load", timeout=30000):
        self.driver.set_page_load_timeout(timeout / 1000)
        self.driver.get(url)

    async def content(self):
        return self.driver.page_source

    async def evaluate(self, script):
        script = script.strip()
        # The existing downloader supplies zero-argument JavaScript arrow functions.
        return self.driver.execute_script(f"return ({script})();")

    async def query_selector(self, selector):
        from selenium.common.exceptions import NoSuchElementException
        try:
            return WaterfoxElement(self.driver, self.driver.find_element("css selector", selector))
        except NoSuchElementException:
            return None

    async def query_selector_all(self, selector):
        return [WaterfoxElement(self.driver, el) for el in self.driver.find_elements("css selector", selector)]

    def locator(self, selector):
        return WaterfoxLocator(self.driver, selector)

    async def wait_for_load_state(self, state="load", timeout=30000):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            ready = self.driver.execute_script("return document.readyState")
            if ready in ("interactive", "complete"):
                return
            time.sleep(0.1)
        raise TimeoutError(f"Waterfox не дождался состояния {state}")

    async def emulate_media(self, media="screen"):
        # The PDF is made from the visible reader view, so screen media is retained.
        return None

    async def screenshot_signature(self):
        return hashlib.sha256(self.driver.get_screenshot_as_png()).hexdigest()

    async def press(self, key):
        from selenium.webdriver.common.keys import Keys
        value = {"Escape": Keys.ESCAPE, "Enter": Keys.ENTER, "ArrowRight": Keys.ARROW_RIGHT}.get(key, key)
        from selenium.webdriver import ActionChains
        ActionChains(self.driver).send_keys(value).perform()



class WaterfoxContext:
    def __init__(self, driver):
        self.driver = driver
        self.page = WaterfoxPage(driver)
        self.pages = [self.page]

    async def new_page(self):
        return self.page

    async def cookies(self):
        return self.driver.get_cookies()

    async def storage_state(self, path):
        # The Waterfox profile itself persists login; do not export its cookies.
        Path(path).write_text(json.dumps({"waterfox_profile_persists_login": True}), encoding="utf-8")

    async def close(self):
        return None


class WaterfoxBrowser:
    def __init__(self, driver):
        self.driver = driver

    async def new_context(self, **kwargs):
        return WaterfoxContext(self.driver)

    async def close(self):
        return None


class WaterfoxConnector:
    """Attach Selenium to the user's regular Waterfox profile through Marionette."""
    def __init__(self):
        self.driver = None
        self.service = None

    async def start(self):
        if os.name != "nt":
            raise RuntimeError(
                "Запускайте Waterfox-версию из Windows PowerShell: py -3.12 download_book.py ..."
            )
        launcher = WATERFOX_HOME / "start_waterfox_marionette.ps1"
        if not launcher.is_file():
            raise FileNotFoundError(f"Не найден запускатель Waterfox: {launcher}")
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(launcher), "-Restart", "-Port", str(PORT)],
            check=True,
            timeout=45,
        )
        from selenium import webdriver
        from selenium.webdriver.firefox.options import Options
        from selenium.webdriver.firefox.service import Service
        self.service = Service(service_args=["--connect-existing", "--marionette-port", str(PORT)])
        try:
            self.driver = await asyncio.wait_for(
                asyncio.to_thread(webdriver.Firefox, service=self.service, options=Options()),
                timeout=45,
            )
        except asyncio.TimeoutError as exc:
            self.service.stop()
            raise TimeoutError("Waterfox не ответил на подключение Marionette за 45 секунд.") from exc
        self.driver.set_page_load_timeout(45)
        self.driver.set_script_timeout(20)
        return self

    async def stop(self):
        # Detach Selenium without closing the user's Waterfox profile.
        if self.service:
            try:
                self.service.stop()
            except Exception:
                pass
