from aiogram import Router

from app.bot.handlers import digest, history, interests, menu, schedule, settings, sources, start


def setup_routers() -> Router:
    router = Router()
    router.include_router(start.router)
    router.include_router(menu.router)
    router.include_router(digest.router)
    router.include_router(interests.router)
    router.include_router(sources.router)
    router.include_router(history.router)
    router.include_router(schedule.router)
    router.include_router(settings.router)
    return router

