"""One-account customer/operator journeys, with persisted and explicit role changes."""

from pathlib import Path

import pytest

from verifydesk import catalog, screens, ui
from verifydesk.store import Store

from .conftest import ADMIN, CLIENT, OTHER
from .test_upgrade import buttons, callbacks, last, order, sent


async def press(env, data, card=500):
    assert data in callbacks(last(env, ADMIN)), (data, callbacks(last(env, ADMIN)))
    await env.callback(ADMIN, data, card=card)
    assert not env.errors


def user_rows(env, ticket_id):
    return env.store.db.execute(
        "SELECT * FROM messages WHERE ticket_id=? AND role='user' ORDER BY id", (ticket_id,)
    ).fetchall()


def latest_prompt(env, kind):
    return env.store.db.execute(
        f"SELECT MAX(message_id) FROM {kind} WHERE chat_id=?", (ADMIN,)
    ).fetchone()[0]


async def test_same_admin_can_complete_real_client_flow_then_answer_as_operator(env):
    await env.message(ADMIN, '/start')
    assert env.store.operator_mode(ADMIN) == 'admin'
    await env.message(ADMIN, '/client')
    assert env.store.operator_mode(ADMIN) == 'client'
    assert 'a:mode:admin' in callbacks(last(env, ADMIN))
    assert 'c:offer:claude:standard' not in callbacks(last(env, ADMIN))
    await press(env, 'c:catalog')
    await press(env, 'c:category:other')
    await press(env, 'c:service:claude')
    assert '$45' in last(env, ADMIN)['text']
    before = len(sent(env, ADMIN))
    await press(env, 'c:order:claude:standard')
    ticket = env.store.for_user(ADMIN)
    assert (ticket.service_code, ticket.plan_code, ticket.price_usd) == ('claude', 'standard', '45.00')
    assert len(sent(env, ADMIN)) == before + 1  # No self-admin notification in the client flow.
    assert 'a:reply:' not in ' '.join(callbacks(last(env, ADMIN)))

    before = len(sent(env, ADMIN))
    await env.message(ADMIN, 'На шаге проверки появилась ошибка')
    assert [row['body'] for row in user_rows(env, ticket.id)] == ['На шаге проверки появилась ошибка']
    assert env.store.ticket(ticket.id).unread == 1
    assert len(sent(env, ADMIN)) == before + 1
    await env.message(ADMIN, '/status')
    assert f'№{ticket.id:04d}' in last(env, ADMIN)['text']
    assert not any(value.startswith("c:pay:") for value in callbacks(last(env, ADMIN)))
    await press(env, 'a:mode:admin')
    assert env.store.operator_mode(ADMIN) == 'admin'
    await press(env, 'a:list:active:0')
    await press(env, f'a:view:{ticket.id}')
    assert 'На шаге проверки' in last(env, ADMIN)['text']
    current = env.store.ticket(ticket.id)
    await press(env, f'a:request_payment:{ticket.id}:{current.version}')
    await env.message(ADMIN, '/client')
    await env.proof(ADMIN, 'https://example.org/mock-payment')
    assert env.store.ticket(ticket.id).payment_stage == 'review'
    await env.message(ADMIN, '/admin')
    await press(env, 'a:next')
    current = env.store.ticket(ticket.id)
    await press(env, f'a:confirm_payment:{ticket.id}:{current.version}')
    assert env.store.ticket(ticket.id).payment_stage == 'confirmed'
    await press(env, f'a:reply:{ticket.id}')
    await env.message(ADMIN, 'Уточните текст ошибки', reply_to=latest_prompt(env, 'reply_targets'))
    assert env.store.ticket(ticket.id).status == 'waiting_user'
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE role='operator'").fetchone()[0] == 1

    await env.message(ADMIN, '/client')
    await env.message(ADMIN, 'Пишет, что ссылка истекла')
    assert env.store.ticket(ticket.id).status == 'in_progress'
    assert len(user_rows(env, ticket.id)) == 3  # Includes the submitted payment proof.
    await env.message(ADMIN, '/admin')
    await env.callback(ADMIN, f'a:status:{ticket.id}')
    version = env.store.ticket(ticket.id).version
    await press(env, f'a:set:{ticket.id}:{version}:resolved')
    await press(env, f'a:confirm:{ticket.id}:{version}:resolved')
    assert env.store.ticket(ticket.id).status == 'resolved'
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:profile')
    assert env.store.profile(ADMIN).resolved_tickets == 1
    assert 'a:mode:admin' in callbacks(last(env, ADMIN))


async def test_mode_survives_database_reopen_and_start_respects_it(env):
    await env.message(ADMIN, '/client')
    path = Path(env.store.db.execute('PRAGMA database_list').fetchone()['file'])
    reopened = Store(path)
    assert reopened.operator_mode(ADMIN) == 'client'
    reopened.close()
    await env.message(ADMIN, '/start')
    assert 'c:catalog' in callbacks(last(env, ADMIN))
    assert 'a:mode:admin' in callbacks(last(env, ADMIN))
    await env.message(ADMIN, '/admin')
    assert env.store.operator_mode(ADMIN) == 'admin'
    await env.message(ADMIN, '/start')
    assert 'a:list:active:0' in callbacks(last(env, ADMIN))
    assert len(callbacks(last(env, ADMIN))) == 3
    await env.message(ADMIN, '/client')
    assert env.store.operator_mode(ADMIN) == 'client'


@pytest.mark.parametrize('uid', [CLIENT, OTHER])
async def test_ordinary_customers_cannot_acquire_operator_access_or_role_state(env, uid):
    await env.message(uid, '/start')
    assert not any(value.startswith('a:') for value in callbacks(last(env, uid)))
    for value in ('a:mode:admin', 'a:mode:client', 'a:home'):
        await env.callback(uid, value)
        assert env.store.operator_mode(uid) != 'client'
        assert 'a:list:active:0' not in callbacks(last(env, uid))
    await env.message(uid, '/client')
    assert env.store.operator_mode(uid) != 'client'
    assert env.store.for_user(uid) is None


@pytest.mark.parametrize('kind', ['reply_targets', 'note_targets'])
async def test_client_mode_rejects_old_operator_and_note_reply_context(env, kind):
    ticket = await order(env)
    callback = f'a:reply:{ticket.id}' if kind == 'reply_targets' else f'a:note:{CLIENT}'
    await env.callback(ADMIN, callback)
    old_prompt = latest_prompt(env, kind)
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:order:claude:standard')
    own = env.store.for_user(ADMIN)
    before_customer = len(sent(env, CLIENT))
    before_own = len(user_rows(env, own.id))
    await env.message(ADMIN, 'Это ответ из прежнего режима', reply_to=old_prompt)
    assert len(sent(env, CLIENT)) == before_customer
    assert len(user_rows(env, own.id)) == before_own
    assert env.store.profile(CLIENT).operator_note == ''
    assert 'c:current' in callbacks(last(env, ADMIN))
    await env.callback(ADMIN, 'c:current')
    assert 'a:mode:admin' in callbacks(last(env, ADMIN))
    assert env.store.operator_mode(ADMIN) == 'client'


async def test_old_admin_status_button_requires_explicit_switch_back(env):
    ticket = await order(env)
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, f'a:set:{ticket.id}:{ticket.version}:in_progress')
    assert env.store.ticket(ticket.id).status == 'new'
    assert env.store.operator_mode(ADMIN) == 'client'
    assert 'a:mode:admin' in callbacks(last(env, ADMIN))


async def test_own_request_appears_in_admin_client_list_only_after_creation(env):
    await env.message(ADMIN, '/admin')
    await env.callback(ADMIN, 'a:clients:0')
    assert f'a:client:{ADMIN}' not in callbacks(last(env, ADMIN))
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:order:claude:standard')
    ticket = env.store.for_user(ADMIN)
    await env.message(ADMIN, '/admin')
    await env.callback(ADMIN, 'a:clients:0')
    await press(env, f'a:client:{ADMIN}')
    assert f'a:view:{ticket.id}' in callbacks(last(env, ADMIN))


async def test_switching_modes_does_not_reprice_recreate_or_close_request(env):
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:order:claude:standard')
    before = env.store.for_user(ADMIN)
    for _ in range(2):
        await env.message(ADMIN, '/admin')
        await env.message(ADMIN, '/client')
    after = env.store.for_user(ADMIN)
    assert (after.id, after.status, after.version, after.price_usd) == (
        before.id, before.status, before.version, '45.00'
    )
    assert env.store.profile(ADMIN).total_tickets == 1


async def test_mode_switch_does_not_make_unbound_admin_text_a_customer_message(env):
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:order:claude:standard')
    ticket = env.store.for_user(ADMIN)
    await env.message(ADMIN, '/admin')
    await env.message(ADMIN, 'Текст без выбранного получателя')
    assert not user_rows(env, ticket.id)
    assert env.store.db.execute("SELECT COUNT(*) FROM messages WHERE role='operator'").fetchone()[0] == 0
    assert 'a:home' in callbacks(last(env, ADMIN))


async def test_customer_home_opens_categories_then_service_without_geography(env):
    await env.message(CLIENT, '/start')
    home = last(env, CLIENT)
    assert 'c:catalog' in callbacks(home)
    assert not any(value.startswith('c:offer:claude:') for value in callbacks(home))
    assert len(buttons(home)) == 4
    assert 'c:wholesale' in callbacks(home)
    assert '$' not in home['text']
    await env.callback(CLIENT, 'c:catalog')
    assert 'c:category:other' in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, 'c:category:other')
    assert 'c:service:claude' in callbacks(last(env, CLIENT))
    await env.callback(CLIENT, 'c:service:claude')
    geography = callbacks(last(env, CLIENT))
    assert 'c:order:claude:standard' in geography
    assert 'Гео уточняйте у оператора' in last(env, CLIENT)['text']
    assert env.store.for_user(CLIENT) is None


async def test_rendered_action_buttons_are_neutral_in_both_roles(env):
    await env.message(ADMIN, '/start')
    await env.message(ADMIN, '/client')
    await env.callback(ADMIN, 'c:service:claude')
    await env.callback(ADMIN, 'c:offer:claude:standard')
    await env.callback(ADMIN, 'c:order:claude:standard')
    ticket = env.store.for_user(ADMIN)
    await env.callback(ADMIN, f'c:pay:{ticket.id}')
    await env.callback(ADMIN, f'c:networks:{ticket.id}:usdt0:0')
    await env.callback(ADMIN, f'c:cancel:{ticket.id}:{ticket.version}')
    await env.message(ADMIN, '/admin')
    await env.callback(ADMIN, f'a:status:{ticket.id}')
    for params in sent(env):
        for button in buttons(params):
            assert button.get('style') is None
            assert button.get('icon_custom_emoji_id') is None
    for offer in catalog.OFFERS.values():
        _, keyboard = screens.offer_card(offer)
        assert all(button.style is None for row in keyboard.inline_keyboard for button in row)
    assert ui.action('Удалить', 'c:home', 'danger').style is None


async def test_preview_inside_client_mode_cannot_create_request_or_change_role(env):
    await env.message(ADMIN, '/client')
    await env.message(ADMIN, '/preview')
    await press(env, 'p:catalog')
    await press(env, 'p:category:other')
    await press(env, 'p:service:claude')
    await press(env, 'p:order:claude:standard')
    assert env.store.for_user(ADMIN) is None
    assert env.store.operator_mode(ADMIN) == 'client'
    assert not env.store.db.execute('SELECT * FROM customer_reply_targets').fetchall()
    await press(env, 'a:home')
    assert env.store.operator_mode(ADMIN) == 'admin'


async def test_startup_restores_command_menu_for_persisted_client_mode(env):
    await env.message(ADMIN, '/client')
    await env.app.post_init(env.app)
    scoped = [params for method, params in env.request.calls
              if method == 'setMyCommands' and params.get('scope', {}).get('chat_id') == ADMIN]
    commands = {item['command'] for item in scoped[-1]['commands']}
    assert commands == {'start', 'status', 'profile', 'help', 'admin'}
    assert 'clients' not in commands
    assert env.store.operator_mode(ADMIN) == 'client'
