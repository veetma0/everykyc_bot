"""Native photo panels; only bot artwork may be replaced by navigation."""

from functools import lru_cache
from hashlib import sha256
from html import unescape
from pathlib import Path
import re

from telegram import InputMediaPhoto, Message
from telegram.constants import MessageLimit, ParseMode
from telegram.error import BadRequest

from . import catalog, rich, ui


ART_DIR = Path(__file__).resolve().parents[1] / "assets" / "showcase"
COMMANDS = {
    "/start": "home", "/menu": "home", "/preview": "home", "/client": "home",
    "/services": "catalog", "/help": "help", "/privacy": "help",
    "/profile": "profile", "/status": "profile", "/cancel": "profile",
}


def cover_for(route: str, text: str) -> str | None:
    visible = unescape(re.sub(r"<[^>]+>", "", text))
    if ui.text_units(visible) > MessageLimit.CAPTION_LENGTH:
        return None
    if route.startswith("/"):
        return COMMANDS.get(route)
    parts = route.split(":")
    if len(parts) < 2 or parts[0] not in {"c", "p"}:
        return None
    verb = parts[1]
    if verb == "sections":
        return "catalog"
    if verb in {"home", "catalog", "help", "profile"}:
        return verb
    if verb == "category" and len(parts) > 2:
        return parts[2] if parts[2] in catalog.CATEGORIES else None
    if verb in {"guide", "service", "offer"} and len(parts) > 2:
        offer = catalog.OFFERS.get((parts[2], "standard"))
        return offer.category if offer else "help"
    if verb in {"privacy", "rules"}:
        return "help"
    if verb in {"agree", "create"}:
        return "home" if verb == "agree" else "catalog"
    return "profile"


@lru_cache(maxsize=16)
def asset_digest(path):
    return sha256(path.read_bytes()).hexdigest()


class PanelPhotos:
    def __init__(self, db, bot_id):
        self.db = db
        self.bot_id = bot_id
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS panel_photos (
                bot_id TEXT NOT NULL, digest TEXT NOT NULL, file_id TEXT NOT NULL,
                unique_id TEXT NOT NULL, PRIMARY KEY (bot_id, digest))"""
        )

    def is_panel(self, message):
        if not isinstance(message, Message) or not message.photo:
            return False
        return bool(self.db.execute(
            "SELECT 1 FROM panel_photos WHERE bot_id=? AND unique_id=?",
            (self.bot_id, message.photo[-1].file_unique_id),
        ).fetchone())

    async def show(self, bot, chat_id, source, cover, text, keyboard, *, use_rich=False, embed_buttons=True):
        """Send or edit; caller handles rejected edits and ambiguous network errors."""
        common = dict(chat_id=chat_id, reply_markup=keyboard)
        if source:
            common["message_id"] = source.message_id
        if not cover:
            if use_rich:
                return await rich.show_rich(bot, chat_id, source, text, keyboard, embed_buttons=embed_buttons)
            if source:
                return await bot.edit_message_text(**common, text=text, parse_mode=ParseMode.HTML,
                                                   disable_web_page_preview=True)
            return await bot.send_message(**common, text=text, parse_mode=ParseMode.HTML,
                                          disable_web_page_preview=True, protect_content=True)
        path = ART_DIR / f"{cover}.jpg"
        digest = asset_digest(path)
        cached = self.db.execute(
            "SELECT file_id, unique_id FROM panel_photos WHERE bot_id=? AND digest=?",
            (self.bot_id, digest),
        ).fetchone()
        if not use_rich and source and source.photo and cached and source.photo[-1].file_unique_id == cached["unique_id"]:
            return await bot.edit_message_caption(**common, caption=text, parse_mode=ParseMode.HTML)

        async def photo(value):
            if use_rich:
                return await rich.show_rich(bot, chat_id, source, text, keyboard, photo=value,
                                            embed_buttons=embed_buttons)
            if source:
                return await bot.edit_message_media(
                    **common, media=InputMediaPhoto(
                        value.read_bytes() if isinstance(value, Path) else value,
                        caption=text, parse_mode=ParseMode.HTML, filename=path.name,
                    )
                )
            return await bot.send_photo(**common, photo=value, caption=text, parse_mode=ParseMode.HTML,
                                        protect_content=True)

        try:
            result = await photo(cached["file_id"] if cached else path)
        except BadRequest as exc:
            if not cached or not any(token in str(exc).lower() for token in
                                     ("file reference", "file_reference", "file identifier", "file_id")):
                raise
            result = await photo(path)
        if use_rich:
            sizes = next((b["photo"] for b in rich.blocks(result) if b["type"] == "photo"), ())
        else:
            sizes = [p.to_dict() for p in result.photo]
        if sizes:
            saved = sizes[-1]
            file_id, unique_id = saved["file_id"], saved["file_unique_id"]
            if not cached or (file_id, unique_id) != (cached["file_id"], cached["unique_id"]):
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO panel_photos VALUES(?,?,?,?)",
                                    (self.bot_id, digest, file_id, unique_id))
        return result
