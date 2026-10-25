from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from .store import OPEN_STATUSES, STATUS_NAMES, TRANSITIONS, Ticket, ticket_status
from . import catalog


HELP_URL = "https://support.claude.com/en/articles/14328960-identity-verification-on-claude"
INSTRUCTIONS = (
    "<b>📋 Наша инструкция</b>\n\n"
    "1. После подтверждения оплаты дождитесь Фамилии и Имени от оператора.\n"
    "2. До этого не создавайте ссылку на верификацию и не начинайте проверку самостоятельно.\n"
    "3. Строго следуйте нашей инструкции. Каждый следующий шаг согласуйте с оператором.\n\n"
    "Проверку собственного аккаунта проходите на свои настоящие данные. "
    "Документы и селфи вводите только на официальной странице Claude.\n"
    "Не отправляйте сюда документы, ссылку проверки, пароли и коды входа."
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
    if ticket and ticket.status in OPEN_STATUSES:
        return customer_ticket(ticket, "Asia/Amman")
    return (
        f"<b>👋 {escape(title)} · помощь с Claude</b>\n\n"
        "Выберите регион, посмотрите стоимость и оформите заказ. Оператор ответит в этом чате.",
        Keyboard([[action("Оформить заказ", "c:service:claude")]]),
    )


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
    if ticket.status == "new" and ticket.payment_stage == "awaiting_payment":
        return payment_request(ticket)
    hints = {
        "new": "Оператор скоро примет заказ. Ответ придёт сюда.",
        "in_progress": "Ожидайте Фамилию и Имя от оператора.\n"
                       "Ссылку на верификацию пока не создавайте.\n"
                       "Строго следуйте нашей инструкции и указаниям оператора.",
        "waiting_user": "Ответ оператора выше. Продолжайте общение в этом чате.\n"
                        "Ссылку на верификацию создавайте только по инструкции оператора.",
        "resolved": "Сопровождение завершено. Спасибо за обращение!",
        "cancelled": "Заказ отменён.",
    }
    hint = hints[ticket.status]
    if ticket.status == "new" and ticket.payment_stage == "review":
        hint = "Чек отправлен. Ожидайте подтверждения оператора."
    text = (
        f"<b>Заказ №{ticket.id:04d} · {catalog.dollars(ticket.price_usd)}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)}\n\n"
        f"{ticket_status(ticket)}\n{hint}"
    )
    if ticket.status not in OPEN_STATUSES:
        button = action("Новый заказ", "c:service:claude")
    elif ticket.payment_stage == "confirmed":
        button = action("📋 Наша инструкция", f"c:guide:{ticket.service_code}")
    else:
        button = action("Написать оператору", f"c:write:{ticket.id}")
    return text, Keyboard([[button]])


def customer_details(ticket: Ticket, timezone: str):
    # Old Telegram cards should open the same simple order screen.
    return customer_ticket(ticket, timezone)


def payment_request(ticket: Ticket):
    return (
        f"<b>💳 Оплата заказа №{ticket.id:04d}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n\n"
        "<b>Сейчас тестовый режим. Реальные реквизиты ещё не подключены.</b>\n"
        "Деньги переводить не нужно.\n\n"
        "Для проверки сценария пришлите тестовый скриншот или ссылку на чек без личных данных. "
        "Перед отправкой оператору бот попросит подтверждение.",
        Keyboard([[action("Отправить чек", f"c:proof_prompt:{ticket.id}")]]),
    )


def admin_home(counts: dict[str, int], queue_count: int | None = None):
    active = sum(counts[key] for key in OPEN_STATUSES)
    waiting = counts["new"] + counts["in_progress"] if queue_count is None else queue_count
    return (
        "<b>Заказы</b>\n\n"
        f"Требуют внимания: <b>{waiting}</b>\n"
        f"В работе: <b>{counts['in_progress'] + counts['waiting_user']}</b>\n\n"
        "Откройте следующий заказ. Ответить можно прямо на его сообщение в Telegram.",
        Keyboard([
            [action(f"Следующий · {waiting}", "a:next")],
            [action(f"Все заказы · {active}", "a:list:active:0")],
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
    text = (
        f"<b>№{ticket.id:04d} · {escape(ticket.display_name)}</b>\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n"
        f"{ticket_status(ticket)}"
    )
    if snippet:
        text += f"\n\n{escape(snippet)}"
    rows = []
    if ticket.status in OPEN_STATUSES:
        if ticket.payment_stage == "not_requested":
            rows.append([
                action("💳 Принять заказ", f"a:request_payment:{ticket.id}:{ticket.version}"),
                action("Ответить", f"a:reply:{ticket.id}"),
            ])
        elif ticket.payment_stage == "review":
            if proof_ready:
                rows.append([
                    action("✅ Оплата получена", f"a:confirm_payment:{ticket.id}:{ticket.version}"),
                    action("Запросить другой чек", f"a:reject_payment:{ticket.id}:{ticket.version}"),
                ])
            else:
                rows.append([action("Проверить чек", f"a:proofs:{ticket.id}")])
        elif ticket.payment_stage == "awaiting_payment":
            rows.append([action("Ответить", f"a:reply:{ticket.id}")])
        else:
            rows.append([
                action("Ответить", f"a:reply:{ticket.id}"),
                action("✅ Выполнен", f"a:set:{ticket.id}:{ticket.version}:resolved"),
            ])
        text += "\n\n💬 Чтобы ответить сразу, используйте Reply на это сообщение."
    rows.append([action("Следующий →", f"a:next:{ticket.id}")])
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
