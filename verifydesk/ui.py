from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from .store import OPEN_STATUSES, STATUS_NAMES, TRANSITIONS, Ticket, ticket_status
from . import catalog


HELP_URL = "https://support.claude.com/en/articles/14328960-identity-verification-on-claude"
INSTRUCTIONS = (
    "<b>📋 Проверка личности в Claude</b>\n\n"
    "Откройте проверку из своего аккаунта и следуйте подсказкам Claude. "
    "Используйте своё настоящее имя и свой документ.\n\n"
    "Если возникла ошибка — напишите её текст сюда, без личных данных. Оператор поможет разобраться.\n\n"
    "❗ <b>Ссылку проверки, документы, селфи, пароли и коды входа сюда не отправляйте.</b>\n\n"
    "Срок ссылки и результат проверки смотрите в Claude. Подписка оплачивается отдельно."
)
PRIVACY = (
    "<b>🔒 Какие данные хранит бот</b>\n\n"
    "Telegram ID, имя и username из Telegram, выбранную услугу, сообщения, статусы и заметки оператора. "
    "Они нужны оператору для ответа и сохраняются после перезапуска. "
    "Если вы пришли по ссылке с меткой, сохраняется её источник — чтобы понимать, откуда приходят заказы.\n\n"
    "Не отправляйте ссылку проверки, документы, селфи, пароли и коды входа. "
    "Тестовые подтверждения оплаты передаются оператору для ручной проверки. Бот хранит текст и ссылку на файл Telegram; файл не скачивается. Другие вложения не передаются оператору. Если сообщение содержит личные данные, "
    "попросите оператора удалить его.\n\n"
    "Это независимый сервис сопровождения. Решение о проверке принимает соответствующий сервис. "
    "Выполнение заказа означает завершение сопровождения. Результат KYC определяет официальный сервис."
)


def action(text: str, data: str, style: str | None = None):
    # All actions use Telegram's neutral appearance, including old styled call sites.
    return Button(text, callback_data=data)


def text_units(text: str):
    return len(text.encode("utf-16-le")) // 2


def clip_text(text: str, limit: int):
    return text.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def home(title: str, ticket: Ticket | None):
    text = (
        f"<b>👋 {escape(title)} · помощь с Claude</b>\n\n"
        "Поможем разобраться с проверкой личности своего аккаунта. "
        "Заказ и общение с оператором — здесь, в одном чате."
    )
    if ticket and ticket.status in OPEN_STATUSES:
        text += (
            f"\n\n📦 <b>Ваш заказ №{ticket.id:04d}</b>\n"
            f"{catalog.service_title(ticket.service_code, ticket.plan_code)}\n{ticket_status(ticket)}"
            "\n\n💬 Напишите сообщение прямо сюда — оператор его получит."
        )
        rows = [
            [action("📦 Мой заказ", f"c:view:{ticket.id}")],
            [action("❓ Как это работает", "c:help")],
        ]
    else:
        text += "\n\nВыберите регион, посмотрите цену и оформите заказ. 👇"
        rows = [[action("🛍 Оформить заказ", "c:service:claude")]]
        if ticket:
            rows.append([action("📦 Мои заказы", "c:profile"), action("❓ Как это работает", "c:help")])
        else:
            rows.append([action("❓ Как это работает", "c:help")])
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
    hints = {
        "new": "Заказ создан. Оператор примет его и пришлёт тестовые реквизиты.\n💬 Вопрос можно отправить прямо в этот чат.",
        "in_progress": "Оператор принял заказ и занимается им.\n💬 Если хотите что-то добавить, напишите сюда.",
        "waiting_user": "Оператор ответил вам в этом чате.\n💬 Продолжайте общение здесь, заказ остаётся в работе.",
        "resolved": "Спасибо за обращение! Сопровождение завершено.\nРезультат проверки смотрите в официальном сервисе.",
        "cancelled": "Заказ отменён. Если помощь снова понадобится, можно оформить новый.",
    }
    hint = hints[ticket.status]
    if ticket.status == "new" and ticket.payment_stage == "awaiting_payment":
        hint = (
            "Тестовые реквизиты уже готовы. Денег переводить не нужно.\n"
            "📎 Пришлите сюда тестовый скриншот или ссылку на подтверждение без личных данных."
        )
    elif ticket.status == "new" and ticket.payment_stage == "review":
        hint = "Подтверждение получено. Оператор проверит его вручную и переведёт заказ в работу."
    text = (
        f"<b>📦 Заказ №{ticket.id:04d}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n\n"
        f"<b>{ticket_status(ticket)}</b>\n{hint}"
    )
    rows = [[action("📋 Детали", f"c:details:{ticket.id}")]]
    if ticket.status in OPEN_STATUSES and ticket.payment_stage in {"awaiting_payment", "review"}:
        rows.insert(0, [action("💳 Тестовые реквизиты", f"c:requisites:{ticket.id}")])
    if ticket.status not in OPEN_STATUSES:
        rows.append([action("🛍 Новый заказ", "c:service:claude")])
    else:
        rows.append([action("🏠 Меню", "c:home")])
    return text, Keyboard(rows)


def customer_details(ticket: Ticket, timezone: str):
    date = datetime.fromtimestamp(ticket.created_at, ZoneInfo(timezone)).strftime("%d.%m.%Y · %H:%M")
    text = (
        f"<b>📋 Детали заказа №{ticket.id:04d}</b>\n\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)}\n"
        f"💵 Сопровождение · <b>{catalog.dollars(ticket.price_usd)}</b>\n"
        f"Оформлен {date}\n{ticket_status(ticket)}\n\n"
        "Результат проверки определяет официальный сервис."
    )
    if ticket.status in OPEN_STATUSES:
        text += "\n💬 Для связи с оператором просто напишите в этот чат."
    rows = [[
        action("💬 Переписка", f"c:history:{ticket.id}:0"),
        action("📖 Инструкция", f"c:guide:{ticket.service_code}"),
    ]]
    if ticket.status in OPEN_STATUSES and ticket.payment_stage in {"awaiting_payment", "review"}:
        rows.append([action("💳 Тестовые реквизиты", f"c:requisites:{ticket.id}")])
    if ticket.status in OPEN_STATUSES:
        rows.append([action("Отменить заказ", f"c:cancel:{ticket.id}:{ticket.version}")])
    rows.append([action("← К заказу", f"c:view:{ticket.id}")])
    return text, Keyboard(rows)


def payment_request(ticket: Ticket):
    return (
        f"<b>💳 Тестовые реквизиты · Заказ №{ticket.id:04d}</b>\n\n"
        "Получатель: Эврикус · ДЕМО\n"
        f"Номер: <code>DEMO-{ticket.id:04d}</code>\n"
        f"Сумма: {catalog.dollars(ticket.price_usd)} (пример)\n\n"
        "⚠️ <b>ДЕМО — деньги не переводите.</b>\n"
        "Пришлите тестовый скриншот или ссылку на подтверждение без личных данных. "
        "Оператор проверит и переведёт заказ в работу.",
        Keyboard([[action("📦 Мой заказ", f"c:view:{ticket.id}")]]),
    )


def admin_home(counts: dict[str, int], queue_count: int | None = None):
    active = sum(counts[key] for key in OPEN_STATUSES)
    waiting = counts["new"] + counts["in_progress"] if queue_count is None else queue_count
    return (
        "<b>🧑‍💻 Кабинет оператора</b>\n\n"
        f"⏳ До начала работы: <b>{counts['new']}</b>\n"
        f"🛠 В работе: <b>{counts['in_progress'] + counts['waiting_user']}</b>\n"
        f"✅ Выполнено: <b>{counts['resolved']}</b>\n\n"
        f"💬 Доступны для ответа: <b>{waiting}</b>\n"
        "«Следующий заказ» откроет заказ и покажет нужное действие.",
        Keyboard([
            [action("▶️ Следующий заказ", "a:next")],
            [action(f"📦 Заказы · {active}", "a:list:active:0"), action("⚙️ Ещё", "a:more")],
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


def admin_ticket(ticket: Ticket, snippet: str | None = None):
    username = f" · @{escape(ticket.username)}" if ticket.username else ""
    text = (
        f"<b>📦 Заказ №{ticket.id:04d}</b>\n{escape(ticket.display_name)}{username}\n\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · <b>{catalog.dollars(ticket.price_usd)}</b>"
        f"\n{ticket_status(ticket)}"
    )
    if ticket.status == "waiting_user":
        text += "\n💬 Вы ответили. При необходимости продолжите общение или завершите заказ."
    found = catalog.OFFERS.get((ticket.service_code, ticket.plan_code))
    if found and found.demo:
        text += "\nДЕМО · запрос о доступности, заказ не подтверждён."
    if ticket.unread:
        text += f"\n💬 Новых сообщений: <b>{ticket.unread}</b>"
    if snippet:
        text += f"\n\n<b>Сообщение клиента</b>\n{escape(snippet)}"
    rows = []
    if ticket.status in OPEN_STATUSES:
        if ticket.payment_stage == "not_requested":
            text += "\n\nПримите заказ — клиент получит тестовые реквизиты."
            rows.append([action("💳 Принять заказ", f"a:request_payment:{ticket.id}:{ticket.version}")])
        elif ticket.payment_stage == "awaiting_payment":
            text += "\n\nЖдём тестовый скриншот или ссылку от клиента."
            rows.append([action("💬 Написать", f"a:reply:{ticket.id}")])
        elif ticket.payment_stage == "review":
            text += "\n\nПроверьте подтверждение вручную. После одобрения заказ перейдёт в работу."
            rows.append([action("🔎 Проверить оплату", f"a:proofs:{ticket.id}")])
        else:
            text += "\n\nОтветьте на это сообщение в Telegram или нажмите «💬 Ответить»."
            rows.append([
                action("💬 Ответить", f"a:reply:{ticket.id}"),
                action("✅ Завершить", f"a:set:{ticket.id}:{ticket.version}:resolved"),
            ])
    rows.append([
        action("⚙️ Подробнее", f"a:details:{ticket.id}"),
        action("➡️ Следующий", f"a:next:{ticket.id}"),
    ])
    return text, Keyboard(rows)


def admin_details(ticket: Ticket):
    text = (
        f"<b>📋 Заказ №{ticket.id:04d} · подробности</b>\n\n"
        f"{escape(ticket.display_name)}\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n"
        f"{ticket_status(ticket)}"
    )
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
    heading = f"<b>📦 №{ticket.id:04d} · {escape(ticket.display_name)}</b>"
    if state == "delivered":
        text = f"{heading}\n\n✅ Ответ отправлен\n{ticket_status(ticket)}"
        rows = [
            [action("➡️ Следующий заказ", f"a:next:{ticket.id}")],
            [action("💬 Дополнить", f"a:reply:{ticket.id}")],
        ]
        if ticket.status in OPEN_STATUSES and ticket.payment_stage in {"legacy", "confirmed"}:
            rows[-1].append(action("✅ Завершить", f"a:set:{ticket.id}:{ticket.version}:resolved"))
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
    if ticket.payment_stage not in {"legacy", "confirmed"}:
        visible = ("cancelled",)
    else:
        visible = ("in_progress", "cancelled") if ticket.status == "new" else ("resolved", "cancelled")
    for status in visible:
        if status in TRANSITIONS[ticket.status]:
            rows.append([action(admin_status(status), f"a:set:{ticket.id}:{ticket.version}:{status}")])
    rows.append([action("← К заказу", f"a:view:{ticket.id}")])
    return f"<b>📦 Заказ №{ticket.id:04d} · статус</b>\n\nСейчас: {ticket_status(ticket)}", Keyboard(rows)


def history(ticket: Ticket, rows, total: int, page: int, admin: bool, timezone: str):
    prefix = "a" if admin else "c"
    texts = [f"<b>💬 Переписка · №{ticket.id:04d}</b>"]
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
