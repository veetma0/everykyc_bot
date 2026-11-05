"""Exchange icon rendering and recovery without duplicate Telegram messages."""

import json

import pytest
from telegram.error import BadRequest, TimedOut

from verifydesk import screens, theme, ui

from .conftest import CLIENT


@pytest.fixture(autouse=True)
def clear_theme(tmp_path):
    theme.configure(tmp_path)
    yield
    (tmp_path / "theme.json").unlink(missing_ok=True)
    theme.configure(tmp_path)


def approve_bybit(tmp_path):
    (tmp_path / "theme.json").write_text(json.dumps({
        "enabled": True, "icons": {"bybit": theme.EXCHANGE_ICONS["bybit"]},
    }))
    theme.configure(tmp_path)


@pytest.mark.parametrize("prefix", ["c", "p"])
def test_service_button_uses_only_its_approved_logo(tmp_path, prefix):
    approve_bybit(tmp_path)
    label = "Bybit · $50"
    button = ui.action(label, f"{prefix}:service:bybit")
    assert button.text == label
    assert button.icon_custom_emoji_id == theme.EXCHANGE_ICONS["bybit"]["id"]
    assert button.style is None
    assert ui.action("MEXC · $45", f"{prefix}:service:mexc").icon_custom_emoji_id is None
    assert ui.action("Kraken · $45", f"{prefix}:service:kraken").icon_custom_emoji_id is None
    assert ui.action("Каталог", f"{prefix}:catalog").icon_custom_emoji_id is None
    theme.disable()
    assert ui.action(label, f"{prefix}:service:bybit").icon_custom_emoji_id is None


def test_preview_preserves_logo_and_label_while_rewriting_navigation(tmp_path):
    approve_bybit(tmp_path)
    _, keyboard = screens.category_card("exchanges")
    before = next(button for row in keyboard.inline_keyboard for button in row
                  if button.callback_data == "c:service:bybit")
    preview = screens.preview_markup(keyboard)
    after = next(button for row in preview.inline_keyboard for button in row
                 if button.callback_data == "p:service:bybit")
    assert before.icon_custom_emoji_id == theme.EXCHANGE_ICONS["bybit"]["id"]
    assert after.icon_custom_emoji_id == before.icon_custom_emoji_id
    assert after.text == before.text
    assert before.callback_data == "c:service:bybit"


def has_icons(params):
    return any(button.get("icon_custom_emoji_id")
               for row in params.get("reply_markup", {}).get("inline_keyboard", [])
               for button in row)


async def test_rejected_icon_retries_same_card_without_sending_new_message(env, tmp_path, monkeypatch):
    approve_bybit(tmp_path)
    original = env.request.do_request

    async def reject_icons(url, method, request_data=None, **kwargs):
        name = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        if name == "editMessageText" and has_icons(params):
            env.request.calls.append((name, params))
            raise BadRequest("CUSTOM_EMOJI_INVALID")
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", reject_icons)
    await env.callback(CLIENT, "c:category:exchanges", card=8123)
    messages = [(name, params) for name, params in env.request.calls
                if name in {"editMessageText", "sendMessage"}]
    assert [name for name, _ in messages] == ["editMessageText", "editMessageText"]
    first, second = [params for _, params in messages]
    assert first["message_id"] == second["message_id"] == 8123
    assert first["chat_id"] == second["chat_id"] == CLIENT
    assert first["text"] == second["text"]
    assert has_icons(first) and not has_icons(second)
    assert not theme.enabled()


@pytest.mark.parametrize("reject_first", [False, True])
async def test_uncertain_edit_never_sends_another_message(env, tmp_path, monkeypatch, reject_first):
    approve_bybit(tmp_path)
    original = env.request.do_request

    async def uncertain_edit(url, method, request_data=None, **kwargs):
        name = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        if name == "editMessageText":
            env.request.calls.append((name, params))
            if reject_first and has_icons(params):
                raise BadRequest("CUSTOM_EMOJI_INVALID")
            raise TimedOut()
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", uncertain_edit)
    await env.callback(CLIENT, "c:category:exchanges", card=8123)
    messages = [(name, params) for name, params in env.request.calls
                if name in {"editMessageText", "sendMessage"}]
    assert [name for name, _ in messages] == ["editMessageText"] * (2 if reject_first else 1)
    assert all(params["message_id"] == 8123 for _, params in messages)
