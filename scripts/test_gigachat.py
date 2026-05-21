from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings


DEFAULT_PROMPT = "Ответь одним коротким предложением: GigaChat подключен и работает."


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def extract_answer(response) -> str:
    choices = getattr(response, "choices", None)
    if not choices:
        return str(response)

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    if message is None and isinstance(first_choice, dict):
        message = first_choice.get("message")

    if isinstance(message, dict):
        return str(message.get("content", "")).strip()

    content = getattr(message, "content", "")
    return str(content).strip()


async def run_test(prompt: str, model: str | None, verify_ssl: bool) -> int:
    try:
        from gigachat import GigaChat
        from gigachat.models import Chat, Messages, MessagesRole
    except ImportError as exc:
        print(f"GigaChat SDK is not installed: {exc}")
        return 1

    load_dotenv(PROJECT_ROOT / ".env")
    settings = get_settings()
    credentials = settings.gigachat_credentials

    if not credentials:
        print("GIGACHAT_CREDENTIALS is empty. Add it to .env and run the script again.")
        return 1

    print("GigaChat credentials: configured")
    print(f"Credentials mask: {mask_secret(credentials)}")
    print(f"Model: {model or 'SDK default'}")
    print(f"SSL verification: {'on' if verify_ssl else 'off'}")

    payload = Chat(
        model=model,
        messages=[
            Messages(
                role=MessagesRole.USER,
                content=prompt,
            )
        ],
        max_tokens=80,
        temperature=0.2,
    )

    try:
        async with GigaChat(
            credentials=credentials,
            verify_ssl_certs=verify_ssl,
            timeout=30,
        ) as client:
            response = await client.achat(payload)
    except Exception as exc:
        print(f"GigaChat request failed: {type(exc).__name__}: {exc}")
        return 1

    answer = extract_answer(response)
    print()
    print("GigaChat response:")
    print(answer or "<empty response>")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Simple GigaChat connectivity test using GIGACHAT_CREDENTIALS from .env"
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt to send to GigaChat",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model name. If omitted, the SDK default is used.",
    )
    parser.add_argument(
        "--verify-ssl",
        action="store_true",
        help="Enable SSL certificate verification. By default it is disabled for easier local testing.",
    )

    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_test(args.prompt, args.model, args.verify_ssl)))


if __name__ == "__main__":
    main()
