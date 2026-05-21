from aiogram.utils.keyboard import InlineKeyboardBuilder


VALID_BUTTON_STYLES = {"primary", "success", "danger"}


def normalize_button_style(style: str | None) -> str | None:
    return style if style in VALID_BUTTON_STYLES else None


def button(kb: InlineKeyboardBuilder, *, text: str, callback_data: str, style: str | None = None) -> None:
    normalized = normalize_button_style(style)
    if normalized:
        kb.button(text=text, callback_data=callback_data, style=normalized)
    else:
        kb.button(text=text, callback_data=callback_data)
