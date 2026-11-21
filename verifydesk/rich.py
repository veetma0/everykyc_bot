"""Native Telegram rich panels, including buttons inside the message bubble."""

from html import escape
from pathlib import Path
from unicodedata import combining

from telegram import InlineKeyboardMarkup, InputFile, Message
from telegram.error import BadRequest, EndPointNotFound


def blocks(message):
    if not isinstance(message, Message):
        return ()
    # PTB 22.8 retains newer Bot API fields in api_kwargs.
    return message.api_kwargs.get("rich_message", {}).get("blocks", ())


# On a 320px screen Telegram Web K gives a rich row 215 CSS pixels, including
# 8px side insets. The 16px labels have 20px padding on each side and an 8px gap.
_ROW_WIDTH = 199
_BUTTON_PADDING = 40
_ROW_GAP = 8
_LABEL_WIDTHS = {
    letter: pixels
    for pixels, letters in (
        (4, "ijl"),
        (5, " !',./:;I\\|"),
        (6, "ft·"),
        (7, "()[]r{}‹›"),
        (8, '"*-`гт'),
        (9, "17?JLaceksvxyzГавзксухьэя"),
        (10, "#$+235<=>FT^_bdghnopqu~бдеёийлнопрцчъ–"),
        (11, "04689ABEKPSVXYZАБВЕЁЗКРТУХЬ"),
        (12, "&CDHNRUДИЙЛНПСЧЭЯы"),
        (13, "GOQwОЦжмю"),
        (14, "MmМФЪфшщ✓"),
        (15, "Ы"),
        (16, "%WШЩ→←—"),
        (17, "@ЖЮ"),
        (19, "№"),
    )
    for letter in letters
}


def _button_width(button):
    # Conservative advance widths for the Latin and Cyrillic labels we ship.
    # Unknown glyphs, including emoji, reserve a full icon slot.
    label_width = sum(
        _LABEL_WIDTHS.get(letter, 20) for letter in button.text
        if letter not in ("\ufe0f", "\ufe0e", "\u200d") and not combining(letter)
    )
    icon_width = 25 if button.icon_custom_emoji_id else 0
    return _BUTTON_PADDING + label_width + icon_width


def layout_rows(source_rows):
    """Keep the order of each keyboard row and reserve space for every label."""
    for source in source_rows:
        row = []
        widths = []
        for button in source:
            width = _button_width(button)
            if row and sum(widths) + width + len(row) * _ROW_GAP > _ROW_WIDTH:
                yield _row_alignment(widths), row
                row, widths = [], []
            row.append(button)
            widths.append(width)
        if row:
            yield _row_alignment(widths), row


def _row_alignment(widths):
    equal_width = max(widths) * len(widths) + (len(widths) - 1) * _ROW_GAP
    return "left" if len(widths) > 1 and equal_width > _ROW_WIDTH else None


def button_rows(keyboard):
    rows = []
    if not isinstance(keyboard, InlineKeyboardMarkup):
        return rows
    for alignment, row in layout_rows(keyboard.inline_keyboard):
        buttons = []
        for button in row:
            if button.callback_data is not None:
                target = f'type="callback_data" data="{escape(button.callback_data)}"'
            elif button.url:
                target = f'type="url" url="{escape(button.url)}"'
            elif button.copy_text:
                target = f'type="copy_text" text="{escape(button.copy_text.text)}"'
            else:
                raise BadRequest("Button requires a conventional inline keyboard")
            label = escape(button.text)
            if button.icon_custom_emoji_id:
                label = f'<tg-emoji emoji-id="{escape(button.icon_custom_emoji_id)}">🔹</tg-emoji> {label}'
            style = f' style="{escape(button.style)}"' if button.style else ""
            buttons.append(f"<tg-button {target}{style}>{label}</tg-button>")
        align = f' align="{alignment}"' if alignment else ""
        rows.append(f"<tg-button-row{align}>" + "".join(buttons) + "</tg-button-row>")
    return rows


async def show_rich(bot, chat_id, source, text, keyboard, *, photo=None):
    """Use PTB's regular request queue and multipart transport for Bot API rich fields."""
    paragraphs = text.split("\n\n") if len(text) > 4096 else [text]
    body = ["<p>" + paragraph.replace("\n", "<br/>") + "</p>" for paragraph in paragraphs if paragraph]
    body.extend(button_rows(keyboard))
    content = {}
    params = {"chat_id": chat_id, "rich_message": content}
    if photo is not None:
        ref = photo
        if isinstance(photo, Path):
            params["cover_file"] = InputFile(photo.read_bytes(), filename=photo.name)
            ref = "attach://cover_file"
        content["media"] = [{"id": "cover", "media": {"type": "photo", "media": ref}}]
        body.insert(0, '<img src="tg://photo?id=cover"/>')
    content["html"] = "".join(body)
    try:
        if source:
            params.pop("chat_id")
            # The rich_message field replaces the text field for an edit.
            return await bot.edit_message_text(
                text=None, chat_id=chat_id, message_id=source.message_id, api_kwargs=params,
            )
        params["protect_content"] = True
        return await bot.do_api_request("sendRichMessage", params, return_type=Message)
    except EndPointNotFound as exc:
        raise BadRequest("Rich messages are unavailable on this Bot API") from exc
