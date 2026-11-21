"""Small native screens for the catalog, personal cards and mock checkout."""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import catalog, ui
from .store import OPEN_STATUSES, ticket_status


CATALOG_PAGE_SIZE = 5


def _two_columns(buttons):
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)]


def category_offers(category):
    return [offer for offer in catalog.OFFERS.values() if offer.category == category]


def category_page(offer):
    """Every offer has a stable return address, including old service buttons."""
    return category_offers(offer.category).index(offer) // CATALOG_PAGE_SIZE


def _service_button(offer):
    # Short names keep both columns readable on narrow Telegram clients.
    title = catalog.SHORT_TITLES.get(offer.service, offer.title)
    label = f"{title} · {catalog.offer_price(offer)}" if offer.available else f"⛔ {title}"
    return ui.action(label, f"c:service:{offer.service}")


def catalog_card():
    shortcuts = []
    lines = ["<b>Каталог услуг</b>", "", "Популярные сервисы"]
    for code in ("claude", "bybit", "alipay"):
        offer = catalog.offer(code, "standard")
        title = catalog.SHORT_TITLES.get(code, offer.title)
        lines.append(f"{escape(title)} · {catalog.offer_price(offer)}")
        shortcuts.append(ui.action(title, f"c:service:{code}"))
    return "\n".join(lines), ui.Keyboard([
        *_two_columns(shortcuts),
        [ui.action("Все разделы", "c:sections", "primary")],
        [ui.action("‹ Главная", "c:home")],
    ])


def sections_card():
    return (
        "<b>Все разделы</b>\n\nВыберите раздел каталога.",
        ui.Keyboard(
            _two_columns([ui.action(title, f"c:category:{code}") for code, title in catalog.CATEGORIES.items()])
            + [[ui.action("‹ Каталог", "c:catalog")]]
        ),
    )


def category_card(category, page=0):
    title = catalog.CATEGORIES[category]
    offers = category_offers(category)
    pages = max(1, (len(offers) + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * CATALOG_PAGE_SIZE
    lines = [f"<b>Каталог · {title}</b>"]
    if pages > 1:
        lines.append(f"Страница {page + 1} из {pages}")
    lines += ["", "На кнопке — стоимость сопровождения. Доступность для вашей страны уточнит оператор."]
    rows = _two_columns([_service_button(offer) for offer in offers[start:start + CATALOG_PAGE_SIZE]])
    navigation = []
    if page:
        navigation.append(ui.action(f"‹ {page}/{pages}", f"c:category:{category}:{page - 1}"))
    if page + 1 < pages:
        navigation.append(ui.action(f"{page + 2}/{pages} ›", f"c:category:{category}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([ui.action("‹ Разделы", "c:sections")])
    return "\n".join(lines), ui.Keyboard(rows)


def offer_card(offer):
    text = f"<b>{escape(offer.title)} · Верификация</b>\n\n"
    rows = []
    if not offer.available:
        text += "Сервис прекратил работу. Открыть новый заказ на верификацию здесь уже нельзя."
    else:
        text += f"{escape(offer.detail)}\n\n"
        text += f"<b>Стоимость сопровождения · {catalog.offer_price(offer)}</b>\n"
        text += "Доступность для вашей страны и условия уточнит оператор до оплаты.\n"
        if offer.price_from:
            text += "Точная стоимость зависит от задачи.\n"
        if offer.service == "claude":
            text += "Подписка Claude оплачивается отдельно.\n"
        text += (
            "\nПроверку вы проходите сами на свои данные в официальном сервисе. "
            "Оформляя заказ, подтверждаете, что аккаунт ваш.\n\n"
            "<b>Оформление без списаний.</b>"
        )
        rows.append([ui.action(
            f"Заказать · {catalog.offer_price(offer)}", f"c:order:{offer.service}:{offer.plan}", "primary",
        )])
    rows.append([ui.action(f"‹ {catalog.CATEGORIES[offer.category]}", f"c:category:{offer.category}:{category_page(offer)}"),
                 ui.action("В каталог", "c:catalog")])
    return text, ui.Keyboard(rows)


def guide(service="general"):
    if service != "general" and (service, "standard") not in catalog.OFFERS:
        raise ValueError("Service unavailable")
    title = "Как это работает" if service == "general" else f"{catalog.service_title(service, 'standard')} · Следующие шаги"
    steps = (
        "<b>Выберите сервис.</b> Узнайте цену в карточке, оформите заказ и напишите свой вопрос.\n\n"
        "<b>Согласуйте условия.</b> Оператор уточнит вашу страну и задачу. "
        "После согласования он отправит реквизиты в этот чат.\n\n"
        "<b>Получите помощь.</b> Пришлите чек после оплаты. Когда оператор подтвердит его, он подскажет следующий шаг."
        if service == "general" else
        "Откройте раздел проверки личности в своём аккаунте и следуйте подсказкам оператора.\n\n"
        "Если возникла ошибка, пришлите её текст в этот чат без личных данных."
    )
    return (
        f"<b>{escape(title)}</b>\n\n"
        f"{steps}\n\n"
        "Проверку проходите самостоятельно на свои данные в официальном сервисе. "
        "Ссылку KYC, документы, селфи, пароли и коды входа сюда не отправляйте."
        + ("\n\nПодписка Claude оплачивается отдельно." if service == "claude" else "")
    )


def unavailable_service():
    return (
        "<b>⛔ Услуга недоступна</b>\n\nВыберите другое направление в каталоге.",
        ui.Keyboard([[ui.action("Каталог услуг", "c:catalog", "primary")],
                     [ui.action("‹ Главная", "c:home")]]),
    )


def help_card():
    rows = [
        [ui.action("Выбрать услугу", "c:catalog", "primary")],
        [ui.action("Как это работает", "c:guide:general"), ui.action("Мои данные", "c:privacy")],
        [ui.action("‹ Главная", "c:home"), ui.action("Правила", "c:rules")],
    ]
    return (
        "<b>Помощь</b>\n\n"
        "<b>Как связаться с оператором?</b>\n"
        "Выберите услугу и оформите заказ. Если заказ уже открыт, просто напишите сюда.\n\n"
        "<b>Когда платить?</b>\n"
        "Оператор пришлёт реквизиты, когда вы согласуете задачу, цену и условия.\n\n"
        "<b>Куда отправлять документы?</b>\n"
        "Загружайте их только на официальной странице проверки аккаунта. Для разбора ошибки достаточно её текста.",
        ui.Keyboard(rows),
    )


def order_page_size(admin):
    return 8 if admin else 4


def orders_card(tickets, offset, total, user_id, admin=False):
    page_size = order_page_size(admin)
    text = "<b>История заказов</b>\n\n"
    if not tickets:
        text += "Заказов пока нет." if admin else "Здесь появятся завершённые и отменённые заказы."
    elif total > page_size:
        text += f"Страница {offset // page_size + 1} из {(total + page_size - 1) // page_size} · Всего {total}"
    else:
        text = text.rstrip()
    rows = []
    for ticket in tickets:
        wholesale = ticket.kind == "wholesale"
        title = "Переписка об опте" if wholesale else catalog.service_title(ticket.service_code, ticket.plan_code)
        number = f"№{ticket.id:04d}"
        status = ticket_status(ticket)
        if admin:
            label = f"{status.split()[0]} {number} · {ui.clip_text(title, 26)}"
        else:
            text += f"\n\n<b>{number} · {escape(title)}</b>\n{escape(status)}"
            label = f"{'Переписка' if wholesale else 'Заказ'} {number}"
        rows.append([ui.action(label, f"{'a' if admin else 'c'}:view:{ticket.id}")])
    if tickets:
        text += "\n\nВыберите заказ, чтобы открыть детали и переписку."
    navigation = []
    base = f"a:orders:{user_id}" if admin else "c:orders"
    if offset:
        navigation.append(ui.action("← Назад", f"{base}:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        navigation.append(ui.action("Далее →", f"{base}:{offset + page_size}"))
    if navigation:
        rows.append(navigation)
    if admin:
        rows.append([ui.action("‹ К клиенту", f"a:client:{user_id}")])
    else:
        rows.append([ui.action("‹ Главная", "c:home")])
    return text, ui.Keyboard(rows)


def admin_profile_card(profile, current, timezone, *, has_history=None):
    if has_history is None:
        has_history = bool(profile.total_tickets)
    name = escape(profile.display_name)
    since = datetime.fromtimestamp(profile.first_seen_at, ZoneInfo(timezone)).strftime("%d.%m.%Y")
    text = f"<b>👤 Карточка клиента</b>\n{name}"
    if profile.username:
        text += f" · @{escape(profile.username)}"
    if current:
        text += (
            f"\n\n<b>📌 Текущий заказ</b>\n{catalog.service_title(current.service_code, current.plan_code)}"
            f" · {catalog.dollars(current.price_usd)}\n№{current.id:04d} · {ticket_status(current)}"
        )
    else:
        text += "\n\nАктивных заказов пока нет."
    text += f"\n\nВсего заказов · <b>{profile.total_tickets}</b>\nЗавершено · <b>{profile.resolved_tickets}</b>"
    text += f"\nС нами с {since} · ID <code>{profile.id}</code>"
    note = escape(profile.operator_note) if profile.operator_note else "Пока нет."
    text += f"\n\n<b>📝 Личная заметка · только вам</b>\n{note}"

    rows = []
    if current:
        rows.append([ui.action("📦 Открыть заказ", f"a:view:{current.id}", "primary")])
    actions = [ui.action("История", f"a:orders:{profile.id}:0")] if has_history else []
    actions.append(ui.action("📝 Заметка", f"a:note:{profile.id}"))
    rows += [actions, [ui.action("← К клиентам", "a:clients:0"), ui.action("🏠 Кабинет", "a:home")]]
    return text, ui.Keyboard(rows)


def payment_card(ticket):
    selected = catalog.NETWORK_BY_CODE.get(ticket.demo_network)
    text = (
        f"<b>USDT · ДЕМО</b>\nЗаказ №{ticket.id:04d}\n\n"
        "Выберите сеть, чтобы проверить сценарий оплаты.\nДеньги не переводятся, реквизитов нет.\n\n"
        f"<b>Стоимость сопровождения:</b> {catalog.dollars(ticket.price_usd)}"
    )
    if selected:
        text += (
            f"\n\nВыбран пример: <b>{escape(selected.title)}</b> · {catalog.NETWORK_GROUPS[selected.group]}"
        )
    if ticket.status not in OPEN_STATUSES:
        text += (
            "\n\nЗаказ закрыт. Сохранён только прошлый выбор."
        )
        return text, ui.Keyboard([[ui.action("← К заказу", f"c:view:{ticket.id}")]])
    rows = [
        [
            ui.action("TRON · TRC20", f"c:network:{ticket.id}:usdt_tron"),
            ui.action("TON", f"c:network:{ticket.id}:usdt_ton"),
        ],
        [ui.action("Ethereum · ERC20", f"c:network:{ticket.id}:usdt_ethereum")],
        [
            ui.action("Другие сети USDT", f"c:networks:{ticket.id}:usdt:0"),
            ui.action("USDT0", f"c:networks:{ticket.id}:usdt0:0"),
        ],
        [ui.action("Другие версии токена", f"c:networks:{ticket.id}:bridged:0")],
        [ui.action("← К заказу", f"c:view:{ticket.id}")],
    ]
    return text, ui.Keyboard(rows)


def network_page(ticket, group, offset):
    networks = [n for n in catalog.NETWORKS if n.group == group]
    offset = max(0, min(offset, ((len(networks) - 1) // 8) * 8))
    rows = [[ui.action(n.title, f"c:network:{ticket.id}:{n.code}")] for n in networks[offset : offset + 8]]
    navigation = []
    if offset:
        navigation.append(ui.action("← Назад", f"c:networks:{ticket.id}:{group}:{offset - 8}"))
    if offset + 8 < len(networks):
        navigation.append(ui.action("Далее →", f"c:networks:{ticket.id}:{group}:{offset + 8}"))
    if navigation:
        rows.append(navigation)
    rows.append([ui.action("К вариантам оплаты", f"c:pay:{ticket.id}")])
    text = (
        f"<b>{catalog.NETWORK_GROUPS[group]} · ДЕМО</b>\n{len(networks)} вариантов\n\n"
        "Выберите сеть для примера. Переводов здесь нет."
    )
    if group == "usdt0":
        text += "\n\nUSDT0 — отдельная версия токена, не обычный USDT."
    elif group == "bridged":
        text += "\n\nЭто отдельные версии токена; прямой выпуск Tether здесь не заявляется."
    return text, ui.Keyboard(rows)


def network_selected(ticket, network):
    return (
        f"<b>Сеть выбрана · ДЕМО</b>\n\nВыбрана сеть <b>{escape(network.title)}</b>.\n"
        "Выбор сохранён. Это демо: оплата не совершена.",
        ui.Keyboard(
            [
                [ui.action("← К заказу", f"c:view:{ticket.id}", "primary")],
                [ui.action("Выбрать другую сеть", f"c:pay:{ticket.id}")],
            ]
        ),
    )


def preview_markup(keyboard):
    if not isinstance(keyboard, ui.Keyboard):
        return keyboard
    rows = []
    for row in keyboard.inline_keyboard:
        buttons = []
        for button in row:
            data = button.to_dict()
            if str(data.get("callback_data", "")).startswith("c:"):
                data["callback_data"] = "p:" + data["callback_data"][2:]
            buttons.append(ui.Button.de_json(data, None))
        rows.append(buttons)
    return ui.Keyboard(rows)
