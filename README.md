# Telegram-бот персональных новостных дайджестов

Учебный MVP Telegram-бота, который собирает RSS-новости, фильтрует их по интересам или выбранным источникам и сохраняет историю дайджестов.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Если виртуальное окружение уже есть, достаточно активировать его и проверить зависимости:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Настройки окружения

Создайте `.env` по примеру `.env.example`:

```env
BOT_TOKEN=
BOT_USE_PROXY=false
BOT_PROXY_URL=
GIGACHAT_CREDENTIALS=
DATABASE_URL=sqlite+aiosqlite:///./bot.db
ADMIN_ID=
LOG_LEVEL=INFO
```

`BOT_TOKEN` обязателен. Если `GIGACHAT_CREDENTIALS` не заполнен, бот использует безопасную заглушку и формирует дайджест из RSS-заголовков.

## Запуск через прокси

По умолчанию бот запускается без прокси. Если polling работает на сервере нестабильно из-за доступа к Telegram Bot API, включите прокси в `.env`:

```env
BOT_USE_PROXY=true
BOT_PROXY_URL=socks5://login:password@host:port
```

Поддерживаются варианты:

```env
BOT_PROXY_URL=socks5://host:port
BOT_PROXY_URL=socks5://login:password@host:port
BOT_PROXY_URL=http://host:port
BOT_PROXY_URL=http://login:password@host:port
```

Если `BOT_USE_PROXY=false` или `BOT_PROXY_URL` пустой, бот запускается как раньше. В логах пароль не показывается: например, `Bot started with proxy: socks5://***`.

## Локальный запуск

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.bot.main
```

При первом запуске создается SQLite-база и добавляются тестовые RSS-источники.

## Запуск через watchdog на VPS

```bash
source .venv/bin/activate
python watchdog.py
```

`watchdog.py` запускает `python -m app.bot.main`, пишет события в `logs/watchdog.log`, перезапускает бота после падения и увеличивает задержку между частыми рестартами.

## Возможности

- персональные дайджесты по интересам;
- дайджесты по выбранным RSS-источникам;
- редактирование интересов;
- выбор и просмотр подписок на источники;
- автоматическая история всех сформированных дайджестов;
- избранное для важных дайджестов;
- оценки `Полезно` / `Не подходит`;
- проверка новых новостей с лимитом 2 попытки на свежий дайджест;
- расписание: утро, вечер или еженедельно по понедельникам;
- выбор часового пояса через город России и UTC-смещение;
- настройка тихих плановых уведомлений.

## Основные файлы

- `app/bot/main.py` — запуск бота.
- `app/bot/handlers/` — пользовательская логика и callback-кнопки.
- `app/bot/keyboards/` — inline-клавиатуры.
- `app/core/rss.py` — чтение RSS.
- `app/core/digest.py` — сборка и обновление дайджеста.
- `app/core/gigachat_client.py` — место подключения GigaChat и fallback-заглушка.
- `app/core/scheduler.py` — APScheduler для плановых рассылок.
- `app/db/` — SQLite-модели и запросы.
- `watchdog.py` — перезапуск бота на VPS.
