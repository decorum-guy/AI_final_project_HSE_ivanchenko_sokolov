from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot.keyboards.digest import digest_actions, long_digest_options
from app.core.digest import build_digest
from app.db import queries
from app.db.database import async_session


logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
_bot: Bot | None = None
SAFE_TELEGRAM_LIMIT = 3800
LONG_DIGEST_TEXT = (
    "Дайджест получился слишком объемным для одного сообщения Telegram.\n\n"
    "Можно перегенерировать короткую версию или получить полный файл."
)


async def start_scheduler(bot: Bot) -> None:
    global _bot
    _bot = bot
    scheduler.start()
    async with async_session() as session:
        users = await queries.scheduled_users(session)
    for user in users:
        await _add_or_replace_job(user.telegram_id)
    logger.info("Scheduler started with %s jobs", len(scheduler.get_jobs()))


async def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


async def reschedule_user(telegram_id: int) -> None:
    if scheduler.running:
        await _add_or_replace_job(telegram_id)


async def _add_or_replace_job(telegram_id: int) -> None:
    job_id = f"digest:{telegram_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    async with async_session() as session:
        user = await queries.get_or_create_user(session, telegram_id, None)
        if not (user.schedule_enabled and user.timezone and user.schedule_time and user.schedule_type):
            return
        hour, minute = map(int, user.schedule_time.split(":"))
        trigger_kwargs = {"hour": hour, "minute": minute, "timezone": user.timezone}
        if user.schedule_type == "weekly":
            trigger_kwargs["day_of_week"] = user.schedule_day or "mon"
        scheduler.add_job(
            send_scheduled_digest,
            CronTrigger(**trigger_kwargs),
            id=job_id,
            replace_existing=True,
            args=[telegram_id],
            misfire_grace_time=300,
        )


async def send_scheduled_digest(telegram_id: int) -> None:
    if not _bot:
        return
    async with async_session() as session:
        user = await queries.get_or_create_user(session, telegram_id, None)
        digest = await build_digest(session, user, "interests", "today", force_new=True)
        silent = user.silent_notifications
    try:
        if len(digest.digest_text) > SAFE_TELEGRAM_LIMIT:
            await _bot.send_message(
                telegram_id,
                LONG_DIGEST_TEXT,
                reply_markup=long_digest_options(digest.id, digest.shorten_attempts_left or 2),
                disable_notification=silent,
            )
            return
        await _bot.send_message(
            telegram_id,
            digest.digest_text,
            reply_markup=digest_actions(digest.id, digest.refresh_attempts_left, digest.is_favorite),
            disable_notification=silent,
            disable_web_page_preview=True,
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to send scheduled digest to %s", telegram_id)
