from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.core.gigachat_client import ask_chatgpt


async def main() -> None:
    settings = get_settings()
    models = [settings.openai_model, settings.openai_fallback_model]
    seen: set[str] = set()

    for model in models:
        if model in seen:
            continue
        seen.add(model)
        print(f"Testing {model}...")
        answer = await ask_chatgpt(
            "Ответь одним словом: ok",
            model=model,
            max_tokens=10,
            temperature=0,
        )
        print(f"{model}: {answer}")


if __name__ == "__main__":
    asyncio.run(main())
