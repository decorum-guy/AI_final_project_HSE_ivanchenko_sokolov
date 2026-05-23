from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


logger = logging.getLogger("llm_debug")

PROMPT_PREVIEW_LIMIT = 1000
ANSWER_PREVIEW_LIMIT = 8000
FULL_LOG_DIR = Path("logs/llm_full")


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


def new_request_id() -> str:
    return uuid4().hex


def _safe_part(value: str | None) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "other").strip("_")
    return text[:80] or "other"


def _file_prefix(task: str, request_id: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return f"{timestamp}_{_safe_part(task)}_{request_id}"


def _write_full_text(task: str, request_id: str, suffix: str, text: str) -> str:
    FULL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = FULL_LOG_DIR / f"{_file_prefix(task, request_id)}_{suffix}.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def write_json_artifact(task: str, request_id: str, suffix: str, payload: Any) -> str:
    FULL_LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = FULL_LOG_DIR / f"{_file_prefix(task, request_id)}_{suffix}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path)


def log_llm_event(
    *,
    task: str,
    event: str,
    request_id: str | None = None,
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
    duration_ms: int | None = None,
    input_items_path: str | None = None,
    input_items_count: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = request_id or new_request_id()
    prompt_path = _write_full_text(task, request_id, "prompt", prompt) if event == "request" and prompt is not None else None
    response_path = _write_full_text(task, request_id, "response", raw_answer) if raw_answer is not None else None

    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": request_id,
        "task": task,
        "event": event,
        "provider": provider,
        "model": model,
        "prompt_length": len(prompt) if prompt is not None else None,
        "response_length": len(raw_answer) if raw_answer is not None else None,
        "prompt_preview": _preview(prompt, PROMPT_PREVIEW_LIMIT),
        "prompt_path": prompt_path,
        "response_path": response_path,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format_type": response_format_type(response_format),
        "raw_answer_preview": _preview(raw_answer, ANSWER_PREVIEW_LIMIT),
        "parsed_result_summary": parsed_summary,
        "fallback_reason": fallback_reason,
        "duration_ms": duration_ms,
        "input_items_path": input_items_path,
        "input_items_count": input_items_count,
    }
    if error is not None:
        payload["error"] = str(error)
        payload["error_type"] = type(error).__name__ if isinstance(error, BaseException) else "str"
    if extra:
        payload["extra"] = extra

    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
    return payload
