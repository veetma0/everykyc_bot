from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from .store import OPEN_STATUSES, STATUS_NAMES, TRANSITIONS, Ticket
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
    "<b>Какие данные хранит бот</b>\n\n"
    "Telegram ID, имя и username из Telegram, выбранную услугу, сообщения, статусы и заметки оператора. "
    "Они нужны оператору для ответа и сохраняются после перезапуска. "
    "Если вы пришли по ссылке с меткой, сохраняется её источник — чтобы понимать, откуда приходят заявки.\n\n"
    "Не отправляйте ссылку проверки, документы, селфи, пароли и коды входа. "
    "Вложения не передаются оператору и не скачиваются ботом. Если сообщение содержит личные данные, "
    "попросите оператора удалить его.\n\n"
    "Это независимый сервис сопровождения. Решение о проверке принимает соответствующий сервис. "
    "Закрытие заявки означает завершение помощи, а не автоматическое подтверждение KYC."
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
        f"<b>{escape(title)} · помощь с Claude</b>\n\n"
        "Поможем разобраться с проверкой личности своего аккаунта. "
        "Инструкции и ответы — в этом чате."
    )
    rows = []
    if ticket and ticket.status in OPEN_STATUSES:
        text += f"\n\n{catalog.service_title(ticket.service_code, ticket.plan_code)}\n№{ticket.id:04d} · {STATUS_NAMES[ticket.status]}"
        text += "\nНапишите сообщение — оно попадёт в вашу заявку."
        rows.append([action("Моя заявка", f"c:view:{ticket.id}")])
        rows.append([action("Как это работает", "c:help")])
    else:
        text += "\n\nВыберите условия и создайте заявку. 👇"
        rows += [
            [action("Claude", "c:service:claude")],
            [action("Моя карточка", "c:profile"), action("Как это работает", "c:help")],
        ]
    return text, Keyboard(rows)


def prepare():
    return (
        "<b>Перед созданием заявки</b>\n\n"
        "• Проверяется ваш собственный аккаунт и ваша личность.\n"
        "• Документ и селфи вы передаёте на официальной странице проверки.\n"
        "• Оператор помогает с инструкциями и ошибками; решение принимает сервис.\n\n"
        "Создав заявку, вы подтверждаете эти условия. Затем просто напишите свой вопрос в этот чат.",
        Keyboard(
            [
                [action("Подтверждаю · создать заявку", "c:create", "primary")],
                [action("Сначала прочитать инструкцию", "c:help")],
                [action("Назад", "c:home")],
            ]
        ),
    )


def customer_ticket(ticket: Ticket, timezone: str):
    hints = {
        "new": "Заявка создана. Ответ придёт сюда.\nВопрос можно написать обычным сообщением.",
        "in_progress": "Ваш ответ получен. Оператор продолжит здесь.\nМожно добавить сообщение.",
        "waiting_user": "Напишите ответ прямо в этот чат.",
        "resolved": "Сопровождение завершено. Результат проверки смотрите в официальном сервисе.",
        "cancelled": "Заявка закрыта. Если помощь снова понадобится, создайте новую.",
    }
    text = (
        f"<b>{catalog.service_title(ticket.service_code, ticket.plan_code)}</b>\n"
        f"Заявка №{ticket.id:04d} · {catalog.dollars(ticket.price_usd)}\n\n"
        f"{STATUS_NAMES[ticket.status]}\n{hints[ticket.status]}"
    )
    rows = [
        [action("Детали", f"c:details:{ticket.id}"), action("Переписка", f"c:history:{ticket.id}:0")],
    ]
    if ticket.status not in OPEN_STATUSES:
        rows.append([action("Новая заявка", "c:service:claude")])
    else:
        rows.append([action("Меню", "c:home")])
    return text, Keyboard(rows)


def customer_details(ticket: Ticket, timezone: str):
    date = datetime.fromtimestamp(ticket.created_at, ZoneInfo(timezone)).strftime("%d.%m.%Y · %H:%M")
    text = (
        f"<b>Детали · №{ticket.id:04d}</b>\n\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)}\n"
        f"Сопровождение · <b>{catalog.dollars(ticket.price_usd)}</b>\n"
        f"Создана {date}\n{STATUS_NAMES[ticket.status]}\n\n"
        "Результат проверки определяет официальный сервис."
    )
    rows = [
        [action("Инструкция", f"c:guide:{ticket.service_code}"), action("Моя карточка", "c:profile")],
        [action("Оплата · демо", f"c:pay:{ticket.id}")],
    ]
    if ticket.status in OPEN_STATUSES:
        rows.insert(0, [action("Написать оператору", f"c:write:{ticket.id}")])
        rows.append([
            action("Закрыть заявку", f"c:cancel:{ticket.id}:{ticket.version}"),
        ])
    rows.append([action("К заявке", f"c:view:{ticket.id}")])
    return text, Keyboard(rows)


def admin_home(counts: dict[str, int], queue_count: int | None = None):
    active = sum(counts[key] for key in OPEN_STATUSES)
    waiting = counts["new"] + counts["in_progress"] if queue_count is None else queue_count
    return (
        "<b>Кабинет оператора</b>\n\n"
        f"Ждут ответа: <b>{waiting}</b>\n"
        f"Ждём клиента: <b>{counts['waiting_user']}</b>\n\n"
        "«Следующая заявка» откроет обращение для ответа.",
        Keyboard(
            [
                [action("Следующая заявка", "a:next")],
                [
                    action(f"Очередь · {waiting}", "a:list:queue:0"),
                    action(f"Все заявки · {active}", "a:list:active:0"),
                ],
                [action("Клиенты", "a:clients:0")],
                [action("Режим клиента", "a:mode:client")],
            ]
        ),
    )


def admin_status(status: str):
    return "🟣 Ждём клиента" if status == "waiting_user" else STATUS_NAMES[status]


def admin_ticket(ticket: Ticket, snippet: str | None = None):
    username = f" · @{escape(ticket.username)}" if ticket.username else ""
    text = (
        f"<b>Заявка №{ticket.id:04d}</b>\n{escape(ticket.display_name)}{username}\n\n"
        f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · <b>{catalog.dollars(ticket.price_usd)}</b>\n{admin_status(ticket.status)}"
    )
    found = catalog.OFFERS.get((ticket.service_code, ticket.plan_code))
    if found and found.demo:
        text += "\nДЕМО · запрос о доступности, заказ не подтверждён."
    if ticket.demo_network:
        network = catalog.NETWORK_BY_CODE.get(ticket.demo_network)
        text += (
            f"\nUSDT · демо: {escape(network.title) if network else 'сеть выбрана'}\nЭто тестовый выбор сети, без оплаты."
        )
    if ticket.unread:
        text += f"\nНовых сообщений: <b>{ticket.unread}</b>"
    if snippet:
        text += f"\n\n<b>Сообщение клиента</b>\n{escape(snippet)}"
    rows = []
    if ticket.status in OPEN_STATUSES:
        text += "\n\nОтветьте на это сообщение в Telegram или нажмите «Ответить»."
        rows.append(
            [
                action("Ответить", f"a:reply:{ticket.id}", "primary"),
                action("Завершить", f"a:set:{ticket.id}:{ticket.version}:resolved"),
            ]
        )
    rows += [
        [
            action("Переписка", f"a:history:{ticket.id}:0"),
            action("Карточка клиента", f"a:client:{ticket.user_id}"),
        ],
        [action("Следующая", f"a:next:{ticket.id}"), action("Очередь", "a:list:queue:0")],
        [action("Статус", f"a:status:{ticket.id}")],
    ]
    return text, Keyboard(rows)


def reply_receipt(ticket: Ticket, state: str):
    heading = f"<b>№{ticket.id:04d} · {escape(ticket.display_name)}</b>"
    if state == "delivered":
        text = f"{heading}\n\n✓ Ответ отправлен\n{admin_status(ticket.status)}"
        rows = [
            [action("Следующая", f"a:next:{ticket.id}")],
            [
                action("Дополнить", f"a:reply:{ticket.id}"),
                action("Завершить", f"a:set:{ticket.id}:{ticket.version}:resolved"),
            ],
        ]
    elif state == "uncertain":
        text = (
            f"{heading}\n\n⚠️ Telegram не подтвердил доставку: сообщение могло дойти.\n"
            "Ответ сохранён. Автоматического повтора не будет.\n"
            f"Статус: {admin_status(ticket.status)}"
        )
        rows = [
            [action("Проверить переписку", f"a:history:{ticket.id}:0")],
            [action("К заявке", f"a:view:{ticket.id}")],
        ]
    else:
        text = (
            f"{heading}\n\n⚠️ Ответ сохранён, но отправить его не удалось.\n"
            "Клиент сможет прочитать его в истории заявки.\n"
            f"Статус: {admin_status(ticket.status)}"
        )
        rows = [
            [action("К заявке", f"a:view:{ticket.id}")],
            [action("Очередь", "a:list:queue:0")],
        ]
    return text, Keyboard(rows)


def status_menu(ticket: Ticket):
    rows = []
    for status in STATUS_NAMES:
        if status in TRANSITIONS[ticket.status]:
            style = "success" if status == "resolved" else None
            rows.append([action(admin_status(status), f"a:set:{ticket.id}:{ticket.version}:{status}", style)])
    rows.append([action("Назад", f"a:view:{ticket.id}")])
    return f"<b>Заявка №{ticket.id:04d} · статус</b>\n\nСейчас: {admin_status(ticket.status)}", Keyboard(rows)


def history(ticket: Ticket, rows, total: int, page: int, admin: bool, timezone: str):
    prefix = "a" if admin else "c"
    texts = [f"<b>Переписка · №{ticket.id:04d}</b>"]
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
    buttons.append([action("К заявке", f"{prefix}:view:{ticket.id}")])
    return "\n\n".join(texts), Keyboard(buttons)
