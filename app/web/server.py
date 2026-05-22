from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web

from app.config import get_settings
from app.core.digest_delivery import ensure_digest_html
from app.db import queries
from app.db.database import async_session


_runner: web.AppRunner | None = None
_site: web.BaseSite | None = None


async def digest_page(request: web.Request) -> web.StreamResponse:
    token = request.match_info["token"]
    async with async_session() as session:
        digest = await queries.get_digest_by_html_token(session, token)
        if not digest:
            raise web.HTTPNotFound(text="Digest not found")
        _, path_text = await ensure_digest_html(session, digest)
    path = Path(path_text)
    if not path.exists():
        raise web.HTTPNotFound(text="Digest file not found")
    return web.FileResponse(path)


async def start_web_server() -> None:
    global _runner, _site
    if _runner is not None:
        return

    settings = get_settings()
    parsed = urlparse(settings.public_base_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    app = web.Application()
    app.router.add_get("/digest/{token}", digest_page)
    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host="0.0.0.0", port=port)
    await _site.start()


async def stop_web_server() -> None:
    global _runner, _site
    if _site is not None:
        await _site.stop()
    if _runner is not None:
        await _runner.cleanup()
    _site = None
    _runner = None
