"""Full owner-supplied rules, rendered as Telegram-sized pages without omissions."""

from hashlib import sha256
from html import escape
from pathlib import Path
import re

from . import ui
from .language import FULFILLMENT, render


TEXT = Path(__file__).with_name("rules.md").read_text(encoding="utf-8")
TEXT_EN = Path(__file__).with_name("rules_en.md").read_text(encoding="utf-8")
# Both languages present the same agreement. Existing consent refers to the source text.
VERSION = sha256(TEXT.encode()).hexdigest()[:16]


def _render(paragraph):
    paragraph = escape(paragraph)
    paragraph = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", paragraph, flags=re.S)
    paragraph = re.sub(r"^#{1,3} (.*)$", r"<b>\1</b>", paragraph, flags=re.M)
    return re.sub(r"^- ", "• ", paragraph, flags=re.M)


def _pages(source):
    pages, current = [], ""
    for paragraph in source.strip().split("\n\n"):
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


PAGES = _pages(TEXT)
PAGES_EN = _pages(TEXT_EN)


def pages(language="ru"):
    return PAGES_EN if language == "en" else PAGES


def full_card(*, accepted=False, language="ru"):
    """Show the complete versioned text and its single action in one rich message."""
    button = (
        ui.action("Home" if language == "en" else "Главная", "c:home")
        if accepted else ui.action("I accept the rules" if language == "en" else "Принимаю правила",
                                   f"c:agree_full:{VERSION}", "primary")
    )
    return "\n\n".join((render(FULFILLMENT, language), *pages(language))), ui.Keyboard([[button]])


def card(page, *, accepted=False, language="ru"):
    english = language == "en"
    content = pages(language)
    title = "Terms of service" if english else "Правила оказания услуг"
    text = f"<b>{title}</b> · {page + 1}/{len(content)}\n\n"
    if page == 0:
        text += render(FULFILLMENT, language) + "\n\n"
        if not accepted:
            text += (
                f"Read all {len(content)} pages. The button to accept is on the last page."
                if english else f"Перед началом прочитайте все {len(content)} страницы. Кнопка согласия — в конце."
            ) + "\n\n"
    text += content[page]
    rows, navigation = [], []
    if page:
        navigation.append(ui.action("‹ Back" if english else "‹ Назад", f"c:rules:{VERSION}:{page - 1}"))
    if page + 1 < len(content):
        navigation.append(ui.action("Next ›" if english else "Далее ›", f"c:rules:{VERSION}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    if page == len(content) - 1 and not accepted:
        text += "\n\n" + ("Accept the rules to open the catalog." if english else
                         "Прочитали все страницы? Подтвердите согласие с правилами, чтобы открыть каталог.")
        rows.append([ui.action("I accept the rules" if english else "Принимаю правила", f"c:agree:{VERSION}")])
    if accepted:
        rows.append([ui.action("Home" if english else "Главная", "c:home")])
    return text, ui.Keyboard(rows)
