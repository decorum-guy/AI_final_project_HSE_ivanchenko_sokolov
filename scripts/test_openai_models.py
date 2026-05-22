from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.core.gigachat_client import ask_chatgpt


def print_settings_info() -> None:
    settings = get_settings()

    print("Настройки OpenAI:")
    print(f"OPENAI_BASE_URL: {settings.openai_base_url}")
    print(f"OPENAI_MODEL: {settings.openai_model}")
    print(f"OPENAI_FALLBACK_MODEL: {settings.openai_fallback_model}")
    print(f"AI_PROVIDER: {settings.ai_provider}")
    print(f"OPENAI_API_KEY указан: {bool(settings.openai_api_key)}")
    print()


def print_http_error(error: httpx.HTTPStatusError) -> None:
    response = error.response

    print("Ошибка HTTP от OpenAI:")
    print(f"Код статуса: {response.status_code}")
    print(f"URL запроса: {response.request.url}")
    print()

    print("Текст ответа:")
    print(response.text)
    print()

    try:
        payload = response.json()
    except json.JSONDecodeError:
        return

    print("Ответ в формате JSON:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()


async def test_model(model: str) -> bool:
    print(f"Проверяю модель: {model}")

    try:
        answer = await ask_chatgpt(
            "Ответь одним словом: ok",
            model=model,
            max_tokens=10,
            temperature=0,
        )
    except httpx.HTTPStatusError as error:
        print_http_error(error)
        return False
    except Exception:
        print("Неожиданная ошибка:")
        traceback.print_exc()
        print()
        return False

    print(f"Ответ модели {model}: {answer}")
    print()
    return True


async def main() -> None:
    settings = get_settings()
    print_settings_info()

    models = [
        settings.openai_model,
        settings.openai_fallback_model,
    ]

    seen: set[str] = set()
    has_success = False

    for model in models:
        if not model or model in seen:
            continue

        seen.add(model)
        ok = await test_model(model)
        has_success = has_success or ok

    if not has_success:
        print("Ни одна модель OpenAI не сработала.")
        sys.exit(1)

    print("Хотя бы одна модель OpenAI работает.")


if __name__ == "__main__":
    asyncio.run(main())