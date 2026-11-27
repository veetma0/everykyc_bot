"""Translation boundaries for authored text, Telegram captions and private notes."""

from html import escape

from scripts.render_ui_preview import card
from verifydesk import ui
from verifydesk.language import verbatim

from .conftest import ADMIN, CLIENT
from .test_upgrade import buttons, last, order


async def test_mixed_language_media_and_proof_go_to_the_recipient_in_their_language(env):
    ticket = await order(env)
    env.store.set_language(CLIENT, "en")
    text = "Кабинет оператора & <b>Заказ</b> </vd-literal> Главная"

    await env.message(CLIENT, photo=True, caption=text)
    incoming = [p for m, p in env.request.calls if m == "sendPhoto" and p["chat_id"] == ADMIN][-1]
    assert escape(text) in incoming["caption"]
    assert "📦 Заказ" in incoming["caption"]
    assert buttons(incoming)[0]["text"] == "💬 Переписка"

    await env.callback(ADMIN, f"a:reply:{ticket.id}")
    await env.message(ADMIN, photo=True, caption=text)
    outgoing = [p for m, p in env.request.calls if m == "sendPhoto" and p["chat_id"] == CLIENT][-1]
    assert outgoing["caption"].startswith("Operator · ")
    assert escape(text) in outgoing["caption"] and "<vd-literal>" not in outgoing["caption"]
    assert buttons(outgoing)[0]["text"] == "💬 Chat"

    env.store.set_language(ADMIN, "en")
    ticket = env.store.ticket(ticket.id)
    await env.callback(ADMIN, f"a:request_payment:{ticket.id}:{ticket.version}")
    await env.proof(CLIENT, photo=True, caption=text)
    await env.callback(ADMIN, f"a:proofs:{ticket.id}")
    photo = [p for m, p in env.request.calls if m == "sendPhoto" and p["chat_id"] == ADMIN][-1]
    assert photo["caption"] == f"🧾 Receipt · order #{ticket.id:04d}"
    proof = last(env, ADMIN)["text"]
    assert "Payment review" in proof and escape(text) in proof


async def test_names_notes_and_excerpt_authors_survive_translation(env):
    ticket = await order(env)
    name = "Оплата & <Чек>"
    note = "Главная · <b>Оператор</b>"
    env.store.remember_user(CLIENT, CLIENT, name, "private_user")
    env.store.set_note(CLIENT, note, ADMIN)
    env.store.remember_user(ADMIN, ADMIN, "Operator", None, language="en")
    env.store.set_language(ADMIN, "en")
    env.store.add_message(ticket.id, "user", "Переписка < > &", CLIENT, CLIENT, 8810)
    await env.callback(ADMIN, f"a:view:{ticket.id}")
    text = last(env, ADMIN)["text"]
    assert escape(name) in text
    assert "Customer: " + escape("Переписка < > &") in text
    await env.callback(ADMIN, "a:clients:0")
    row = next(b for b in buttons(last(env, ADMIN)) if b["callback_data"] == f"a:client:{CLIENT}")
    assert row["text"].startswith(name) and "Orders" in row["text"]
    await env.callback(ADMIN, f"a:client:{CLIENT}")
    text = last(env, ADMIN)["text"]
    assert escape(name) in text and escape(note) in text and "<vd-literal>" not in text
    await env.callback(ADMIN, f"a:note:{CLIENT}")
    prompt = last(env, ADMIN)
    assert escape(name) in prompt["text"]
    assert prompt["reply_markup"]["input_field_placeholder"] == "Private operator note"


def test_local_preview_removes_internal_markers_and_preserves_literal_markup():
    source = "<b>Оплата</b> & Главная"
    panel = card((verbatim(source), ui.Keyboard([[ui.action(verbatim(source), "c:home")]])), "c:home")
    assert panel["text"] == escape(source)
    assert panel["rows"][0][0]["text"] == source
