from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
import feedparser


logger = logging.getLogger(__name__)

DEFAULT_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 RSSValidator/1.0 (compatible; news digest bot source checker)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


async def parse_rss_body(body: bytes) -> Any:
    return await asyncio.to_thread(feedparser.parse, body)


def rss_status_from_result(result: dict[str, Any]) -> tuple[str, str, str]:
    if not result["fetch_ok"]:
        return "ERROR", "FETCH_ERROR", result["fetch_error"]

    http_status = result["http_status"]
    if isinstance(http_status, int) and http_status >= 400:
        return "ERROR", "HTTP_ERROR", f"HTTP status {http_status}"

    if result["body_size_bytes"] == 0:
        return "ERROR", "EMPTY_RESPONSE", "Источник вернул пустой ответ"

    if result.get("looks_like_html") and result["entries_count"] == 0:
        return "ERROR", "HTML_INSTEAD_OF_RSS", "Источник похож на HTML-страницу, а не на RSS/Atom"

    if result["entries_count"] == 0:
        if result["bozo"]:
            return "ERROR", "PARSE_ERROR_NO_ENTRIES", result["bozo_exception"]
        return "ERROR", "NO_ENTRIES", "RSS прочитан, но новости не найдены"

    if result["response_too_large"]:
        return "WARNING", "RESPONSE_TOO_LARGE", "Ответ был слишком большим и был обрезан для проверки"

    if result["bozo"]:
        return "WARNING", "PARSE_WARNING_WITH_ENTRIES", result["bozo_exception"]

    if result.get("looks_like_html"):
        return "WARNING", "HTML_CONTENT_TYPE_WITH_ENTRIES", "Ответ похож на HTML, но feedparser смог извлечь новости"

    return "OK", "OK", "RSS читается нормально"


async def fetch_rss_source(
    session: aiohttp.ClientSession,
    *,
    source_id: str,
    url: str,
    timeout_seconds: int = 10,
    max_bytes: int = 5_000_000,
) -> dict[str, Any]:
    started = time.perf_counter()
    base_result: dict[str, Any] = {
        "source_id": source_id,
        "rss_url": url,
        "fetch_ok": False,
        "http_status": "",
        "final_url": "",
        "content_type": "",
        "body": b"",
        "body_size_bytes": 0,
        "original_body_size_bytes": 0,
        "response_too_large": False,
        "elapsed_ms": 0,
        "fetch_error": "",
        "parsed": None,
        "entries_count": 0,
        "bozo": False,
        "bozo_exception": "",
        "looks_like_html": False,
        "status": "ERROR",
        "issue_code": "NOT_CHECKED",
        "recommendation": "",
    }

    try:
        async with session.get(
            url,
            headers=DEFAULT_RSS_HEADERS,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            allow_redirects=True,
        ) as response:
            body = await response.read()
            original_body_size = len(body)
            response_too_large = original_body_size > max_bytes
            if response_too_large:
                body = body[:max_bytes]

            base_result.update(
                {
                    "fetch_ok": True,
                    "http_status": response.status,
                    "final_url": str(response.url),
                    "content_type": response.headers.get("Content-Type", ""),
                    "body": body,
                    "body_size_bytes": len(body),
                    "original_body_size_bytes": original_body_size,
                    "response_too_large": response_too_large,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                }
            )
            content_type_lower = base_result["content_type"].lower()
            body_start = body[:300].decode("utf-8", errors="replace").lower()
            base_result["looks_like_html"] = (
                "text/html" in content_type_lower
                or "<html" in body_start
                or "<!doctype html" in body_start
            )
    except asyncio.TimeoutError:
        base_result.update(
            {
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "fetch_error": f"Timeout after {timeout_seconds} seconds",
            }
        )
        logger.warning("RSS timeout for %s (%s)", source_id, url)
        status, issue_code, recommendation = rss_status_from_result(base_result)
        base_result.update({"status": status, "issue_code": issue_code, "recommendation": recommendation})
        return base_result
    except Exception as exc:
        base_result.update(
            {
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "fetch_error": f"{type(exc).__name__}: {exc}",
            }
        )
        logger.warning("RSS fetch error for %s (%s): %s", source_id, url, exc)
        status, issue_code, recommendation = rss_status_from_result(base_result)
        base_result.update({"status": status, "issue_code": issue_code, "recommendation": recommendation})
        return base_result

    if isinstance(base_result["http_status"], int) and base_result["http_status"] >= 400:
        logger.warning("RSS HTTP error for %s (%s): %s", source_id, url, base_result["http_status"])

    if base_result["body"]:
        try:
            parsed = await parse_rss_body(base_result["body"])
            entries = list(getattr(parsed, "entries", []) or [])
            bozo = bool(getattr(parsed, "bozo", False))
            bozo_exception = getattr(parsed, "bozo_exception", "")
            bozo_text = str(bozo_exception) if bozo_exception else ""
            base_result.update(
                {
                    "parsed": parsed,
                    "entries_count": len(entries),
                    "bozo": bozo,
                    "bozo_exception": bozo_text,
                }
            )
        except Exception as exc:
            base_result.update(
                {
                    "entries_count": 0,
                    "bozo": True,
                    "bozo_exception": f"{type(exc).__name__}: {exc}",
                }
            )

    status, issue_code, recommendation = rss_status_from_result(base_result)
    base_result.update({"status": status, "issue_code": issue_code, "recommendation": recommendation})

    if base_result["response_too_large"]:
        logger.warning(
            "RSS response too large for %s (%s): original=%s used=%s",
            source_id,
            url,
            base_result["original_body_size_bytes"],
            base_result["body_size_bytes"],
        )
    if base_result["bozo"]:
        logger.warning("RSS parse warning for %s (%s): %s", source_id, url, base_result["bozo_exception"])
    if status == "ERROR":
        logger.warning("RSS source skipped for %s (%s): %s %s", source_id, url, issue_code, recommendation)

    return base_result


async def collect_articles_from_sources(
    sources: list[Any],
    *,
    timeout_seconds: int = 10,
    max_bytes: int = 5_000_000,
    progress_callback=None,
) -> list[dict[str, Any]]:
    connector = aiohttp.TCPConnector(ssl=False)
    results: list[dict[str, Any]] = []
    total = len(sources)
    async with aiohttp.ClientSession(connector=connector) as session:
        for index, source in enumerate(sources, start=1):
            result = await fetch_rss_source(
                session,
                source_id=source.source_id,
                url=source.rss_url,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
            )
            results.append(result)
            if progress_callback:
                found = sum(item.get("entries_count", 0) for item in results if item.get("status") in {"OK", "WARNING"})
                await progress_callback(index, total, found)
    return results
