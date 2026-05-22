from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


def print_settings_info() -> None:
    settings = get_settings()

    print("Настройки OpenAI:")
    print(f"OPENAI_BASE_URL: {settings.openai_base_url}")
    print(f"OPENAI_MODEL: {settings.openai_model}")
    print(f"OPENAI_FALLBACK_MODEL: {settings.openai_fallback_model}")
    print(f"AI_PROVIDER: {settings.ai_provider}")
    print(f"OPENAI_API_KEY указан: {bool(settings.openai_api_key)}")
    print()


def build_payload(model: str, temperature: float) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": "Ответь одним словом: ok",
            }
        ],
        "temperature": temperature,
    }

    if model.startswith("gpt-5"):
        payload["max_completion_tokens"] = 10
    else:
        payload["max_tokens"] = 10

    return payload


def print_error_response(response: httpx.Response) -> None:
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


async def test_model(model: str, temperature: float) -> bool:
    settings = get_settings()

    if not settings.openai_api_key:
        print("OPENAI_API_KEY не указан.")
        return False

    print(f"Проверяю модель: {model}")
    print(f"Проверяю temperature: {temperature}")

    payload = build_payload(model, temperature)

    print("Payload:")
    safe_payload = dict(payload)
    print(json.dumps(safe_payload, ensure_ascii=False, indent=2))
    print()

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{settings.openai_base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code >= 400:
        print_error_response(response)
        return False

    data = response.json()

    print("Ответ OpenAI:")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print()

    choices = data.get("choices") or []
    if not choices:
        print("Ошибка: OpenAI вернул пустой choices.")
        return False

    answer = (choices[0].get("message") or {}).get("content", "")

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

    temperatures = [
        0,
        0.2,
    ]

    seen: set[tuple[str, float]] = set()
    has_success = False

    for model in models:
        if not model:
            continue

        for temperature in temperatures:
            key = (model, temperature)
            if key in seen:
                continue

            seen.add(key)
            ok = await test_model(model, temperature)
            has_success = has_success or ok

    if not has_success:
        print("Ни одна модель OpenAI не сработала.")
        sys.exit(1)

    print("Хотя бы один тест OpenAI прошел успешно.")


if __name__ == "__main__":
    asyncio.run(main())