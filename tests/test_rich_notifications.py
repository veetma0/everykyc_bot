"""Customer status and review notices use native button rows without changing other deliveries."""

import pytest
from telegram import ForceReply
from telegram.error import BadRequest, RetryAfter, TimedOut

from tests.conftest import ADMIN, CLIENT
from tests.rich_helpers import rendered_panel
from verifydesk import ui
from verifydesk.bot import deliver


async def test_customer_notice_is_protected_with_rich_buttons_and_no_cover(env):
    keyboard = ui.Keyboard([[ui.action("Открыть заказ", "c:current", "primary")],
                            [ui.action("В кабинет", "a:mode:admin")]])
    message, state = await deliver(env.app.bot, CLIENT, "<b>Статус заказа</b>", keyboard)
    assert state == "delivered" and message.message_id
    method, params = env.request.calls[-1]
    assert method == "sendRichMessage" and params["protect_content"] is True
    assert "media" not in params["rich_message"]
    assert rendered_panel(params)["reply_markup"] == keyboard.to_dict()


@pytest.mark.parametrize("markup", [
    ForceReply(), None,
    ui.Keyboard([[ui.action("Открыть заказ", "a:view:5")]]),
    ui.Keyboard([[ui.action("Меню", "c:home"), ui.action("Кабинет", "a:home")]]),
])
async def test_operator_prompts_and_noncustomer_notifications_keep_their_original_markup(env, markup):
    message, state = await deliver(env.app.bot, ADMIN, "Состояние", markup)
    assert state == "delivered" and message.text == "Состояние"
    name, params = env.request.calls[-1]
    assert name == "sendMessage" and params.get("reply_markup") == (markup.to_dict() if markup else None)


@pytest.mark.parametrize("kind,state", [(BadRequest, "delivered"), (TimedOut, "uncertain"), (RetryAfter, "failed")])
async def test_native_notification_recovery_only_after_definite_format_rejection(env, monkeypatch, kind, state):
    monkeypatch.setenv("PTB_TIMEDELTA", "1")
    if kind is RetryAfter:
        error = RetryAfter(0)
    elif kind is BadRequest:
        error = BadRequest("rich format unsupported")
    else:
        error = TimedOut()
    original = env.request.do_request
    attempts = []

    async def refuse_rich(url, method, request_data=None, **kwargs):
        endpoint = url.rsplit("/", 1)[-1]
        attempts.append(endpoint)
        if endpoint == "sendRichMessage":
            raise error
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", refuse_rich)
    text = "<b>Важное сообщение</b>\n\n" + "т" * 4000
    keyboard = ui.Keyboard([[ui.action("Открыть заказ", "c:current")]])
    message, observed = await deliver(env.app.bot, CLIENT, text, keyboard)
    assert observed == state
    if isinstance(error, BadRequest):
        assert attempts == ["sendRichMessage", "sendMessage"]
        assert message.text == text and message.reply_markup == keyboard
    else:
        assert message is None and "sendMessage" not in attempts
        assert attempts.count("sendRichMessage") == (2 if isinstance(error, RetryAfter) else 1)
