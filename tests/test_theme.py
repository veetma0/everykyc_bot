import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, TimedOut

from verifydesk import catalog, screens, theme, ui
from verifydesk.bot import deliver


@pytest.fixture(autouse=True)
def reset_theme(tmp_path):
    theme.configure(tmp_path)
    yield
    (tmp_path / "theme.json").unlink(missing_ok=True)
    theme.configure(tmp_path)


def enable(tmp_path):
    (tmp_path / "theme.json").write_text(
        json.dumps({"enabled": True, "icons": {"star": {"id": "123456", "emoji": "⭐"}}})
    )
    theme.configure(tmp_path)


async def test_known_custom_emoji_rejection_falls_back_once(tmp_path):
    enable(tmp_path)
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[BadRequest("Custom emoji unavailable"), SimpleNamespace(message_id=1)]
        )
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Дальше", callback_data="c:catalog", icon_custom_emoji_id="123456")]]
    )
    result, state = await deliver(bot, 101, '<tg-emoji emoji-id="123456">⭐</tg-emoji> Текст', keyboard)
    assert state == "delivered" and result.message_id == 1
    assert bot.send_message.await_count == 2
    second = bot.send_message.await_args_list[-1].kwargs
    assert "tg-emoji" not in second["text"]
    assert second["reply_markup"].inline_keyboard[0][0].icon_custom_emoji_id is None
    assert not theme.enabled()


async def test_ambiguous_network_failure_never_retries_themed_message(tmp_path):
    enable(tmp_path)
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimedOut()))
    _, state = await deliver(bot, 101, theme.mark())
    assert state == "uncertain"
    assert bot.send_message.await_count == 1


async def test_emoji_api_success_without_entity_does_not_enable(tmp_path):
    bot = SimpleNamespace(
        get_forum_topic_icon_stickers=AsyncMock(
            return_value=[SimpleNamespace(custom_emoji_id="123456", emoji="⭐")]
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(entities=[])),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert not supported and not theme.enabled()


async def test_only_confirmed_custom_entities_are_enabled(tmp_path):
    bot = SimpleNamespace(
        get_forum_topic_icon_stickers=AsyncMock(
            return_value=[SimpleNamespace(custom_emoji_id="123456", emoji="⭐")]
        ),
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                entities=[SimpleNamespace(type="custom_emoji", custom_emoji_id="123456")]
            )
        ),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert supported and theme.enabled()
    assert "tg-emoji" in theme.mark()
    assert ui.action("Услуги", "c:catalog", "primary").icon_custom_emoji_id is None
    assert ui.action("Услуги", "c:catalog", "primary").style is None


def test_malformed_theme_is_ignored(tmp_path):
    (tmp_path / "theme.json").write_text("[]")
    theme.configure(tmp_path)
    assert not theme.enabled()


def test_descriptions_fit_telegram_and_all_new_callbacks_fit_limits():
    assert len(catalog.SHORT_DESCRIPTION) <= 120
    assert len(catalog.DESCRIPTION) <= 512
    cards = [screens.catalog_card(), *(screens.offer_card(offer) for offer in catalog.OFFERS.values())]
    for text, keyboard in cards:
        assert ui.text_units(text) < 4096
        for row in keyboard.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64
    assert len(catalog.NETWORK_BY_CODE) == len(catalog.NETWORKS)
