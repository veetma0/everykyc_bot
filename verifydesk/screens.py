"""Small native screens for the catalog, personal cards and mock checkout."""

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from . import catalog, ui
from .store import OPEN_STATUSES, STATUS_NAMES


def catalog_card():
    return (
        "<b>💬 Помощь с Claude</b>\n\n"
        "Инструкции и помощь с ошибками проверки своего аккаунта.\n\n"
        "Выберите Claude, чтобы увидеть условия.",
        ui.Keyboard(
            [
                [ui.action("Claude", "c:service:claude")],
                [ui.action("Меню", "c:home")],
            ]
        ),
    )


def service_card(service):
    if service != "claude":
        raise ValueError("Unknown service")
    return (
        "<b>Claude · помощь с KYC</b>\n\n"
        "Выберите вашу страну проживания.\n"
        "Цена — за сопровождение, подписка Claude отдельно.",
        ui.Keyboard([
            [ui.action("Армения · $35", "c:offer:claude:armenia")],
            [ui.action("Европа · $50", "c:offer:claude:europe")],
            [ui.action("Назад", "c:home")],
        ]),
    )


def offer_card(offer):
    text = f"<b>{escape(offer.title)}{' · ДЕМО' if offer.demo else ''}</b>\n\n{escape(offer.detail)}\n\n"
    if offer.demo:
        text += "Доступность и стоимость пока не подтверждены. Уточним у оператора."
        label = "Спросить о доступности"
    else:
        text += f"<b>Сопровождение:</b> {catalog.dollars(offer.price_usd)} · подписка отдельно.\n"
        if offer.price_usd is None:
            text += "Оператор сообщит цену до начала работы.\n"
        text += "\nПроверку вы проходите сами на свои данные. Документы — только в официальном сервисе."
        label = (
            f"Создать заявку · {catalog.dollars(offer.price_usd)}" if offer.price_usd else "Уточнить условия"
        )
    text += "\n\nБез списаний. Создавая заявку, вы подтверждаете, что аккаунт ваш."
    return text, ui.Keyboard(
        [
            [ui.action(label, f"c:order:{offer.service}:{offer.plan}", "primary")],
            [ui.action("Как это проходит", f"c:guide:{offer.service}:{offer.plan}")],
            [ui.action("Выбор региона", "c:service:claude")]
            if offer.service == "claude"
            else [ui.action("К услугам", "c:catalog")],
        ]
    )


def guide(service="general"):
    if service == "claude":
        return ui.INSTRUCTIONS
    if service != "general":
        raise ValueError("Service unavailable")
    return (
        "<b>💬 Как мы помогаем с Claude</b>\n\n"
        "1. Выберите условия и создайте заявку.\n"
        "2. Напишите вопрос прямо в чат.\n"
        "3. Получите ответ оператора здесь.\n\n"
        "Проверку вы проходите сами на свои данные в Claude. "
        "Документы, селфи и ссылку проверки сюда не отправляйте."
    )


def unavailable_service():
    return (
        "<b>Сейчас доступна только помощь с Claude</b>\n\n"
        "Эта услуга отключена. История прежних заявок сохранена в вашей карточке.",
        ui.Keyboard([
            [ui.action("Claude", "c:service:claude")],
            [ui.action("Моя карточка", "c:profile"), ui.action("Меню", "c:home")],
        ]),
    )


def profile_card(profile, current, timezone, admin=False):
    name = escape(profile.display_name)
    since = datetime.fromtimestamp(profile.first_seen_at, ZoneInfo(timezone)).strftime("%d.%m.%Y")
    text = f"<b>{'Карточка клиента' if admin else 'Моя карточка'}</b>\n{name}"
    if profile.username:
        text += f" · @{escape(profile.username)}"
    if current:
        text += (
            f"\n\n<b>Сейчас</b>\n{catalog.service_title(current.service_code, current.plan_code)}"
            f" · {catalog.dollars(current.price_usd)}\n№{current.id:04d} · {STATUS_NAMES[current.status]}"
        )
    else:
        text += "\n\nАктивных заявок пока нет."
    if profile.total_tickets or admin:
        text += f"\n\nВсего заявок · <b>{profile.total_tickets}</b>\nЗавершено · <b>{profile.resolved_tickets}</b>"
    if admin:
        text += f"\nС нами с {since} · ID <code>{profile.id}</code>"
    rows = []
    prefix = "a" if admin else "c"
    if current:
        rows.append([ui.action("Открыть заявку", f"{prefix}:view:{current.id}", "primary")])
    elif not admin:
        rows.append([ui.action("Выбрать услугу", "c:catalog")])
    history_button = (
        [ui.action("История заявок", f"{prefix}:orders:{profile.id}:0" if admin else "c:orders:0")]
        if profile.total_tickets else []
    )
    if admin:
        note = escape(profile.operator_note) if profile.operator_note else "Пока нет."
        text += f"\n\n<b>Личная заметка · только вам</b>\n{note}"
        rows += [
            history_button + [ui.action("Заметка", f"a:note:{profile.id}")],
            [ui.action("К клиентам", "a:clients:0"), ui.action("Кабинет", "a:home")],
        ]
    else:
        rows += [
            history_button + [ui.action("Помощь", "c:help")],
            [ui.action("Меню", "c:home"), ui.action("Мои данные", "c:privacy")],
        ]
    return text, ui.Keyboard(rows)


def payment_card(ticket):
    selected = catalog.NETWORK_BY_CODE.get(ticket.demo_network)
    text = (
        f"<b>USDT · ДЕМО</b>\nЗаявка №{ticket.id:04d}\n\n"
        "Выберите сеть, чтобы проверить сценарий оплаты.\nДеньги не переводятся, реквизитов нет.\n\n"
        f"<b>Стоимость сопровождения:</b> {catalog.dollars(ticket.price_usd)}"
    )
    if selected:
        text += (
            f"\n\nВыбран пример: <b>{escape(selected.title)}</b> · {catalog.NETWORK_GROUPS[selected.group]}"
        )
    if ticket.status not in OPEN_STATUSES:
        text += (
            "\n\nЗаявка закрыта. Сохранён только прошлый выбор."
        )
        return text, ui.Keyboard([[ui.action("К заявке", f"c:view:{ticket.id}")]])
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
        [ui.action("К заявке", f"c:view:{ticket.id}")],
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
                [ui.action("К заявке", f"c:view:{ticket.id}", "primary")],
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
