from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


logger = logging.getLogger("llm_debug")

PROMPT_PREVIEW_LIMIT = 1000
ANSWER_PREVIEW_LIMIT = 8000


def _preview(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def response_format_type(response_format: dict[str, Any] | None) -> str | None:
    if not response_format:
        return None
    value = response_format.get("type")
    return str(value) if value else None


def log_llm_event(
    *,
    task: str,
    event: str,
    provider: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    response_format: dict[str, Any] | None = None,
    raw_answer: str | None = None,
    parsed_summary: dict[str, Any] | None = None,
    error: BaseException | str | None = None,
    fallback_reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "event": event,
        "provider": provider,
        "model": model,
        "prompt_length": len(prompt) if prompt is not None else None,
        "prompt_preview": _preview(prompt, PROMPT_PREVIEW_LIMIT),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format_type": response_format_type(response_format),
        "raw_answer_preview": _preview(raw_answer, ANSWER_PREVIEW_LIMIT),
        "parsed_result_summary": parsed_summary,
        "fallback_reason": fallback_reason,
    }
    if error is not None:
        payload["error"] = str(error)
        payload["error_type"] = type(error).__name__ if isinstance(error, BaseException) else "str"
    if extra:
        payload["extra"] = extra

    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
