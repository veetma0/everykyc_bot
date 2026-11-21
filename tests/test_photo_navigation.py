"""Check the actual PTB requests and message identities across storefront navigation."""

from hashlib import sha256

import pytest
from telegram.error import BadRequest

from tests.conftest import ADMIN, CLIENT, OTHER, BOT_USER
from verifydesk import catalog, media, rules


def expected_photo(key):
    digest = sha256((media.ART_DIR / f"{key}.jpg").read_bytes()).hexdigest()
    return "photo-" + digest[:12]


def display_calls(env):
    return [(name, params) for name, params in env.request.calls if name in {
        "sendPhoto", "editMessageMedia", "editMessageCaption", "sendMessage", "editMessageText",
    }]


async def test_menu_changes_art_in_place_and_reuses_each_upload(env):
    await env.message(CLIENT, "/menu")
    home = next(msg for (uid, _), msg in env.request.messages.items() if uid == CLIENT)
    panel_id = home["message_id"]
    assert home["photo"][-1]["file_id"] == expected_photo("home")
    for route, art, method in [
        ("c:catalog", "catalog", "editMessageMedia"),
        ("c:category:exchanges", "exchanges", "editMessageMedia"),
        ("c:service:bybit", "exchanges", "editMessageCaption"),
        ("c:home", "home", "editMessageMedia"),
        ("c:profile", "profile", "editMessageMedia"),
        ("c:help", "help", "editMessageMedia"),
    ]:
        before = len(display_calls(env))
        await env.callback(CLIENT, route, card=panel_id)
        calls = display_calls(env)[before:]
        assert len(calls) == 1 and calls[0][0] == method
        assert calls[0][1]["message_id"] == panel_id
        assert env.request.messages[(CLIENT, panel_id)]["photo"][-1]["file_id"] == expected_photo(art)
        if route == "c:home":
            assert calls[0][1]["media"]["media"] == expected_photo("home")
    await env.message(OTHER, "/start")
    assert display_calls(env)[-1][1]["photo"] == expected_photo("home")


@pytest.mark.parametrize("command", ["/preview", "/client"])
async def test_operator_customer_entry_has_home_art_but_cabinet_is_text(env, command):
    await env.message(ADMIN, command)
    panel = next(iter(env.request.messages.values()))
    assert panel["photo"][-1]["file_id"] == expected_photo("home")
    await env.callback(ADMIN, "a:home", card=panel["message_id"])
    assert display_calls(env)[-1][0] == "sendMessage"


async def test_resolved_home_and_preview_routes_keep_their_art(env):
    await env.message(CLIENT, "/cancel")
    assert list(env.request.messages.values())[-1]["photo"][-1]["file_id"] == expected_photo("home")
    await env.callback(ADMIN, "a:preview")
    assert env.request.messages[(ADMIN, 500)]["photo"][-1]["file_id"] == expected_photo("home")
    await env.message(OTHER, "/client")
    assert display_calls(env)[-1][0] == "sendMessage"


async def test_long_rules_keep_complete_text_and_back_returns_to_photo(env):
    await env.message(CLIENT, "/menu")
    old_id = next(iter(env.request.messages.values()))["message_id"]
    await env.callback(CLIENT, "c:rules", card=old_id)
    method, params = display_calls(env)[-1]
    assert method == "sendMessage" and rules.PAGES[0] in params["text"]
    rules_card = list(env.request.messages.values())[-1]
    await env.callback(CLIENT, "c:home", card=rules_card["message_id"])
    method, params = display_calls(env)[-1]
    assert method == "editMessageMedia" and params["message_id"] == rules_card["message_id"]


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
    assert [name for name, _ in display_calls(env)[previous:]] == ["sendPhoto"]
    assert env.request.messages[(CLIENT, source_id)]["photo"] == [photo]
    assert env.store.customer_reply_ticket(CLIENT, source_id).id == ticket.id


async def test_expired_and_inaccessible_buttons_open_fresh_panels(env, monkeypatch):
    await env.message(CLIENT, "/menu")
    source_id = list(env.request.messages.values())[0]["message_id"]
    original = env.request.do_request

    async def expired(url, method, request_data=None, **kwargs):
        if url.endswith("/editMessageMedia"):
            raise BadRequest("message to edit not found")
        return await original(url, method, request_data, **kwargs)

    monkeypatch.setattr(env.request, "do_request", expired)
    await env.callback(CLIENT, "c:catalog", card=source_id)
    assert display_calls(env)[-1][0] == "sendPhoto"
    inaccessible_id = 1515
    env.request.messages[(CLIENT, inaccessible_id)] = {
        "message_id": inaccessible_id, "date": 0, "chat": {"id": CLIENT, "type": "private"},
    }
    await env.callback(CLIENT, "c:help", card=inaccessible_id)
    assert display_calls(env)[-1][0] == "sendPhoto"
    assert list(env.request.messages.values())[-1]["photo"][-1]["file_id"] == expected_photo("help")


def test_all_catalog_artworks_and_caption_boundaries():
    for (code, _plan), offer in catalog.OFFERS.items():
        assert media.cover_for(f"c:service:{code}", offer.title) == offer.category
        assert (media.ART_DIR / f"{offer.category}.jpg").is_file()
    assert media.cover_for("p:privacy", "<b>" + "&amp;" * 1024 + "</b>") == "help"
    assert media.cover_for("c:help", "🫖" * 513) is None
