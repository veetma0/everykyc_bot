"""Small native screens for the catalog, personal cards and mock checkout."""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import catalog, ui
from .store import OPEN_STATUSES, ticket_status


def catalog_card():
    return (
        "<b>✨ Каталог услуг</b>\n\n"
        "Помогаем с верификацией вашего аккаунта. Выберите раздел, чтобы посмотреть услуги и цены.\n\n"
        "📍 Гео уточняйте у оператора.\n💬 По оптовым заказам — отдельная переписка с оператором.",
        ui.Keyboard(
            [[ui.action(title, f"c:category:{code}")] for code, title in catalog.CATEGORIES.items()]
            + [[ui.action("🤝 Обсудить опт", "c:wholesale")],
               [ui.action("📦 Мои заказы", "c:profile"), ui.action("🏠 Меню", "c:home")]]
        ),
    )


def category_card(category):
    title = catalog.CATEGORIES[category]
    offers = [o for o in catalog.OFFERS.values() if o.category == category]
    lines = [f"<b>{title}</b>", ""]
    rows = []
    for selected in offers:
        unavailable = " · недоступно" if not selected.available else ""
        lines.append(f"<b>{escape(selected.title)}</b> — {catalog.offer_price(selected)}{unavailable}")
        rows.append([ui.action(
            f"{selected.title} · {catalog.offer_price(selected)}{unavailable}",
            f"c:service:{selected.service}",
        )])
    lines += ["", "📍 Гео уточняйте у оператора.", "💬 Условия и доступность согласуем до оплаты."]
    rows.append([ui.action("← Все разделы", "c:catalog")])
    return "\n".join(lines), ui.Keyboard(rows)


def service_card(service):
    return offer_card(catalog.offer(service, "standard"))


def offer_card(offer):
    text = (
        f"<b>{catalog.CATEGORIES[offer.category].split()[0]} {escape(offer.title)}</b>\n\n"
        f"{escape(offer.detail)}\n\n"
        f"💵 <b>Стоимость:</b> {catalog.offer_price(offer)}\n"
        "📍 Гео уточняйте у оператора.\n\n"
    )
    rows = []
    if not offer.available:
        text += "⛔ Сервис прекратил работу. Новые заказы на верификацию не принимаются."
    else:
        if offer.price_from:
            text += "Итоговую стоимость согласуйте с оператором до оплаты.\n\n"
        if offer.service == "claude":
            text += "<b>Подписка не входит в стоимость.</b> Подписку Claude вы оплачиваете самостоятельно.\n\n"
        text += (
            "💬 Оператор примет сделку и отправит вам реквизиты.\n\n"
            "🔒 Проверку вы проходите сами на свои данные. Документы — только в официальном сервисе.\n\n"
            "Создание заказа — без списаний. Оформляя заказ, вы подтверждаете, что аккаунт ваш."
        )
        rows.append([ui.action(
            f"🛍 Оформить заказ · {catalog.offer_price(offer)}", f"c:order:{offer.service}:{offer.plan}",
        )])
    rows.append([ui.action("← К разделу", f"c:category:{offer.category}")])
    return text, ui.Keyboard(rows)


def guide(service="general"):
    if service != "general" and (service, "standard") not in catalog.OFFERS:
        raise ValueError("Service unavailable")
    title = "Как оформить заказ" if service == "general" else catalog.service_title(service, "standard")
    return (
        f"<b>📋 {escape(title)} · инструкция</b>\n\n"
        "1️⃣ Выберите услугу и оформите заказ. Гео уточняйте у оператора.\n"
        "2️⃣ Оператор примет сделку и отправит вам реквизиты.\n"
        "3️⃣ После оплаты просто пришлите чек в этот чат — фото, файл или ссылку.\n"
        "4️⃣ Оператор получит сообщение и проверит оплату. Бот сообщит: «Оплата подтверждена. Ожидайте сообщения от оператора».\n\n"
        "🔒 Проверку проходите самостоятельно на свои данные в официальном сервисе. "
        "Ссылку KYC, документы, селфи, пароли и коды входа сюда не отправляйте."
        + ("\n\n💡 Подписка Claude оплачивается отдельно." if service == "claude" else "")
    )


def unavailable_service():
    return (
        "<b>⛔ Услуга недоступна</b>\n\nВыберите другое направление в каталоге. История прежних заказов сохранена.",
        ui.Keyboard([[ui.action("✨ Каталог услуг", "c:catalog")], [ui.action("📦 Мои заказы", "c:profile")]]),
    )


def profile_card(profile, current, timezone, admin=False):
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
        [ui.action("🗂 История заказов", f"{prefix}:orders:{profile.id}:0" if admin else "c:orders:0")]
        if profile.total_tickets else []
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
