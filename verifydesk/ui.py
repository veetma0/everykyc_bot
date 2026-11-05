from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard

from .store import OPEN_STATUSES, STATUS_NAMES, TRANSITIONS, Ticket, can_customer_cancel, ticket_status
from . import catalog, theme


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
    parts = data.split(":")
    icon = theme.service_icon(parts[2]) if len(parts) == 3 and parts[1] == "service" else None
    return Button(text, callback_data=data, icon_custom_emoji_id=icon)


def text_units(text: str):
    return len(text.encode("utf-16-le")) // 2


def clip_text(text: str, limit: int):
    return text.encode("utf-16-le")[: limit * 2].decode("utf-16-le", errors="ignore")


def conversation_title(ticket: Ticket):
    return f"{'🤝 Опт' if getattr(ticket, 'kind', 'order') == 'wholesale' else '📦 Заказ'} №{ticket.id:04d}"


def conversation_keyboard(tickets, selected_id=None):
    return Keyboard([[
        action(("✓ " if ticket.id == selected_id else "") + conversation_title(ticket), f"c:chat:{ticket.id}")
        for ticket in tickets
    ]])


def home(title: str, ticket: Ticket | None):
    rows = [
        [action("Каталог услуг", "c:catalog")],
        [action("Мои заказы", "c:profile"), action("Помощь", "c:help")],
        [action("Правила сервиса", "c:rules")],
    ]
    text = (
        f"<b>{escape(title)}</b>\n"
        "Помощь с верификацией вашего аккаунта.\n\n"
        "Выберите сервис в каталоге — там есть цены и условия. "
        "После оформления заказа оператор ответит в этом чате."
    )
    if ticket and ticket.status in OPEN_STATUSES:
        text += (
            f"\n\n<b>Ваш заказ №{ticket.id:04d}</b>\n"
            f"{escape(catalog.service_title(ticket.service_code, ticket.plan_code))} · {ticket_status(ticket)}"
        )
        rows.insert(0, [action("Продолжить заказ", f"c:chat:{ticket.id}")])
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
            + ("Ранее открытая переписка с оператором.\n\n"
               "Напишите сообщение в этот чат. Оператор ответит здесь."
               if active else "Обсуждение завершено. Переписка сохранена.")
        )
        return text, Keyboard(customer_ticket_navigation(ticket))
    if ticket.status == "new" and ticket.payment_stage == "awaiting_payment":
        return payment_request(ticket)
    hints = {
        "new": "Оператор уточнит вашу страну и условия, затем отправит реквизиты.\n"
               "Пока опишите, с чем нужна помощь.",
        "in_progress": "Ожидайте сообщения от оператора.\n"
                       "Порядок самостоятельной проверки уточнит оператор.\n"
                       "🔒 Ссылку KYC, документы и коды входа сюда не отправляйте.",
        "waiting_user": "Оператор ждёт ваш ответ. Напишите его в этом чате.",
        "resolved": "Сопровождение завершено. Спасибо за обращение!",
        "cancelled": "Заказ отменён.",
    }
    hint = hints[ticket.status]
    if ticket.status == "new" and ticket.payment_stage == "review":
        hint = "Подтверждение оплаты отправлено оператору. Ожидайте его ответа."
    text = (
        f"<b>{conversation_title(ticket)}</b>\n"
        f"{escape(catalog.service_title(ticket.service_code, ticket.plan_code))} · {catalog.dollars(ticket.price_usd)}\n\n"
        f"<b>{ticket_status(ticket)}</b>\n{hint}"
    )
    rows = []
    if ticket.status not in OPEN_STATUSES:
        rows.append([action("Выбрать услугу", "c:catalog")])
    else:
        if ticket.payment_stage != "review":
            text += "\n\nСообщения оператору отправляйте прямо в этот чат."
        if ticket.payment_stage == "confirmed":
            rows.append([action("Инструкция", f"c:guide:{ticket.service_code}")])
    rows += customer_ticket_navigation(ticket)
    return text, Keyboard(rows)


def customer_ticket_navigation(ticket: Ticket):
    rows = [[action("Переписка", f"c:history:{ticket.id}:0")]]
    if can_customer_cancel(ticket):
        rows.append([action("Отменить заказ", f"c:cancel:{ticket.id}:{ticket.version}")])
    rows.append([action("Мои заказы", "c:profile"), action("Главная", "c:home")])
    return rows


def customer_details(ticket: Ticket, timezone: str):
    return customer_ticket(ticket, timezone)


def payment_request(ticket: Ticket):
    if ticket.has_payment_proof:
        return (
            f"<b>{conversation_title(ticket)}</b>\n"
            f"{escape(catalog.service_title(ticket.service_code, ticket.plan_code))} · {catalog.dollars(ticket.price_usd)}\n\n"
            "<b>🧾 Нужен другой чек</b>\n"
            "По предыдущему чеку оператор не смог подтвердить оплату.\n\n"
            "Пришлите новый скриншот, файл или ссылку на чек в этот чат. "
            "Если не знаете, что исправить, уточните у оператора.\n\n"
            "Повторно платить без согласования с оператором не нужно.",
            Keyboard(customer_ticket_navigation(ticket)),
        )
    return (
        f"<b>{conversation_title(ticket)}</b>\n"
        f"{escape(catalog.service_title(ticket.service_code, ticket.plan_code))} · {catalog.dollars(ticket.price_usd)}\n\n"
        "<b>💳 Ожидает оплаты</b>\n"
        "Оператор принял заказ. Дождитесь реквизитов в этом чате и согласуйте условия до оплаты.\n\n"
        "После оплаты пришлите сюда фото, файл или ссылку на чек. "
        "Скройте лишние личные данные. Оператор проверит оплату.\n\n"
        "После отправки чека отменить заказ сможет только оператор.",
        Keyboard(customer_ticket_navigation(ticket)),
    )


def review_request(ticket: Ticket):
    return (
        f"<b>⭐ Как всё прошло?</b>\n{conversation_title(ticket)}\n\n"
        "Оцените работу от 1 до 5 звёзд. После оценки можно добавить комментарий.",
        Keyboard([
            [action(f"{stars} ⭐", f"c:rate:{ticket.id}:{stars}") for stars in range(1, 6)],
            [action("Не сейчас", "c:home")],
        ]),
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
        "<b>Кабинет оператора</b>\n\n"
        f"Требуют внимания: <b>{waiting}</b>\n"
        f"💳 Чеки на проверке: <b>{stages['review'] if stages else 0}</b>\n"
        f"🛠 В работе: <b>{counts['in_progress'] + counts['waiting_user']}</b>\n\n"
        "Сначала — чеки, затем заказы в работе и новые обращения.",
        Keyboard([
            [action(f"▶️ Следующий · {waiting}", "a:next")],
            [action(f"Обращения · {active}", "a:list:active:0"), action("По номеру", "a:find")],
            [action("Ещё", "a:more")],
        ]),
    )


def admin_more():
    return (
        "<b>Дополнительно</b>\n\nВыберите раздел.",
        Keyboard([
            [action("Очередь ответов", "a:list:queue:0"), action("Архив заказов", "a:list:closed:0")],
            [action("Клиенты", "a:clients:0")],
            [action("Иконки бирж", "a:style"), action("Предпросмотр", "a:preview")],
            [action("Режим клиента", "a:mode:client")],
            [action("‹ В кабинет", "a:home")],
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
        excerpt = clip_text(snippet, 420)
        text += f"\n\n{escape(excerpt)}"
        if text_units(snippet) > 420:
            text += "…\nПолностью — в переписке."
    if ticket.payment_stage == "awaiting_payment" and not wholesale:
        text += (
            "\n\nОбъясните клиенту через «Ответить», что нужно исправить в чеке."
            if ticket.has_payment_proof else
            "\n\nОтправьте клиенту реквизиты и согласованные условия через «Ответить»."
        )
    rows = []
    if ticket.status in OPEN_STATUSES:
        if not wholesale and ticket.payment_stage == "not_requested":
            rows.append([action("💳 Принять заказ", f"a:request_payment:{ticket.id}:{ticket.version}")])
        elif not wholesale and ticket.payment_stage == "review":
            if proof_ready:
                rows.append([action("✅ Оплата получена", f"a:confirm_payment:{ticket.id}:{ticket.version}")])
                rows.append([action("Запросить другой чек", f"a:reject_payment:{ticket.id}:{ticket.version}")])
            else:
                rows.append([action("🔎 Проверить чек", f"a:proofs:{ticket.id}")])
        reply = [action("Ответить", f"a:reply:{ticket.id}")]
        if not wholesale and ticket.payment_stage in {"legacy", "confirmed"}:
            reply.append(action(
                "Завершить заказ",
                f"a:set:{ticket.id}:{ticket.version}:resolved",
            ))
        rows.append(reply)
        if wholesale:
            rows.append([action("Завершить обсуждение", f"a:set:{ticket.id}:{ticket.version}:resolved")])
        text += "\n\nНажмите «Ответить» или ответьте на это сообщение в Telegram."
    rows.append([
        action("Переписка", f"a:history:{ticket.id}:0"),
        action("Подробнее", f"a:details:{ticket.id}"),
    ])
    rows.append([action("Следующий", f"a:next:{ticket.id}"), action("В кабинет", "a:home")])
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
        action("Переписка", f"a:history:{ticket.id}:0"),
        action("Клиент", f"a:client:{ticket.user_id}"),
    ]]
    if ticket.payment_stage in {"awaiting_payment", "review", "confirmed"}:
        rows.append([action("Подтверждения оплаты", f"a:proofs:{ticket.id}")])
    if ticket.status in OPEN_STATUSES:
        rows.append([action("Изменить статус", f"a:status:{ticket.id}")])
    rows.append([action("‹ К заказу", f"a:view:{ticket.id}"), action("В кабинет", "a:home")])
    return text, Keyboard(rows)


def reply_receipt(ticket: Ticket, state: str):
    heading = f"<b>{conversation_title(ticket)} · {escape(ticket.display_name)}</b>"
    if state == "delivered":
        text = f"{heading}\n\n✅ Ответ отправлен\n{ticket_status(ticket)}\n\nМожно продолжать писать этому клиенту в чат."
        rows = [
            [action("Дополнить", f"a:reply:{ticket.id}"), action("Следующий", f"a:next:{ticket.id}")],
        ]
        if ticket.status in OPEN_STATUSES and ticket.payment_stage in {"legacy", "confirmed"}:
            rows.append([action(
                "Завершить обсуждение" if getattr(ticket, "kind", "order") == "wholesale" else "Завершить заказ",
                f"a:set:{ticket.id}:{ticket.version}:resolved",
            )])
    elif state == "uncertain":
        text = (
            f"{heading}\n\n⚠️ Telegram не подтвердил доставку: сообщение могло дойти.\n"
            "Ответ сохранён. Автоматического повтора не будет.\n"
            f"Статус: {ticket_status(ticket)}"
        )
        rows = [
            [action("Проверить переписку", f"a:history:{ticket.id}:0")],
        ]
    else:
        text = (
            f"{heading}\n\n⚠️ Ответ сохранён, но отправить его не удалось.\n"
            "Клиент сможет прочитать его в переписке заказа.\n"
            f"Статус: {ticket_status(ticket)}"
        )
        rows = [
            [action("Очередь ответов", "a:list:queue:0")],
        ]
    rows.append([action("‹ К заказу", f"a:view:{ticket.id}"), action("В кабинет", "a:home")])
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
            labels = {
                "in_progress": "Начать работу",
                "resolved": "Завершить обсуждение" if getattr(ticket, "kind", "order") == "wholesale"
                else "Завершить заказ",
                "cancelled": "Закрыть обсуждение" if getattr(ticket, "kind", "order") == "wholesale"
                else "Отменить заказ",
            }
            rows.append([action(
                labels[status], f"a:set:{ticket.id}:{ticket.version}:{status}",
            )])
    rows.append([action("‹ К заказу", f"a:view:{ticket.id}"), action("В кабинет", "a:home")])
    return f"<b>{conversation_title(ticket)} · статус</b>\n\nСейчас: {ticket_status(ticket)}", Keyboard(rows)


def history(ticket: Ticket, rows, total: int, page: int, admin: bool, timezone: str):
    prefix = "a" if admin else "c"
    texts = [f"<b>{conversation_title(ticket)} · переписка</b>"]
    if total > 4:
        texts.append(f"Страница {page + 1} из {(total + 3) // 4}" + (" · последние сообщения" if page == 0 else ""))
    elif not rows:
        texts.append("Сообщений пока нет.")
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
