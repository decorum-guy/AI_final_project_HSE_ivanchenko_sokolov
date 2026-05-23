from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp
import feedparser
import pandas as pd

from app.core.rss_fetcher import DEFAULT_RSS_HEADERS, fetch_rss_source


REQUIRED_COLUMNS = [
    "source_id",
    "title",
    "category",
    "description",
    "rss_url",
    "is_active",
]

DEFAULT_HEADERS = DEFAULT_RSS_HEADERS


@dataclass
class Source:
    row_number: int
    source_id: str
    title: str
    category: str
    description: str
    rss_url: str
    is_active: bool


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    text = str(value).strip().lower()

    return text in {"true", "1", "yes", "y", "да", "активен", "active"}


def clean_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""

    if pd.isna(value):
        return ""

    text = str(value)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > limit:
        return text[:limit].rstrip() + "..."

    return text


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\s+", " ", title)
    title = re.sub(r"[^\w\sа-яё-]", "", title, flags=re.IGNORECASE)
    return title.strip()


def explain_bozo_exception(exception_text: str) -> str:
    text = exception_text.lower()

    if "declared as us-ascii" in text and "parsed as utf-8" in text:
        return (
            "Проблема кодировки: источник объявляет одну кодировку, "
            "а фактически данные читаются как другая. Часто это не критично, "
            "если новости всё равно извлекаются."
        )

    if "mismatched tag" in text:
        return (
            "В RSS есть ошибка XML-разметки: закрывающий тег не совпадает "
            "с открывающим. Feedparser может частично прочитать такую ленту."
        )

    if "not well-formed" in text or "invalid token" in text:
        return (
            "В RSS есть некорректный XML-символ или битая разметка. "
            "Часто возникает из-за спецсимволов, HTML-вставок или ошибки на стороне сайта."
        )

    if "syntax error" in text:
        return (
            "Синтаксическая ошибка в XML/RSS. Возможно, сайт отдает не чистый RSS, "
            "а HTML, редирект, защитную страницу или поврежденный XML."
        )

    if "no element found" in text:
        return (
            "Пустой или обрезанный XML-документ. Возможно, источник вернул пустой ответ "
            "или соединение оборвалось."
        )

    if "document is empty" in text:
        return (
            "Источник вернул пустой документ. Возможно, RSS временно недоступен."
        )

    if "undefined entity" in text:
        return (
            "В RSS используется HTML/XML-сущность, которая не объявлена корректно. "
            "Feedparser может прочитать часть ленты, но формально XML битый."
        )

    return (
        "Feedparser обнаружил проблему при разборе RSS/XML. "
        "Точная причина указана в поле bozo_exception."
    )


def parse_entry_date(entry: Any) -> str:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass

    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                dt = parsedate_to_datetime(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except Exception:
                return clean_text(value, limit=120)

    return ""


def read_sources(path: Path, include_inactive: bool) -> list[Source]:
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    df = pd.read_excel(path, engine="openpyxl")

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(
            "В sources.xlsx не хватает колонок: "
            + ", ".join(missing)
            + "\nОжидаемые колонки: "
            + ", ".join(REQUIRED_COLUMNS)
        )

    sources: list[Source] = []

    for idx, row in df.iterrows():
        source_id = clean_text(row.get("source_id"), limit=120)
        title = clean_text(row.get("title"), limit=200)
        category = clean_text(row.get("category"), limit=120)
        description = clean_text(row.get("description"), limit=500)
        rss_url = clean_text(row.get("rss_url"), limit=1000)
        is_active = to_bool(row.get("is_active"))

        row_number = idx + 2

        if not source_id or not rss_url:
            continue

        if not include_inactive and not is_active:
            continue

        sources.append(
            Source(
                row_number=row_number,
                source_id=source_id,
                title=title,
                category=category,
                description=description,
                rss_url=rss_url,
                is_active=is_active,
            )
        )

    return sources


async def fetch_url(
    session: aiohttp.ClientSession,
    url: str,
    timeout_seconds: int,
    max_bytes: int,
    source_id: str = "",
) -> dict[str, Any]:
    return await fetch_rss_source(
        session,
        source_id=source_id or url,
        url=url,
        timeout_seconds=timeout_seconds,
        max_bytes=max_bytes,
    )
    
def parse_feed(body: bytes) -> Any:
    return feedparser.parse(body)


def analyze_parsed_feed(parsed: Any, content_type: str, body: bytes) -> dict[str, Any]:
    entries = list(getattr(parsed, "entries", []) or [])
    feed_info = getattr(parsed, "feed", {}) or {}

    bozo = bool(getattr(parsed, "bozo", False))
    bozo_exception = getattr(parsed, "bozo_exception", "")

    bozo_exception_type = ""
    bozo_exception_text = ""
    bozo_explanation = ""

    if bozo_exception:
        bozo_exception_type = type(bozo_exception).__name__
        bozo_exception_text = clean_text(str(bozo_exception), limit=800)
        bozo_explanation = explain_bozo_exception(bozo_exception_text)

    first_entry = entries[0] if entries else {}

    latest_title = clean_text(first_entry.get("title", ""), limit=300)
    latest_link = clean_text(first_entry.get("link", ""), limit=500)
    latest_date = parse_entry_date(first_entry) if first_entry else ""

    feed_title = clean_text(feed_info.get("title", ""), limit=300)
    feed_link = clean_text(feed_info.get("link", ""), limit=500)

    version = clean_text(getattr(parsed, "version", ""), limit=120)
    encoding = clean_text(getattr(parsed, "encoding", ""), limit=120)

    content_type_lower = content_type.lower()
    body_start = body[:300].decode("utf-8", errors="replace").lower()

    looks_like_html = (
        "text/html" in content_type_lower
        or "<html" in body_start
        or "<!doctype html" in body_start
    )

    return {
        "entries_count": len(entries),
        "feed_title": feed_title,
        "feed_link": feed_link,
        "feed_version": version,
        "feed_encoding": encoding,
        "bozo": bozo,
        "bozo_exception_type": bozo_exception_type,
        "bozo_exception": bozo_exception_text,
        "bozo_explanation": bozo_explanation,
        "looks_like_html": looks_like_html,
        "latest_title": latest_title,
        "latest_link": latest_link,
        "latest_date": latest_date,
    }


def determine_status(row: dict[str, Any]) -> tuple[str, str, str]:
    if not row["fetch_ok"]:
        return "ERROR", "FETCH_ERROR", row["fetch_error"]

    http_status = row["http_status"]

    if isinstance(http_status, int) and http_status >= 400:
        return "ERROR", "HTTP_ERROR", f"HTTP status {http_status}"

    if row["body_size_bytes"] == 0:
        return "ERROR", "EMPTY_RESPONSE", "Источник вернул пустой ответ"

    if row["looks_like_html"] and row["entries_count"] == 0:
        return (
            "ERROR",
            "HTML_INSTEAD_OF_RSS",
            "Источник похож на HTML-страницу, а не на RSS/Atom",
        )

    if row["entries_count"] == 0:
        if row["bozo"]:
            return (
                "ERROR",
                "PARSE_ERROR_NO_ENTRIES",
                row["bozo_explanation"] or row["bozo_exception"],
            )

        return (
            "ERROR",
            "NO_ENTRIES",
            "RSS прочитан, но новости не найдены",
        )

    if row["response_too_large"]:
        return (
            "WARNING",
            "RESPONSE_TOO_LARGE",
            (
                "Ответ был слишком большим и был обрезан для проверки. "
                "Если есть bozo/no element found, это может быть следствием обрезки, "
                "а не ошибкой самого RSS."
            ),
        )

    if row["bozo"]:
        return (
            "WARNING",
            "PARSE_WARNING_WITH_ENTRIES",
            row["bozo_explanation"] or row["bozo_exception"],
        )

    if row["looks_like_html"]:
        return (
            "WARNING",
            "HTML_CONTENT_TYPE_WITH_ENTRIES",
            "Ответ похож на HTML, но feedparser смог извлечь новости",
        )

    return "OK", "OK", "RSS читается нормально"


async def check_source(
    source: Source,
    session: aiohttp.ClientSession,
    timeout_seconds: int,
    max_bytes: int,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        fetch_result = await fetch_url(
            session=session,
            url=source.rss_url,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            source_id=source.source_id,
        )

        parsed_analysis: dict[str, Any] = {
            "entries_count": 0,
            "feed_title": "",
            "feed_link": "",
            "feed_version": "",
            "feed_encoding": "",
            "bozo": False,
            "bozo_exception_type": "",
            "bozo_exception": "",
            "bozo_explanation": "",
            "looks_like_html": False,
            "latest_title": "",
            "latest_link": "",
            "latest_date": "",
        }

        if fetch_result.get("parsed") is not None:
            parsed_analysis = analyze_parsed_feed(
                parsed=fetch_result["parsed"],
                content_type=fetch_result["content_type"],
                body=fetch_result["body"],
            )
        elif fetch_result["fetch_ok"] and fetch_result["body"]:
            try:
                parsed = await asyncio.to_thread(parse_feed, fetch_result["body"])
                parsed_analysis = analyze_parsed_feed(
                    parsed=parsed,
                    content_type=fetch_result["content_type"],
                    body=fetch_result["body"],
                )
            except Exception as exc:
                parsed_analysis["bozo"] = True
                parsed_analysis["bozo_exception_type"] = type(exc).__name__
                parsed_analysis["bozo_exception"] = clean_text(str(exc), limit=800)
                parsed_analysis["bozo_explanation"] = (
                    "Не удалось разобрать ответ как RSS/Atom."
                )

        result = {
            "row_number": source.row_number,
            "source_id": source.source_id,
            "title": source.title,
            "category": source.category,
            "description": source.description,
            "rss_url": source.rss_url,
            "is_active": source.is_active,
            **fetch_result,
            **parsed_analysis,
        }

        status, issue_code, recommendation = determine_status(result)

        result["status"] = status
        result["issue_code"] = issue_code
        result["recommendation"] = recommendation

        result.pop("body", None)
        result.pop("parsed", None)

        return result


async def validate_sources(
    path: Path,
    include_inactive: bool,
    timeout_seconds: int,
    concurrency: int,
    max_bytes: int,
    out_dir: Path,
) -> None:
    sources = read_sources(path=path, include_inactive=include_inactive)

    if not sources:
        print("Не найдено источников для проверки.")
        return

    print(f"Файл: {path}")
    print(f"Источников для проверки: {len(sources)}")
    print(f"Timeout на источник: {timeout_seconds} сек.")
    print(f"Concurrency: {concurrency}")
    print()

    semaphore = asyncio.Semaphore(concurrency)

    connector = aiohttp.TCPConnector(ssl=False)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            check_source(
                source=source,
                session=session,
                timeout_seconds=timeout_seconds,
                max_bytes=max_bytes,
                semaphore=semaphore,
            )
            for source in sources
        ]

        results: list[dict[str, Any]] = []

        for index, task in enumerate(asyncio.as_completed(tasks), start=1):
            result = await task
            results.append(result)

            print(
                f"[{index}/{len(sources)}] "
                f"{result['status']:7} "
                f"{result['source_id']} "
                f"entries={result['entries_count']} "
                f"issue={result['issue_code']}"
            )

    df = pd.DataFrame(results)

    status_order = {"ERROR": 0, "WARNING": 1, "OK": 2}
    df["_status_order"] = df["status"].map(status_order).fillna(9)
    df = df.sort_values(
        by=["_status_order", "category", "source_id"],
        ascending=[True, True, True],
    ).drop(columns=["_status_order"])

    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"rss_validation_report_{timestamp}.csv"
    xlsx_path = out_dir / f"rss_validation_report_{timestamp}.xlsx"

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    summary = (
        df.groupby(["status", "issue_code"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(by=["status", "count"], ascending=[True, False])
    )

    errors = df[df["status"] == "ERROR"].copy()
    warnings = df[df["status"] == "WARNING"].copy()
    ok = df[df["status"] == "OK"].copy()

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="all_sources", index=False)
        summary.to_excel(writer, sheet_name="summary", index=False)
        errors.to_excel(writer, sheet_name="errors", index=False)
        warnings.to_excel(writer, sheet_name="warnings", index=False)
        ok.to_excel(writer, sheet_name="ok", index=False)

    print()
    print("Готово.")
    print(f"OK: {len(ok)}")
    print(f"WARNING: {len(warnings)}")
    print(f"ERROR: {len(errors)}")
    print()
    print(f"CSV отчет: {csv_path}")
    print(f"Excel отчет: {xlsx_path}")

    if len(errors) > 0:
        print()
        print("Источники с ошибками:")
        for _, row in errors.head(20).iterrows():
            print(
                f"- {row['source_id']} | {row['title']} | "
                f"{row['issue_code']} | {row['recommendation']}"
            )

    if len(warnings) > 0:
        print()
        print("Источники с предупреждениями:")
        for _, row in warnings.head(20).iterrows():
            print(
                f"- {row['source_id']} | {row['title']} | "
                f"{row['issue_code']} | {row['recommendation']}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Проверка RSS-источников из sources.xlsx"
    )

    parser.add_argument(
        "--path",
        type=Path,
        default=Path("app/data/sources.xlsx"),
        help="Путь к sources.xlsx",
    )

    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Проверять также источники с is_active=false",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="Timeout на один RSS-источник в секундах",
    )

    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Сколько источников проверять параллельно",
    )

    parser.add_argument(
        "--max-bytes",
        type=int,
        default=5_000_000,
        help="Максимальный размер ответа одного RSS в байтах",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("reports"),
        help="Папка для отчетов",
    )

    args = parser.parse_args()

    asyncio.run(
        validate_sources(
            path=args.path,
            include_inactive=args.include_inactive,
            timeout_seconds=args.timeout,
            concurrency=args.concurrency,
            max_bytes=args.max_bytes,
            out_dir=args.out_dir,
        )
    )


if __name__ == "__main__":
    main()
