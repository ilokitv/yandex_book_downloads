# Скачивание книг с books.yandex.ru

Скрипт сохраняет текст страниц Яндекс Книг в Markdown (`.md`) и скачивает изображения из текста рядом с файлом. Текст читается из `.section1.content-container`, а страницы перелистываются клавишей →.

## Установка для Waterfox (Windows)

1. Установите Python 3.12 и Waterfox.
2. Положите папки `yandex_book_downloads` и `waterfox-selenium-chatgpt` рядом на Рабочем столе.
3. В PowerShell откройте папку `yandex_book_downloads` и установите зависимости:

```powershell
py -3.12 -m pip install -r requirements.txt
```

Скрипт подключается к обычному профилю Waterfox и использует сохранённую в нём авторизацию.

## Скачивание одной книги

```powershell
py -3.12 download_book.py <URL_книги> [имя_файла.md]
```

Например:

```powershell
py -3.12 download_book.py https://books.yandex.ru/books/L1M4BIWv
```

Результат появится в `downloads/book_L1M4BIWv.md`. Иллюстрации будут лежать в `downloads/images/` и будут вставлены в Markdown относительными ссылками. Файл можно открыть в редакторе и позже конвертировать в FB2 или другой формат.

## Пакетное скачивание по Excel

```powershell
py -3.12 batch_download_books.py books.xlsx
```

Колонки без заголовков: A — номер, B — ссылка, C — название, D — автор (необязательно). Для каждой книги создаётся папка в `downloads/` с Markdown-файлом и изображениями.

## Требования

- Windows, Python 3.12 и Waterfox
- папка `waterfox-selenium-chatgpt` рядом с репозиторием
- Selenium и GeckoDriver (Selenium подберёт драйвер при запуске)
