"""Profile maintenance must not delay the bot's message handling at startup."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest
from telegram.error import TelegramError

from verifydesk import catalog
from verifydesk.bot import Desk
from verifydesk.config import Config


def profile_bot(overrides=None):
    values = {
        language: {
            "name": catalog.PROFILE_NAME,
            "short_description": catalog.SHORT_DESCRIPTION,
            "description": catalog.DESCRIPTION,
        }
        for language in ("", "ru")
    }
    for (language, field), value in (overrides or {}).items():
        values[language][field] = value
    bot = SimpleNamespace(username="test_bot")
    for field in ("name", "short_description", "description"):
        def getter(language_code="", field=field):
            return SimpleNamespace(**{field: values[language_code][field]})

        setattr(bot, f"get_my_{field}", AsyncMock(side_effect=getter))
        setattr(bot, f"set_my_{field}", AsyncMock(return_value=True))
    return bot


def desk_for(store, tmp_path):
    return Desk(Config("test-token", (9001,), tmp_path), store)


async def test_matching_profiles_in_both_languages_are_never_rewritten(store, tmp_path):
    desk = desk_for(store, tmp_path)
    bot = profile_bot()
    await desk.sync_profile(bot)
    for field in ("name", "short_description", "description"):
        getter = getattr(bot, f"get_my_{field}")
        assert getter.await_args_list == [call(language_code=""), call(language_code="ru")]
        getattr(bot, f"set_my_{field}").assert_not_awaited()


@pytest.mark.parametrize("language", ["", "ru"])
@pytest.mark.parametrize(
    "field,expected",
    [
        ("name", catalog.PROFILE_NAME),
        ("short_description", catalog.SHORT_DESCRIPTION),
        ("description", catalog.DESCRIPTION),
    ],
)
async def test_sync_updates_only_the_changed_field_and_language(store, tmp_path, language, field, expected):
    desk = desk_for(store, tmp_path)
    bot = profile_bot({(language, field): "outdated"})
    await desk.sync_profile(bot)
    getattr(bot, f"set_my_{field}").assert_awaited_once_with(expected, language_code=language)
    for other in {"name", "short_description", "description"} - {field}:
        getattr(bot, f"set_my_{other}").assert_not_awaited()


@pytest.mark.parametrize("error", [TelegramError("profile unavailable"), TimeoutError()])
async def test_profile_failure_does_not_abort_startup(store, tmp_path, monkeypatch, caplog, error):
    desk = desk_for(store, tmp_path)
    bot = SimpleNamespace(
        username="test_bot",
        get_webhook_info=AsyncMock(return_value=SimpleNamespace(url="")),
        set_my_commands=AsyncMock(return_value=True),
    )
    sync = AsyncMock(side_effect=error)
    monkeypatch.setattr(Desk, "sync_profile", sync)
    configure = Mock()
    monkeypatch.setattr("verifydesk.bot.theme.configure", configure)
    store.remember_user(101, 101, "Test client", None)
    order, _ = store.create_ticket(101)
    pending, _ = store.add_message(order.id, "operator", "Test pending answer", 9001, 9001, 1)
    with caplog.at_level(logging.INFO, logger="verifydesk.bot"):
        await desk.post_init(SimpleNamespace(bot=bot))

    sync.assert_awaited_once_with(bot)
    configure.assert_called_once_with(tmp_path)
    assert bot.set_my_commands.await_count == 2
    assert store.db.execute("SELECT delivery FROM messages WHERE id=?", (pending,)).fetchone()[0] == "uncertain"
    assert "Бот запущен: @test_bot" in caplog.text
