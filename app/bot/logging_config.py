from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path("logs")
BOT_LOG_FILE = LOG_DIR / "bot.log"
BOT_ERRORS_LOG_FILE = LOG_DIR / "bot-errors.log"
BOT_DEBUG_LOG_FILE = LOG_DIR / "bot-debug.log"
LLM_DEBUG_LOG_FILE = LOG_DIR / "llm-debug.log"

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

    debug_file_handler = RotatingFileHandler(
        BOT_DEBUG_LOG_FILE,
        maxBytes=10_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    debug_file_handler.setLevel(logging.DEBUG)
    debug_file_handler.setFormatter(formatter)

    llm_debug_handler = RotatingFileHandler(
        LLM_DEBUG_LOG_FILE,
        maxBytes=10_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    llm_debug_handler.setLevel(logging.INFO)
    llm_debug_handler.setFormatter(logging.Formatter("%(message)s"))

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[console_handler, bot_file_handler, errors_file_handler, debug_file_handler],
        force=True,
    )

    logging.getLogger("aiogram.event").setLevel(logging.DEBUG)

    llm_debug_logger = logging.getLogger("llm_debug")
    llm_debug_logger.setLevel(logging.INFO)
    llm_debug_logger.handlers.clear()
    llm_debug_logger.addHandler(llm_debug_handler)
    llm_debug_logger.propagate = False
