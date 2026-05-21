import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.bot.handlers import setup_routers
from app.bot.middlewares import UserActivityMiddleware
from app.config import get_settings
from app.core.scheduler import start_scheduler, stop_scheduler
from app.db.database import async_session, init_db
from app.db.queries import seed_sources


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Add it to .env before starting the bot.")

    await init_db()
    async with async_session() as session:
        await seed_sources(session)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()
    dp.message.middleware(UserActivityMiddleware())
    dp.callback_query.middleware(UserActivityMiddleware())
    dp.include_router(setup_routers())
    await start_scheduler(bot)
    try:
        await dp.start_polling(bot)
    finally:
        await stop_scheduler()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
