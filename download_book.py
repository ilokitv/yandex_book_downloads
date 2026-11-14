import asyncio
import os
import sys
from pathlib import Path
from waterfox_adapter import WaterfoxConnector, WaterfoxBrowser, WaterfoxPage
from urllib.parse import urlparse, parse_qs
from urllib.request import urlretrieve
import time
from pypdf import PdfWriter, PdfReader

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

class YandexBookDownloader:

    def __init__(self, output_dir: str='downloads', session_state_file: str='session_state.json'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session_state_file = Path(session_state_file)
        self.browser: WaterfoxBrowser = None
        self.page: WaterfoxPage = None
        self.playwright = None
        self.context = None
        self.waterfox = None

    async def init_browser(self, headless: bool=False):
        self.waterfox = await WaterfoxConnector().start()
        self.playwright = self.waterfox
        self.browser = WaterfoxBrowser(self.waterfox.driver)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        print('✓ Подключен Waterfox с вашим обычным профилем.')

    async def save_session_state(self):
        print('✓ Авторизация уже сохранена в профиле Waterfox.')

    async def close_browser(self):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.waterfox:
                await self.waterfox.stop()
        except Exception:
            pass

    async def ensure_active_page(self):
        try:
            if self.page and (not self.page.is_closed()):
                return
        except Exception:
            pass
        try:
            if self.context:
                pages = self.context.pages
                for p in reversed(pages):
                    try:
                        if not p.is_closed():
                            self.page = p
                            return
                    except Exception:
                        continue
                self.page = await self.context.new_page()
        except Exception:
            self.page = None

    async def check_auth(self) -> bool:
        try:
            await self.ensure_active_page()
            if not self.page:
                return False
            cookies = await self.context.cookies()
            session_cookies = ['Session_id', 'sessionid2', 'yandex_login']
            has_session = False
            for cookie in cookies:
                cookie_name = cookie.get('name', '').lower()
                cookie_value = cookie.get('value', '')
                if 'session_id' in cookie_name or 'sessionid' in cookie_name:
                    if cookie_value and len(cookie_value) > 20:
                        has_session = True
                        break
                if 'yandex_login' in cookie_name or 'login' in cookie_name:
                    if cookie_value and len(cookie_value) > 0:
                        has_session = True
                        break
            if not has_session:
                return False
            login_buttons = await self.page.query_selector_all('a, button, [role="button"]')
            for btn in login_buttons:
                try:
                    text = await btn.inner_text()
                    href = await btn.get_attribute('href')
                    if text and ('войти' in text.lower() or 'вход' in text.lower() or 'login' in text.lower()):
                        if href and ('passport' in href or 'auth' in href):
                            return False
                except Exception:
                    continue
            return True
        except Exception:
            return False

    async def wait_for_auth(self, timeout: int=300):
        print('Проверка авторизации...')
        await asyncio.sleep(1.5)
        if await self.check_auth():
            print('✓ Вы уже авторизованы')
            return True
        print('⚠ Требуется авторизация')
        print('Пожалуйста, авторизуйтесь в открывшемся окне Waterfox.')
        print('После авторизации скрипт продолжит работу автоматически...')
        print('(Ожидание до 5 минут...)')
        start_time = time.time()
        check_count = 0
        while time.time() - start_time < timeout:
            try:
                await asyncio.sleep(1.5)
                check_count += 1
                if await self.check_auth():
                    await asyncio.sleep(0.5)
                    if await self.check_auth():
                        print('✓ Авторизация успешна!')
                        await asyncio.sleep(1)
                        return True
                if check_count % 10 == 0:
                    elapsed = int(time.time() - start_time)
                    print(f'Ожидание авторизации... ({elapsed} сек)')
            except Exception as e:
                await asyncio.sleep(1.5)
        print('⚠ Таймаут ожидания авторизации')
        return False

    async def wait_for_captcha(self, timeout: int=60):
        print('Ожидание прохождения капчи...')
        print('Пожалуйста, пройдите капчу в открывшемся браузере.')
        captcha_selectors = ['iframe[src*="captcha"]', '.captcha', '[data-captcha]', 'iframe[title*="captcha" i]', 'iframe[title*="капча" i]']
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                captcha_found = False
                for selector in captcha_selectors:
                    if await self.page.query_selector(selector):
                        captcha_found = True
                        break
                if not captcha_found:
                    book_content = await self.page.query_selector('.book-content, .reader, [class*="book"], [class*="reader"]')
                    if book_content:
                        print('Капча пройдена, загружается книга...')
                        await asyncio.sleep(2)
                        return True
                await asyncio.sleep(1)
            except Exception as e:
                await asyncio.sleep(1)
        return False

    async def extract_book_id(self, url: str) -> str:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        if len(path_parts) >= 2 and path_parts[0] == 'books':
            return path_parts[1]
        return None

    async def save_cover_image(self):
        try:
            await self.ensure_active_page()
            if not self.page:
                return
            cover_url = await self.page.evaluate('\n                () => {\n                    const selectors = [\n                        \'[data-test-id="COVER"] img\',\n                        \'.Cover_container img\',\n                        \'.Cover_image__ZAscW\',\n                        \'img[alt*="Незнайки"]\',\n                        \'img[src*="books-covers"]\'\n                    ];\n                    for (const s of selectors) {\n                        const el = document.querySelector(s);\n                        if (el && el.src) return el.src;\n                    }\n                    return \'\';\n                }\n            ')
            if not cover_url:
                print('Не удалось найти обложку на странице.')
                return
            cover_path = self.output_dir / 'cover.jpg'
            await asyncio.to_thread(urlretrieve, cover_url, str(cover_path))
            print(f'✓ Обложка сохранена: {cover_path}')
        except Exception as e:
            print(f'⚠ Не удалось сохранить обложку: {e}')

    async def find_next_page_button(self):
        next_page_selectors = ['button[data-reader-page-direction="forward"]', 'button[aria-label*="Следующая страница"]', '.Pagination_pagination_forward__AENcl', 'div[class*="Pagination_pagination_forward"]', '[data-e2e="reader.nextPage"]', '[data-testid="reader-next-page"]', 'button[aria-label*="следующ"]', 'button[aria-label*="next" i]', 'button[title*="следующ"]', 'button[title*="next" i]', '[data-testid*="next"]', '[role="button"][aria-label*="следующ"]', 'a[aria-label*="следующ"]']
        for selector in next_page_selectors:
            try:
                button = await self.page.query_selector(selector)
                if button:
                    is_visible = await button.is_visible()
                    is_disabled = await button.get_attribute('disabled')
                    if is_visible and (not is_disabled):
                        return button
            except Exception:
                continue
        return None

    async def get_page_content_hash(self) -> str:
        try:
            return await self.page.screenshot_signature()
        except Exception:
            return ''

    async def close_app_promo(self):
        try:
            await self.ensure_active_page()
            if not self.page or self.page.is_closed():
                return
            locator_selectors = ['.AppPromoDesktopBanner_cross__AcVH4', '[class*="AppPromoDesktopBanner_cross"]', '[data-e2e="app-promo"] [class*="cross"]', '[data-e2e="app-promo"] [class*="close"]', '[role="dialog"] [class*="cross"]']
            for selector in locator_selectors:
                try:
                    loc = self.page.locator(selector).first
                    if await loc.count() > 0 and await loc.is_visible():
                        await loc.click(force=True, timeout=2000)
                        print(f'Закрыл всплывающее окно приложения/QR через селектор: {selector}')
                        await asyncio.sleep(0.25)
                        return
                except Exception:
                    continue
            closed = await self.page.evaluate('\n                () => {\n                    // 1) Точный селектор из вашего примера\n                    const exactCross = document.querySelector(\'.AppPromoDesktopBanner_cross__AcVH4\');\n                    if (exactCross) {\n                        const clickable =\n                            exactCross.closest(\'button\') ||\n                            exactCross.closest(\'[role="button"]\') ||\n                            exactCross.parentElement ||\n                            exactCross;\n                        clickable.dispatchEvent(new MouseEvent(\'click\', { bubbles: true, cancelable: true }));\n                        return true;\n                    }\n\n                    // 2) Дополнительные fallback-селекторы на случай смены классов\n                    const genericCross = document.querySelector(\'[class*="AppPromoDesktopBanner_cross"]\');\n                    if (genericCross) {\n                        const clickable =\n                            genericCross.closest(\'button\') ||\n                            genericCross.closest(\'[role="button"]\') ||\n                            genericCross.parentElement ||\n                            genericCross;\n                        clickable.dispatchEvent(new MouseEvent(\'click\', { bubbles: true, cancelable: true }));\n                        return true;\n                    }\n\n                    const root = document.querySelector(\'[data-e2e="app-promo"], [class*="promo"], [class*="qr"]\');\n                    if (!root) return false;\n\n                    const closeBtn =\n                        root.querySelector(\'[aria-label*="закрыть" i]\') ||\n                        root.querySelector(\'[aria-label*="close" i]\') ||\n                        root.querySelector(\'[class*="cross"]\') ||\n                        root.querySelector(\'[class*="close"]\') ||\n                        root.querySelector(\'button\') ||\n                        root.querySelector(\'[role="button"]\');\n                    if (closeBtn) {\n                        closeBtn.dispatchEvent(new MouseEvent(\'click\', { bubbles: true, cancelable: true }));\n                        return true;\n                    }\n\n                    return false;\n                }\n            ')
            if closed:
                print('Закрыл всплывающее окно приложения/QR.')
                await asyncio.sleep(0.25)
                try:
                    await self.page.keyboard.press('Escape')
                except Exception:
                    pass
        except Exception:
            pass

    async def wait_for_content_load(self, timeout: int=5):
        try:
            await self.page.wait_for_load_state('networkidle', timeout=timeout * 1000)
        except Exception:
            await asyncio.sleep(1)

    async def hide_reader_ui_for_pdf(self):
        try:
            await self.page.evaluate('\n                () => {\n                    const styleId = \'yb-pdf-hide-ui\';\n                    let style = document.getElementById(styleId);\n                    if (!style) {\n                        style = document.createElement(\'style\');\n                        style.id = styleId;\n                        document.head.appendChild(style);\n                    }\n                    style.textContent = `\n                        /* Верхняя панель ридера и похожие элементы */\n                        [data-e2e="reader.header"],\n                        [data-e2e="header"],\n                        [class*="Header"],\n                        [class*="header"],\n                        [class*="TopBar"],\n                        [class*="toolbar"],\n                        [class*="AppPromo"],\n                        [data-e2e="app-promo"] {\n                            display: none !important;\n                            visibility: hidden !important;\n                            opacity: 0 !important;\n                            pointer-events: none !important;\n                        }\n\n                        /* Нижняя панель прогресса (прячем в PDF) */\n                        .Footer_footer__progress__jR_ru,\n                        [class*="Footer_footer__progress"],\n                        .ProgressBox_progress__r0uiE,\n                        [class*="ProgressBox_progress"],\n                        [data-e2e="progress.slider"] {\n                            display: none !important;\n                            visibility: hidden !important;\n                            opacity: 0 !important;\n                            pointer-events: none !important;\n                        }\n\n                        /* Убираем отступ сверху, который обычно остаётся после скрытия header */\n                        body, html {\n                            margin-top: 0 !important;\n                            padding-top: 0 !important;\n                        }\n                    `;\n                }\n            ')
            await asyncio.sleep(0.2)
        except Exception:
            pass

    async def get_progress_percent(self) -> int:
        try:
            text, slider_info = await self.page.evaluate('\n                () => {\n                    const footer = document.querySelector(\'[data-e2e="footer.progress"]\');\n                    const footerText = footer ? (footer.textContent || footer.innerText || \'\') : \'\';\n                    const slider = document.querySelector(\'[data-e2e="progress.slider"] input[type="range"]\');\n                    let sliderData = null;\n                    if (slider) {\n                        sliderData = {\n                            value: slider.value,\n                            min: slider.min || \'0\',\n                            max: slider.max || \'1000\'\n                        };\n                    }\n                    return [footerText, sliderData];\n                }\n            ')
            if text:
                m = __import__('re').search(r'\d+', text)
                if m:
                    return int(m.group(0))
            if slider_info and isinstance(slider_info, dict):
                try:
                    val = float(slider_info.get('value', '0') or 0.0)
                    mn = float(slider_info.get('min', '0') or 0.0)
                    mx = float(slider_info.get('max', '1000') or 1000.0)
                    if mx > mn:
                        return int(round((val - mn) / (mx - mn) * 100))
                except Exception:
                    return 0
        except Exception:
            return 0
        return 0

    async def move_reader_to_start(self):
        try:
            await self.ensure_active_page()
            if not self.page:
                return
            await asyncio.sleep(1.5)
            for attempt in range(1, 5):
                try:
                    viewport = self.page.viewport_size or {'width': 1920, 'height': 1080}
                    await self.page.mouse.move(int(viewport['width'] * 0.5), int(viewport['height'] * 0.9))
                    await asyncio.sleep(0.2)
                    await self.page.mouse.click(int(viewport['width'] * 0.5), int(viewport['height'] * 0.95))
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
                try:
                    slider_loc = self.page.locator('[data-e2e="progress.slider"]').first
                    if await slider_loc.count() > 0:
                        box = await slider_loc.bounding_box()
                        if box:
                            left_x = box['x'] + 1
                            mid_y = box['y'] + box['height'] / 2
                            await self.page.mouse.click(left_x, mid_y)
                            await asyncio.sleep(0.2)
                            await self.page.mouse.move(left_x + 20, mid_y)
                            await self.page.mouse.down()
                            await self.page.mouse.move(left_x, mid_y, steps=5)
                            await self.page.mouse.up()
                            await asyncio.sleep(0.2)
                except Exception:
                    pass
                result = await self.page.evaluate('\n                    () => {\n                        const slider = document.querySelector(\'[data-e2e="progress.slider"]\');\n                        const rangeInput =\n                            (slider && slider.querySelector(\'input[type="range"]\')) ||\n                            document.querySelector(\'[data-e2e="progress.slider"] input[type="range"]\') ||\n                            document.querySelector(\'.ProgressBox_progress__r0uiE input[type="range"]\') ||\n                            document.querySelector(\'[class*="ProgressBox_progress"] input[type="range"]\') ||\n                            document.querySelector(\'input[type="range"][aria-orientation="horizontal"]\');\n                        if (!rangeInput) return { ok: false, reason: "no-input", now: -1 };\n\n                        const min = Number(rangeInput.min || "0");\n                        const max = Number(rangeInput.max || "1000");\n\n                        rangeInput.focus();\n                        rangeInput.value = String(min);\n                        rangeInput.setAttribute("value", String(min));\n                        rangeInput.setAttribute("aria-valuenow", String(min));\n                        rangeInput.dispatchEvent(new Event(\'input\', { bubbles: true }));\n                        rangeInput.dispatchEvent(new Event(\'change\', { bubbles: true }));\n\n                        const track = (slider && slider.querySelector(\'.MuiSlider-track\')) || document.querySelector(\'.MuiSlider-track\');\n                        if (track) {\n                            track.style.left = \'0%\';\n                            track.style.width = \'0%\';\n                        }\n                        const thumb = (slider && slider.querySelector(\'.MuiSlider-thumb\')) || document.querySelector(\'.MuiSlider-thumb\');\n                        if (thumb) {\n                            thumb.style.left = \'0%\';\n                        }\n\n                        const now = Number(rangeInput.value || "0");\n                        const percent = max > min ? ((now - min) / (max - min)) * 100 : 0;\n                        return { ok: percent <= 1.0, reason: "set", now: percent };\n                    }\n                ')
                now_percent = result.get('now', -1) if isinstance(result, dict) else -1
                if isinstance(result, dict) and result.get('ok'):
                    print(f'Выставил прогресс книги в начало (0%), сейчас ~{now_percent:.2f}%.')
                    await asyncio.sleep(0.5)
                    return
                print(f'Попытка {attempt}/4 выставить прогресс в 0 не сработала (сейчас ~{now_percent:.2f}%).')
                await asyncio.sleep(0.5)
            print('⚠ Не удалось гарантированно выставить прогресс в 0 для этой книги.')
        except Exception:
            pass

    async def turn_page(self) -> tuple[bool, bool]:
        try:
            await self.ensure_active_page()
            if not self.page or self.page.is_closed():
                return (False, False)
            old_hash = await self.get_page_content_hash()
            old_url = self.page.url
            old_progress = await self.get_progress_percent()
            page_changed = False
            await self.page.keyboard.press('ArrowRight')
            for _ in range(20):
                await asyncio.sleep(0.15)
                new_hash = await self.get_page_content_hash()
                new_url = self.page.url
                new_progress = await self.get_progress_percent()
                page_changed = old_hash != new_hash or old_url != new_url or old_progress != new_progress
                if page_changed:
                    break
            if not page_changed:
                print('Клавиша → не изменила страницу или прогресс; останавливаюсь, чтобы не сохранять дубли.')
                return (False, False)
            return (True, page_changed)
        except Exception as e:
            print(f'Ошибка при перелистывании: {e}')
            return (False, False)

    async def check_if_last_page(self) -> bool:
        try:
            button = await self.find_next_page_button()
            if not button:
                return True
            is_disabled = await button.get_attribute('disabled')
            if is_disabled:
                return True
            classes = await button.get_attribute('class')
            if classes and ('disabled' in classes.lower() or 'last' in classes.lower()):
                return True
            return False
        except Exception:
            return False

    async def download_book(self, book_url: str, output_filename: str=None, skip_auth: bool=False):
        try:
            await self.ensure_active_page()
            if not self.page:
                raise RuntimeError('Нет активной вкладки браузера для скачивания.')
            if not skip_auth:
                print('Открываю главную страницу Yandex Books для авторизации...')
                await self.page.goto('https://books.yandex.ru/', wait_until='networkidle', timeout=30000)
                if not await self.wait_for_auth():
                    print('⚠ Не удалось подтвердить авторизацию. Продолжаю попытку скачать книгу...')
            print(f'\nОткрываю страницу книги: {book_url}')
            try:
                await self.page.wait_for_load_state('load', timeout=2500)
            except Exception:
                pass
            await asyncio.sleep(0.5)
            goto_attempts = 3
            last_error = None
            for attempt in range(1, goto_attempts + 1):
                try:
                    print(f'  Переход к книге (попытка {attempt}/{goto_attempts})...')
                    await self.page.goto(book_url, wait_until='domcontentloaded', timeout=30000)
                    try:
                        await self.page.wait_for_load_state('networkidle', timeout=5000)
                    except Exception:
                        pass
                    break
                except Exception as e:
                    last_error = e
                    print(f'  ⚠ Ошибка навигации: {e}')
                    if attempt == goto_attempts:
                        raise
                    await asyncio.sleep(1)
            await self.ensure_active_page()
            if not self.page:
                raise RuntimeError('Вкладка браузера закрыта перед чтением контента.')
            page_content = await self.page.content()
            if 'книга недоступна' in page_content.lower() or 'book unavailable' in page_content.lower():
                print('⚠ Книга недоступна. Возможно, требуется авторизация или подписка.')
                print('Проверьте, что вы авторизованы и имеете доступ к этой книге.')
                await asyncio.sleep(2.5)
            await self.save_cover_image()
            print('Пробую открыть режим чтения (читатель)...')
            open_reader_selectors = ['a[href*="/reader/"]', 'a:has-text("Читать")', 'button:has-text("Читать")', '[data-testid*="read"]', '[class*="read"] a', '[class*="read"] button']
            reader_opened = False
            for selector in open_reader_selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el and await el.is_visible():
                        await el.scroll_into_view_if_needed()
                        await asyncio.sleep(0.25)
                        await el.click()
                        reader_opened = True
                        print(f'  Нашёл элемент для открытия чтения: {selector}')
                        break
                except Exception:
                    continue
            if not reader_opened:
                if '/books/' in book_url and '/reader/' not in book_url:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(book_url)
                        path_parts = parsed.path.strip('/').split('/')
                        if len(path_parts) >= 2 and path_parts[0] == 'books':
                            book_id = path_parts[1]
                            reader_url = f'https://books.yandex.ru/reader/{book_id}?resource=book'
                            print(f'  Пытаюсь открыть ридер по URL: {reader_url}')
                            try:
                                await self.page.goto(reader_url, wait_until='domcontentloaded', timeout=30000)
                                reader_opened = True
                            except Exception as e:
                                print(f'  ⚠ Не удалось открыть ридер по URL: {e}')
                    except Exception:
                        pass
            await asyncio.sleep(1.5)
            try:
                await self.page.emulate_media(media='screen')
            except Exception:
                pass
            await asyncio.sleep(1.5)
            await self.move_reader_to_start()
            if not output_filename:
                book_id = await self.extract_book_id(book_url)
                if book_id:
                    output_filename = f'book_{book_id}.pdf'
                else:
                    output_filename = 'book.pdf'
            output_path = self.output_dir / output_filename
            temp_dir = self.output_dir / 'temp_pages'
            temp_dir.mkdir(exist_ok=True)
            page_files = []
            page_num = 1
            max_pages = 1000
            high_progress_count = 0
            last_progress_value = -1
            print('Начинаю сбор страниц книги...')
            while page_num <= max_pages:
                print(f'\n=== Страница {page_num} ===')
                print(f'Ожидание загрузки страницы {page_num}...')
                await self.wait_for_content_load(timeout=2.5)
                await asyncio.sleep(0.25)
                await self.close_app_promo()
                print(f'Подготовка страницы {page_num} к сохранению...')
                await self.page.evaluate('\n                    () => {\n                        window.scrollBy(0, 120);\n                        window.scrollTo(0, 0);\n                    }\n                ')
                await asyncio.sleep(0.5)
                should_save = True
                try:
                    progress_value_early = await self.get_progress_percent()
                    print(f'Текущий прогресс (до сохранения): {progress_value_early}%')
                    if progress_value_early > 85:
                        if progress_value_early == last_progress_value:
                            high_progress_count += 1
                            should_save = False
                            if high_progress_count >= 4:
                                print(f'Прогресс > 85% и не меняется ({progress_value_early}%) четыре раза подряд. Останавливаюсь на странице {page_num}.')
                                break
                        else:
                            high_progress_count = 1
                    else:
                        high_progress_count = 0
                    last_progress_value = progress_value_early
                except Exception:
                    should_save = True
                await self.hide_reader_ui_for_pdf()
                temp_page_path = temp_dir / f'page_{page_num:04d}.pdf'
                if should_save:
                    print(f'Сохранение страницы {page_num}...')
                try:
                    await self.page.pdf(path=str(temp_page_path), format='A4', landscape=True, scale=0.8, print_background=True, margin={'top': '0cm', 'right': '0cm', 'bottom': '0cm', 'left': '0cm'})
                    if should_save:
                        page_files.append(str(temp_page_path))
                        print(f'✓ Страница {page_num} сохранена')
                except Exception as e:
                    print(f'Ошибка при сохранении страницы {page_num}: {e}')
                print(f'Перелистываю на страницу {page_num + 1}...')
                success, _ = await self.turn_page()
                if not success:
                    print('Не удалось перелистнуть страницу. Считаю, что достигнута последняя страница.')
                    break
                page_num += 1
            print(f'\nОбъединяю {len(page_files)} страниц в один PDF...')
            writer = PdfWriter()
            for page_file in page_files:
                try:
                    if os.path.exists(page_file):
                        reader = PdfReader(page_file)
                        for page in reader.pages:
                            writer.add_page(page)
                except Exception as e:
                    print(f'Ошибка при объединении {page_file}: {e}')
            with open(output_path, 'wb') as output_file:
                writer.write(output_file)
            print('Удаляю временные файлы...')
            for page_file in page_files:
                try:
                    if os.path.exists(page_file):
                        os.remove(page_file)
                except Exception as e:
                    print(f'Не удалось удалить {page_file}: {e}')
            try:
                temp_dir.rmdir()
            except Exception:
                pass
            print(f'✓ Книга успешно скачана: {output_path} ({len(page_files)} страниц)')
            return str(output_path)
        except Exception as e:
            print(f'Ошибка при скачивании книги: {e}')
            raise

async def main():
    if len(sys.argv) < 2:
        print('Использование: py -3.12 download_book.py <URL_книги> [имя_файла.pdf]')
        print('Пример: python download_book.py https://books.yandex.ru/books/rN65jwOm?utm_place=post_slider')
        sys.exit(1)
    book_url = sys.argv[1]
    output_filename = sys.argv[2] if len(sys.argv) > 2 else None
    downloader = YandexBookDownloader()
    try:
        print('Запуск Waterfox...')
        await downloader.init_browser(headless=False)
        await downloader.download_book(book_url, output_filename)
    except KeyboardInterrupt:
        print('\nПрервано пользователем')
    except Exception as e:
        print(f'Произошла ошибка: {e}')
    finally:
        await downloader.close_browser()
if __name__ == '__main__':
    asyncio.run(main())
