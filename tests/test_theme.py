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
        [[InlineKeyboardButton("Дальше", callback_data="c:catalog", icon_custom_emoji_id="123456", style="primary")]]
    )
    result, state = await deliver(bot, 101, '<tg-emoji emoji-id="123456">⭐</tg-emoji> Текст', keyboard)
    assert state == "delivered" and result.message_id == 1
    assert bot.send_message.await_count == 2
    second = bot.send_message.await_args_list[-1].kwargs
    assert "tg-emoji" not in second["text"]
    assert second["reply_markup"].inline_keyboard[0][0].icon_custom_emoji_id is None
    assert second["reply_markup"].inline_keyboard[0][0].style == "primary"
    assert not theme.enabled()


async def test_ambiguous_network_failure_never_retries_themed_message(tmp_path):
    enable(tmp_path)
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=TimedOut()))
    _, state = await deliver(bot, 101, theme.mark())
    assert state == "uncertain"
    assert bot.send_message.await_count == 1


async def test_emoji_api_success_without_entity_does_not_enable(tmp_path):
    bot = SimpleNamespace(
        get_sticker_set=AsyncMock(
            return_value=SimpleNamespace(
                sticker_type="custom_emoji",
                stickers=[SimpleNamespace(custom_emoji_id=theme.EXCHANGE_ICONS["bybit"]["id"])],
            )
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(reply_markup=None)),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert not supported and not theme.enabled()
    assert theme.service_icon("bybit") is None


async def test_only_returned_pack_button_icons_are_enabled_and_survive_restart(tmp_path):
    bybit = theme.EXCHANGE_ICONS["bybit"]["id"]
    mexc = theme.EXCHANGE_ICONS["mexc"]["id"]
    bot = SimpleNamespace(
        get_sticker_set=AsyncMock(
            return_value=SimpleNamespace(
                sticker_type="custom_emoji",
                stickers=[SimpleNamespace(custom_emoji_id=bybit), SimpleNamespace(custom_emoji_id=mexc)],
            )
        ),
        send_message=AsyncMock(
            return_value=SimpleNamespace(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Bybit", callback_data="c:service:bybit", icon_custom_emoji_id=bybit),
                    InlineKeyboardButton("MEXC", callback_data="c:service:mexc"),
                ]])
            )
        ),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert supported and theme.enabled()
    bot.get_sticker_set.assert_awaited_once_with("GentleeChron")
    submitted = bot.send_message.await_args.kwargs["reply_markup"]
    assert all(button.callback_data.startswith("p:service:")
               for row in submitted.inline_keyboard for button in row)
    assert theme.service_icon("bybit") == bybit
    assert theme.service_icon("mexc") is None
    assert theme.service_icon("unknown") is None
    theme.configure(tmp_path)
    assert theme.service_icon("bybit") == bybit
    assert ui.action("Услуги", "c:catalog", "primary").icon_custom_emoji_id is None
    assert ui.action("Услуги", "c:catalog", "primary").style == "primary"


async def test_unrecognized_pack_artwork_is_never_guessed(tmp_path):
    bot = SimpleNamespace(
        get_sticker_set=AsyncMock(return_value=SimpleNamespace(
            sticker_type="custom_emoji",
            stickers=[SimpleNamespace(custom_emoji_id="123456", emoji="⭐")],
        )),
        send_message=AsyncMock(),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert not supported
    bot.send_message.assert_not_awaited()


async def test_pack_rejection_disables_exchange_icons(tmp_path):
    enable(tmp_path)
    bot = SimpleNamespace(get_sticker_set=AsyncMock(side_effect=BadRequest("STICKERSET_INVALID")))
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert not supported and not theme.enabled()


async def test_ambiguous_preview_delivery_is_not_repeated(tmp_path):
    bot = SimpleNamespace(
        get_sticker_set=AsyncMock(return_value=SimpleNamespace(
            sticker_type="custom_emoji",
            stickers=[SimpleNamespace(custom_emoji_id=theme.EXCHANGE_ICONS["bybit"]["id"])],
        )),
        send_message=AsyncMock(side_effect=TimedOut()),
    )
    supported, _ = await theme.preview(bot, 101, tmp_path)
    assert not supported and not theme.enabled()
    bot.send_message.assert_awaited_once()


def test_service_logo_must_match_verified_service_and_be_enabled(tmp_path):
    icon = theme.EXCHANGE_ICONS["bybit"]
    (tmp_path / "theme.json").write_text(json.dumps({
        "enabled": True, "icons": {"mexc": icon},
    }))
    theme.configure(tmp_path)
    assert theme.service_icon("mexc") is None
    assert theme.service_icon("bybit") is None
    (tmp_path / "theme.json").write_text(json.dumps({
        "enabled": False, "icons": {"bybit": icon},
    }))
    theme.configure(tmp_path)
    assert theme.service_icon("bybit") is None


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
