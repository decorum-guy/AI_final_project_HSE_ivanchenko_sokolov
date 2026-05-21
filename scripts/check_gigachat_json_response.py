from __future__ import annotations

import json
import os
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        os.environ.setdefault(key, value)


def main() -> None:
    load_env_file()

    credentials = os.getenv("GIGACHAT_CREDENTIALS")

    if not credentials:
        print("ERROR: GIGACHAT_CREDENTIALS не найден в .env или env")
        return

    try:
        from gigachat import GigaChat
        from gigachat.models import Chat, Messages, MessagesRole
    except Exception as exc:
        print("ERROR: не удалось импортировать gigachat SDK")
        print(type(exc).__name__, exc)
        return

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "score": {"type": "integer"},
        },
        "required": ["title", "score"],
    }

    chat = Chat(
        model="GigaChat-2",
        messages=[
            Messages(
                role=MessagesRole.USER,
                content=(
                    "Верни JSON-объект с полями title и score. "
                    "title должен быть test, score должен быть 7."
                ),
            )
        ],
        response_format={
            "type": "json_schema",
            "schema": schema,
            "strict": True,
        },
        max_tokens=300,
    )

    print("Проверяю GigaChat response_format=json_schema...")

    try:
        with GigaChat(credentials=credentials, verify_ssl_certs=False) as client:
            response = client.chat(chat)

        raw = response.choices[0].message.content

        print("\nRAW RESPONSE:")
        print(raw)

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            print("\nRESULT: JSON_SCHEMA_UNSUPPORTED_OR_BAD_OUTPUT")
            print("GigaChat ответил, но ответ не является валидным JSON.")
            print("JSON error:", exc)
            return

        print("\nPARSED JSON:")
        print(parsed)

        if parsed.get("title") == "test" and parsed.get("score") == 7:
            print("\nRESULT: SUPPORTED")
            print("response_format=json_schema работает корректно.")
        else:
            print("\nRESULT: PARTIALLY_WORKS")
            print("JSON валидный, но поля не совпали с ожидаемыми.")

    except TypeError as exc:
        print("\nRESULT: SDK_DOES_NOT_SUPPORT_RESPONSE_FORMAT")
        print("Похоже, установленный gigachat SDK не принимает response_format.")
        print(type(exc).__name__, exc)

    except Exception as exc:
        print("\nRESULT: API_OR_MODEL_ERROR")
        print("Запрос с response_format не прошел.")
        print(type(exc).__name__, exc)


if __name__ == "__main__":
    main()