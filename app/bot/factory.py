import logging
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import Settings


logger = logging.getLogger(__name__)
SUPPORTED_PROXY_SCHEMES = {"http", "socks5"}


def mask_proxy_url(proxy_url: str) -> str:
    parsed = urlparse(proxy_url)
    if not parsed.scheme:
        return "***"
    return f"{parsed.scheme}://***"


def _validate_proxy_url(proxy_url: str) -> None:
    parsed = urlparse(proxy_url)
    if parsed.scheme not in SUPPORTED_PROXY_SCHEMES:
        raise ValueError("Proxy URL must start with http:// or socks5://")
    if not parsed.hostname or not parsed.port:
        raise ValueError("Proxy URL must include host and port")


def create_bot(settings: Settings) -> Bot:
    if not settings.bot_use_proxy or not settings.bot_proxy_url:
        logger.info("Bot started without proxy")
        return Bot(token=settings.bot_token)

    try:
        _validate_proxy_url(settings.bot_proxy_url)
        session = AiohttpSession(proxy=settings.bot_proxy_url)
    except Exception:
        logger.exception("Invalid proxy configuration: %s", mask_proxy_url(settings.bot_proxy_url))
        raise

    logger.info("Bot started with proxy: %s", mask_proxy_url(settings.bot_proxy_url))
    return Bot(token=settings.bot_token, session=session)
