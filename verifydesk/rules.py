"""Full owner-supplied rules, rendered as Telegram-sized pages without omissions."""

from hashlib import sha256
from html import escape
from pathlib import Path
import re

from . import ui


TEXT = Path(__file__).with_name("rules.md").read_text(encoding="utf-8")
VERSION = sha256(TEXT.encode()).hexdigest()[:16]


def _render(paragraph):
    paragraph = escape(paragraph)
    paragraph = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", paragraph, flags=re.S)
    paragraph = re.sub(r"^#{1,3} (.*)$", r"<b>\1</b>", paragraph, flags=re.M)
    return re.sub(r"^- ", "• ", paragraph, flags=re.M)


def _pages():
    pages, current = [], ""
    for paragraph in TEXT.strip().split("\n\n"):
        rendered = _render(paragraph)
        candidate = current + ("\n\n" if current else "") + rendered
        if ui.text_units(candidate) > 3300:
            pages.append(current)
            current = rendered
        else:
            current = candidate
    if current:
        pages.append(current)
    return tuple(pages)


PAGES = _pages()


def card(page, *, accepted=False):
    text = (
        f"<b>Правила оказания услуг</b> · {page + 1}/{len(PAGES)}\n\n"
    )
    if page == 0 and not accepted:
        text += f"Перед началом прочитайте все {len(PAGES)} страницы. Кнопка согласия — в конце.\n\n"
    text += PAGES[page]
    rows, navigation = [], []
    if page:
        navigation.append(ui.action("‹ Назад", f"c:rules:{VERSION}:{page - 1}"))
    if page + 1 < len(PAGES):
        navigation.append(ui.action("Далее ›", f"c:rules:{VERSION}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    if page == len(PAGES) - 1 and not accepted:
        text += "\n\nПрочитали все страницы? Подтвердите согласие с правилами, чтобы открыть каталог."
        rows.append([ui.action("Прочитал и согласен", f"c:agree:{VERSION}")])
    if accepted:
        rows.append([ui.action("Главная", "c:home")])
    return text, ui.Keyboard(rows)
