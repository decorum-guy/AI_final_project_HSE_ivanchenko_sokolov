from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.gigachat_client import repair_digest_text
from app.db import queries
from app.db.models import DigestHistory


SAFE_TELEGRAM_LIMIT = 3800
HTML_DIGESTS_DIR = Path("app/data/html_digests")
LONG_DIGEST_TEXT = (
    "К сожалению, дайджест получился слишком объемным для одного сообщения Telegram, "
    "поэтому я собрал его для вас на отдельной странице.\n\n"
    "Можно открыть полный дайджест по кнопке ниже или получить его частями."
)
HISTORY_LONG_DIGEST_TEXT = (
    "Дайджест слишком большой для одного сообщения. Можно открыть страницу сайта с дайджестом "
    "или получить его несколькими сообщениями."
)
SHORTEN_FAILED_TEXT = (
    "Не удалось сделать короткую версию через ИИ. Можно открыть HTML-страницу или получить дайджест частями."
)

DETAILS_HEADER_RE = re.compile(r"<b>\s*Подробно\s*</b>", flags=re.IGNORECASE)
SUMMARY_HEADER_RE = re.compile(r"<b>\s*Очень кратко\s*</b>", flags=re.IGNORECASE)
FINAL_HEADER_RE = re.compile(r"<b>\s*Итог\s*</b>", flags=re.IGNORECASE)
NEWS_BLOCK_RE = re.compile(
    r"(<b>\d+\.\s+.+?</b>\s*.*?)(?=(?:<b>\d+\.\s+.+?</b>)|<b>\s*Итог\s*</b>|$)",
    flags=re.DOTALL | re.IGNORECASE,
)
TITLE_RE = re.compile(r"^\s*(<b>.*?</b>)", flags=re.DOTALL)
BLOCKQUOTE_RE = re.compile(r"<blockquote>(.*?)</blockquote>", flags=re.DOTALL | re.IGNORECASE)
SOURCE_LINK_RE = re.compile(r'<a\s+href="([^"]+)">(.*?)</a>', flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class DigestSections:
    title_html: str
    summary_html: str
    news_blocks: list[str]
    final_html: str


def is_digest_too_long(text: str) -> bool:
    return len(text) > SAFE_TELEGRAM_LIMIT


def public_digest_url(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/digest/{token}"


def digest_page_title(digest: DigestHistory) -> str:
    title = (digest.digest_title or "Дайджест ИнфоПульс").strip()
    return title[:80] or "Дайджест ИнфоПульс"


def _period_label(period: str) -> str:
    return {
        "today": "за сегодня",
        "3days": "за 3 дня",
        "week": "за неделю",
    }.get(period, period)


def _mode_label(source_mode: str) -> str:
    return {
        "selected_sources": "По источникам",
        "interests": "По интересам",
    }.get(source_mode, source_mode)


def _extract_sections(text: str) -> DigestSections:
    normalized = repair_digest_text(text)
    title_match = TITLE_RE.search(normalized)
    title_html = title_match.group(1) if title_match else "<b>📰 Дайджест</b>"

    summary_html = ""
    summary_split = SUMMARY_HEADER_RE.split(normalized, maxsplit=1)
    if len(summary_split) == 2:
        details_split = DETAILS_HEADER_RE.split(summary_split[1], maxsplit=1)
        if len(details_split) == 2:
            summary_html = details_split[0].strip()

    details_split = DETAILS_HEADER_RE.split(normalized, maxsplit=1)
    details_html = details_split[1] if len(details_split) == 2 else normalized
    final_split = FINAL_HEADER_RE.split(details_html, maxsplit=1)
    news_area = final_split[0]
    final_html = final_split[1].strip() if len(final_split) == 2 else ""
    news_blocks = [block.strip() for block in NEWS_BLOCK_RE.findall(news_area) if block.strip()]
    return DigestSections(
        title_html=title_html.strip(),
        summary_html=summary_html.strip(),
        news_blocks=news_blocks,
        final_html=final_html.strip(),
    )


def split_digest_into_parts(text: str) -> list[str]:
    sections = _extract_sections(text)
    news_blocks = sections.news_blocks
    if not news_blocks:
        return [repair_digest_text(text)]

    candidates: list[int] = []
    if len(news_blocks) % 2 == 0:
        candidates.append(2)
    candidates.extend([3, 4])

    for part_count in candidates:
        parts = _build_parts(sections, part_count)
        if parts:
            return parts

    return [repair_digest_text(text)]


def _build_parts(sections: DigestSections, part_count: int) -> list[str] | None:
    groups = _split_evenly(sections.news_blocks, part_count)
    parts: list[str] = []
    for index, group in enumerate(groups, start=1):
        chunks = [f"<b>Часть {index}/{part_count}</b>"]
        if index == 1:
            chunks.append(sections.title_html)
            if sections.summary_html:
                chunks.append("<b>Очень кратко</b>")
                chunks.append(sections.summary_html)
        chunks.append("<b>Подробно</b>")
        chunks.extend(group)
        if index == part_count and sections.final_html:
            chunks.append("<b>Итог</b>")
            chunks.append(sections.final_html)
        part_text = "\n\n".join(chunk for chunk in chunks if chunk).strip()
        if len(part_text) > SAFE_TELEGRAM_LIMIT:
            return None
        parts.append(part_text)
    return parts


def _split_evenly(items: list[str], parts: int) -> list[list[str]]:
    base, remainder = divmod(len(items), parts)
    result: list[list[str]] = []
    index = 0
    for part_index in range(parts):
        size = base + (1 if part_index < remainder else 0)
        if size <= 0:
            continue
        result.append(items[index : index + size])
        index += size
    return result


async def ensure_digest_html(session: AsyncSession, digest: DigestHistory) -> tuple[str, str]:
    token = digest.html_token or secrets.token_urlsafe(18)
    path = HTML_DIGESTS_DIR / f"{token}.html"
    html = render_digest_page(digest, token)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    resolved_path = str(path.resolve())
    if digest.html_token != token or digest.html_path != resolved_path:
        await queries.save_digest_html(session, digest, token, resolved_path)
    return token, resolved_path


def render_digest_page(digest: DigestHistory, token: str | None = None) -> str:
    sections = _extract_sections(digest.digest_text)
    summary_inner = _strip_outer_blockquote(sections.summary_html) or "Краткий обзор дайджеста недоступен."
    final_inner = _strip_outer_blockquote(sections.final_html) or "Короткий вывод не был сформирован."
    cards_html = "\n".join(_render_news_card(block) for block in sections.news_blocks) or (
        '<article class="news-card"><p class="muted">Подробные блоки новостей пока недоступны.</p></article>'
    )
    created_at = digest.created_at.strftime("%d.%m.%Y %H:%M") if isinstance(digest.created_at, datetime) else ""
    title_text = _strip_tags(sections.title_html) or "Дайджест ИнфоПульс"
    page_url = public_digest_url(token or digest.html_token or "")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(digest_page_title(digest))}</title>
  <meta name="description" content="{escape(title_text)}">
  <style>
    :root {{
      --bg: #f6f1e8;
      --paper: rgba(255, 252, 247, 0.92);
      --paper-strong: #fffdf8;
      --line: rgba(116, 94, 66, 0.18);
      --text: #1e1b16;
      --muted: #6a5e4f;
      --accent: #0f766e;
      --accent-soft: rgba(15, 118, 110, 0.12);
      --shadow: 0 18px 60px rgba(61, 44, 27, 0.12);
      --radius: 26px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 28%),
        radial-gradient(circle at top right, rgba(194, 65, 12, 0.10), transparent 24%),
        linear-gradient(180deg, #f7efe3 0%, #f3eee7 100%);
    }}
    .shell {{
      width: min(1100px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 48px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.82), rgba(255,248,238,0.94));
      border: 1px solid var(--line);
      border-radius: 32px;
      box-shadow: var(--shadow);
      padding: 28px;
      backdrop-filter: blur(12px);
    }}
    .eyebrow {{
      display: inline-flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 13px;
      font-weight: 600;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(28px, 5vw, 46px);
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr);
      gap: 20px;
      margin-top: 20px;
    }}
    .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 24px;
      box-shadow: var(--shadow);
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .summary-quote, .final-quote {{
      margin: 0;
      padding: 18px 20px;
      border-left: 4px solid var(--accent);
      background: rgba(255,255,255,0.78);
      border-radius: 18px;
      line-height: 1.7;
      color: var(--text);
    }}
    .news-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-top: 20px;
    }}
    .news-card {{
      background: var(--paper-strong);
      border: 1px solid rgba(116, 94, 66, 0.14);
      border-radius: 24px;
      padding: 22px;
      box-shadow: 0 12px 30px rgba(61, 44, 27, 0.08);
    }}
    .news-card h3 {{
      margin: 0 0 16px;
      font-size: 21px;
      line-height: 1.3;
    }}
    .news-card p {{
      margin: 0 0 12px;
      line-height: 1.65;
      color: var(--text);
    }}
    .news-card .label {{
      font-weight: 700;
    }}
    .news-card a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid rgba(15, 118, 110, 0.25);
    }}
    .news-card a:hover {{
      border-bottom-color: currentColor;
    }}
    .meta {{
      display: grid;
      gap: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .meta strong {{
      color: var(--text);
    }}
    .muted {{
      color: var(--muted);
    }}
    .footer {{
      margin-top: 20px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
    }}
    @media (max-width: 900px) {{
      .grid, .news-grid {{
        grid-template-columns: 1fr;
      }}
      .shell {{
        width: min(100% - 20px, 1100px);
        padding-top: 16px;
      }}
      .hero, .panel, .news-card {{
        border-radius: 22px;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="eyebrow">
        <span class="chip">ИнфоПульс</span>
        <span class="chip">{escape(_mode_label(digest.source_mode))}</span>
        <span class="chip">{escape(_period_label(digest.period))}</span>
      </div>
      <h1>{escape(title_text)}</h1>
    </section>

    <section class="grid">
      <article class="panel">
        <h2>Очень кратко</h2>
        <blockquote class="summary-quote">{summary_inner}</blockquote>
      </article>
      <aside class="panel">
        <h2>О дайджесте</h2>
        <div class="meta">
          <div><strong>Создан:</strong> {escape(created_at or "н/д")}</div>
          <div><strong>Формат:</strong> Telegram HTML + web-страница</div>
          <div><strong>Ссылка:</strong> <a href="{escape(page_url, quote=True)}">Открыть этот дайджест</a></div>
        </div>
      </aside>
    </section>

    <section class="panel" style="margin-top: 20px;">
      <h2>Подробно</h2>
      <div class="news-grid">
        {cards_html}
      </div>
    </section>

    <section class="panel" style="margin-top: 20px;">
      <h2>Итог</h2>
      <blockquote class="final-quote">{final_inner}</blockquote>
    </section>

    <div class="footer">Страница сохранена в постоянном архиве дайджестов ИнфоПульс.</div>
  </main>
</body>
</html>
"""


def _render_news_card(block: str) -> str:
    title_match = re.search(r"<b>(\d+\.\s+.+?)</b>", block, flags=re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Новость"
    short = _capture_block_value(block, "Кратко")
    why = _capture_block_value(block, "Почему важно")
    source_html = _capture_source_line(block)
    return (
        '<article class="news-card">'
        f"<h3>{escape(_strip_tags(title))}</h3>"
        f'<p><span class="label">Кратко:</span> {short}</p>'
        f'<p><span class="label">Почему важно:</span> {why}</p>'
        f"<p>{source_html}</p>"
        "</article>"
    )


def _capture_block_value(block: str, label: str) -> str:
    pattern = re.compile(
        rf"<b>\s*{re.escape(label)}\s*:\s*</b>\s*(.*?)(?=(?:<b>\s*(?:Кратко|Почему важно)\s*:\s*</b>|Источник:|$))",
        flags=re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(block)
    if not match:
        return "—"
    return match.group(1).strip()


def _capture_source_line(block: str) -> str:
    match = re.search(r"Источник:\s*(.*)$", block, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return '<span class="muted">Источник не указан</span>'
    source_body = match.group(1).strip().splitlines()[0].strip()
    link_match = SOURCE_LINK_RE.search(source_body)
    if link_match:
        href, title = link_match.groups()
        return f'Источник: <a href="{escape(href, quote=True)}">{title.strip()}</a>'
    return f"Источник: {source_body}"


def _strip_outer_blockquote(value: str) -> str:
    match = BLOCKQUOTE_RE.search(value or "")
    return match.group(1).strip() if match else value.strip()


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()
