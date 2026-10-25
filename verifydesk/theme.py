"""Optional first-party Telegram custom emoji with explicit API acceptance checks."""

import json
from pathlib import Path
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError, TelegramError


_path: Path | None = None
_theme: dict = {"enabled": False, "icons": {}}


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
        stickers = await bot.get_forum_topic_icon_stickers()
        preferred = ("✨", "⭐", "⚡", "💎", "💡", "🛡", "🛡️")
        selected = sorted(
            (s for s in stickers if s.custom_emoji_id and s.emoji in preferred),
            key=lambda s: preferred.index(s.emoji),
        )[:3]
        if not selected:
            disable()
            return False, "Подходящие Telegram-иконки не найдены. Оставлено обычное оформление."
        icons = {str(i): {"id": s.custom_emoji_id, "emoji": s.emoji} for i, s in enumerate(selected)}
        text = " ".join(f'<tg-emoji emoji-id="{s.custom_emoji_id}">{s.emoji}</tg-emoji>' for s in selected)
        message = await bot.send_message(
            chat_id=admin_id,
            text=f"{text} <b>Эврикус · проверка оформления</b>\n\nПремиум-эмодзи включаются, когда Telegram подтверждает их поддержку для этого бота.",
            parse_mode="HTML",
            protect_content=True,
        )
        accepted = {
            entity.custom_emoji_id for entity in (message.entities or ()) if entity.type == "custom_emoji"
        }
        icons = {key: icon for key, icon in icons.items() if icon["id"] in accepted}
        _theme = {"enabled": bool(icons), "icons": icons}
        _save()
        return (
            enabled(),
            "Премиум-эмодзи включены."
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
