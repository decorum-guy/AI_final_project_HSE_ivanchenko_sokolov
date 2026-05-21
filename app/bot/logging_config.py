from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path("logs")
BOT_LOG_FILE = LOG_DIR / "bot.log"
BOT_ERRORS_LOG_FILE = LOG_DIR / "bot-errors.log"

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_bot_logging(log_level: str) -> None:
    LOG_DIR.mkdir(exist_ok=True)

    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    bot_file_handler = RotatingFileHandler(
        BOT_LOG_FILE,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    bot_file_handler.setLevel(level)
    bot_file_handler.setFormatter(formatter)

    errors_file_handler = RotatingFileHandler(
        BOT_ERRORS_LOG_FILE,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    errors_file_handler.setLevel(logging.ERROR)
    errors_file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=level,
        handlers=[console_handler, bot_file_handler, errors_file_handler],
        force=True,
    )
