from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.digest import _period_title_with_date, prepare_digest_input
from app.core.gigachat_client import ask_llm, postprocess_digest_html, repair_digest_text, GigaChatDigestClient
from app.db import queries
from app.db.database import async_session
from app.db.models import User


TECHNICAL_NUMBER_CODES = {
    "33",
    "160",
    "171",
    "187",
    "8211",
    "8212",
    "8220",
    "8221",
    "8230",
}

NUMBER_RE = re.compile(r"(?<![A-Za-zА-Яа-я0-9])\d+(?:[.,]\d+)?(?:\s*[A-Za-zА-Яа-я%]+)?")
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")


def clean_text(value: Any) -> str:
    text = str(value or "")
    text = HTML_ENTITY_RE.sub(" ", text)
    text = html.unescape(text)
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def safe_filename_part(value: str) -> str:
    value = re.sub(r"[^A-Za-zА-Яа-я0-9_.-]+", "_", value.strip())
    value = value.strip("._")
    return value[:80] or "value"


def extract_important_numbers(text: str) -> list[str]:
    cleaned = clean_text(text)
    numbers: list[str] = []
    seen: set[str] = set()
    for match in NUMBER_RE.finditer(cleaned):
        raw = match.group(0).strip()
        digits = re.sub(r"\D+", "", raw)
        if not digits:
            continue
        if digits in TECHNICAL_NUMBER_CODES:
            continue
        if len(digits) <= 1 and not any(unit in raw.lower() for unit in ("%", "м", "км", "гб", "млн", "млрд", "$", "₽")):
            continue
        normalized = digits
        if normalized in seen:
            continue
        numbers.append(normalized)
        seen.add(normalized)
    return numbers


def numbers_with_context(text: str) -> list[dict[str, str]]:
    cleaned = clean_text(text)
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in NUMBER_RE.finditer(cleaned):
        raw = match.group(0).strip()
        digits = re.sub(r"\D+", "", raw)
        if not digits or digits in TECHNICAL_NUMBER_CODES or digits in seen:
            continue
        start = max(0, match.start() - 70)
        end = min(len(cleaned), match.end() + 70)
        result.append(
            {
                "number": digits,
                "raw": raw,
                "context": cleaned[start:end].strip(),
            }
        )
        seen.add(digits)
    return result


def strip_digest_text(text: str) -> str:
    return clean_text(text).lower()


def validate_digest_quality(items, digest_text: str) -> dict[str, Any]:
    plain_digest = strip_digest_text(digest_text)
    missing_numbers: list[dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        source_text = f"{item.title}\n{item.summary or ''}"
        item_numbers = numbers_with_context(source_text)
        missing = [number for number in item_numbers if number["number"] not in plain_digest]
        if missing:
            missing_numbers.append(
                {
                    "item_index": index,
                    "source_id": item.source_id,
                    "source": item.source,
                    "title": item.title,
                    "link": item.link,
                    "missing_numbers": missing,
                    "summary_preview": clean_text(item.summary or "")[:500],
                }
            )

    structural_warnings: list[str] = []
    lowered = digest_text.lower()
    if "<b>очень кратко</b>" not in lowered and "очень кратко" not in lowered:
        structural_warnings.append("missing_very_short_block")
    if "<b>подробно</b>" not in lowered and "подробно" not in lowered:
        structural_warnings.append("missing_details_block")
    if "<b>итог</b>" not in lowered and "итог" not in lowered:
        structural_warnings.append("missing_final_block")
    if "**" in digest_text or "```" in digest_text or re.search(r"\[[^\]]+]\(https?://", digest_text):
        structural_warnings.append("markdown_markers_present")
    if digest_text.lower().find("итог") != -1 and digest_text.lower().find("подробно") != -1:
        if digest_text.lower().find("итог") < digest_text.lower().find("подробно"):
            structural_warnings.append("final_block_before_details")

    suspicious_terms: list[dict[str, str]] = []
    intro = digest_text.split("<b>Подробно</b>", 1)[0]
    intro_plain = strip_digest_text(intro)
    for index, item in enumerate(items, start=1):
        item_plain = strip_digest_text(f"{item.title}\n{item.summary or ''}")
        if "звягинцев" in item_plain and "звягинцев" in intro_plain and "японск" in intro_plain and "японск" not in item_plain:
            suspicious_terms.append(
                {
                    "item_index": str(index),
                    "source": item.source,
                    "title": item.title,
                    "term": "японск*",
                    "where": "intro",
                    "reason": "Во вступлении термин стоит рядом с новостью про Звягинцева, но его нет во входном title/summary этой новости.",
                }
            )

    return {
        "missing_numbers_count": len(missing_numbers),
        "missing_numbers": missing_numbers,
        "structural_warnings_count": len(structural_warnings),
        "structural_warnings": structural_warnings,
        "suspicious_terms_count": len(suspicious_terms),
        "suspicious_terms": suspicious_terms,
    }


def item_to_dict(index: int, item) -> dict[str, Any]:
    published = item.published.isoformat() if item.published else None
    source_text = f"{item.title}\n{item.summary or ''}"
    return {
        "index": index,
        "source_id": item.source_id,
        "source": item.source,
        "category": item.category,
        "published": published,
        "title": item.title,
        "summary": item.summary,
        "link": item.link,
        "numbers": numbers_with_context(source_text),
    }


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def provider_list(value: str) -> list[str]:
    if value == "both":
        return ["gigachat", "chatgpt"]
    return [value]


async def load_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def run_provider(
    provider: str,
    prompt: str,
    items,
    output_dir: Path,
    max_tokens: int,
    temperature: float,
    chatgpt_model: str | None,
) -> dict[str, Any]:
    prefix = provider
    prompt_path = output_dir / f"{prefix}_prompt.txt"
    raw_path = output_dir / f"{prefix}_raw_response.html"
    postprocessed_path = output_dir / f"{prefix}_postprocessed.html"
    quality_path = output_dir / f"{prefix}_quality_report.json"

    write_text(prompt_path, prompt)

    started = time.perf_counter()
    result: dict[str, Any] = {
        "provider": provider,
        "ok": False,
        "prompt_path": str(prompt_path),
        "raw_response_path": str(raw_path),
        "postprocessed_path": str(postprocessed_path),
        "quality_report_path": str(quality_path),
    }

    try:
        raw_answer = await ask_llm(
            prompt,
            provider=provider,
            model=chatgpt_model if provider == "chatgpt" else None,
            max_tokens=max_tokens,
            temperature=temperature,
            task=f"test_digest_{provider}",
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        write_text(raw_path, raw_answer)

        postprocessed = repair_digest_text(postprocess_digest_html(raw_answer))
        write_text(postprocessed_path, postprocessed)

        quality_report = validate_digest_quality(items, postprocessed)
        write_json(quality_path, quality_report)

        result.update(
            {
                "ok": True,
                "duration_ms": duration_ms,
                "raw_response_length": len(raw_answer),
                "postprocessed_length": len(postprocessed),
                "missing_numbers_count": quality_report["missing_numbers_count"],
                "structural_warnings_count": quality_report["structural_warnings_count"],
                "suspicious_terms_count": quality_report["suspicious_terms_count"],
            }
        )
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        error_payload = {"error": repr(exc), "duration_ms": duration_ms}
        write_json(quality_path, error_payload)
        result.update(error_payload)
        return result


async def main_async(args: argparse.Namespace) -> int:
    user = await load_user(args.telegram_id)
    if not user:
        print(f"Пользователь с telegram_id={args.telegram_id} не найден в БД.")
        return 1

    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == args.telegram_id))
        if not user:
            print(f"Пользователь с telegram_id={args.telegram_id} не найден в БД.")
            return 1
        await queries.sync_sources(session)
        prepared = await prepare_digest_input(session, user, args.mode, args.period)
        selected_sources = await queries.selected_sources(session, user.id)
        interests_text = user.interests_text
        interests_keywords = user.interests_keywords

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"{timestamp}_user{args.telegram_id}_{safe_filename_part(args.period)}_{safe_filename_part(args.mode)}"
    output_dir = Path(args.output_dir) / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    period_title = _period_title_with_date(args.period)
    items_payload = [item_to_dict(index, item) for index, item in enumerate(prepared.items, start=1)]
    input_stats = {
        "telegram_id": args.telegram_id,
        "period": args.period,
        "period_title": period_title,
        "mode": args.mode,
        "created_at": datetime.now().isoformat(),
        "interests_text": interests_text,
        "interests_keywords": interests_keywords,
        "selected_sources_count": len(selected_sources),
        "selected_sources": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "category": source.category,
                "description": source.description,
            }
            for source in selected_sources
        ],
        "prepare_stats": prepared.stats,
        "note": prepared.note,
        "input_items_count": len(prepared.items),
    }

    write_json(output_dir / "input_items.json", items_payload)
    write_json(output_dir / "input_stats.json", input_stats)

    summary: dict[str, Any] = {
        **input_stats,
        "output_dir": str(output_dir),
        "providers": {},
    }

    print(f"Output dir: {output_dir}")
    print(f"Interests: {interests_text or '-'}")
    print(f"Keywords: {interests_keywords or '-'}")
    print(f"Selected sources: {len(selected_sources)}")
    print(f"Input items: {len(prepared.items)}")
    for item in items_payload:
        print(f"{item['index']}. {item['source']} — {item['title']}")
        if item["numbers"]:
            compact_numbers = ", ".join(number["raw"] for number in item["numbers"])
            print(f"   numbers: {compact_numbers}")
    print()

    for provider in provider_list(args.providers):
        client = GigaChatDigestClient(provider)
        prompt = client._build_digest_prompt(prepared.items, period_title)
        result = await run_provider(
            provider=provider,
            prompt=prompt,
            items=prepared.items,
            output_dir=output_dir,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            chatgpt_model=args.chatgpt_model,
        )
        summary["providers"][provider] = result

        print(f"Provider: {provider}")
        if result.get("ok"):
            print("  OK")
            print(f"  response length: {result.get('postprocessed_length')}")
            print(f"  missing numbers: {result.get('missing_numbers_count')}")
            print(f"  structural warnings: {result.get('structural_warnings_count')}")
            print(f"  suspicious terms: {result.get('suspicious_terms_count')}")
            quality = json.loads(Path(result["quality_report_path"]).read_text(encoding="utf-8"))
            for item in quality.get("missing_numbers", []):
                missed = ", ".join(number["raw"] for number in item.get("missing_numbers", []))
                print(f"  - item #{item['item_index']} {item['source']}: missing {missed}")
            for item in quality.get("suspicious_terms", []):
                print(f"  - suspicious {item['term']} near item #{item['item_index']}: {item['reason']}")
        else:
            print(f"  ERROR: {result.get('error')}")
        print(f"  prompt: {result.get('prompt_path')}")
        print(f"  raw: {result.get('raw_response_path')}")
        print(f"  postprocessed: {result.get('postprocessed_path')}")
        print(f"  quality: {result.get('quality_report_path')}")
        print()

    write_json(output_dir / "summary.json", summary)
    print(f"Summary: {output_dir / 'summary.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Тестирует генерацию дайджеста через LLM без Telegram и без сохранения в историю."
    )
    parser.add_argument("--telegram-id", type=int, required=True, help="Telegram ID пользователя из БД бота.")
    parser.add_argument("--period", choices=["today", "3days", "week"], default="today")
    parser.add_argument("--mode", choices=["interests", "selected_sources"], default="interests")
    parser.add_argument("--providers", choices=["both", "gigachat", "chatgpt"], default="both")
    parser.add_argument("--output-dir", default="reports/llm_digest_tests")
    parser.add_argument("--max-tokens", type=int, default=2600)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--chatgpt-model", default=None, help="Опционально: конкретная модель ChatGPT, например gpt-5.4-mini.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
