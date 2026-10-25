"""First recognized /start source; no inference of search queries or impressions.

Only allowlisted campaign codes are retained. A user's first recognized source
is immutable, even after direct or differently tagged starts. Tickets snapshot
that source at creation; pre-existing tickets are never attributed retroactively.
"""

from html import escape


SOURCES = {
    "src_tg_post": "Публикации в Telegram",
    "src_profile": "Ссылка в профиле",
    "src_site_claude": "Страница о Claude",
    "src_site_alipay": "Страница об Alipay",
    "src_partner": "Партнёрская ссылка",
}


def start_source(text: str) -> str | None:
    parts = text.split()
    if len(parts) != 2 or parts[0].split("@")[0].lower() != "/start":
        return None
    payload = parts[1]
    return payload if len(payload) <= 64 and payload in SOURCES else None


def report(rows) -> str:
    lines = [
        "<b>Источники заявок</b>",
        "За всё время · запуски с меткой. Входы операторов исключены.",
    ]
    if not rows:
        lines.append("Запусков с распознанной меткой пока нет.")
    for row in rows:
        lines.append(
            f"<b>{escape(SOURCES[row['source_code']])}</b>\n"
            f"Запустили: {row['started_users']} · С заявкой: {row['requested_users']} · "
            f"Заявок: {row['tickets']}"
        )
    lines += [
        "Запуски и клиенты считаются по людям, заявки — по обращениям.",
        "Учитывается первая распознанная метка. Старые заявки не приписываются новой ссылке.",
        "Это не просмотры, позиции в поиске или оплаты. Непомеченные входы здесь не учтены.",
    ]
    return "\n\n".join(lines)
