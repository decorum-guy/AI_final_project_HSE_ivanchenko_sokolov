from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.rss_fetcher import DEFAULT_RSS_HEADERS, fetch_rss_source


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def find_source_url(source_id: str, path: Path) -> tuple[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"Файл источников не найден: {path}")

    df = pd.read_excel(path, engine="openpyxl")
    required_columns = {"source_id", "title", "rss_url"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"В sources.xlsx не хватает колонок: {', '.join(sorted(missing))}")

    for _, row in df.iterrows():
        current_source_id = clean_text(row.get("source_id"))
        if current_source_id == source_id:
            title = clean_text(row.get("title")) or source_id
            rss_url = clean_text(row.get("rss_url"))
            if not rss_url:
                raise ValueError(f"У источника {source_id} пустой rss_url")
            return title, rss_url

    raise ValueError(f"Источник не найден в sources.xlsx: {source_id}")


def print_headers() -> None:
    print("Хедеры, которые использует бот:")
    for key, value in DEFAULT_RSS_HEADERS.items():
        print(f"{key}: {value}")
    print()


def print_result(result: dict[str, Any]) -> None:
    print("Результат fetch_rss_source:")
    print(f"source_id: {result.get('source_id')}")
    print(f"rss_url: {result.get('rss_url')}")
    print(f"fetch_ok: {result.get('fetch_ok')}")
    print(f"status: {result.get('status')}")
    print(f"issue_code: {result.get('issue_code')}")
    print(f"recommendation: {result.get('recommendation')}")
    print(f"fetch_error: {result.get('fetch_error')}")
    print(f"http_status: {result.get('http_status')}")
    print(f"final_url: {result.get('final_url')}")
    print(f"content_type: {result.get('content_type')}")
    print(f"elapsed_ms: {result.get('elapsed_ms')}")
    print(f"body_size_bytes: {result.get('body_size_bytes')}")
    print(f"original_body_size_bytes: {result.get('original_body_size_bytes')}")
    print(f"response_too_large: {result.get('response_too_large')}")
    print(f"entries_count: {result.get('entries_count')}")
    print(f"bozo: {result.get('bozo')}")
    print(f"bozo_exception: {result.get('bozo_exception')}")
    print(f"looks_like_html: {result.get('looks_like_html')}")
    print()

    body = result.get("body") or b""
    if body:
        preview = body[:800].decode("utf-8", errors="replace")
        print("Первые 800 символов ответа:")
        print(preview)
        print()

    parsed = result.get("parsed")
    entries = list(getattr(parsed, "entries", []) or []) if parsed else []
    if entries:
        print("Первые новости:")
        for index, entry in enumerate(entries[:5], start=1):
            title = entry.get("title", "Без заголовка")
            link = entry.get("link", "")
            print(f"{index}. {title}")
            if link:
                print(f"   {link}")


async def debug_fetch(args: argparse.Namespace) -> None:
    source_arg = args.source
    if is_url(source_arg):
        source_id = args.source_id or "manual_url"
        title = source_id
        url = source_arg
    else:
        source_id = source_arg
        title, url = find_source_url(source_id, args.path)

    print(f"Источник: {source_id} — {title}")
    print(f"URL: {url}")
    print(f"Timeout: {args.timeout} сек.")
    print(f"Max bytes: {args.max_bytes}")
    print()
    print_headers()

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        result = await fetch_rss_source(
            session,
            source_id=source_id,
            url=url,
            timeout_seconds=args.timeout,
            max_bytes=args.max_bytes,
        )

    print_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Debug-проверка одного RSS тем же fetcher-кодом и headers, которые использует бот."
    )
    parser.add_argument(
        "source",
        help="source_id из app/data/sources.xlsx или прямой RSS URL",
    )
    parser.add_argument(
        "--source-id",
        default="",
        help="source_id для ручного URL, если нужно задать имя в отчете",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("app/data/sources.xlsx"),
        help="Путь к sources.xlsx",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Timeout на RSS-запрос в секундах",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5_000_000,
        help="Максимальный размер ответа в байтах",
    )

    args = parser.parse_args()
    asyncio.run(debug_fetch(args))


if __name__ == "__main__":
    main()
