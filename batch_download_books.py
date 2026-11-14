import asyncio
import sys
import re
from pathlib import Path
import pandas as pd
from download_book import YandexBookDownloader

def append_completed_record(base_dir: Path, number: str, title: str):
    try:
        md_path = base_dir / 'COMPLETED.md'
        if not md_path.exists():
            md_path.write_text('# Скачанные книги\n\n- Номер — Название\n\n', encoding='utf-8')
        line = f"- {number} — {title or '-'}\n"
        with md_path.open('a', encoding='utf-8') as f:
            f.write(line)
    except Exception:
        pass

def sanitize_filename(name: str) -> str:
    if not name:
        return 'book'
    name = re.sub('[<>:"/\\\\\\\\|?*]', '_', name)
    name = ''.join((ch for ch in name if ch.isprintable())).strip()
    if len(name) > 150:
        name = name[:150].rstrip()
    return name or 'book'

async def download_from_excel(excel_path: str):
    excel_path = Path(excel_path)
    if not excel_path.exists():
        print(f'Файл Excel не найден: {excel_path}')
        sys.exit(1)
    print(f'Читаю Excel: {excel_path}')
    df = pd.read_excel(excel_path, sheet_name=0, header=None)
    if df.shape[1] < 2:
        print('В Excel нет данных в нужном формате (нужны как минимум 2 колонки: номер и ссылка).')
        sys.exit(1)
    base_output_dir = Path('downloads')
    base_output_dir.mkdir(exist_ok=True)
    downloader = YandexBookDownloader(output_dir=str(base_output_dir))
    try:
        print('Запуск браузера для пакетной загрузки...')
        await downloader.init_browser(headless=False)
        print('Открываю https://books.yandex.ru/ для авторизации...')
        try:
            await downloader.page.goto('https://books.yandex.ru/', wait_until='domcontentloaded', timeout=15000)
            try:
                await downloader.page.wait_for_load_state('networkidle', timeout=5000)
            except Exception:
                pass
        except Exception:
            print('Страница долго открывается или зависла.')
            input('Откройте books.yandex.ru в этом же окне браузера вручную и нажмите Enter для продолжения...')
        is_auth = await downloader.check_auth()
        if is_auth:
            print('✓ Уже авторизованы (используется сохраненная сессия).')
        else:
            print('\n=== Авторизация в Яндексе ===')
            print('1) Перейдите в открывшийся браузер и авторизуйтесь в Яндексе (Yandex ID).')
            print('2) Убедитесь, что вы залогинены (виден ваш профиль / аватар).')
            input('3) После авторизации нажмите Enter в этом окне, чтобы продолжить загрузку книг...')
            await downloader.save_session_state()
        total = len(df)
        print(f'Найдено строк: {total}')
        for idx, row in df.iterrows():
            num_raw = row.iloc[0]
            num_str = ''
            if not pd.isna(num_raw):
                num_str = str(num_raw).strip()
            if not num_str:
                num_str = str(idx + 1)
            folder_name = sanitize_filename(num_str)
            book_folder = base_output_dir / folder_name
            book_folder.mkdir(parents=True, exist_ok=True)
            downloader.output_dir = book_folder
            url = str(row.iloc[1]).strip() if df.shape[1] > 1 and (not pd.isna(row.iloc[1])) else ''
            title = str(row.iloc[2]).strip() if df.shape[1] > 2 and (not pd.isna(row.iloc[2])) else ''
            author = str(row.iloc[3]).strip() if df.shape[1] > 3 and (not pd.isna(row.iloc[3])) else ''
            if not url or not url.startswith('http'):
                print(f'[{idx + 1}/{total}] Пропуск строки — нет корректной ссылки: {url!r}')
                continue
            safe_title = sanitize_filename(title)
            safe_author = sanitize_filename(author)
            if safe_author and safe_title:
                filename = f'{safe_author} - {safe_title}.md'
            elif safe_title:
                filename = f'{safe_title}.md'
            else:
                filename = None
            print(f'\n[{idx + 1}/{total}] Скачиваю книгу:')
            print(f'  Папка : {book_folder}')
            print(f'  URL   : {url}')
            print(f"  Назв. : {title or '-'}")
            print(f"  Автор : {author or '-'}")
            if filename:
                print(f'  Файл  : {filename}')
            try:
                await downloader.download_book(book_url=url, output_filename=filename, skip_auth=True)
                append_completed_record(base_output_dir, folder_name, title)
            except Exception as e:
                print(f'  ⚠ Ошибка при скачивании этой книги: {e}')
                continue
            await asyncio.sleep(2)
        print('\nПакетная загрузка завершена.')
    finally:
        await downloader.close_browser()

async def main():
    if len(sys.argv) < 2:
        print('Использование: python batch_download_books.py <путь_к_файлу_Excel>')
        print('Пример: python batch_download_books.py books.xlsx')
        sys.exit(1)
    excel_path = sys.argv[1]
    await download_from_excel(excel_path)
if __name__ == '__main__':
    asyncio.run(main())
