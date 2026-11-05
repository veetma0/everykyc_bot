"""Verified exchange logos, enabled only after Telegram accepts their buttons."""

import json
from pathlib import Path
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError, TelegramError


_path: Path | None = None
_theme: dict = {"enabled": False, "icons": {}}

# IDs fetched with getStickerSet and matched visually to the actual pack artwork.
# See docs/telegram-emoji.md; pack order or its generic emoji is not a brand identifier.
EMOJI_SET = "GentleeChron"
EXCHANGE_ICONS = {
    "bybit": {"id": "5467878076618651228", "emoji": "🤨", "title": "Bybit"},
    "bitget": {"id": "5190501916047589770", "emoji": "🤓", "title": "Bitget"},
    "mexc": {"id": "5253802359531781197", "emoji": "😝", "title": "MEXC"},
    "gate": {"id": "5255891002127824529", "emoji": "🥳", "title": "Gate.io"},
    "htx": {"id": "5246723630657714779", "emoji": "😎", "title": "HTX"},
    "kucoin": {"id": "5246825000475833741", "emoji": "🥸", "title": "KuCoin"},
    "okx": {"id": "5460660847934190864", "emoji": "🤩", "title": "OKX"},
}


def configure(data_dir: Path):
    global _path, _theme
    _path = data_dir / "theme.json"
    try:
        _theme = json.loads(_path.read_text())
        if not isinstance(_theme, dict) or not isinstance(_theme.get("icons", {}), dict):
            raise ValueError()
        _theme["icons"] = {
            key: value
            for key, value in _theme.get("icons", {}).items()
            if isinstance(value, dict)
            and str(value.get("id", "")).isdigit()
            and isinstance(value.get("emoji"), str)
            and 0 < len(value["emoji"]) <= 16
        }
    except (OSError, ValueError):
        _theme = {"enabled": False, "icons": {}}


def enabled():
    return bool(_theme.get("enabled") and _theme.get("icons"))


def disable():
    _theme["enabled"] = False
    _save()


def _save():
    if _path:
        _path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _path.write_text(json.dumps(_theme, ensure_ascii=False))
        _path.chmod(0o600)


def icon_id():
    if not enabled():
        return None
    return next(iter(_theme["icons"].values()))["id"]


def service_icon(service_code: str):
    """Never substitute another service's logo, or an unconfirmed pack icon."""
    if not enabled():
        return None
    expected = EXCHANGE_ICONS.get(service_code)
    accepted = _theme["icons"].get(service_code)
    if expected and accepted and accepted["id"] == expected["id"]:
        return expected["id"]
    return None


def mark():
    if not enabled():
        return "✦"
    icon = next(iter(_theme["icons"].values()))
    return f'<tg-emoji emoji-id="{icon["id"]}">{icon["emoji"]}</tg-emoji>'


def without_custom_emoji(text, keyboard):
    text = re.sub(r"<tg-emoji\b[^>]*>(.*?)</tg-emoji>", r"\1", text, flags=re.DOTALL)
    if isinstance(keyboard, InlineKeyboardMarkup):
        rows = []
        for row in keyboard.inline_keyboard:
            buttons = []
            for button in row:
                data = button.to_dict()
                data.pop("icon_custom_emoji_id", None)
                buttons.append(InlineKeyboardButton.de_json(data, None))
            rows.append(buttons)
        keyboard = InlineKeyboardMarkup(rows)
    return text, keyboard


async def preview(bot, admin_id: int, data_dir: Path):
    global _theme
    configure(data_dir)
    try:
        sticker_set = await bot.get_sticker_set(EMOJI_SET)
        available = {s.custom_emoji_id for s in sticker_set.stickers if s.custom_emoji_id}
        selected = {code: icon for code, icon in EXCHANGE_ICONS.items() if icon["id"] in available}
        if sticker_set.sticker_type != "custom_emoji" or not selected:
            disable()
            return False, "Иконки бирж в GentleeChron не найдены. Оставлены обычные подписи."
        buttons = [
            InlineKeyboardButton(
                icon["title"], callback_data=f"p:service:{code}", icon_custom_emoji_id=icon["id"]
            )
            for code, icon in selected.items()
        ]
        keyboard = InlineKeyboardMarkup([buttons[index:index + 2] for index in range(0, len(buttons), 2)])
        message = await bot.send_message(
            chat_id=admin_id,
            text=(
                "<b>Иконки бирж · GentleeChron</b>\n\n"
                "Проверяем, поддерживает ли Telegram иконки на кнопках этого бота. "
                "Названия бирж остаются видны в любом случае."
            ),
            parse_mode="HTML",
            reply_markup=keyboard,
            protect_content=True,
        )
        accepted = {
            button.icon_custom_emoji_id
            for row in (message.reply_markup.inline_keyboard if message.reply_markup else ())
            for button in row
        }
        icons = {code: icon for code, icon in selected.items() if icon["id"] in accepted}
        _theme = {"enabled": bool(icons), "icons": icons}
        _save()
        return (
            enabled(),
            f"Иконки бирж включены: {len(icons)}."
            if enabled()
            else "Telegram не подтвердил премиум-эмодзи. Оставлены обычные символы.",
        )
    except BadRequest:
        disable()
        return False, "Telegram отклонил премиум-эмодзи. Используется обычное оформление."
    except NetworkError:
        return False, "Telegram не подтвердил проверку оформления. Повтор автоматически не отправляется."
    except TelegramError:
        disable()
        return False, "Премиум-эмодзи сейчас недоступны. Используется обычное оформление."
