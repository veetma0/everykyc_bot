import logging
import time
from html import escape

from telegram import BotCommand, BotCommandScopeChat, ForceReply, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from .config import Config
from .store import OPEN_STATUSES, STATUS_NAMES, StaleTicket, Store
from . import acquisition, catalog, screens, theme, ui


log = logging.getLogger(__name__)
MAX_TEXT = 2400


def operator_commands():
    return [
        BotCommand("admin", "Кабинет оператора"),
        BotCommand("next", "Следующая заявка для ответа"),
        BotCommand("start", "Текущее меню"),
        BotCommand("client", "Перейти в режим клиента"),
        BotCommand("clients", "Карточки клиентов"),
        BotCommand("preview", "Посмотреть глазами клиента"),
        BotCommand("style", "Проверить премиум-эмодзи"),
        BotCommand("id", "Мой Telegram ID"),
    ]


def customer_commands(operator=False):
    commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("status", "Моя заявка"),
        BotCommand("services", "Услуги"),
        BotCommand("profile", "Моя карточка"),
        BotCommand("help", "Помощь"),
        BotCommand("privacy", "Мои данные"),
    ]
    if operator:
        commands.append(BotCommand("admin", "Вернуться в админку"))
    return commands


async def deliver(bot, chat_id, text, reply_markup=None):
    """Never retry an ambiguous network send: it may already have reached Telegram."""
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            protect_content=True,
            disable_web_page_preview=True,
        )
        return message, "delivered"
    except BadRequest:
        if theme.enabled():
            theme.disable()
            text, reply_markup = theme.without_custom_emoji(text, reply_markup)
            return await deliver(bot, chat_id, text, reply_markup)
        return None, "failed"
    except NetworkError as exc:
        log.warning("Доставка не подтверждена: %s", type(exc).__name__)
        return None, "uncertain"
    except TelegramError as exc:
        log.warning("Сообщение не отправлено: %s", type(exc).__name__)
        return None, "failed"


class Desk:
    def __init__(self, config: Config, store: Store):
        self.config = config
        self.store = store
        self.notification_digest_at = {}

    def is_admin(self, user_id: int):
        return user_id in self.config.admin_ids

    def client_mode(self, user_id: int):
        return self.is_admin(user_id) and self.store.operator_mode(user_id) == "client"

    async def switch_mode(self, update, context, mode):
        uid = update.effective_user.id
        if not self.is_admin(uid):
            return
        self.store.release_claim(uid)
        self.store.set_operator_mode(uid, mode)
        try:
            commands = customer_commands(True) if mode == "client" else operator_commands()
            await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(uid))
        except TelegramError:
            pass
        card = (
            ui.home(self.config.title, self.store.for_user(uid))
            if mode == "client"
            else ui.admin_home(self.store.counts(), self.store.queue_count(uid))
        )
        await self.screen(update, context, *card, customer=mode == "client")

    def customer_keyboard(self, uid, keyboard):
        if not self.is_admin(uid) or not isinstance(keyboard, ui.Keyboard):
            return keyboard
        rows = list(keyboard.inline_keyboard)
        if not any(button.callback_data == "a:mode:admin" for row in rows for button in row):
            switches = []
            if not self.client_mode(uid):
                switches.append(ui.action("Режим клиента", "a:mode:client"))
            switches.append(ui.action("В админку", "a:mode:admin"))
            rows.append(switches)
        return ui.Keyboard(rows)

    def recovery_keyboard(self, admin=False):
        return ui.Keyboard(
            [[ui.action("Кабинет оператора", "a:home")]]
            if admin
            else [
                [ui.action("Моя заявка / услуги", "c:current", "primary")],
                [ui.action("Главное меню", "c:home")],
            ]
        )

    def preview_keyboard(self, keyboard):
        converted = screens.preview_markup(keyboard)
        rows = list(converted.inline_keyboard) if isinstance(converted, ui.Keyboard) else []
        if not any(button.callback_data == "a:home" for row in rows for button in row):
            rows.append([ui.action("Кабинет оператора", "a:home")])
        return ui.Keyboard(rows)

    def remember(self, update: Update):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat or chat.type != ChatType.PRIVATE:
            return False
        self.store.remember_user(user.id, chat.id, user.full_name, user.username)
        return True

    def map_customer_card(self, update, message, keyboard):
        if not message or not isinstance(keyboard, ui.Keyboard):
            return
        query = update.callback_query
        if query and not str(query.data).startswith("c:"):
            return
        targets = {
            button.callback_data.split(":")[2]
            for row in keyboard.inline_keyboard
            for button in row
            if isinstance(button.callback_data, str)
            and button.callback_data.startswith(("c:write:", "c:details:"))
        }
        if len(targets) != 1:
            return
        target = targets.pop()
        if not target.isdigit():
            return
        ticket = self.authorized_ticket(int(target), update.effective_user.id)
        if ticket and ticket.status in OPEN_STATUSES:
            self.store.map_customer_reply(update.effective_chat.id, message.message_id, ticket.id)

    async def screen(self, update, context, text, keyboard=None, *, customer=None):
        query = update.callback_query
        preview = query and isinstance(query.data, str) and query.data.startswith("p:")
        if preview:
            text = "<b>ПРЕДПРОСМОТР · без создания заявки</b>\n\n" + text
            keyboard = self.preview_keyboard(keyboard)
        elif self.is_admin(update.effective_user.id):
            if customer is None:
                if query:
                    customer = str(query.data).startswith("c:")
                else:
                    words = (update.effective_message.text or "").split()
                    command = words[0].split("@")[0].lower() if words else ""
                    customer = command in {"/profile", "/services", "/help", "/privacy", "/status"} or (
                        command == "/start" and self.client_mode(update.effective_user.id)
                    )
            if customer:
                text = (
                    "<i>Режим клиента</i>\n\n"
                    if self.client_mode(update.effective_user.id)
                    else "<i>Режим админа · просмотр клиента</i>\n\n"
                ) + text
                keyboard = self.customer_keyboard(update.effective_user.id, keyboard)
        if query and query.message:
            # A card edited into a menu must stop being a reply target for its previous ticket.
            self.store.unmap_reply(update.effective_chat.id, query.message.message_id)
            try:
                await query.edit_message_text(
                    text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True
                )
                self.map_customer_card(update, query.message, keyboard)
                return query.message
            except BadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    self.map_customer_card(update, query.message, keyboard)
                    return query.message
            except NetworkError:
                return None
            except TelegramError:
                pass
        message, _ = await deliver(context.bot, update.effective_chat.id, text, keyboard)
        self.map_customer_card(update, message, keyboard)
        return message

    async def command(self, update, context):
        if not self.remember(update):
            return
        command = update.effective_message.text.split()[0].split("@")[0].lower()
        uid = update.effective_user.id
        if command == "/start" and not self.is_admin(uid):
            source = acquisition.start_source(update.effective_message.text)
            if source:
                self.store.remember_source(uid, source)
        if command == "/id":
            await self.screen(update, context, f"Ваш Telegram ID: <code>{uid}</code>")
        elif command in {"/admin", "/client"}:
            if not self.is_admin(uid):
                await self.screen(update, context, "Эта команда доступна только оператору.")
                return
            await self.switch_mode(update, context, "admin" if command == "/admin" else "client")
        elif command in {"/clients", "/preview", "/style", "/sources", "/next"}:
            if not self.is_admin(uid):
                await self.screen(update, context, "Эта команда доступна только оператору.")
                return
            if self.client_mode(uid) and command != "/preview":
                await self.screen(
                    update,
                    context,
                    "Сейчас вы в режиме клиента. Для работы с клиентами вернитесь в админку.",
                    ui.Keyboard([[ui.action("В админку", "a:mode:admin")]]),
                )
                return
            if command == "/next":
                await self.next_ticket(update, context)
            elif command == "/clients":
                await self.clients_screen(update, context, 0)
            elif command == "/sources":
                await self.screen(
                    update,
                    context,
                    acquisition.report(self.store.source_summary(self.config.admin_ids)),
                    ui.Keyboard([[ui.action("В админку", "a:home")]]),
                )
            elif command == "/preview":
                text, keyboard = ui.home(self.config.title, None)
                await self.screen(
                    update, context, "<b>ПРЕДПРОСМОТР</b>\n\n" + text, self.preview_keyboard(keyboard)
                )
            else:
                await self.style_preview(update, context)
        elif command == "/profile":
            await self.profile_screen(update, context, uid)
        elif command == "/services":
            await self.screen(update, context, *screens.catalog_card())
        elif command == "/help":
            await self.help(update, context)
        elif command == "/privacy":
            await self.screen(
                update, context, ui.PRIVACY, ui.Keyboard([[ui.action("Главное меню", "c:home")]])
            )
        elif command == "/status":
            ticket = self.store.for_user(uid)
            if ticket:
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            else:
                await self.screen(
                    update,
                    context,
                    "У вас пока нет заявок.",
                    ui.Keyboard([[ui.action("Выбрать услугу", "c:catalog", "primary")]]),
                )
        elif command == "/start" and self.is_admin(uid):
            try:
                commands = customer_commands(True) if self.client_mode(uid) else operator_commands()
                await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(uid))
            except TelegramError:
                pass
            card = (
                ui.home(self.config.title, self.store.for_user(uid))
                if self.client_mode(uid)
                else ui.admin_home(self.store.counts(), self.store.queue_count(uid))
            )
            await self.screen(update, context, *card)
        else:
            await self.screen(update, context, *ui.home(self.config.title, self.store.for_user(uid)))

    async def help(self, update, context):
        await self.screen(
            update,
            context,
            screens.guide(),
            ui.Keyboard(
                [
                    [
                        ui.action("Claude · инструкция", "c:guide:claude"),
                    ],
                    [ui.action("Выбрать услугу", "c:catalog", "primary")],
                    [ui.action("Главное меню", "c:home")],
                ]
            ),
        )

    async def notify_admins(self, bot, ticket, body=None):
        text, keyboard = ui.admin_ticket(ticket, body)
        delivered = False
        counts = self.store.counts()
        busy_queue = counts["new"] + counts["in_progress"] >= 20 and ticket.status in OPEN_STATUSES
        for admin_id in self.config.admin_ids:
            if admin_id == ticket.user_id and self.client_mode(admin_id):
                continue
            if busy_queue:
                now = time.monotonic()
                previous = self.notification_digest_at.get(admin_id)
                if previous is not None and now - previous < 15:
                    continue
                self.notification_digest_at[admin_id] = now
                await deliver(
                    bot, admin_id,
                    "<b>📥 Новые обращения в очереди</b>\n\n"
                    "Сообщения сохранены. Нажмите «Следующая заявка», чтобы ответить.\n"
                    "При большом потоке уведомления объединяются.",
                    ui.Keyboard([
                        [ui.action("Следующая заявка", "a:next")],
                        [ui.action("Очередь", "a:list:queue:0")],
                    ]),
                )
                # A digest does not deliver the individual message or identify a reply recipient.
                continue
            message, _ = await deliver(bot, admin_id, text, keyboard)
            if message:
                self.store.map_reply(admin_id, message.message_id, ticket.id)
                delivered = True
        return delivered

    def authorized_ticket(self, ticket_id, uid, admin=False):
        ticket = self.store.ticket(ticket_id)
        if not ticket:
            return None
        if admin:
            return ticket if self.is_admin(uid) else None
        return ticket if ticket.user_id == uid else None

    async def claim_conflict(self, update, context, ticket):
        await self.screen(
            update, context,
            f"<b>№{ticket.id:04d} уже отвечает другой оператор</b>\n\n"
            "Ваше сообщение не отправлено. Возьмите следующее обращение.",
            ui.Keyboard([[ui.action("Следующая заявка", "a:next")], [ui.action("Очередь", "a:list:queue:0")]]),
        )

    async def open_reply(self, update, context, ticket, *, show_card=False):
        uid = update.effective_user.id
        if ticket.status not in OPEN_STATUSES:
            raise StaleTicket()
        if not self.store.claim_ticket(ticket.id, uid):
            await self.claim_conflict(update, context, ticket)
            return
        rows = self.store.db.execute(
            "SELECT role,body FROM messages WHERE ticket_id=? AND role IN ('user','operator') "
            "ORDER BY id DESC LIMIT 3", (ticket.id,),
        ).fetchall()
        if show_card:
            shown = await self.screen(update, context, *ui.admin_ticket(ticket))
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
        details = []
        for row in reversed(rows):
            label = "Клиент" if row["role"] == "user" else "Оператор"
            body = ui.clip_text(row["body"], 500)
            if ui.text_units(row["body"]) > 500:
                body += "…"
            details.append(f"<b>{label}:</b> {escape(body)}")
        context_text = "\n\n".join(details) if details else "Клиент создал заявку и ждёт ответа."
        prompt, _ = await deliver(
            context.bot, uid,
            f"<b>Ответ · №{ticket.id:04d} · {escape(ticket.display_name)}</b>\n\n"
            f"{context_text}\n\n"
            "Напишите ответ ниже — он уйдёт этому клиенту.\n/admin — выйти из ответа.",
            ForceReply(input_field_placeholder=f"Ответ клиенту · №{ticket.id:04d}"),
        )
        if prompt:
            self.store.map_reply(uid, prompt.message_id, ticket.id)
        else:
            self.store.release_claim(uid, ticket.id)

    async def next_ticket(self, update, context, skip_ticket_id=None):
        uid = update.effective_user.id
        ticket = self.store.claim_next(uid, skip_ticket_id)
        if ticket:
            await self.open_reply(update, context, ticket, show_card=True)
            return
        counts = self.store.counts()
        waiting = counts["new"] + counts["in_progress"]
        text = (
            "Других свободных заявок сейчас нет. Можно вернуться в очередь."
            if skip_ticket_id is not None else
            "Сейчас свободных заявок нет. Остальные обращения уже взяли операторы."
            if waiting else
            "✅ Очередь пуста. Новых обращений, ожидающих ответа, пока нет."
        )
        await self.screen(
            update, context, text,
            ui.Keyboard([[ui.action("Проверить очередь", "a:list:queue:0")], [ui.action("В админку", "a:home")]]),
        )

    async def callback(self, update, context):
        if not self.remember(update):
            return
        query = update.callback_query
        try:
            await query.answer()
        except TelegramError:
            pass
        data = query.data
        if not isinstance(data, str) or len(data.encode()) > 64:
            return
        uid = update.effective_user.id
        parts = data.split(":")
        if parts[0] in {"a", "p"} and not self.is_admin(uid):
            await self.screen(update, context, "Доступ к кабинету оператора закрыт.")
            return
        try:
            if parts[0] == "c":
                await self.customer_callback(update, context, uid, parts)
            elif parts[0] == "p":
                await self.customer_callback(update, context, uid, parts, preview=True)
            elif parts[0] == "a":
                await self.admin_callback(update, context, uid, parts)
        except (ValueError, IndexError, KeyError, StaleTicket):
            await self.screen(
                update,
                context,
                "Данные обновились. Откройте актуальную карточку или меню.",
                self.recovery_keyboard(parts[0] == "a"),
            )

    async def customer_callback(self, update, context, uid, parts, preview=False):
        verb = parts[1]
        if verb in {"service", "offer", "order", "guide"} and parts[2] in catalog.RETIRED_SERVICES:
            await self.screen(update, context, *screens.unavailable_service())
            return
        if preview and verb in {"create", "order", "close", "network", "write"}:
            await self.screen(
                update,
                context,
                "В предпросмотре заявки и сообщения не отправляются, выбор не сохраняется.",
                ui.Keyboard([[ui.action("К услугам", "c:catalog")]]),
            )
            return
        if verb == "home":
            await self.screen(
                update,
                context,
                *ui.home(self.config.title, None if preview else self.store.for_user(uid)),
            )
        elif verb == "catalog":
            await self.screen(update, context, *screens.catalog_card())
        elif verb == "service":
            await self.screen(update, context, *screens.service_card(parts[2]))
        elif verb == "offer":
            await self.screen(update, context, *screens.offer_card(catalog.offer(parts[2], parts[3])))
        elif verb == "order":
            selected = catalog.offer(parts[2], parts[3])
            ticket, created = self.store.create_ticket(
                uid, selected.service, selected.plan, None if selected.demo else selected.price_usd
            )
            if not created and (ticket.service_code, ticket.plan_code) != (selected.service, selected.plan):
                await self.screen(
                    update,
                    context,
                    f"<b>У вас уже есть активная заявка №{ticket.id:04d}</b>\n\n"
                    f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n\n"
                    f"Вы выбрали {escape(selected.title)}. Напишите новый запрос в текущую заявку — оператор поможет уточнить направление. Условия текущей заявки сохранены.",
                    ui.Keyboard(
                        [
                            [ui.action("Открыть текущую заявку", f"c:view:{ticket.id}", "primary")],
                            [ui.action("К услугам", "c:catalog")],
                        ]
                    ),
                )
                return
            await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            if created:
                await self.notify_admins(context.bot, ticket)
        elif verb == "profile":
            await self.profile_screen(update, context, uid)
        elif verb == "orders":
            await self.orders_screen(update, context, uid, int(parts[2]), False)
        elif verb == "guide":
            service = parts[2]
            if service != "claude":
                raise ValueError()
            rows = []
            if service == "claude":
                rows.append([ui.Button("Официальная инструкция Claude ↗", url=ui.HELP_URL)])
            if len(parts) > 3:
                selected = catalog.offer(service, parts[3])
                rows.append(
                    [
                        ui.action(
                            "Вернуться к услуге", f"c:offer:{selected.service}:{selected.plan}", "primary"
                        )
                    ]
                )
            else:
                target = (
                    "c:service:claude"
                    if service == "claude" and not self.store.for_user(uid, active_only=True)
                    else "c:current"
                )
                rows.append([ui.action("Вернуться", target)])
            rows += [
                [ui.action("Главное меню", "c:home")],
            ]
            await self.screen(update, context, screens.guide(service), ui.Keyboard(rows))
        elif verb in {"pay", "networks", "network"}:
            ticket = self.authorized_ticket(int(parts[2]), uid)
            if not ticket:
                await self.screen(update, context, "Эта заявка недоступна.", self.recovery_keyboard())
                return
            if ticket.status not in OPEN_STATUSES:
                await self.screen(update, context, *screens.payment_card(ticket))
                return
            if verb == "pay":
                await self.screen(update, context, *screens.payment_card(ticket))
            elif verb == "networks":
                if parts[3] not in catalog.NETWORK_GROUPS:
                    raise ValueError()
                await self.screen(update, context, *screens.network_page(ticket, parts[3], int(parts[4])))
            else:
                network = catalog.NETWORK_BY_CODE[parts[3]]
                ticket = self.store.set_demo_network(ticket.id, network.code)
                await self.screen(update, context, *screens.network_selected(ticket, network))
        elif verb == "prepare":
            current = self.store.for_user(uid, active_only=True)
            await self.screen(
                update,
                context,
                *(ui.customer_ticket(current, self.config.timezone) if current else screens.catalog_card()),
            )
        elif verb == "help":
            await self.help(update, context)
        elif verb == "privacy":
            await self.screen(
                update, context, ui.PRIVACY, ui.Keyboard([[ui.action("Главное меню", "c:home")]])
            )
        elif verb == "current":
            current = self.store.for_user(uid, active_only=True)
            await self.screen(
                update,
                context,
                *(ui.customer_ticket(current, self.config.timezone) if current else screens.catalog_card()),
            )
        elif verb == "create":
            await self.screen(update, context, *screens.catalog_card())
        elif verb in {"view", "details", "history", "cancel", "close", "message", "write"}:
            ticket = self.authorized_ticket(int(parts[2]), uid)
            if not ticket:
                await self.screen(update, context, "Эта заявка недоступна.", self.recovery_keyboard())
                return
            if verb == "write":
                if ticket.status not in OPEN_STATUSES:
                    await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
                    return
                prompt, _ = await deliver(
                    context.bot,
                    uid,
                    f"<b>Сообщение оператору · №{ticket.id:04d}</b>\n\nНапишите вопрос в ответ на это сообщение. Оператор ответит здесь.",
                    ForceReply(input_field_placeholder="Напишите ваш вопрос"),
                )
                if prompt:
                    self.store.map_customer_reply(uid, prompt.message_id, ticket.id)
            elif verb == "details":
                await self.screen(update, context, *ui.customer_details(ticket, self.config.timezone))
            elif verb == "history":
                await self.show_history(update, context, ticket, int(parts[3]), False)
            elif verb == "message":
                await self.full_message(update, context, ticket, int(parts[3]), False)
            elif verb == "cancel":
                if ticket.status not in OPEN_STATUSES or int(parts[3]) != ticket.version:
                    raise StaleTicket()
                await self.screen(
                    update,
                    context,
                    f"<b>Закрыть заявку №{ticket.id:04d}?</b>\n\nПереписка останется в истории. При необходимости можно создать новую заявку.",
                    ui.Keyboard(
                        [
                            [ui.action("Да, закрыть", f"c:close:{ticket.id}:{ticket.version}", "danger")],
                            [ui.action("Продолжить общение", f"c:view:{ticket.id}")],
                        ]
                    ),
                )
            elif verb == "close":
                ticket = self.store.set_status(ticket.id, int(parts[3]), "cancelled", uid)
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
                await self.notify_admins(context.bot, ticket)
            else:
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
        else:
            raise ValueError("Unknown customer action")

    async def admin_callback(self, update, context, uid, parts):
        verb = parts[1]
        if verb == "mode":
            mode = parts[2]
            if mode not in {"admin", "client"}:
                raise ValueError("Unknown mode")
            await self.switch_mode(update, context, mode)
            return
        if verb == "home":
            await self.switch_mode(update, context, "admin")
            return
        if verb == "preview":
            text, keyboard = ui.home(self.config.title, None)
            await self.screen(
                update, context, "<b>ПРЕДПРОСМОТР</b>\n\n" + text, self.preview_keyboard(keyboard)
            )
            return
        if self.client_mode(uid):
            await self.screen(
                update,
                context,
                "Сейчас вы в режиме клиента. Для работы с заявками вернитесь в админку.",
                ui.Keyboard([[ui.action("В админку", "a:mode:admin")]]),
            )
            return
        if verb == "next":
            skip = int(parts[2]) if len(parts) > 2 else None
            await self.next_ticket(update, context, skip)
            return
        if verb == "style":
            await self.style_preview(update, context)
            return
        if verb == "clients":
            await self.clients_screen(update, context, int(parts[2]))
            return
        if verb == "client":
            await self.profile_screen(update, context, int(parts[2]), admin=True)
            return
        if verb == "orders":
            await self.orders_screen(update, context, int(parts[2]), int(parts[3]), True)
            return
        if verb == "note":
            profile = self.store.profile(int(parts[2]))
            if not profile:
                raise ValueError()
            prompt, _ = await deliver(
                context.bot,
                uid,
                f"<b>Приватная заметка · {escape(profile.display_name)}</b>\nID клиента: {profile.id}\n\n"
                "Ответьте на это сообщение. Заметку увидит только оператор; клиенту она не отправляется. До 1200 символов. Для очистки пришлите минус: −",
                ForceReply(input_field_placeholder="Заметка только для оператора"),
            )
            if prompt:
                self.store.map_note_reply(uid, prompt.message_id, profile.id)
            return
        if verb == "list":
            scope, offset = parts[2], max(0, int(parts[3]))
            page = (
                lambda position: self.store.queue_page(uid, position)
            ) if scope == "queue" else lambda position: self.store.page(scope, position)
            tickets, total = page(offset)
            if offset >= total and offset > 0:
                offset = max(0, ((total - 1) // 8) * 8)
                tickets, total = page(offset)
            rows = [
                [
                    ui.action(
                        f"{'● ' if t.unread else ''}№{t.id:04d} · {t.display_name[:24]} · {ui.admin_status(t.status)}",
                        f"a:{'reply' if scope == 'queue' else 'view'}:{t.id}",
                    )
                ]
                for t in tickets
            ]
            navigation = []
            if offset > 0:
                navigation.append(ui.action("← Назад", f"a:list:{scope}:{max(0, offset - 8)}"))
            if offset + 8 < total:
                navigation.append(ui.action("Далее →", f"a:list:{scope}:{offset + 8}"))
            if navigation:
                rows.append(navigation)
            if scope == "active":
                rows.append([ui.action("Завершённые", "a:list:closed:0")])
            rows.append([ui.action("Кабинет оператора", "a:home")])
            title = {"queue": "Ожидающие ответа", "active": "Активные", "new": "Новые", "closed": "Завершённые"}[scope]
            text = f"<b>{title} заявки · {total}</b>\n\n" + (
                "Выберите заявку. ● — есть новые сообщения." if tickets else "Здесь пока пусто."
            )
            await self.screen(update, context, text, ui.Keyboard(rows))
            return
        ticket = self.authorized_ticket(int(parts[2]), uid, admin=True)
        if not ticket:
            await self.screen(update, context, "Заявка не найдена.", self.recovery_keyboard(True))
            return
        if verb == "view":
            rows, _ = self.store.messages(ticket.id, size=1)
            snippet = rows[-1]["body"] if rows and rows[-1]["role"] == "user" else None
            shown = await self.screen(update, context, *ui.admin_ticket(ticket, snippet))
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
                self.store.mark_read(ticket.id)
        elif verb == "history":
            await self.show_history(update, context, ticket, int(parts[3]), True)
        elif verb == "message":
            await self.full_message(update, context, ticket, int(parts[3]), True)
        elif verb == "reply":
            await self.open_reply(update, context, ticket, show_card=True)
        elif verb == "status":
            await self.screen(update, context, *ui.status_menu(ticket))
        elif verb in {"set", "confirm"}:
            version, status = int(parts[3]), parts[4]
            if ticket.version != version:
                raise StaleTicket()
            owner = self.store.claim_owner(ticket.id)
            if owner is not None and owner != uid:
                await self.claim_conflict(update, context, ticket)
                return
            if verb == "set" and status in {"resolved", "cancelled"}:
                await self.screen(
                    update,
                    context,
                    f"<b>Завершить заявку №{ticket.id:04d}?</b>\n\nСтатус: {STATUS_NAMES[status]}\n"
                    "Это завершает сопровождение, а не подтверждает результат проверки сервиса.",
                    ui.Keyboard(
                        [
                            [
                                ui.action(
                                    "Подтвердить", f"a:confirm:{ticket.id}:{version}:{status}", "success"
                                )
                            ],
                            [ui.action("Назад", f"a:view:{ticket.id}")],
                        ]
                    ),
                )
                return
            ticket = self.store.set_status(ticket.id, version, status, uid)
            customer_text, customer_keys = ui.customer_ticket(ticket, self.config.timezone)
            _, state = await deliver(
                context.bot,
                ticket.chat_id,
                customer_text,
                self.customer_keyboard(ticket.user_id, customer_keys),
            )
            text, keyboard = ui.admin_ticket(ticket)
            if state != "delivered":
                text += "\n\n⚠️ Статус сохранён. Доставка уведомления клиенту не подтверждена."
            shown = await self.screen(update, context, text, keyboard)
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
        else:
            raise ValueError("Unknown operator action")

    async def clients_screen(self, update, context, offset):
        if not self.is_admin(update.effective_user.id):
            return
        offset = max(0, offset)
        profiles, total = self.store.clients_page(offset, exclude_ids=self.config.admin_ids)
        if offset >= total and offset:
            offset = max(0, ((total - 1) // 8) * 8)
            profiles, total = self.store.clients_page(offset, exclude_ids=self.config.admin_ids)
        rows = [
            [
                ui.action(
                    f"{profile.display_name[:30]} · {profile.total_tickets} заявок", f"a:client:{profile.id}"
                )
            ]
            for profile in profiles
        ]
        navigation = []
        if offset:
            navigation.append(ui.action("← Назад", f"a:clients:{max(0, offset - 8)}"))
        if offset + 8 < total:
            navigation.append(ui.action("Далее →", f"a:clients:{offset + 8}"))
        if navigation:
            rows.append(navigation)
        rows.append([ui.action("Кабинет оператора", "a:home")])
        await self.screen(
            update,
            context,
            f"<b>Клиенты · {total}</b>\n\n"
            + (
                "Карточка объединяет обращения, текущую заявку и вашу заметку."
                if profiles
                else "Клиенты появятся здесь, когда откроют бота."
            ),
            ui.Keyboard(rows),
        )

    async def profile_screen(self, update, context, user_id, admin=False):
        if admin:
            if not self.is_admin(update.effective_user.id):
                return
        elif update.effective_user.id != user_id:
            return
        profile = self.store.profile(user_id)
        if not profile:
            await self.screen(update, context, "Карточка пока не найдена.", self.recovery_keyboard(admin))
            return
        current = self.store.for_user(user_id, active_only=True)
        await self.screen(
            update, context, *screens.profile_card(profile, current, self.config.timezone, admin)
        )

    async def orders_screen(self, update, context, user_id, offset, admin):
        if (admin and not self.is_admin(update.effective_user.id)) or (
            not admin and user_id != update.effective_user.id
        ):
            return
        offset = max(0, offset)
        total = self.store.db.execute("SELECT COUNT(*) FROM tickets WHERE user_id=?", (user_id,)).fetchone()[
            0
        ]
        if offset >= total and offset:
            offset = max(0, ((total - 1) // 8) * 8)
        rows = self.store.db.execute(
            "SELECT id FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 8 OFFSET ?", (user_id, offset)
        ).fetchall()
        prefix = "a" if admin else "c"
        buttons = []
        for row in rows:
            ticket = self.store.ticket(row["id"])
            buttons.append(
                [
                    ui.action(
                        f"№{ticket.id:04d} · {catalog.service_title(ticket.service_code, ticket.plan_code)} · {STATUS_NAMES[ticket.status]}",
                        f"{prefix}:view:{ticket.id}",
                    )
                ]
            )
        navigation = []
        base = f"a:orders:{user_id}" if admin else "c:orders"
        if offset:
            navigation.append(ui.action("← Назад", f"{base}:{max(0, offset - 8)}"))
        if offset + 8 < total:
            navigation.append(ui.action("Далее →", f"{base}:{offset + 8}"))
        if navigation:
            buttons.append(navigation)
        buttons.append([ui.action("К карточке", f"a:client:{user_id}" if admin else "c:profile")])
        await self.screen(
            update,
            context,
            f"<b>История заявок · {total}</b>\n\n" + ("Выберите обращение." if rows else "Заявок пока нет."),
            ui.Keyboard(buttons),
        )

    async def style_preview(self, update, context):
        if not self.is_admin(update.effective_user.id):
            return
        _, result = await theme.preview(context.bot, update.effective_user.id, self.config.data_dir)
        await self.screen(
            update,
            context,
            f"<b>Оформление Эврикус</b>\n\n{result}\n\nДля премиум-эмодзи Telegram требует Premium у владельца бота или дополнительный username на Fragment. Основные кнопки работают и без них.",
            ui.Keyboard([[ui.action("Кабинет оператора", "a:home")]]),
        )

    async def show_history(self, update, context, ticket, page, admin):
        page = max(0, page)
        _, total = self.store.messages(ticket.id)
        page = min(page, max(0, (total - 1) // 4))
        rows, total = self.store.messages(ticket.id, page)
        text, keyboard = ui.history(ticket, rows, total, page, admin, self.config.timezone)
        prefix = "a" if admin else "c"
        full_buttons = [
            [
                ui.action(
                    f"Сообщение от {self._stamp(row['created_at'])} целиком",
                    f"{prefix}:message:{ticket.id}:{row['id']}",
                )
            ]
            for row in rows
            if ui.text_units(row["body"]) > 650
        ]
        if full_buttons:
            keyboard = ui.Keyboard(full_buttons + list(keyboard.inline_keyboard))
        shown = await self.screen(update, context, text, keyboard)
        if admin and shown:
            self.store.map_reply(update.effective_chat.id, shown.message_id, ticket.id)
            if page == 0:
                self.store.mark_read(ticket.id)

    def _stamp(self, stamp):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(stamp, ZoneInfo(self.config.timezone)).strftime("%d.%m %H:%M")

    async def full_message(self, update, context, ticket, message_id, admin):
        row = self.store.db.execute(
            "SELECT body,role FROM messages WHERE id=? AND ticket_id=?", (message_id, ticket.id)
        ).fetchone()
        if not row:
            raise ValueError()
        prefix = "a" if admin else "c"
        shown = await self.screen(
            update,
            context,
            f"<b>Заявка №{ticket.id:04d} · сообщение</b>\n\n{escape(row['body'])}",
            ui.Keyboard([[ui.action("К переписке", f"{prefix}:history:{ticket.id}:0")]]),
        )
        if admin and shown:
            self.store.map_reply(update.effective_chat.id, shown.message_id, ticket.id)

    async def message(self, update, context):
        if not update.message or not self.remember(update):
            return
        message = update.message
        uid = update.effective_user.id
        if not message.text:
            await deliver(
                context.bot,
                uid,
                "Опишите вопрос текстом. Документы и селфи загружайте только на официальной странице проверки. Вложения оператору не передаются.",
            )
            return
        if not message.text.strip():
            await deliver(context.bot, uid, "Напишите вопрос текстом — сообщение не должно быть пустым.")
            return
        if ui.text_units(message.text) > MAX_TEXT:
            await deliver(
                context.bot, uid, f"Сообщение слишком длинное. Разделите его на части до {MAX_TEXT} символов."
            )
            return
        if self.store.find_source(message.chat_id, message.message_id):
            return
        reply = message.reply_to_message
        if self.client_mode(uid) and reply:
            operator_target = self.store.reply_ticket(uid, reply.message_id)
            note_target = self.store.note_reply_user(uid, reply.message_id)
            if operator_target is not None or note_target is not None:
                await deliver(
                    context.bot,
                    uid,
                    "Это ответ из админки. Сейчас вы как клиент — сообщение не отправлено.",
                    ui.Keyboard([[ui.action("В админку", "a:mode:admin")]]),
                )
                return
        target = self.store.customer_reply_ticket(uid, reply.message_id) if reply else None
        if target is None and reply and reply.from_user and reply.from_user.id == uid:
            source = self.store.find_source(uid, reply.message_id)
            if source and source["role"] == "user":
                target = self.store.ticket(source["ticket_id"])
        if target and (target.user_id != uid or target.status not in OPEN_STATUSES):
            await deliver(
                context.bot,
                uid,
                "Эта переписка уже закрыта или недоступна. Сообщение не отправлено.",
                self.recovery_keyboard(),
            )
            return
        if self.is_admin(uid) and not self.client_mode(uid) and target is None:
            await self.operator_message(update, context)
            return
        if reply and target is None and reply.from_user and reply.from_user.id == context.bot.id:
            await deliver(
                context.bot,
                uid,
                "Сообщение не отправлено. Откройте свою заявку и напишите в чат без ответа на старое сообщение.",
                self.recovery_keyboard(),
            )
            return
        ticket = target or self.store.for_user(uid, active_only=True)
        if not ticket:
            await deliver(
                context.bot,
                uid,
                "Сообщение пока не отправлено. Выберите услугу, создайте заявку и отправьте вопрос ещё раз.",
                ui.Keyboard([[ui.action("Выбрать услугу", "c:catalog", "primary")]]),
            )
            return
        message_id, created = self.store.add_message(
            ticket.id, "user", message.text, uid, uid, message.message_id
        )
        if not created:
            return
        ticket = self.store.ticket(ticket.id)
        notified = await self.notify_admins(context.bot, ticket, message.text)
        self.store.delivery(message_id, "delivered" if notified else "stored")
        receipt, _ = await deliver(
            context.bot,
            uid,
            f"✓ Сообщение в заявке <b>№{ticket.id:04d}</b>.\n🟠 Ждёт оператора — ответ придёт сюда.",
            self.customer_keyboard(uid, ui.Keyboard([[ui.action("Статус заявки", f"c:view:{ticket.id}")]])),
        )
        if receipt:
            self.store.map_customer_reply(uid, receipt.message_id, ticket.id)

    async def operator_message(self, update, context):
        message = update.message
        uid = update.effective_user.id
        reply = message.reply_to_message
        note_user = self.store.note_reply_user(uid, reply.message_id) if reply else None
        if note_user is not None:
            if ui.text_units(message.text) > 1200:
                await deliver(
                    context.bot, uid, "Сократите заметку до 1200 символов и ответьте на то же приглашение."
                )
                return
            body = "" if message.text.strip() in {"-", "−", "—"} else message.text
            self.store.set_note(note_user, body, uid)
            await self.profile_screen(update, context, note_user, admin=True)
            return
        ticket = self.store.reply_ticket(uid, reply.message_id) if reply else None
        if not ticket:
            await deliver(
                context.bot,
                uid,
                "Сообщение пока не отправлено. Выберите заявку и нажмите «Ответить».",
                self.recovery_keyboard(True),
            )
            return
        if ticket.status not in OPEN_STATUSES:
            await deliver(
                context.bot,
                uid,
                f"Заявка №{ticket.id:04d} закрыта. Ответ клиенту не отправлен.",
                self.recovery_keyboard(True),
            )
            return
        if self.store.stale_operator_reply(uid, reply.message_id, uid):
            await self.screen(
                update, context,
                f"<b>Переписка №{ticket.id:04d} обновилась</b>\n\n"
                "Другой оператор уже отправил ответ. Ваше сообщение не отправлено.\n"
                "Откройте актуальную переписку перед следующим ответом.",
                ui.Keyboard([[ui.action("Открыть и ответить", f"a:reply:{ticket.id}")]]),
            )
            return
        if not self.store.claim_ticket(ticket.id, uid):
            await self.claim_conflict(update, context, ticket)
            return
        message_id, created = self.store.add_message(
            ticket.id, "operator", message.text, uid, uid, message.message_id
        )
        if not created:
            return
        sent, state = await deliver(
            context.bot,
            ticket.chat_id,
            f"<b>Оператор · №{ticket.id:04d}</b>\n\n{escape(message.text)}\n\n"
            "🟣 Нужен ваш ответ · напишите в этот чат.",
            self.customer_keyboard(
                ticket.user_id,
                ui.Keyboard(
                    [
                        [ui.action("Моя заявка", f"c:view:{ticket.id}")],
                    ]
                ),
            ),
        )
        current = self.store.finalize_operator_delivery(message_id, state, uid)
        if sent:
            self.store.map_customer_reply(ticket.chat_id, sent.message_id, ticket.id)
        receipt, _ = await deliver(context.bot, uid, *ui.reply_receipt(current, state))
        if receipt:
            self.store.map_reply(uid, receipt.message_id, ticket.id)

    async def edited_message(self, update, context):
        if self.remember(update):
            await deliver(
                context.bot,
                update.effective_chat.id,
                "Изменение сообщения в Telegram не меняет переписку заявки. Если нужно что-то исправить, пришлите новое сообщение.",
            )

    async def unknown_command(self, update, context):
        if self.remember(update):
            await deliver(
                context.bot,
                update.effective_chat.id,
                "Такой команды нет. Выберите действие ниже.",
                self.recovery_keyboard(
                    self.is_admin(update.effective_user.id) and not self.client_mode(update.effective_user.id)
                ),
            )

    async def error(self, update, context):
        log.error("Ошибка обработки: %s", type(context.error).__name__)
        if update and update.effective_chat and update.effective_chat.type == ChatType.PRIVATE:
            await deliver(
                context.bot,
                update.effective_chat.id,
                "Не удалось завершить действие. Проверьте заявку и переписку перед повторной отправкой.",
                self.recovery_keyboard(
                    self.is_admin(update.effective_chat.id) and not self.client_mode(update.effective_chat.id)
                ),
            )

    async def post_init(self, application):
        webhook = await application.bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError("У бота подключён другой сервис. Отключите его перед запуском polling.")
        self.store.recover_pending()
        theme.configure(self.config.data_dir)
        await application.bot.set_my_commands(customer_commands())
        for admin_id in self.config.admin_ids:
            try:
                await application.bot.set_my_commands(
                    customer_commands(True) if self.client_mode(admin_id) else operator_commands(),
                    scope=BotCommandScopeChat(admin_id),
                )
            except TelegramError:
                log.warning("Оператору нужно открыть чат с ботом и нажать Start.")
        for language in ("", "ru"):
            await application.bot.set_my_name(catalog.PROFILE_NAME, language_code=language)
            await application.bot.set_my_short_description(catalog.SHORT_DESCRIPTION, language_code=language)
            await application.bot.set_my_description(catalog.DESCRIPTION, language_code=language)
        log.info("Бот запущен: @%s", application.bot.username)


def build_application(config: Config, store: Store, *, request=None):
    desk = Desk(config, store)
    builder = (
        Application.builder()
        .token(config.token)
        .concurrent_updates(False)
        .rate_limiter(AIORateLimiter(overall_max_rate=25, max_retries=1))
        .post_init(desk.post_init)
    )
    if request is not None:
        builder = builder.request(request).get_updates_request(request)
    application = builder.build()
    application.add_handler(
        CommandHandler(
            [
                "start",
                "help",
                "status",
                "privacy",
                "admin",
                "client",
                "id",
                "services",
                "profile",
                "clients",
                "preview",
                "style",
                "sources",
                "next",
            ],
            desk.command,
        )
    )
    application.add_handler(CallbackQueryHandler(desk.callback))
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, desk.edited_message))
    application.add_handler(MessageHandler(filters.COMMAND, desk.unknown_command))
    application.add_handler(MessageHandler(filters.ALL, desk.message))
    application.add_error_handler(desk.error)
    return application
