from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from .store import OPEN_STATUSES, STATUS_NAMES, TRANSITIONS, Ticket, can_customer_cancel, ticket_status
from . import catalog


HELP_URL = "https://support.claude.com/en/articles/14328960-identity-verification-on-claude"
INSTRUCTIONS = (
    "<b>📋 Наша инструкция</b>\n\n"
    "1️⃣ Дождитесь оператора — он объяснит порядок действий.\n"
    "2️⃣ Откройте проверку в своём аккаунте на официальном сайте сервиса и проходите её самостоятельно на свои настоящие данные.\n"
    "3️⃣ Если возникла ошибка, напишите её текст в этот чат без личных данных.\n\n"
    "Строго следуйте нашей инструкции; вопросы уточняйте у оператора.\n\n"
    "🔒 <b>Ссылку KYC, документы, селфи, пароли и коды входа сюда не отправляйте.</b>\n"
    "Документы и селфи — только на официальной странице проверки.\n\n"
    "💡 Подписку Claude вы оплачиваете самостоятельно. Сопровождение не включает её стоимость."
)
PRIVACY = (
    "<b>🔒 Какие данные хранит бот</b>\n\n"
    "Telegram ID, имя и username, выбранную услугу, сообщения, статусы и заметки оператора. "
    "Переписки по сделке и опту хранятся отдельно. Сохраняются выбранная переписка, "
    "версия правил, время согласия, оценки и комментарии к отзывам. "
    "Если вы пришли по ссылке с меткой, сохраняется её источник.\n\n"
    "Фото и файлы из переписки передаются оператору. Бот сохраняет текст и идентификатор файла Telegram; "
    "сам файл на диск не скачивается. Чеки оператор проверяет вручную.\n\n"
    "🔒 Не отправляйте документы для KYC, селфи, ссылки проверки, пароли и коды входа. "
    "Документы для проверки личности направляйте только через официальный интерфейс платформы. "
    "Перед отправкой чека закройте лишние личные и платёжные данные.\n\n"
    "Это независимый сервис сопровождения. Решение о проверке принимает соответствующая платформа. "
    "Если нужно удалить данные из переписки, напишите оператору."
)


def action(text: str, data: str, style: str | None = None):
    # All actions use Telegram's neutral appearance, including old styled call sites.
    return Button(text, callback_data=data)


def text_units(text: str):
    return len(text.encode("utf-16-le")) // 2


def clip_text(text: str, limit: int):
    return text.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def conversation_title(ticket: Ticket):
    return f"{'🤝 Опт' if getattr(ticket, 'kind', 'order') == 'wholesale' else '📦 Сделка'} №{ticket.id:04d}"


def conversation_keyboard(tickets, selected_id=None):
    return Keyboard([[
        action(("✓ " if ticket.id == selected_id else "") + conversation_title(ticket), f"c:chat:{ticket.id}")
        for ticket in tickets
    ]])


def home(title: str, ticket: Ticket | None):
    rows = [
        [action("✨ Каталог услуг", "c:catalog")],
        [action("🤝 Обсудить опт", "c:wholesale")],
        [action("📦 Мои заказы", "c:profile"), action("📜 Правила", "c:rules")],
    ]
    text = (
        f"<b>👋 {escape(title)} · помощь с верификацией</b>\n\n"
        "Выберите услугу или обсудите оптовые условия с оператором.\n"
        "📍 Гео уточняйте у оператора."
    )
    if ticket and ticket.status in OPEN_STATUSES:
        text += f"\n\n{conversation_title(ticket)} · {ticket_status(ticket)}"
        rows.insert(0, [action(conversation_title(ticket), f"c:chat:{ticket.id}")])
    return text, Keyboard(rows)


def prepare():
    return (
        "<b>📋 Перед оформлением заказа</b>\n\n"
        "Проверку вы проходите сами на свои данные. Документы и селфи — только на официальной странице. "
        "Оператор поможет с шагами и ошибками.\n\n"
        "Оформляя заказ, вы подтверждаете, что аккаунт ваш. Затем напишите вопрос в этот чат.",
        Keyboard([
            [action("🛍 Оформить заказ", "c:create")],
            [action("← Назад", "c:home")],
        ]),
    )


def customer_ticket(ticket: Ticket, timezone: str):
    if getattr(ticket, "kind", "order") == "wholesale":
        active = ticket.status in OPEN_STATUSES
        text = (
            f"<b>{conversation_title(ticket)}</b>\n\n"
            + ("Обсудим объём, услуги и индивидуальные условия.\n\n"
               "💬 Просто напишите сообщение в этот чат. Оператор ответит здесь."
               if active else "Обсуждение завершено. Переписка сохранена.")
        )
        rows = [[action("🏠 Меню", "c:home")]]
        if not active:
            rows.insert(0, [action("🤝 Обсудить опт", "c:wholesale")])
        return text, Keyboard(rows)
    if ticket.status == "new" and ticket.payment_stage == "awaiting_payment":
        return payment_request(ticket)
    hints = {
        "new": "Оператор примет сделку и отправит вам реквизиты.",
        "in_progress": "Ожидайте сообщения от оператора.\n"
                       "Прочитайте инструкцию перед началом самостоятельной проверки.\n"
                       "🔒 Ссылку KYC, документы и коды входа сюда не отправляйте.",
        "waiting_user": "Ответ оператора выше. Продолжайте общение в этом чате.\n"
                        "Проверку проходите самостоятельно в своём аккаунте; ссылку KYC сюда не отправляйте.",
        "resolved": "Сопровождение завершено. Спасибо за обращение!",
        "cancelled": "Заказ отменён.",
    }
    hint = hints[ticket.status]
    if ticket.status == "new" and ticket.payment_stage == "review":
        hint = "Подтверждение оплаты отправлено оператору. Ожидайте его ответа."
    text = (
        f"<b>{conversation_title(ticket)} · {catalog.dollars(ticket.price_usd)}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)}\n\n"
        f"{ticket_status(ticket)}\n{hint}"
    )
    rows = []
    if ticket.status not in OPEN_STATUSES:
        rows.append([action("✨ Новый заказ", "c:catalog")])
    else:
        text += "\n\n💬 Сообщения и чек отправляйте прямо в этот чат."
        if ticket.payment_stage == "confirmed":
            rows.append([action("📋 Наша инструкция", f"c:guide:{ticket.service_code}")])
        if can_customer_cancel(ticket):
            rows.append([action("❌ Отменить заказ", f"c:cancel:{ticket.id}:{ticket.version}")])
    rows.append([action("🏠 Меню", "c:home")])
    return text, Keyboard(rows)


def customer_details(ticket: Ticket, timezone: str):
    return customer_ticket(ticket, timezone)


def payment_request(ticket: Ticket):
    rows = []
    if can_customer_cancel(ticket):
        rows.append([action("❌ Отменить заказ", f"c:cancel:{ticket.id}:{ticket.version}")])
    rows.append([action("🏠 Меню", "c:home")])
    return (
        f"<b>💳 Оплата · {conversation_title(ticket)}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n\n"
        "Оператор принял сделку и отправит вам реквизиты в этом чате.\n"
        "Дождитесь реквизитов и согласуйте условия до оплаты.\n\n"
        "После оплаты просто пришлите сюда скриншот, файл или ссылку на чек без лишних личных данных. "
        "Оператор получит сообщение и проверит оплату.\n\n"
        "После отправки чека отменить заказ сможет только оператор.",
        Keyboard(rows),
    )


def review_request(ticket: Ticket):
    return (
        f"<b>⭐ Как всё прошло?</b>\n{conversation_title(ticket)}\n\n"
        "Оцените работу от 1 до 5 звёзд. После оценки можно добавить комментарий.",
        Keyboard([[
            action(f"{stars} ⭐", f"c:rate:{ticket.id}:{stars}") for stars in range(1, 6)
        ]]),
    )


def review_comment_card(ticket: Ticket, stars: int):
    return (
        f"<b>{'⭐' * stars}{'☆' * (5 - stars)} · спасибо за оценку!</b>\n"
        f"{conversation_title(ticket)}\n\n"
        "Напишите комментарий одним сообщением или сохраните оценку без комментария.",
        Keyboard([[action("✓ Без комментария", f"c:review_skip:{ticket.id}")]]),
    )


def admin_home(counts: dict[str, int], queue_count: int | None = None, stages=None):
    active = sum(counts[key] for key in OPEN_STATUSES)
    waiting = counts["new"] + counts["in_progress"] if queue_count is None else queue_count
    return (
        "<b>🧑‍💻 Заказы и опт</b>\n\n"
        f"Требуют внимания: <b>{waiting}</b>\n"
        f"💳 Чеки на проверке: <b>{stages['review'] if stages else 0}</b>\n"
        f"🛠 В работе: <b>{counts['in_progress'] + counts['waiting_user']}</b>\n\n"
        "«Следующий» открывает обращения по очереди: чеки, работа, новые сделки и опт.\n"
        "Ответить сразу можно через Telegram Reply на сообщение клиента.",
        Keyboard([
            [action(f"▶️ Следующий · {waiting}", "a:next")],
            [action(f"📋 Все обращения · {active}", "a:list:active:0"), action("🔎 По номеру", "a:find")],
        ]),
    )


def admin_more():
    return (
        "<b>⚙️ Дополнительно</b>\n\nВыберите нужный раздел.",
        Keyboard([
            [action("💬 Очередь ответов", "a:list:queue:0"), action("🗂 Архив заказов", "a:list:closed:0")],
            [action("👥 Клиенты", "a:clients:0")],
            [action("👀 Режим клиента", "a:mode:client")],
            [action("← В кабинет", "a:home")],
        ]),
    )


def admin_status(status: str):
    return STATUS_NAMES[status]


def admin_ticket(ticket: Ticket, snippet: str | None = None, *, proof_ready=False):
    wholesale = getattr(ticket, "kind", "order") == "wholesale"
    text = f"<b>{conversation_title(ticket)} · {escape(ticket.display_name)}</b>\n"
    if not wholesale:
        text += f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n"
    text += ticket_status(ticket)
    if snippet:
        text += f"\n\n{escape(snippet)}"
    if ticket.payment_stage == "awaiting_payment" and not wholesale:
        text += "\n\n💳 Отправьте клиенту реквизиты и согласованные условия через «Ответить»."
    rows = []
    if ticket.status in OPEN_STATUSES:
        if not wholesale and ticket.payment_stage == "not_requested":
            rows.append([action("💳 Принять заказ", f"a:request_payment:{ticket.id}:{ticket.version}")])
        elif not wholesale and ticket.payment_stage == "review":
            if proof_ready:
                rows.append([
                    action("✅ Оплата получена", f"a:confirm_payment:{ticket.id}:{ticket.version}"),
                    action("↩️ Запросить другой чек", f"a:reject_payment:{ticket.id}:{ticket.version}"),
                ])
            else:
                rows.append([action("🔎 Проверить чек", f"a:proofs:{ticket.id}")])
        reply = [action("💬 Ответить", f"a:reply:{ticket.id}")]
        if wholesale or ticket.payment_stage in {"legacy", "confirmed"}:
            reply.append(action(
                "✅ Завершить обсуждение" if wholesale else "✅ Выполнен",
                f"a:set:{ticket.id}:{ticket.version}:resolved",
            ))
        rows.append(reply)
        text += "\n\n💬 Ответьте через Reply на это сообщение или нажмите «Ответить» и пишите в чат."
    rows.append([action("▶️ Следующее обращение", f"a:next:{ticket.id}")])
    return text, Keyboard(rows)


def admin_details(ticket: Ticket):
    text = (
        f"<b>{conversation_title(ticket)} · подробности</b>\n\n"
        f"{escape(ticket.display_name)}\n"
    )
    if getattr(ticket, "kind", "order") != "wholesale":
        text += f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n"
    text += ticket_status(ticket)
    if ticket.demo_network:
        network = catalog.NETWORK_BY_CODE.get(ticket.demo_network)
        text += (
            f"\n\nUSDT · демо: {escape(network.title) if network else 'сеть выбрана'}"
            "\nЭто тестовый выбор сети, без оплаты."
        )
    rows = [[
        action("💬 Переписка", f"a:history:{ticket.id}:0"),
        action("👤 Клиент", f"a:client:{ticket.user_id}"),
    ]]
    if ticket.payment_stage in {"awaiting_payment", "review", "confirmed"}:
        rows.append([action("🔎 Подтверждения оплаты", f"a:proofs:{ticket.id}")])
    if ticket.status in OPEN_STATUSES:
        rows.append([action("⚙️ Изменить статус", f"a:status:{ticket.id}")])
    rows.append([action("← К заказу", f"a:view:{ticket.id}")])
    return text, Keyboard(rows)


def reply_receipt(ticket: Ticket, state: str):
    heading = f"<b>{conversation_title(ticket)} · {escape(ticket.display_name)}</b>"
    if state == "delivered":
        text = f"{heading}\n\n✅ Ответ отправлен\n{ticket_status(ticket)}"
        rows = [
            [action("▶️ Следующее обращение", f"a:next:{ticket.id}")],
            [action("💬 Дополнить", f"a:reply:{ticket.id}")],
        ]
        if ticket.status in OPEN_STATUSES and ticket.payment_stage in {"legacy", "confirmed"}:
            rows[-1].append(action(
                "✅ Завершить обсуждение" if getattr(ticket, "kind", "order") == "wholesale" else "✅ Завершить",
                f"a:set:{ticket.id}:{ticket.version}:resolved",
            ))
        elif ticket.status in OPEN_STATUSES:
            rows[-1].append(action("📦 К заказу", f"a:view:{ticket.id}"))
    elif state == "uncertain":
        text = (
            f"{heading}\n\n⚠️ Telegram не подтвердил доставку: сообщение могло дойти.\n"
            "Ответ сохранён. Автоматического повтора не будет.\n"
            f"Статус: {ticket_status(ticket)}"
        )
        rows = [
            [action("💬 Проверить переписку", f"a:history:{ticket.id}:0")],
            [action("← К заказу", f"a:view:{ticket.id}")],
        ]
    else:
        text = (
            f"{heading}\n\n⚠️ Ответ сохранён, но отправить его не удалось.\n"
            "Клиент сможет прочитать его в переписке заказа.\n"
            f"Статус: {ticket_status(ticket)}"
        )
        rows = [
            [action("← К заказу", f"a:view:{ticket.id}")],
            [action("💬 Очередь ответов", "a:list:queue:0")],
        ]
    return text, Keyboard(rows)


def status_menu(ticket: Ticket):
    rows = []
    # waiting_user is an internal reply-queue state, not another order stage.
    if getattr(ticket, "kind", "order") == "wholesale":
        visible = ("resolved", "cancelled")
    elif ticket.payment_stage not in {"legacy", "confirmed"}:
        visible = ("cancelled",)
    else:
        visible = ("in_progress", "cancelled") if ticket.status == "new" else ("resolved", "cancelled")
    for status in visible:
        if status in TRANSITIONS[ticket.status]:
            rows.append([action(
                "✅ Обсуждение завершено" if getattr(ticket, "kind", "order") == "wholesale" and status == "resolved"
                else admin_status(status), f"a:set:{ticket.id}:{ticket.version}:{status}",
            )])
    rows.append([action("← К заказу", f"a:view:{ticket.id}")])
    return f"<b>{conversation_title(ticket)} · статус</b>\n\nСейчас: {ticket_status(ticket)}", Keyboard(rows)


def history(ticket: Ticket, rows, total: int, page: int, admin: bool, timezone: str):
    prefix = "a" if admin else "c"
    texts = [f"<b>{conversation_title(ticket)} · переписка</b>"]
    for row in rows:
        label = {"user": "Клиент" if admin else "Вы", "operator": "Оператор", "system": "Событие"}[
            row["role"]
        ]
        stamp = datetime.fromtimestamp(row["created_at"], ZoneInfo(timezone)).strftime("%d.%m %H:%M")
        # Keep one history card within Telegram limits; the original text remains in SQLite.
        body = clip_text(row["body"], 650) + ("…" if text_units(row["body"]) > 650 else "")
        delivery = ""
        if row["role"] == "operator" and row["delivery"] != "delivered":
            delivery = " · доставка в чат не подтверждена"
        texts.append(f"<b>{label} · {stamp}</b>{delivery}\n{escape(body)}")
    navigation = []
    if (page + 1) * 4 < total:
        navigation.append(action("← Раньше", f"{prefix}:history:{ticket.id}:{page + 1}"))
    if page > 0:
        navigation.append(action("Позже →", f"{prefix}:history:{ticket.id}:{page - 1}"))
    buttons = [navigation] if navigation else []
    buttons.append([action("← К заказу", f"{prefix}:view:{ticket.id}")])
    return "\n\n".join(texts), Keyboard(buttons)
