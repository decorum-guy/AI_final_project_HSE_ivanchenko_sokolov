from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.db.database import async_session
from app.db.queries import get_or_create_user


class UserActivityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = None
        if isinstance(event, Message):
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user

        if tg_user:
            async with async_session() as session:
                await get_or_create_user(
                    session,
                    tg_user.id,
                    tg_user.username,
                    tg_user.first_name,
                    tg_user.last_name,
                )
        return await handler(event, data)
