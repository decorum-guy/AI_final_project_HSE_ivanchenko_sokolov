from app.core.rss import NewsItem


def filter_by_interests(items: list[NewsItem], interests_text: str | None) -> list[NewsItem]:
    if not interests_text:
        return items[:20]
    words = {word.lower().strip(" ,.;:!?") for word in interests_text.split() if len(word) > 2}
    if not words:
        return items[:20]
    matched = [
        item
        for item in items
        if words & set((item.title + " " + item.summary + " " + item.source).lower().split())
    ]
    return (matched or items)[:20]

