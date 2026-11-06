"""Small native screens for the catalog, personal cards and mock checkout."""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import catalog, ui
from .store import OPEN_STATUSES, ticket_status


CATALOG_PAGE_SIZE = 8
CATEGORY_BUTTON_TITLES = {
    "exchanges": "Биржи", "marketplaces": "Маркетплейсы", "wallets": "Кошельки",
    "telegram": "Telegram", "casinos": "Казино", "other": "AI и сервисы",
}


def _two_columns(buttons):
    return [buttons[index:index + 2] for index in range(0, len(buttons), 2)]


def category_offers(category):
    return [offer for offer in catalog.OFFERS.values() if offer.category == category]


def category_page(offer):
    """Every offer has a stable return address, including old service buttons."""
    return category_offers(offer.category).index(offer) // CATALOG_PAGE_SIZE


def _service_button(offer):
    # Short names keep both columns readable on narrow Telegram clients.
    title = {"fragment": "Fragment", "telegram_wallet": "Wallet",
             "dragon_money": "Dragon M."}.get(offer.service, offer.title)
    label = f"{title} · {catalog.offer_price(offer)}" if offer.available else f"⛔ {title}"
    return ui.action(label, f"c:service:{offer.service}")


def catalog_card():
    return (
        "<b>Каталог услуг</b>\n\n"
        "Выберите категорию.\n"
        "Цена сопровождения — на кнопке сервиса.",
        ui.Keyboard(
            _two_columns([ui.action(CATEGORY_BUTTON_TITLES[code], f"c:category:{code}")
                          for code in catalog.CATEGORIES])
            + [[ui.action("Мои заказы", "c:profile"), ui.action("‹ Главная", "c:home")]]
        ),
    )


def category_card(category, page=0):
    title = catalog.CATEGORIES[category]
    offers = category_offers(category)
    pages = max(1, (len(offers) + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * CATALOG_PAGE_SIZE
    lines = [f"<b>{title}</b>"]
    if pages > 1:
        lines.append(f"{page + 1} / {pages} · {len(offers)} сервисов")
    lines += ["", "Выберите сервис — откроется карточка с условиями.",
              "Доступность для вашей страны уточнит оператор."]
    rows = _two_columns([_service_button(offer) for offer in offers[start:start + CATALOG_PAGE_SIZE]])
    navigation = []
    if page:
        navigation.append(ui.action("‹ Предыдущие", f"c:category:{category}:{page - 1}"))
    if page + 1 < pages:
        navigation.append(ui.action("Следующие ›", f"c:category:{category}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([ui.action("‹ Разделы", "c:catalog"), ui.action("Главная", "c:home")])
    return "\n".join(lines), ui.Keyboard(rows)


def service_card(service):
    return offer_card(catalog.offer(service, "standard"))


def offer_card(offer):
    text = f"<b>{escape(offer.title)}</b>\n"
    rows = []
    if not offer.available:
        text += "\n⛔ Сервис прекратил работу. Новые заказы на верификацию не принимаются."
    else:
        text += f"<b>{catalog.offer_price(offer)}</b> · сопровождение KYC\n\n"
        text += f"{escape(offer.detail)}\n\n"
        text += "Доступность для вашей страны и условия уточнит оператор до оплаты.\n"
        if offer.price_from:
            text += "Точная стоимость зависит от задачи.\n"
        if offer.service == "claude":
            text += "Подписка Claude оплачивается отдельно.\n"
        text += (
            "\nПроверку вы проходите сами на свои данные в официальном сервисе. "
            "Оформляя заказ, подтверждаете, что аккаунт ваш.\n\n"
            "<b>Создание заказа без списаний.</b> Затем напишите вопрос в этот чат."
        )
        rows.append([ui.action(
            f"Оформить заказ · {catalog.offer_price(offer)}", f"c:order:{offer.service}:{offer.plan}", "primary",
        )])
    rows.append([ui.action("‹ К списку", f"c:category:{offer.category}:{category_page(offer)}"),
                 ui.action("Главная", "c:home")])
    return text, ui.Keyboard(rows)


def guide(service="general"):
    if service != "general" and (service, "standard") not in catalog.OFFERS:
        raise ValueError("Service unavailable")
    title = "Как оформить заказ" if service == "general" else catalog.service_title(service, "standard")
    steps = (
        "1. Выберите услугу, оформите заказ и напишите вопрос в этот чат.\n\n"
        "2. Оператор уточнит страну и условия, затем отправит реквизиты.\n\n"
        "3. После оплаты пришлите сюда чек — фото, файл или ссылку. Оператор проверит его и подтвердит оплату.\n\n"
        "4. Следуйте подсказкам оператора. Вся переписка останется здесь."
        if service == "general" else
        "1. Дождитесь указаний оператора по вашему вопросу.\n\n"
        "2. Откройте проверку в своём аккаунте на официальном сайте или в приложении сервиса.\n\n"
        "3. Если появилась ошибка, пришлите её текст в этот чат без личных данных."
    )
    return (
        f"<b>{escape(title)} · инструкция</b>\n\n"
        f"{steps}\n\n"
        "🔒 Проверку проходите самостоятельно на свои данные в официальном сервисе. "
        "Ссылку KYC, документы, селфи, пароли и коды входа сюда не отправляйте."
        + ("\n\n💡 Подписка Claude оплачивается отдельно." if service == "claude" else "")
    )


def unavailable_service():
    return (
        "<b>⛔ Услуга недоступна</b>\n\nВыберите другое направление в каталоге. История прежних заказов сохранена.",
        ui.Keyboard([[ui.action("Каталог услуг", "c:catalog", "primary")],
                     [ui.action("Мои заказы", "c:profile")]]),
    )


def help_card(current=None):
    rows = []
    if current and current.status in OPEN_STATUSES:
        rows.append([ui.action("Написать по заказу", "c:current", "primary")])
    else:
        rows.append([ui.action("Выбрать услугу", "c:catalog", "primary")])
    rows += [[ui.action("Правила", "c:rules"), ui.action("Мои данные", "c:privacy")],
             [ui.action("Инструкция", "c:guide:general"), ui.action("Главная", "c:home")]]
    return (
        "<b>Помощь</b>\n\n"
        "<b>Связь с оператором</b>\n"
        "Откройте заказ и пишите прямо в этот чат. Ответ придёт сюда.\n\n"
        "<b>Условия и оплата</b>\n"
        "Сначала оператор уточнит страну и задачу. После согласования отправит реквизиты.\n\n"
        "<b>Верификация</b>\n"
        "Проверку проходите вы. Документы, селфи и коды вводите только в официальном сервисе.",
        ui.Keyboard(rows),
    )


def profile_card(profile, current, timezone, admin=False, has_history=None):
    if has_history is None:
        has_history = bool(profile.total_tickets)
    if not admin:
        text = "<b>Мои заказы</b>"
        rows = []
        if current:
            text += (
                f"\n\n<b>{escape(catalog.service_title(current.service_code, current.plan_code))}</b>"
                f" · {catalog.dollars(current.price_usd)}\n"
                f"Заказ №{current.id:04d}\n{ticket_status(current)}"
            )
            rows.append([ui.action("Продолжить заказ", f"c:view:{current.id}", "primary")])
        else:
            text += (
                "\n\nАктивных заказов сейчас нет.\nПереписка и детали — в истории заказов."
                if has_history else "\n\nПока нет заказов.\nВыберите сервис — здесь появятся статус и переписка."
            )
            rows.append([ui.action("Выбрать услугу", "c:catalog", "primary")])
        if has_history:
            rows.append([ui.action("История заказов", "c:orders:0")])
        rows.append([ui.action("Помощь", "c:help"), ui.action("Главная", "c:home")])
        return text, ui.Keyboard(rows)
    name = escape(profile.display_name)
    since = datetime.fromtimestamp(profile.first_seen_at, ZoneInfo(timezone)).strftime("%d.%m.%Y")
    text = f"<b>{'👤 Карточка клиента' if admin else '📦 Мои заказы'}</b>\n{name}"
    if profile.username:
        text += f" · @{escape(profile.username)}"
    if current:
        text += (
            f"\n\n<b>📌 Текущий заказ</b>\n{catalog.service_title(current.service_code, current.plan_code)}"
            f" · {catalog.dollars(current.price_usd)}\n№{current.id:04d} · {ticket_status(current)}"
        )
    else:
        text += "\n\nАктивных заказов пока нет."
    if profile.total_tickets or admin:
        text += f"\n\nВсего заказов · <b>{profile.total_tickets}</b>\nЗавершено · <b>{profile.resolved_tickets}</b>"
    if admin:
        text += f"\nС нами с {since} · ID <code>{profile.id}</code>"
    rows = []
    prefix = "a" if admin else "c"
    if current:
        rows.append([ui.action("📦 Открыть заказ", f"{prefix}:view:{current.id}", "primary")])
    elif not admin:
        rows.append([ui.action("🛍 Оформить заказ", "c:catalog")])
    history_button = (
        [ui.action("История", f"{prefix}:orders:{profile.id}:0" if admin else "c:orders:0")]
        if has_history else []
    )
    if admin:
        note = escape(profile.operator_note) if profile.operator_note else "Пока нет."
        text += f"\n\n<b>📝 Личная заметка · только вам</b>\n{note}"
        rows += [
            history_button + [ui.action("📝 Заметка", f"a:note:{profile.id}")],
            [ui.action("← К клиентам", "a:clients:0"), ui.action("🏠 Кабинет", "a:home")],
        ]
    else:
        if history_button:
            rows.append(history_button)
        rows.append([ui.action("🏠 Меню", "c:home"), ui.action("🔒 Мои данные", "c:privacy")])
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
