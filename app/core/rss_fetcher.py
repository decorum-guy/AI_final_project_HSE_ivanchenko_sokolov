from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from types import SimpleNamespace
from typing import Any

import aiohttp
import feedparser


logger = logging.getLogger(__name__)

DEFAULT_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsDigestBot/1.0; +https://example.com)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}
RSS_CHUNK_SIZE = 64 * 1024
MIN_SOCK_READ_TIMEOUT_SECONDS = 3
MAX_SOCK_READ_TIMEOUT_SECONDS = 5


async def parse_rss_body(body: bytes) -> Any:
    return await asyncio.to_thread(feedparser.parse, body)


def _clean_rss_text(value: str) -> str:
    text = html.unescape(html.unescape(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip()


def _extract_tag_text(snippet: str, tag_name: str) -> str:
    match = re.search(
        rf"<(?:(?:[A-Za-z0-9_-]+):)?{re.escape(tag_name)}\b[^>]*>(.*?)(?:</(?:(?:[A-Za-z0-9_-]+):)?{re.escape(tag_name)}>|$)",
        snippet,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return _clean_rss_text(match.group(1))


def _salvage_partial_rss_entries(body: bytes) -> list[dict[str, str]]:
    """Extract minimal entries from broken RSS where the response timed out mid-item."""
    text = body.decode("utf-8", errors="replace")
    snippets = re.findall(r"<item\b[^>]*>.*?</item>", text, flags=re.IGNORECASE | re.DOTALL)

    last_item_start = text.lower().rfind("<item")
    last_item_end = text.lower().rfind("</item>")
    if last_item_start != -1 and last_item_start > last_item_end:
        snippets.append(text[last_item_start:])

    entries: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for snippet in snippets[:50]:
        title = _extract_tag_text(snippet, "title")
        link = _extract_tag_text(snippet, "link")
        summary = _extract_tag_text(snippet, "description") or _extract_tag_text(snippet, "full-text")
        published = _extract_tag_text(snippet, "pubDate")
        category = _extract_tag_text(snippet, "category")

        if not title and not link:
            continue
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)

        entry = {
            "title": title or "Без заголовка",
            "link": link,
            "summary": summary,
        }
        if published:
            entry["published"] = published
        if category:
            entry["tags"] = [{"term": category}]
        entries.append(entry)
    return entries


def rss_status_from_result(result: dict[str, Any]) -> tuple[str, str, str]:
    if not result["fetch_ok"]:
        return "ERROR", "FETCH_ERROR", result["fetch_error"]

    http_status = result["http_status"]
    if isinstance(http_status, int) and http_status >= 400:
        return "ERROR", "HTTP_ERROR", f"HTTP status {http_status}"

    if result["body_size_bytes"] == 0:
        return "ERROR", "EMPTY_RESPONSE", "Source returned an empty response"

    if result.get("partial_response") and result["entries_count"] == 0:
        return "ERROR", "PARTIAL_RESPONSE_NO_ENTRIES", result.get("partial_reason") or "Partial RSS response without entries"

    if result.get("looks_like_html") and result["entries_count"] == 0:
        return "ERROR", "HTML_INSTEAD_OF_RSS", "Response looks like HTML, not RSS/Atom"

    if result["entries_count"] == 0:
        if result["bozo"]:
            return "ERROR", "PARSE_ERROR_NO_ENTRIES", result["bozo_exception"]
        return "ERROR", "NO_ENTRIES", "RSS parsed, but no entries found"

    if result.get("partial_response"):
        return "WARNING", "PARTIAL_RESPONSE_WITH_ENTRIES", result.get("partial_reason") or "Partial RSS response parsed with entries"

    if result["response_too_large"]:
        return "WARNING", "RESPONSE_TOO_LARGE", "Response was too large and was truncated"

    if result["bozo"]:
        return "WARNING", "PARSE_WARNING_WITH_ENTRIES", result["bozo_exception"]

    if result.get("looks_like_html"):
        return "WARNING", "HTML_CONTENT_TYPE_WITH_ENTRIES", "Response looks like HTML, but feedparser extracted entries"

    return "OK", "OK", "RSS parsed successfully"


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
        "partial_response": False,
        "partial_reason": "",
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

    body_chunks: list[bytes] = []
    body_size = 0
    response_too_large = False
    partial_response = False
    partial_reason = ""
    sock_read_timeout = max(
        MIN_SOCK_READ_TIMEOUT_SECONDS,
        min(timeout_seconds, MAX_SOCK_READ_TIMEOUT_SECONDS),
    )

    try:
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=timeout_seconds,
            sock_connect=timeout_seconds,
            sock_read=sock_read_timeout,
        )
        async with session.get(
            url,
            headers=DEFAULT_RSS_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        ) as response:
            while True:
                try:
                    chunk = await response.content.read(RSS_CHUNK_SIZE)
                except asyncio.TimeoutError:
                    partial_response = bool(body_chunks)
                    partial_reason = f"Read timeout after {sock_read_timeout} seconds with partial body"
                    break
                if not chunk:
                    break
                body_chunks.append(chunk)
                body_size += len(chunk)
                if body_size >= max_bytes:
                    response_too_large = True
                    partial_response = True
                    partial_reason = f"Response exceeded max_bytes={max_bytes} and was truncated"
                    break

            body = b"".join(body_chunks)
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
                    "original_body_size_bytes": body_size,
                    "response_too_large": response_too_large,
                    "partial_response": partial_response,
                    "partial_reason": partial_reason,
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
        body = b"".join(body_chunks)
        if body:
            base_result.update(
                {
                    "fetch_ok": True,
                    "body": body,
                    "body_size_bytes": len(body),
                    "original_body_size_bytes": len(body),
                    "partial_response": True,
                    "partial_reason": f"Timeout after {timeout_seconds} seconds with partial body",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000),
                    "fetch_error": f"Timeout after {timeout_seconds} seconds with partial body",
                }
            )
        else:
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
        status, issue_code, recommendation = rss_status_from_result(base_result)
        base_result.update({"status": status, "issue_code": issue_code, "recommendation": recommendation})
        logger.warning("RSS source skipped for %s (%s): %s %s", source_id, url, issue_code, recommendation)
        return base_result

    if base_result["body"]:
        try:
            parsed = await parse_rss_body(base_result["body"])
            entries = list(getattr(parsed, "entries", []) or [])
            bozo = bool(getattr(parsed, "bozo", False))
            bozo_exception = getattr(parsed, "bozo_exception", "")
            bozo_text = str(bozo_exception) if bozo_exception else ""
            if not entries and base_result.get("partial_response"):
                entries = _salvage_partial_rss_entries(base_result["body"])
                if entries:
                    parsed = SimpleNamespace(entries=entries, bozo=True, bozo_exception="salvaged entries from partial RSS response")
                    bozo = True
                    bozo_text = "salvaged entries from partial RSS response"
            base_result.update(
                {
                    "parsed": parsed,
                    "entries_count": len(entries),
                    "bozo": bozo,
                    "bozo_exception": bozo_text,
                }
            )
        except Exception as exc:
            salvaged_entries = _salvage_partial_rss_entries(base_result["body"]) if base_result.get("partial_response") else []
            if salvaged_entries:
                base_result.update(
                    {
                        "parsed": SimpleNamespace(entries=salvaged_entries, bozo=True, bozo_exception="salvaged entries after parse failure"),
                        "entries_count": len(salvaged_entries),
                        "bozo": True,
                        "bozo_exception": "salvaged entries after parse failure",
                    }
                )
            else:
                base_result.update(
                    {
                        "entries_count": 0,
                        "bozo": True,
                        "bozo_exception": f"{type(exc).__name__}: {exc}",
                    }
                )

    status, issue_code, recommendation = rss_status_from_result(base_result)
    base_result.update({"status": status, "issue_code": issue_code, "recommendation": recommendation})

    if base_result["partial_response"]:
        logger.warning(
            "RSS partial response for %s (%s): %s bytes, entries=%s, reason=%s",
            source_id,
            url,
            base_result["body_size_bytes"],
            base_result["entries_count"],
            base_result["partial_reason"],
        )
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
                found = sum(
                    item.get("entries_count", 0)
                    for item in results
                    if item.get("status") in {"OK", "WARNING"}
                )
                await progress_callback(index, total, found)
    return results
