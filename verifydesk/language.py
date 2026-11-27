"""Render bot-authored copy for a recipient while preserving quoted customer data."""

from functools import lru_cache
from html import escape, unescape
import re

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup

FULFILLMENT = (
    "После подтверждения оплаты мы начинаем искать специалиста для вашего заказа. "
    "Результат придёт не сразу. Срок согласуем с вами до оплаты."
)
PAID_FULFILLMENT = (
    "Оплата подтверждена. Подбор специалиста начался. "
    "Новости по заказу появятся здесь, результат — в согласованный срок."
)
_EXTRA = {
    FULFILLMENT: "Once payment is confirmed, we start looking for a specialist for your order. "
                 "Delivery takes time. We agree on a timeframe with you before you pay.",
    PAID_FULFILLMENT: "Payment confirmed. We’ve started looking for a specialist. "
                      "You’ll get updates here and the result within the agreed timeframe.",
    "Язык интерфейса": "Interface language",
    "Выберите язык интерфейса.": "Choose your interface language.",
    "Сменить язык": "Change language",
}
_LITERAL = re.compile(r"<vd-literal>(.*?)</vd-literal>", re.DOTALL)
_NUMBER = re.compile(r"\{(\w+)\}")


def verbatim(value: str):
    """Quote untrusted text before mixing it with translatable HTML or button labels."""
    return f"<vd-literal>{escape(value)}</vd-literal>"


@lru_cache(maxsize=1)
def _catalog():
    from . import english_bot, english_screens

    entries = {**english_bot.TRANSLATIONS, **english_screens.TRANSLATIONS, **_EXTRA}
    buttons = {**english_screens.BUTTON_TRANSLATIONS, **english_bot.BUTTON_TRANSLATIONS}
    alternatives, templates = [], {}
    for source in sorted(entries, key=len, reverse=True):
        parts, fields, end = [], [], 0
        for token in _NUMBER.finditer(source):
            field = token[1]
            group = f"n{len(templates)}_{field}"
            parts.extend((re.escape(source[end:token.start()]), fr"(?P<{group}>[0-9]+)"))
            fields.append((field, group))
            end = token.end()
        parts.append(re.escape(source[end:]))
        expression = "".join(parts)
        if fields:
            key = f"t{len(templates)}"
            templates[key] = (entries[source], fields)
            expression = f"(?P<{key}>{expression})"
        left = r"(?<![А-Яа-яЁё])" if source[0].isalpha() else ""
        right = r"(?![А-Яа-яЁё])" if source[-1].isalpha() else ""
        alternatives.append(left + expression + right)
    # Skip unrelated characters in mixed-language text before trying every phrase.
    initials = re.escape("".join(sorted({phrase[0] for phrase in entries})))
    pattern = re.compile(f"(?=[{initials}])(?:" + "|".join(alternatives) + ")")
    return pattern, entries, templates, buttons


def render(value: str, language: str, *, button=False, plain=False) -> str:
    if language == "en" and button:
        override = _catalog()[3].get(value)
        if override is not None:
            return override

    def translate(chunk):
        if language != "en" or not re.search("[А-Яа-яЁё]", chunk):
            return chunk
        pattern, entries, templates, _ = _catalog()

        def replace(match):
            if match.lastgroup is None:
                return entries[match[0]]
            template, fields = templates[match.lastgroup]
            return template.format_map({field: match[group] for field, group in fields})

        return pattern.sub(replace, chunk)

    parts, start = [], 0
    for item in _LITERAL.finditer(value):
        parts.extend((translate(value[start:item.start()]), unescape(item[1]) if plain else item[1]))
        start = item.end()
    parts.append(translate(value[start:]))
    return "".join(parts)


def markup(keyboard, language):
    if isinstance(keyboard, ForceReply) and keyboard.input_field_placeholder:
        data = keyboard.to_dict()
        data["input_field_placeholder"] = render(data["input_field_placeholder"], language, plain=True)
        return ForceReply.de_json(data, None)
    if not isinstance(keyboard, InlineKeyboardMarkup):
        return keyboard
    rows = []
    for row in keyboard.inline_keyboard:
        buttons = []
        for item in row:
            label = render(item.text, language, button=True, plain=True)
            buttons.append(item if label == item.text else InlineKeyboardButton.de_json(
                {**item.to_dict(), "text": label}, None,
            ))
        rows.append(buttons)
    return InlineKeyboardMarkup(rows)
