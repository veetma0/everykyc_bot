"""Check wire requests, native button rows and message identities across storefront navigation."""

from hashlib import sha256
from xml.etree import ElementTree

import pytest
from telegram import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, EndPointNotFound, TimedOut

from tests.conftest import ADMIN, CLIENT, OTHER, BOT_USER
from tests.rich_helpers import rendered_panel
from verifydesk import catalog, media, rich, rules, screens, theme, ui


def expected_photo(key):
    digest = sha256((media.ART_DIR / f"{key}.jpg").read_bytes()).hexdigest()
    return "photo-" + digest[:12]


def display_calls(env):
    return [(name, params) for name, params in env.request.calls if name in {
        "sendRichMessage", "sendPhoto", "editMessageMedia", "editMessageCaption", "sendMessage", "editMessageText",
    }]


def rich_photo(message):
    assert not {"reply_markup", "caption", "photo", "text"}.intersection(message)
    blocks = message["rich_message"]["blocks"]
    assert any(block["type"] == "buttons" for block in blocks)
    photo = next(block for block in blocks if block["type"] == "photo")
    return photo["photo"][-1]["file_id"]


async def test_long_rules_send_and_edit_with_actions_outside_deferred_blocks(env):
    env.require_terms = True
    await env.message(CLIENT, "/start")
    agree = f"c:agree_full:{rules.VERSION}"
    name, params = display_calls(env)[-1]
    assert name == "sendRichMessage"
    assert "<tg-button" not in params["rich_message"]["html"]
    assert [[b["callback_data"] for b in row] for row in params["reply_markup"]["inline_keyboard"]] == [[agree]]
    panel_id = next(mid for (uid, mid) in env.request.messages if uid == CLIENT)
    await env.callback(CLIENT, agree, card=panel_id)
    assert env.store.terms_state(CLIENT)["accepted_version"] == rules.VERSION
    assert rich_photo(env.request.messages[(CLIENT, panel_id)]) == expected_photo("catalog")
    await env.callback(CLIENT, "c:help", card=panel_id)
    await env.callback(CLIENT, "c:rules", card=panel_id)
    name, params = display_calls(env)[-1]
    assert name == "editMessageText" and params["message_id"] == panel_id
    assert "<tg-button" not in params["rich_message"]["html"]
    assert [[b["callback_data"] for b in row] for row in params["reply_markup"]["inline_keyboard"]] == [["c:home"]]
    await env.callback(CLIENT, "c:home", card=panel_id)
    assert rich_photo(env.request.messages[(CLIENT, panel_id)]) == expected_photo("home")


async def test_menu_changes_art_in_place_and_reuses_each_upload(env):
    await env.message(CLIENT, "/menu")
    home = next(msg for (uid, _), msg in env.request.messages.items() if uid == CLIENT)
    panel_id = home["message_id"]
    assert rich_photo(home) == expected_photo("home")
    name, params = display_calls(env)[-1]
    assert name == "sendRichMessage"
    assert params["rich_message"]["media"][0]["media"]["media"] == "attach://cover_file"
    rows = [block["buttons"] for block in home["rich_message"]["blocks"] if block["type"] == "buttons"]
    assert any(button.get("style") == "primary" and button["callback_data"] == "c:catalog"
               for row in rows for button in row)
    for route, art in [
        ("c:catalog", "catalog"), ("c:category:exchanges", "exchanges"), ("c:service:bybit", "exchanges"),
        ("c:home", "home"), ("c:profile", "profile"), ("c:help", "help"),
    ]:
        before = len(display_calls(env))
        await env.callback(CLIENT, route, card=panel_id)
        calls = display_calls(env)[before:]
        assert len(calls) == 1 and calls[0][0] == "editMessageText" and "text" not in calls[0][1]
        assert calls[0][1]["message_id"] == panel_id
        assert rich_photo(env.request.messages[(CLIENT, panel_id)]) == expected_photo(art)
        if route in {"c:home", "c:service:bybit"}:
            assert calls[0][1]["rich_message"]["media"][0]["media"]["media"] == expected_photo(art)
    await env.message(OTHER, "/start")
    assert display_calls(env)[-1][1]["rich_message"]["media"][0]["media"]["media"] == expected_photo("home")


@pytest.mark.parametrize("command", ["/preview", "/client"])
async def test_operator_customer_entry_has_home_art_but_cabinet_is_text(env, command):
    await env.message(ADMIN, command)
    panel = next(iter(env.request.messages.values()))
    assert rich_photo(panel) == expected_photo("home")
    await env.callback(ADMIN, "a:home", card=panel["message_id"])
    method, data = display_calls(env)[-1]
    assert method in {"sendMessage", "editMessageText"} and "text" in data


async def test_resolved_home_and_preview_routes_keep_their_art(env):
    await env.message(CLIENT, "/cancel")
    assert rich_photo(list(env.request.messages.values())[-1]) == expected_photo("home")
    await env.callback(ADMIN, "a:preview")
    assert rich_photo(env.request.messages[(ADMIN, 500)]) == expected_photo("home")
    await env.message(OTHER, "/client")
    assert "text" in display_calls(env)[-1][1]


async def test_long_rules_keep_complete_text_and_back_returns_to_home_art(env):
    await env.message(CLIENT, "/menu")
    panel_id = next(iter(env.request.messages.values()))["message_id"]
    await env.callback(CLIENT, "c:rules", card=panel_id)
    method, params = display_calls(env)[-1]
    assert method == "editMessageText" and params["message_id"] == panel_id
    assert all(page in rendered_panel(params)["text"] for page in rules.PAGES)
    await env.callback(CLIENT, "c:home", card=panel_id)
    assert rich_photo(env.request.messages[(CLIENT, panel_id)]) == expected_photo("home")


async def test_foreign_attachment_remains_intact_and_keeps_its_reply_binding(env):
    await env.callback(CLIENT, "c:order:bybit:standard")
    ticket = env.store.for_user(CLIENT)
    source_id = 5648
    photo = {"file_id": "customer-receipt", "file_unique_id": "original", "width": 400, "height": 400}
    env.request.messages[(CLIENT, source_id)] = {
        "message_id": source_id, "date": 1700000000, "from": BOT_USER,
        "chat": {"id": CLIENT, "type": "private"}, "photo": [photo], "caption": "Оператор",
    }
    env.store.map_customer_reply(CLIENT, source_id, ticket.id)
    previous = len(display_calls(env))
    await env.callback(CLIENT, f"c:history:{ticket.id}:0", card=source_id)
    assert [name for name, _ in display_calls(env)[previous:]] == ["sendRichMessage"]
    assert env.request.messages[(CLIENT, source_id)]["photo"] == [photo]
    assert env.store.customer_reply_ticket(CLIENT, source_id).id == ticket.id


async def test_expired_and_inaccessible_buttons_open_fresh_panels(env, monkeypatch):
    await env.message(CLIENT, "/menu")
    source_id = list(env.request.messages.values())[0]["message_id"]
    original = env.request.do_request

    async def expired(url, method, request_data=None, **kwargs):
        if url.endswith("/editMessageText"):
            raise BadRequest("message to edit not found")
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", expired)
    await env.callback(CLIENT, "c:catalog", card=source_id)
    assert display_calls(env)[-1][0] == "sendRichMessage"
    inaccessible_id = 1515
    env.request.messages[(CLIENT, inaccessible_id)] = {
        "message_id": inaccessible_id, "date": 0, "chat": {"id": CLIENT, "type": "private"},
    }
    await env.callback(CLIENT, "c:help", card=inaccessible_id)
    assert display_calls(env)[-1][0] == "sendRichMessage"
    assert rich_photo(list(env.request.messages.values())[-1]) == expected_photo("help")


async def test_button_markup_escapes_display_text_and_preserves_action_values(env):
    label = 'Гид <A> & "B"'
    route = 'c:key:A&B"'
    url = 'https://example.org/?a=1&b=2'
    copied = 'A & "B"'
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=route, style="primary")],
        [InlineKeyboardButton("Открыть", url=url), InlineKeyboardButton("Копировать", copy_text=CopyTextButton(copied))],
    ])
    result = await rich.show_rich(env.app.bot, CLIENT, None, "<b>Раздел</b>", keyboard)
    blocks = result.api_kwargs["rich_message"]["blocks"]
    assert blocks[0] == {"type": "paragraph", "text": {"type": "bold", "text": "Раздел"}}
    assert blocks[1]["buttons"] == [{"text": label, "callback_data": route, "style": "primary"}]
    assert blocks[2]["buttons"] == [{"text": "Открыть", "url": url}]
    assert blocks[3]["buttons"] == [{"text": "Копировать", "copy_text": {"text": copied}}]


def test_width_aware_rows_preserve_labels_order_icons_and_keyboard_fallback():
    plain = InlineKeyboardButton("Гид", callback_data="c:guide:general")
    logo = InlineKeyboardButton("Гид", callback_data="c:guide:general", icon_custom_emoji_id="42")
    rules_button = InlineKeyboardButton("Правила", callback_data="c:rules")
    keyboard = InlineKeyboardMarkup([[plain, rules_button], [logo, rules_button]])
    rows = [ElementTree.fromstring(html) for html in rich.button_rows(keyboard)]
    assert [[button.get("data") for button in row] for row in rows] == [
        ["c:guide:general", "c:rules"], ["c:guide:general"], ["c:rules"],
    ]
    assert rows[0].get("align") == "left"
    assert rows[1][0][0].attrib == {"emoji-id": "42"}
    assert keyboard.inline_keyboard == ((plain, rules_button), (logo, rules_button))


def test_all_priced_service_labels_fit_a_narrow_row_with_their_verified_logos(monkeypatch):
    monkeypatch.setattr(theme, "_theme", {"enabled": True, "icons": theme.EXCHANGE_ICONS})
    for category in catalog.CATEGORIES:
        offers = screens.category_offers(category)
        for page in range((len(offers) + screens.CATALOG_PAGE_SIZE - 1) // screens.CATALOG_PAGE_SIZE):
            _, keyboard = screens.category_card(category, page)
            for _, row in rich.layout_rows(keyboard.inline_keyboard):
                assert sum(rich._button_width(button) for button in row) + 8 * (len(row) - 1) <= 199


async def test_reduced_rating_rows_keep_every_score_and_skip_action(env):
    await env.callback(CLIENT, "c:order:claude:standard")
    ticket = env.store.for_user(CLIENT)
    text, keyboard = ui.review_request(ticket)
    rows = [ElementTree.fromstring(html) for html in rich.button_rows(keyboard)]
    assert "от 1 до 5 звёзд" in text
    assert [[button.text for button in row] for row in rows] == [["1", "2", "3"], ["4", "5"], ["Не сейчас"]]
    assert [button.get("data") for row in rows for button in row] == [
        *(f"c:rate:{ticket.id}:{score}" for score in range(1, 6)), "c:home",
    ]


@pytest.mark.parametrize("error", [BadRequest("method not found"), EndPointNotFound("Not Found")])
async def test_unsupported_rich_request_falls_back_to_native_photo(env, monkeypatch, error):
    original = env.request.do_request

    async def old_server(url, method, request_data=None, **kwargs):
        if url.endswith("/sendRichMessage"):
            raise error
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", old_server)
    await env.message(CLIENT, "/start")
    only, = env.request.messages.values()
    assert only["photo"][-1]["file_id"] == expected_photo("home")
    assert "inline_keyboard" in only["reply_markup"]


async def test_old_photo_panel_migrates_when_telegram_rejects_conversion(env, monkeypatch):
    original = env.request.do_request
    old_server = True

    async def upgrade(url, method, request_data=None, **kwargs):
        if old_server and url.endswith("/sendRichMessage"):
            raise BadRequest("method not found")
        if url.endswith("/editMessageText") and "rich_message" in request_data.parameters:
            raise BadRequest("There is no text in the message to edit")
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", upgrade)
    await env.message(CLIENT, "/menu")
    old_panel, = env.request.messages.values()
    old_server = False
    await env.callback(CLIENT, "c:catalog", card=old_panel["message_id"])
    old_panel, new_panel = env.request.messages.values()
    assert old_panel["photo"][-1]["file_id"] == expected_photo("home")
    assert not old_panel.get("reply_markup")
    assert rich_photo(new_panel) == expected_photo("catalog")
    assert old_panel["message_id"] != new_panel["message_id"]


async def test_uncertain_first_rich_send_never_starts_a_second_panel(env, monkeypatch):
    attempts = []
    original = env.request.do_request

    async def network_error(url, method, request_data=None, **kwargs):
        if url.endswith("/sendRichMessage"):
            attempts.append("rich")
            raise TimedOut()
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", network_error)
    await env.message(CLIENT, "/start")
    assert attempts == ["rich"]
    assert not env.request.messages


def test_all_catalog_artworks_and_caption_boundaries():
    for (code, _plan), offer in catalog.OFFERS.items():
        assert media.cover_for(f"c:service:{code}", offer.title) == offer.category
        assert (media.ART_DIR / f"{offer.category}.jpg").is_file()
    assert media.cover_for("p:privacy", "<b>" + "&amp;" * 1024 + "</b>") == "help"
    assert media.cover_for("c:help", "🫖" * 513) is None
