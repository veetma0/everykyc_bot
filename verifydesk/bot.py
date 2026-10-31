import asyncio
import logging
import re
import time
from html import escape
from urllib.parse import urlsplit

from telegram import BotCommand, BotCommandScopeChat, ForceReply, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    filters,
)

from .config import Config
from .store import OPEN_STATUSES, STATUS_NAMES, StaleTicket, Store, can_customer_cancel, ticket_status
from . import acquisition, catalog, rules, screens, theme, ui


log = logging.getLogger(__name__)
MAX_TEXT = 2400


def contains_verification_link(message):
    text = message.text or message.caption or ""
    urls = re.findall(r"https?://[^\s<>]+", text, re.IGNORECASE)
    urls += [e.url for e in (message.entities or message.caption_entities or ()) if e.url]
    for url in urls:
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or "").casefold().rstrip(".")
        except ValueError:
            continue
        if host == "withpersona.com" or host.endswith(".withpersona.com"):
            return True
        if host in {"claude.ai", "claude.com"} and any(
            word in parsed.path.casefold() for word in ("verif", "identity")
        ):
            return True
    return False


def operator_commands():
    return [
        BotCommand("admin", "Кабинет оператора"),
        BotCommand("next", "Следующий заказ"),
        BotCommand("order", "Найти заказ по номеру"),
        BotCommand("start", "Текущее меню"),
        BotCommand("client", "Перейти в режим клиента"),
        BotCommand("clients", "Карточки клиентов"),
    ]


def customer_commands(operator=False):
    commands = [
        BotCommand("start", "Главное меню"),
        BotCommand("status", "Мой заказ"),
        BotCommand("profile", "Мои заказы"),
        BotCommand("help", "Помощь"),
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

    def admin_home(self, uid):
        return ui.admin_home(self.store.counts(), self.store.queue_count(uid), self.store.stage_counts())

    async def terms_gate(self, update, context):
        """Block every customer update, including old buttons, until explicit consent."""
        if not self.remember(update):
            return
        uid = update.effective_user.id
        query = update.callback_query
        data = str(query.data) if query else ""
        body = update.effective_message.text or ""
        command = body.split()[0].split("@")[0].lower() if body.split() else ""
        if self.is_admin(uid):
            if command == "/admin" or data in {"a:mode:admin", "a:home"}:
                return
            entering_client = command == "/client" or data == "a:mode:client"
            if entering_client:
                self.store.release_claim(uid)
                self.store.set_operator_mode(uid, "client")
            if data.startswith("p:") or (not self.client_mode(uid) and not entering_client):
                return
        if command == "/start" and not self.is_admin(uid):
            source = acquisition.start_source(body)
            if source:
                self.store.remember_source(uid, source)
        state = self.store.terms_state(uid)
        accepted = bool(state and state["accepted_version"] == rules.VERSION)
        terms_action = data == "c:rules" or data.startswith(("c:rules:", "c:agree:"))
        if accepted and not terms_action:
            return
        if query:
            try:
                await query.answer()
            except TelegramError:
                pass
        self.store.clear_input(uid)
        context.user_data.pop("order_search_until", None)
        if data == f"c:agree:{rules.VERSION}" and not accepted:
            if self.store.accept_terms(uid, rules.VERSION, len(rules.PAGES) - 1):
                await self.screen(update, context, *ui.home(self.config.title, self.store.for_user(uid)), customer=True)
                raise ApplicationHandlerStop
        page = 0
        parts = data.split(":")
        if len(parts) == 4 and parts[:2] == ["c", "rules"] and parts[2] == rules.VERSION:
            try:
                requested = int(parts[3])
            except ValueError:
                requested = 0
            reached = state["viewed_page"] if state and state["viewed_version"] == rules.VERSION else -1
            if 0 <= requested < len(rules.PAGES) and (accepted or requested <= reached + 1):
                page = requested
        shown = await self.screen(update, context, *rules.card(page, accepted=accepted), customer=True)
        if shown:
            self.store.mark_terms_page(uid, rules.VERSION, page)
        raise ApplicationHandlerStop

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
            else self.admin_home(uid)
        )
        await self.screen(update, context, *card, customer=mode == "client")

    def customer_chats(self, uid):
        return [ticket for kind in ("order", "wholesale")
                if (ticket := self.store.for_user(uid, active_only=True, kind=kind))]

    def finish_pending_review(self, uid):
        pending = self.store.pending_review(uid)
        if pending:
            self.store.finish_review(pending["ticket_id"], uid)

    def customer_keyboard(self, uid, keyboard):
        rows = list(keyboard.inline_keyboard) if isinstance(keyboard, ui.Keyboard) else []
        chats = self.customer_chats(uid)
        if len(chats) > 1 and not any(str(b.callback_data).startswith("c:chat:") for row in rows for b in row):
            focus = self.store.customer_focus(uid)
            rows += list(ui.conversation_keyboard(chats, focus.id if focus else None).inline_keyboard)
        if self.is_admin(uid) and not any(b.callback_data == "a:mode:admin" for row in rows for b in row):
            rows.append([ui.action("🧑‍💻 В кабинет", "a:mode:admin")])
        return ui.Keyboard(rows) if rows else None

    def recovery_keyboard(self, admin=False):
        return ui.Keyboard(
            [[ui.action("🧑‍💻 Кабинет оператора", "a:home")]]
            if admin
            else [[ui.action("📦 Открыть заказ", "c:current")]]
        )

    def preview_keyboard(self, keyboard):
        converted = screens.preview_markup(keyboard)
        rows = list(converted.inline_keyboard) if isinstance(converted, ui.Keyboard) else []
        if not any(button.callback_data == "a:home" for row in rows for button in row):
            rows.append([ui.action("🧑‍💻 Кабинет оператора", "a:home")])
        return ui.Keyboard(rows)

    def remember(self, update: Update):
        user, chat = update.effective_user, update.effective_chat
        if not user or not chat or chat.type != ChatType.PRIVATE:
            return False
        self.store.remember_user(user.id, chat.id, user.full_name, user.username)
        return True

    def map_customer_card(self, update, message, keyboard):
        if not message:
            return
        query = update.callback_query
        parts = str(query.data).split(":") if query else []
        ticket = None
        uid = update.effective_user.id
        if len(parts) > 2 and parts[0] == "c" and parts[1] in {
            "chat", "view", "details", "history", "message", "write", "requisites", "proof_prompt",
        } and parts[2].isdigit():
            ticket = self.authorized_ticket(int(parts[2]), uid)
        elif len(parts) > 1 and parts[:2] == ["c", "order"]:
            ticket = self.store.for_user(uid, active_only=True)
        elif parts[:2] == ["c", "wholesale"]:
            ticket = self.store.for_user(uid, active_only=True, kind="wholesale")
        elif not query and (update.effective_message.text or "").split(" ")[0] == "/status":
            ticket = self.store.customer_focus(uid) or self.store.for_user(uid, active_only=True)
        if ticket:
            self.store.map_customer_reply(update.effective_chat.id, message.message_id, ticket.id)

    async def notify_customer_status(self, bot, ticket, notice=None):
        text, keyboard = ui.customer_ticket(ticket, self.config.timezone)
        if notice:
            text = notice + "\n\n" + text
        message, state = await deliver(
            bot, ticket.chat_id, text, self.customer_keyboard(ticket.user_id, keyboard)
        )
        if message:
            self.store.map_customer_reply(ticket.chat_id, message.message_id, ticket.id)
        return state

    async def screen(self, update, context, text, keyboard=None, *, customer=None):
        query = update.callback_query
        preview = query and isinstance(query.data, str) and query.data.startswith("p:")
        if preview:
            text = "<b>👀 ПРЕДПРОСМОТР · без создания заказа</b>\n\n" + text
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
        if not preview and (not self.is_admin(update.effective_user.id) or customer):
            keyboard = self.customer_keyboard(update.effective_user.id, keyboard)
        if query and query.message:
            # A card edited into a menu must stop being a reply target for its previous ticket.
            self.store.unmap_reply(update.effective_chat.id, query.message.message_id)
            with self.store.db:
                self.store.db.execute("DELETE FROM review_reply_targets WHERE user_id=? AND message_id=?",
                                      (update.effective_user.id, query.message.message_id))
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
        self.store.clear_input(uid)
        self.finish_pending_review(uid)
        context.user_data.pop("order_search_until", None)
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
        elif command in {"/clients", "/preview", "/style", "/sources", "/next", "/order"}:
            if not self.is_admin(uid):
                await self.screen(update, context, "Эта команда доступна только оператору.")
                return
            if self.client_mode(uid) and command != "/preview":
                await self.screen(
                    update,
                    context,
                    "Сейчас вы в режиме клиента. Для работы с клиентами вернитесь в админку.",
                    ui.Keyboard([[ui.action("🧑‍💻 В админку", "a:mode:admin")]]),
                )
                return
            if command == "/next":
                await self.next_ticket(update, context)
            elif command == "/order":
                args = update.effective_message.text.split(maxsplit=1)
                if len(args) == 1:
                    await self.start_order_search(update, context)
                else:
                    await self.find_order(update, context, args[1])
            elif command == "/clients":
                await self.clients_screen(update, context, 0)
            elif command == "/sources":
                await self.screen(
                    update,
                    context,
                    acquisition.report(self.store.source_summary(self.config.admin_ids)),
                    ui.Keyboard([[ui.action("🧑‍💻 В админку", "a:home")]]),
                )
            elif command == "/preview":
                text, keyboard = ui.home(self.config.title, None)
                await self.screen(
                    update, context, "<b>👀 ПРЕДПРОСМОТР</b>\n\n" + text, self.preview_keyboard(keyboard)
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
                update, context, ui.PRIVACY, ui.Keyboard([[ui.action("🏠 Главное меню", "c:home")]])
            )
        elif command == "/status":
            ticket = self.store.customer_focus(uid) or self.store.for_user(uid)
            if ticket:
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            else:
                await self.screen(
                    update,
                    context,
                    "У вас пока нет заказов.",
                    ui.Keyboard([[ui.action("🛍 Оформить заказ", "c:catalog", "primary")]]),
                )
        elif command == "/cancel":
            ticket = self.store.for_user(uid, active_only=True)
            if ticket:
                await self.customer_callback(update, context, uid, ["c", "cancel", str(ticket.id), str(ticket.version)])
            else:
                await self.screen(update, context, *ui.home(self.config.title, self.store.for_user(uid)))
        elif command == "/start" and self.is_admin(uid):
            try:
                commands = customer_commands(True) if self.client_mode(uid) else operator_commands()
                await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(uid))
            except TelegramError:
                pass
            card = (
                ui.home(self.config.title, self.store.for_user(uid))
                if self.client_mode(uid)
                else self.admin_home(uid)
            )
            await self.screen(update, context, *card)
        else:
            await self.screen(update, context, *ui.home(self.config.title, self.store.for_user(uid)))

    async def help(self, update, context):
        await self.screen(
            update,
            context,
            screens.guide(),
            ui.Keyboard([[ui.action("📦 К заказу", "c:current")]]),
        )

    def admin_card(self, ticket, body=None):
        if body is None:
            rows = self.store.db.execute(
                "SELECT role,body FROM messages WHERE ticket_id=? AND role IN ('user','operator') "
                "ORDER BY id DESC LIMIT 3", (ticket.id,),
            ).fetchall()
            body = "\n\n".join(
                ("Клиент: " if r["role"] == "user" else "Вы: ") + ui.clip_text(r["body"], 400)
                for r in reversed(rows)
            )
        text, keyboard = ui.admin_ticket(ticket, body)
        review = self.store.review(ticket.id)
        if review:
            text += "\n\n<b>Отзыв клиента</b>\n" + "⭐" * review["stars"]
            if review["comment"]:
                text += "\n" + escape(review["comment"])
        return text, keyboard

    async def notify_admins(self, bot, ticket, body=None):
        delivered = False
        busy_queue = (
            self.store.queue_count() >= 20 and ticket.status in OPEN_STATUSES
            and ticket.payment_stage != "review"
        )
        for admin_id in self.config.admin_ids:
            if admin_id == ticket.user_id and self.client_mode(admin_id):
                continue
            text, keyboard = self.admin_card(ticket, body)
            if ticket.payment_stage == "review" and body is None:
                proofs = self.store.payment_proofs(ticket.id)
                if proofs:
                    image_ready = await self.send_proof_image(bot, admin_id, ticket, proofs[0])
                    text, keyboard = ui.admin_ticket(ticket, proofs[0]["body"], proof_ready=image_ready)
            if busy_queue:
                now = time.monotonic()
                previous = self.notification_digest_at.get(admin_id)
                if previous is not None and now - previous < 15:
                    continue
                self.notification_digest_at[admin_id] = now
                await deliver(
                    bot, admin_id,
                    "<b>📥 Новые обращения в очереди</b>\n\n"
                    "Сообщения сохранены. Нажмите «➡️ Следующий заказ», чтобы ответить.\n"
                    "При большом потоке уведомления объединяются.",
                    ui.Keyboard([
                        [ui.action("➡️ Следующий заказ", "a:next")],
                        [ui.action("📥 Очередь", "a:list:queue:0")],
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
        self.store.clear_input(update.effective_user.id)
        self.store.release_claim(update.effective_user.id)
        await self.screen(
            update, context,
            f"<b>№{ticket.id:04d} уже отвечает другой оператор</b>\n\n"
            "Ваше сообщение не отправлено. Возьмите следующее обращение.",
            ui.Keyboard([[ui.action("➡️ Следующий заказ", "a:next")], [ui.action("📥 Очередь", "a:list:queue:0")]]),
        )

    async def open_reply(self, update, context, ticket, *, show_card=False):
        uid = update.effective_user.id
        if ticket.status not in OPEN_STATUSES:
            raise StaleTicket()
        if not self.store.claim_ticket(ticket.id, uid):
            await self.claim_conflict(update, context, ticket)
            return
        ticket = self.store.ticket(ticket.id)
        rows = self.store.db.execute(
            "SELECT role,body FROM messages WHERE ticket_id=? AND role IN ('user','operator') "
            "ORDER BY id DESC LIMIT 3", (ticket.id,),
        ).fetchall()
        details = []
        for row in reversed(rows):
            label = "Клиент" if row["role"] == "user" else "Оператор"
            body = ui.clip_text(row["body"], 500)
            if ui.text_units(row["body"]) > 500:
                body += "…"
            details.append(f"<b>{label}:</b> {escape(body)}")
        context_text = "\n\n".join(details) if details else "Клиент оформил заказ и ждёт ответа."
        rows = [[ui.action("← К обращению", f"a:view:{ticket.id}"), ui.action("▶️ Другой заказ", f"a:next:{ticket.id}")]]
        if ticket.payment_stage in {"legacy", "confirmed"}:
            rows.insert(0, [ui.action("✅ Выполнен", f"a:set:{ticket.id}:{ticket.version}:resolved")])
        prompt, _ = await deliver(
            context.bot, uid,
            f"<b>Ответ · {ui.conversation_title(ticket)} · {escape(ticket.display_name)}</b>\n\n"
            f"{context_text}\n\n"
            "Пишите текст, присылайте фото или файл — сообщения сразу уйдут этому клиенту.\n"
            "Получатель закреплён до выхода из переписки. Telegram Reply позволяет ответить на конкретное обращение.",
            ui.Keyboard(rows),
        )
        if prompt:
            self.store.map_reply(uid, prompt.message_id, ticket.id)
            self.store.focus_operator(uid, ticket.id, prompt.message_id)
        else:
            self.store.release_claim(uid, ticket.id)

    async def next_ticket(self, update, context, skip_ticket_id=None):
        uid = update.effective_user.id
        ticket = self.store.claim_next(uid, skip_ticket_id)
        if ticket:
            if ticket.payment_stage == "not_requested":
                shown = await self.screen(update, context, *self.admin_card(ticket))
                if shown:
                    self.store.map_reply(uid, shown.message_id, ticket.id)
            elif ticket.payment_stage == "review":
                await self.payment_proofs_screen(update, context, ticket)
            else:
                await self.open_reply(update, context, ticket, show_card=True)
            return
        counts = self.store.counts()
        waiting = counts["new"] + counts["in_progress"]
        text = (
            "Других свободных заказов сейчас нет. Можно вернуться в очередь."
            if skip_ticket_id is not None else
            "Свободных заказов сейчас нет. Заказы с ожиданием оплаты и заказы других операторов доступны в списке."
            if waiting else
            "✅ Очередь пуста. Новых обращений, ожидающих ответа, пока нет."
        )
        await self.screen(
            update, context, text,
            ui.Keyboard([[ui.action("📥 Проверить очередь", "a:list:queue:0")], [ui.action("🧑‍💻 В админку", "a:home")]]),
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
            if parts[0] in {"a", "c"}:
                if parts[1] in {"send_draft", "discard_draft"}:
                    self.store.clear_input(uid)
                    await self.screen(update, context, "Теперь сообщения отправляются прямо в чат. Старый черновик не отправлен.", self.recovery_keyboard(parts[0] == "a"))
                    return
                context.user_data.pop("order_search_until", None)
                self.store.clear_input(uid)
            if parts[0] == "c":
                await self.customer_callback(update, context, uid, parts)
            elif parts[0] == "p":
                await self.customer_callback(update, context, uid, parts, preview=True)
            elif parts[0] == "a":
                await self.admin_callback(update, context, uid, parts)
        except (ValueError, IndexError, KeyError, StaleTicket):
            if parts[0] == "a":
                context.user_data.pop("order_search_until", None)
                self.store.clear_input(uid)
                self.store.release_claim(uid)
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
        if preview and verb in {"create", "order", "close", "network", "write", "proof_prompt", "send_draft", "wholesale", "chat", "rate", "review_skip"}:
            await self.screen(
                update,
                context,
                "В предпросмотре заказы и сообщения не отправляются, выбор не сохраняется.",
                ui.Keyboard([[ui.action("✨ К услугам", "c:catalog")]]),
            )
            return
        if not preview and verb not in {"rate", "review_skip"}:
            self.finish_pending_review(uid)
        if verb in {"wholesale", "chat"}:
            if verb == "wholesale":
                ticket, created = self.store.create_ticket(uid, kind="wholesale")
            else:
                ticket, created = self.authorized_ticket(int(parts[2]), uid), False
            if not ticket or ticket.status not in OPEN_STATUSES:
                raise StaleTicket()
            self.store.set_customer_focus(uid, ticket.id)
            await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            if created:
                await self.notify_admins(context.bot, ticket)
            return
        if verb in {"rate", "review_skip"}:
            ticket = self.authorized_ticket(int(parts[2]), uid)
            if not ticket or ticket.kind != "order" or ticket.status != "resolved":
                raise StaleTicket()
            if verb == "review_skip":
                self.store.finish_review(ticket.id, uid)
                await self.screen(update, context, "💛 Спасибо за оценку!", ui.Keyboard([[ui.action("🏠 Меню", "c:home")]]))
            else:
                stars = int(parts[3])
                if not 1 <= stars <= 5:
                    raise ValueError()
                pending = self.store.pending_review(uid)
                if pending and pending["ticket_id"] != ticket.id:
                    self.finish_pending_review(uid)
                review = self.store.rate_ticket(ticket.id, uid, stars)
                if review["finished_at"]:
                    await self.screen(update, context, "💛 Ваш отзыв уже сохранён.", ui.Keyboard([[ui.action("🏠 Меню", "c:home")]]))
                else:
                    shown = await self.screen(update, context, *ui.review_comment_card(ticket, review["stars"]))
                    if shown:
                        self.store.map_review_reply(uid, shown.message_id, ticket.id)
            return
        if verb == "rules":
            page = int(parts[3]) if len(parts) == 4 and parts[2] == rules.VERSION else 0
            if not 0 <= page < len(rules.PAGES):
                raise ValueError()
            await self.screen(update, context, *rules.card(page, accepted=True))
        elif verb == "home":
            await self.screen(
                update,
                context,
                *ui.home(self.config.title, None if preview else self.store.for_user(uid)),
            )
        elif verb == "catalog":
            await self.screen(update, context, *screens.catalog_card())
        elif verb == "category":
            await self.screen(update, context, *screens.category_card(parts[2]))
        elif verb == "service":
            await self.screen(update, context, *screens.service_card(parts[2]))
        elif verb in {"offer", "order"} and (parts[2], parts[3]) not in catalog.OFFERS:
            # Old region cards must show current terms and require a fresh order click.
            await self.screen(update, context, *screens.service_card(parts[2]))
        elif verb == "offer":
            await self.screen(update, context, *screens.offer_card(catalog.offer(parts[2], parts[3])))
        elif verb == "order":
            selected = catalog.offer(parts[2], parts[3])
            if not selected.available:
                await self.screen(update, context, *screens.offer_card(selected))
                return
            ticket, created = self.store.create_ticket(
                uid, selected.service, selected.plan, None if selected.demo else selected.price_usd
            )
            if not created and (ticket.service_code, ticket.plan_code) != (selected.service, selected.plan):
                await self.screen(
                    update,
                    context,
                    f"<b>У вас уже есть активный заказ №{ticket.id:04d}</b>\n\n"
                    f"{catalog.service_title(ticket.service_code, ticket.plan_code)} · {catalog.dollars(ticket.price_usd)}\n\n"
                    f"Вы выбрали {escape(selected.title)}. Напишите новый запрос в текущий заказ — оператор поможет уточнить направление. Условия текущего заказа сохранены.",
                    ui.Keyboard(
                        [
                            [ui.action("📦 Открыть заказ", f"c:view:{ticket.id}", "primary")],
                            [ui.action("✨ К услугам", "c:catalog")],
                        ]
                    ),
                )
                return
            self.store.set_customer_focus(uid, ticket.id)
            await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            if created:
                await self.notify_admins(context.bot, ticket)
        elif verb == "profile":
            await self.profile_screen(update, context, uid)
        elif verb == "orders":
            await self.orders_screen(update, context, uid, int(parts[2]), False)
        elif verb == "guide":
            service = parts[2]
            if (service, "standard") not in catalog.OFFERS:
                raise ValueError()
            rows = []
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
                    "c:catalog"
                    if not self.store.for_user(uid, active_only=True)
                    else "c:current"
                )
                rows.append([ui.action("Вернуться", target)])
            await self.screen(update, context, screens.guide(service), ui.Keyboard(rows))
        elif verb in {"pay", "networks", "network"}:
            ticket = self.authorized_ticket(int(parts[2]), uid)
            if not ticket:
                await self.screen(update, context, "Этот заказ недоступен.", self.recovery_keyboard())
                return
            if ticket.status in OPEN_STATUSES and not preview:
                self.store.set_customer_focus(uid, ticket.id)
            # Retired network demos must not bring the old payment menus back.
            await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
        elif verb == "prepare":
            current = self.store.for_user(uid, active_only=True)
            if current and not preview:
                self.store.set_customer_focus(uid, current.id)
            await self.screen(
                update,
                context,
                *(ui.customer_ticket(current, self.config.timezone) if current else screens.catalog_card()),
            )
        elif verb == "help":
            await self.help(update, context)
        elif verb == "privacy":
            await self.screen(
                update, context, ui.PRIVACY, ui.Keyboard([[ui.action("🏠 Главное меню", "c:home")]])
            )
        elif verb == "current":
            current = self.store.for_user(uid, active_only=True)
            if current and not preview:
                self.store.set_customer_focus(uid, current.id)
            await self.screen(
                update,
                context,
                *(ui.customer_ticket(current, self.config.timezone) if current else screens.catalog_card()),
            )
        elif verb == "create":
            await self.screen(update, context, *screens.catalog_card())
        elif verb in {"view", "details", "history", "cancel", "close", "message", "write", "requisites", "proof_prompt"}:
            ticket = self.authorized_ticket(int(parts[2]), uid)
            if not ticket:
                await self.screen(update, context, "Этот заказ недоступен.", self.recovery_keyboard())
                return
            if verb in {"proof_prompt", "write", "requisites"}:
                if ticket.status in OPEN_STATUSES:
                    self.store.set_customer_focus(uid, ticket.id)
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
            elif verb == "details":
                if ticket.status in OPEN_STATUSES:
                    self.store.set_customer_focus(uid, ticket.id)
                await self.screen(update, context, *ui.customer_details(ticket, self.config.timezone))
            elif verb == "history":
                await self.show_history(update, context, ticket, int(parts[3]), False)
            elif verb == "message":
                await self.full_message(update, context, ticket, int(parts[3]), False)
            elif verb == "cancel":
                if ticket.status not in OPEN_STATUSES or int(parts[3]) != ticket.version:
                    raise StaleTicket()
                if not can_customer_cancel(ticket):
                    await self.screen(
                        update, context,
                        "🔒 После отправки чека самостоятельная отмена закрыта. По этому заказу поможет оператор.",
                        ui.Keyboard([[ui.action("🏠 Меню", "c:home")]]),
                    )
                    return
                await self.screen(
                    update,
                    context,
                    f"<b>Отменить заказ №{ticket.id:04d}?</b>\n\nПереписка останется в истории. При необходимости можно оформить новый заказ.",
                    ui.Keyboard(
                        [
                            [ui.action("❌ Да, отменить", f"c:close:{ticket.id}:{ticket.version}", "danger")],
                            [ui.action("⬅️ Вернуться к заказу", f"c:view:{ticket.id}")],
                        ]
                    ),
                )
            elif verb == "close":
                ticket = self.store.set_status(ticket.id, int(parts[3]), "cancelled", uid, customer_cancel=True)
                await self.screen(update, context, *ui.customer_ticket(ticket, self.config.timezone))
                await self.notify_admins(context.bot, ticket)
            else:
                if ticket.status in OPEN_STATUSES:
                    self.store.set_customer_focus(uid, ticket.id)
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
                update, context, "<b>👀 ПРЕДПРОСМОТР</b>\n\n" + text, self.preview_keyboard(keyboard)
            )
            return
        if self.client_mode(uid):
            await self.screen(
                update,
                context,
                "Сейчас вы в режиме клиента. Для работы с заказами вернитесь в админку.",
                ui.Keyboard([[ui.action("🧑‍💻 В админку", "a:mode:admin")]]),
            )
            return
        if verb == "next":
            skip = int(parts[2]) if len(parts) > 2 else None
            await self.next_ticket(update, context, skip)
            return
        if verb == "find":
            await self.start_order_search(update, context)
            return
        if verb == "more":
            await self.screen(update, context, *ui.admin_more())
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
                f"<b>📝 Приватная заметка · {escape(profile.display_name)}</b>\nID клиента: {profile.id}\n\n"
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
            rows = []
            for ticket in tickets:
                owner = self.store.claim_owner(ticket.id)
                mark = "🔒 " if owner and owner != uid else "● " if ticket.unread else ""
                action = "view"
                if scope == "queue":
                    if ticket.payment_stage == "review":
                        action = "proofs"
                    elif ticket.payment_stage in {"legacy", "confirmed"}:
                        action = "reply"
                rows.append([ui.action(
                    f"{mark}№{ticket.id:04d} · {ticket.display_name[:24]} · {ticket_status(ticket)}",
                    f"a:{action}:{ticket.id}",
                )])
            navigation = []
            if offset > 0:
                navigation.append(ui.action("← Назад", f"a:list:{scope}:{max(0, offset - 8)}"))
            if offset + 8 < total:
                navigation.append(ui.action("Далее →", f"a:list:{scope}:{offset + 8}"))
            if navigation:
                rows.append(navigation)
            stage_buttons = [
                ui.action(label, f"a:list:{target}:0")
                for target, label in (("new", "🆕 Новые"), ("review", "💳 Чеки"), ("work", "🛠 В работе"), ("payment", "⏳ Ждём оплату"))
                if target != scope
            ]
            rows.extend([stage_buttons[i:i + 2] for i in range(0, len(stage_buttons), 2)])
            if scope == "active":
                rows.append([ui.action("🗂 Завершённые", "a:list:closed:0")])
            else:
                rows.append([ui.action("📋 Все заказы", "a:list:active:0")])
            rows.append([ui.action("🧑‍💻 Кабинет оператора", "a:home")])
            title = {
                "queue": "Требуют внимания", "active": "Активные", "new": "Новые",
                "review": "Проверка оплаты", "work": "В работе", "payment": "Ожидают оплаты", "closed": "Завершённые",
            }[scope]
            text = f"<b>{title} заказы · {total}</b>\n\n" + (
                "● — новые сообщения · 🔒 — уже открыт другим менеджером." if tickets else "Здесь пока пусто."
            )
            await self.screen(update, context, text, ui.Keyboard(rows))
            return
        ticket = self.authorized_ticket(int(parts[2]), uid, admin=True)
        if not ticket:
            await self.screen(update, context, "Заказ не найден.", self.recovery_keyboard(True))
            return
        if verb == "view":
            shown = await self.screen(update, context, *self.admin_card(ticket))
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
                self.store.mark_read(ticket.id)
        elif verb == "history":
            await self.show_history(update, context, ticket, int(parts[3]), True)
        elif verb == "message":
            await self.full_message(update, context, ticket, int(parts[3]), True)
        elif verb == "reply":
            await self.open_reply(update, context, ticket, show_card=True)
        elif verb == "details":
            await self.screen(update, context, *ui.admin_details(ticket))
        elif verb == "request_payment":
            ticket = self.store.request_payment(ticket.id, int(parts[3]), uid)
            text, keyboard = ui.payment_request(ticket)
            message, state = await deliver(
                context.bot, ticket.chat_id, text, self.customer_keyboard(ticket.user_id, keyboard)
            )
            if message:
                self.store.map_customer_reply(ticket.chat_id, message.message_id, ticket.id)
            text, keyboard = self.admin_card(ticket)
            if state != "delivered":
                text += "\n\n⚠️ Доставка уведомления об оплате не подтверждена. Статус сохранён в заказе."
            await self.screen(update, context, text, keyboard)
        elif verb == "proofs":
            await self.payment_proofs_screen(update, context, ticket, int(parts[3]) if len(parts) > 3 else 0)
        elif verb in {"confirm_payment", "reject_payment"}:
            if verb == "confirm_payment":
                ticket = self.store.confirm_payment(ticket.id, int(parts[3]), uid)
            else:
                ticket = self.store.reject_payment(ticket.id, int(parts[3]), uid)
            notice = (
                "↩️ Оператор попросил другое подтверждение. Пришлите новый скриншот или ссылку на чек."
                if verb == "reject_payment" else "✅ Оплата подтверждена. Ожидайте сообщения от оператора."
            )
            state = await self.notify_customer_status(context.bot, ticket, notice)
            text, keyboard = self.admin_card(ticket)
            if state != "delivered":
                text += "\n\n⚠️ Статус сохранён. Доставка уведомления клиенту не подтверждена."
            shown = await self.screen(update, context, text, keyboard)
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
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
                    f"<b>{'Отменить' if status == 'cancelled' else 'Завершить'} заказ №{ticket.id:04d}?</b>\n"
                    f"{escape(ticket.display_name)}\n\nКлиент получит сообщение: {STATUS_NAMES[status]}.",
                    ui.Keyboard(
                        [
                            [
                                ui.action(
                                    "✅ Подтвердить", f"a:confirm:{ticket.id}:{version}:{status}", "success"
                                )
                            ],
                            [ui.action("Назад", f"a:view:{ticket.id}")],
                        ]
                    ),
                )
                return
            ticket = self.store.set_status(ticket.id, version, status, uid)
            state = await self.notify_customer_status(context.bot, ticket)
            if ticket.status == "resolved" and ticket.kind == "order":
                await deliver(context.bot, ticket.chat_id, *ui.review_request(ticket))
            text, keyboard = self.admin_card(ticket)
            if state != "delivered":
                text += "\n\n⚠️ Статус сохранён. Доставка уведомления клиенту не подтверждена."
            shown = await self.screen(update, context, text, keyboard)
            if shown:
                self.store.map_reply(uid, shown.message_id, ticket.id)
        else:
            raise ValueError("Unknown operator action")

    async def start_order_search(self, update, context):
        uid = update.effective_user.id
        if not self.is_admin(uid) or self.client_mode(uid):
            return
        self.store.clear_input(uid)
        self.store.release_claim(uid)
        context.user_data["order_search_until"] = time.monotonic() + 300
        await self.screen(
            update, context, "<b>🔎 Найти заказ</b>\n\nВведите номер, например <b>123</b> или <b>№0123</b>.",
            ui.Keyboard([[ui.action("Назад к заказам", "a:home")]]),
        )

    async def find_order(self, update, context, value):
        uid = update.effective_user.id
        if not self.is_admin(uid) or self.client_mode(uid):
            return
        self.store.clear_input(uid)
        self.store.release_claim(uid)
        match = re.fullmatch(r"[#№]?\s*(\d{1,10})", value.strip())
        ticket = self.store.ticket(int(match[1])) if match and int(match[1]) > 0 else None
        if ticket is None:
            context.user_data["order_search_until"] = time.monotonic() + 300
            await self.screen(
                update, context,
                "Заказ не найден. Введите другой номер, например <b>123</b>.",
                ui.Keyboard([[ui.action("Назад к заказам", "a:home")]]),
            )
            return
        context.user_data.pop("order_search_until", None)
        shown = await self.screen(update, context, *self.admin_card(ticket))
        if shown:
            self.store.map_reply(uid, shown.message_id, ticket.id)
            self.store.mark_read(ticket.id)

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
                    f"{profile.display_name[:30]} · {profile.total_tickets} заказов", f"a:client:{profile.id}"
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
        rows.append([ui.action("🧑‍💻 Кабинет оператора", "a:home")])
        await self.screen(
            update,
            context,
            f"<b>👥 Клиенты · {total}</b>\n\n"
            + (
                "Карточка объединяет обращения, текущий заказ и вашу заметку."
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
                        f"№{ticket.id:04d} · {catalog.service_title(ticket.service_code, ticket.plan_code)} · {ticket_status(ticket)}",
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
        buttons.append([ui.action("👤 К карточке", f"a:client:{user_id}" if admin else "c:profile")])
        await self.screen(
            update,
            context,
            f"<b>🗂 История заказов · {total}</b>\n\n" + ("Выберите обращение." if rows else "Заказов пока нет."),
            ui.Keyboard(buttons),
        )

    async def style_preview(self, update, context):
        if not self.is_admin(update.effective_user.id):
            return
        _, result = await theme.preview(context.bot, update.effective_user.id, self.config.data_dir)
        await self.screen(
            update,
            context,
            f"<b>🎨 Оформление Эврикус</b>\n\n{result}\n\nДля премиум-эмодзи Telegram требует Premium у владельца бота или дополнительный username на Fragment. Основные кнопки работают и без них.",
            ui.Keyboard([[ui.action("🧑‍💻 Кабинет оператора", "a:home")]]),
        )

    async def show_history(self, update, context, ticket, page, admin):
        if not admin and ticket.status in OPEN_STATUSES:
            self.store.set_customer_focus(update.effective_user.id, ticket.id)
        page = max(0, page)
        _, total = self.store.messages(ticket.id)
        page = min(page, max(0, (total - 1) // 4))
        rows, total = self.store.messages(ticket.id, page)
        text, keyboard = ui.history(ticket, rows, total, page, admin, self.config.timezone)
        prefix = "a" if admin else "c"
        full_buttons = [
            [
                ui.action(
                    f"📎 Сообщение от {self._stamp(row['created_at'])}",
                    f"{prefix}:message:{ticket.id}:{row['id']}",
                )
            ]
            for row in rows
            if ui.text_units(row["body"]) > 650 or self.store.attachment(row["id"])
            or self.store.db.execute("SELECT 1 FROM payment_proofs WHERE message_id=? AND file_id IS NOT NULL", (row["id"],)).fetchone()
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
            "SELECT id,body,role FROM messages WHERE id=? AND ticket_id=?", (message_id, ticket.id)
        ).fetchone()
        if not row:
            raise ValueError()
        attachment = self.store.attachment(message_id) or self.store.db.execute(
            "SELECT file_id,file_kind FROM payment_proofs WHERE message_id=? AND file_id IS NOT NULL", (message_id,),
        ).fetchone()
        if attachment:
            await self.relay_attachment(context.bot, update.effective_user.id, ticket,
                attachment["file_id"], attachment["file_kind"], row["body"], operator=not admin)
        prefix = "a" if admin else "c"
        shown = await self.screen(
            update,
            context,
            f"<b>Заказ №{ticket.id:04d} · сообщение</b>\n\n{escape(row['body'])}",
            ui.Keyboard([[ui.action("💬 К переписке", f"{prefix}:history:{ticket.id}:0")]]),
        )
        if admin and shown:
            self.store.map_reply(update.effective_chat.id, shown.message_id, ticket.id)

    async def send_proof_image(self, bot, chat_id, ticket, proof):
        """Relay only the payment image the customer explicitly submitted; never download it."""
        if not proof["file_id"]:
            return True
        caption = f"🧾 Подтверждение · заказ №{ticket.id:04d}"
        try:
            if proof["file_kind"] == "photo":
                await bot.send_photo(chat_id=chat_id, photo=proof["file_id"], caption=caption, protect_content=True)
            else:
                await bot.send_document(
                    chat_id=chat_id, document=proof["file_id"], caption=caption, protect_content=True
                )
            return True
        except TelegramError as exc:
            log.warning("Изображение подтверждения не доставлено: %s", type(exc).__name__)
            return False

    async def payment_proofs_screen(self, update, context, ticket, offset=0):
        proofs = self.store.payment_proofs(ticket.id)
        if not proofs:
            await self.screen(
                update, context, "🧾 Подтверждение оплаты пока не прислано.",
                ui.Keyboard([[ui.action("⬅️ К заказу", f"a:view:{ticket.id}")]]),
            )
            return
        offset = max(0, min(offset, len(proofs) - 1))
        proof = proofs[offset]
        image_sent = await self.send_proof_image(context.bot, update.effective_user.id, ticket, proof)
        text = (
            f"<b>🔎 Проверка оплаты · заказ №{ticket.id:04d}</b>\n"
            f"{escape(ticket.display_name)} · {catalog.dollars(ticket.price_usd)}\n"
            f"Подтверждение {offset + 1} из {len(proofs)}\n\n"
            f"{escape(proof['body'])}\n\n"
            "Проверьте подтверждение. Только после вашего решения заказ перейдёт в работу."
        )
        rows = []
        if not image_sent:
            text += "\n\n⚠️ Скриншот не загрузился. Откройте проверку ещё раз, чтобы увидеть его."
            rows.append([ui.action("🔄 Показать скриншот", f"a:proofs:{ticket.id}:{offset}")])
        elif ticket.status in OPEN_STATUSES and ticket.payment_stage == "review" and offset == 0:
            rows.append([ui.action("✅ Оплата получена", f"a:confirm_payment:{ticket.id}:{ticket.version}")])
            rows.append([ui.action("↩️ Запросить другой чек", f"a:reject_payment:{ticket.id}:{ticket.version}")])
        navigation = []
        if offset + 1 < len(proofs):
            navigation.append(ui.action("← Раньше", f"a:proofs:{ticket.id}:{offset + 1}"))
        if offset:
            navigation.append(ui.action("К последнему →", f"a:proofs:{ticket.id}:0"))
        if navigation:
            rows.append(navigation)
        rows.append([ui.action("⬅️ К заказу", f"a:view:{ticket.id}")])
        await self.screen(update, context, text, ui.Keyboard(rows))

    def message_content(self, message):
        body = message.text or message.caption or ""
        urls = [e.url for e in (message.entities or message.caption_entities or ()) if e.url]
        for url in urls:
            if url not in body:
                body += "\n" + url
        photo = message.photo[-1] if message.photo else None
        media = photo or message.document
        return body, media, "photo" if photo else "document" if media else None

    def customer_routing_hint(self, uid, ticket):
        chats = self.customer_chats(uid)
        selected = self.store.customer_focus(uid)
        if len(chats) > 1 and (not selected or selected.id != ticket.id):
            current = ui.conversation_title(selected) if selected else "переписка ещё не выбрана"
            return f"💬 Сейчас выбран чат: {current}. Чтобы ответить по этому обращению, выберите его ниже или используйте Telegram Reply."
        return "💬 Пишите прямо сюда. Сообщения уйдут в эту переписку."

    async def relay_attachment(self, bot, chat_id, ticket, file_id, file_kind, body, *, operator=False):
        title = ui.conversation_title(ticket)
        header = ("Оператор · " if operator else f"{ticket.display_name} · ") + title
        caption = escape(header) + ("\n\n" + escape(ui.clip_text(body, 650)) if body else "")
        if ui.text_units(body) > 650:
            caption += "\n…Полный текст — в переписке."
        if operator and len(self.customer_chats(ticket.user_id)) > 1:
            caption += "\n\nОтветьте через Telegram Reply или выберите нужную переписку ниже."
        prefix = "c" if operator else "a"
        keyboard = ui.Keyboard([[ui.action("💬 Переписка", f"{prefix}:history:{ticket.id}:0")]])
        if operator:
            keyboard = self.customer_keyboard(ticket.user_id, keyboard)
        try:
            send = bot.send_photo if file_kind == "photo" else bot.send_document
            sent = await send(chat_id=chat_id, **{file_kind: file_id}, caption=caption,
                              parse_mode=ParseMode.HTML, reply_markup=keyboard, protect_content=True)
            if operator:
                self.store.map_customer_reply(chat_id, sent.message_id, ticket.id)
            else:
                self.store.map_reply(chat_id, sent.message_id, ticket.id)
            return sent, "delivered"
        except NetworkError:
            return None, "uncertain"
        except TelegramError:
            return None, "failed"

    async def message(self, update, context):
        if not update.message or not self.remember(update):
            return
        message, uid = update.message, update.effective_user.id
        body, media, file_kind = self.message_content(message)
        if self.store.find_source(message.chat_id, message.message_id) or self.store.review_source(message.chat_id, message.message_id):
            return
        operator = self.is_admin(uid) and not self.client_mode(uid)
        if operator:
            searching = context.user_data.get("order_search_until", 0)
            if searching and not message.reply_to_message and time.monotonic() < searching:
                await self.find_order(update, context, body)
                return
            context.user_data.pop("order_search_until", None)
        if not body.strip() and not media:
            await deliver(context.bot, uid, "Пришлите текст, фото или файл.")
            return
        if ui.text_units(body) > MAX_TEXT:
            await deliver(context.bot, uid, f"Разделите сообщение на части до {MAX_TEXT} символов.")
            return
        if media and media.file_size and media.file_size > 20 * 1024 * 1024:
            await deliver(context.bot, uid, "Пришлите файл размером до 20 МБ.")
            return
        if operator:
            await self.operator_message(update, context)
            return
        if contains_verification_link(message):
            await deliver(context.bot, uid, "🔒 <b>Ссылку проверки не отправляйте.</b>\nПроверку проходите самостоятельно. Опишите ошибку без документов и кодов входа.")
            return
        reply = message.reply_to_message
        if self.client_mode(uid) and reply and (
            self.store.reply_ticket(uid, reply.message_id) or self.store.note_reply_user(uid, reply.message_id)
        ):
            await deliver(context.bot, uid, "Это ответ из админки. Сейчас вы как клиент — сообщение не отправлено.", self.customer_keyboard(uid, self.recovery_keyboard()))
            return
        review_target = self.store.review_reply_ticket(uid, reply.message_id) if reply else None
        pending = self.store.pending_review(uid)
        if review_target or (pending and not reply):
            review_id = review_target.id if review_target else pending["ticket_id"]
            review = self.store.review(review_id)
            if review["finished_at"]:
                await deliver(context.bot, uid, "Этот отзыв уже сохранён. Откройте нужную переписку из меню.", self.recovery_keyboard())
                return
            if media or not body.strip() or ui.text_units(body) > 1200:
                await deliver(context.bot, uid, "Напишите комментарий текстом до 1200 символов или выберите «Без комментария».")
                return
            self.store.finish_review(review_id, uid, body, source_chat=message.chat_id, source_message=message.message_id)
            await deliver(context.bot, uid, "💛 Спасибо! Оценка и комментарий сохранены.", self.customer_keyboard(uid, ui.Keyboard([[ui.action("🏠 Меню", "c:home")]])))
            return
        if reply:
            target = self.store.customer_reply_ticket(uid, reply.message_id)
            if target is None and reply.from_user and reply.from_user.id == uid:
                source = self.store.find_source(uid, reply.message_id)
                if source and source["role"] == "user":
                    target = self.store.ticket(source["ticket_id"])
            if not target or target.user_id != uid or target.status not in OPEN_STATUSES:
                await deliver(context.bot, uid, "Эта переписка уже закрыта или недоступна. Сообщение не отправлено.", self.recovery_keyboard())
                return
            self.finish_pending_review(uid)
            ticket = target
        else:
            ticket = self.store.customer_focus(uid)
            if not ticket:
                chats = self.customer_chats(uid)
                previous_selection = self.store.db.execute("SELECT ticket_id FROM customer_focus WHERE user_id=?", (uid,)).fetchone()
                if len(chats) == 1 and not previous_selection:
                    ticket = chats[0]
                    self.store.set_customer_focus(uid, ticket.id)
                else:
                    text = "Выберите переписку ниже. Предыдущая переписка закрыта или выбор ещё не сделан; сообщение пока не отправлено." if chats else "Откройте услугу или раздел «Обсудить опт», затем пишите прямо сюда. Сообщение пока не отправлено."
                    keyboard = ui.conversation_keyboard(chats) if chats else ui.Keyboard([[ui.action("✨ Услуги", "c:catalog"), ui.action("🤝 Обсудить опт", "c:wholesale")]])
                    await deliver(context.bot, uid, text, self.customer_keyboard(uid, keyboard))
                    return
        is_proof = ticket.kind == "order" and ticket.payment_stage in {"awaiting_payment", "review"} and (
            media or re.search(r"https?://[^\s<>]+", body, re.I)
        )
        stored_body = body or ("📷 Фото" if file_kind == "photo" else "📎 Файл")
        if is_proof:
            mid, created = self.store.submit_payment_proof(ticket.id, stored_body, uid, message.chat_id, message.message_id,
                media.file_id if media else None, file_kind)
        else:
            mid, created = self.store.add_message(ticket.id, "user", stored_body, uid, message.chat_id, message.message_id)
            if media:
                self.store.attach_message(mid, media.file_id, file_kind)
        if not created:
            return
        ticket = self.store.ticket(ticket.id)
        media_states = []
        if media and not is_proof:
            for admin_id in self.config.admin_ids:
                if admin_id != uid or not self.client_mode(uid):
                    _, media_state = await self.relay_attachment(context.bot, admin_id, ticket, media.file_id, file_kind, body)
                    media_states.append(media_state)
        notified = await self.notify_admins(context.bot, ticket, None if is_proof else stored_body)
        delivery_state = "delivered" if notified else "stored"
        if media_states and "delivered" not in media_states:
            delivery_state = "uncertain" if "uncertain" in media_states else "failed"
        self.store.delivery(mid, delivery_state)
        receipt, _ = await deliver(context.bot, uid,
            f"✓ {ui.conversation_title(ticket)} · " + ("Подтверждение сохранено для проверки оператором." if is_proof else "Сообщение сохранено. Оператор ответит здесь."),
            self.customer_keyboard(uid, None))
        if receipt:
            self.store.map_customer_reply(uid, receipt.message_id, ticket.id)

    async def operator_message(self, update, context):
        message = update.message
        uid = update.effective_user.id
        reply = message.reply_to_message
        body, media, file_kind = self.message_content(message)
        note_user = self.store.note_reply_user(uid, reply.message_id) if reply else None
        if note_user is not None:
            if media or ui.text_units(body) > 1200:
                await deliver(
                    context.bot, uid, "Сократите заметку до 1200 символов и ответьте на то же приглашение."
                )
                return
            body = "" if body.strip() in {"-", "−", "—"} else body
            self.store.set_note(note_user, body, uid)
            await self.profile_screen(update, context, note_user, admin=True)
            return
        ticket = self.store.reply_ticket(uid, reply.message_id) if reply else self.store.focused_ticket(uid)
        if not ticket:
            await deliver(
                context.bot,
                uid,
                "Сообщение пока не отправлено. Выберите заказ и нажмите «Ответить».",
                self.recovery_keyboard(True),
            )
            return
        if ticket.status not in OPEN_STATUSES:
            await deliver(
                context.bot,
                uid,
                f"Заказ №{ticket.id:04d} закрыт. Ответ клиенту не отправлен.",
                self.recovery_keyboard(True),
            )
            return
        if reply and self.store.stale_operator_reply(uid, reply.message_id, uid):
            await self.screen(
                update, context,
                f"<b>Переписка №{ticket.id:04d} обновилась</b>\n\n"
                "Другой оператор уже отправил ответ. Ваше сообщение не отправлено.\n"
                "Откройте актуальную переписку перед следующим ответом.",
                ui.Keyboard([[ui.action("💬 Открыть и ответить", f"a:reply:{ticket.id}")]]),
            )
            return
        if not self.store.claim_ticket(ticket.id, uid):
            await self.claim_conflict(update, context, ticket)
            return
        await self.send_operator_text(update, context, ticket, body, message.message_id,
                                      media.file_id if media else None, file_kind)

    async def send_operator_text(self, update, context, ticket, body, source_message, file_id=None, file_kind=None):
        uid = update.effective_user.id
        if not self.store.claim_ticket(ticket.id, uid):
            await self.claim_conflict(update, context, ticket)
            return
        stored_body = body or ("📷 Фото" if file_kind == "photo" else "📎 Файл")
        message_id, created = self.store.add_message(ticket.id, "operator", stored_body, uid, uid, source_message)
        if not created:
            return
        if file_id:
            self.store.attach_message(message_id, file_id, file_kind)
            sent, state = await self.relay_attachment(context.bot, ticket.chat_id, ticket, file_id, file_kind, body, operator=True)
        else:
            sent, state = await deliver(context.bot, ticket.chat_id,
                f"<b>Оператор · {ui.conversation_title(ticket)}</b>\n\n{escape(body)}\n\n"
                f"{ticket_status(ticket)}\n{escape(self.customer_routing_hint(ticket.user_id, ticket))}",
                self.customer_keyboard(ticket.user_id, None))
        current = self.store.finalize_operator_delivery(message_id, state, uid)
        if sent:
            self.store.map_customer_reply(ticket.chat_id, sent.message_id, ticket.id)
        receipt, _ = await deliver(context.bot, uid, *ui.reply_receipt(current, state))
        if receipt:
            self.store.map_reply(uid, receipt.message_id, ticket.id)
            # Keep explicit recipient visible and selected for consecutive replies.
            if self.store.claim_ticket(ticket.id, uid):
                self.store.focus_operator(uid, ticket.id, receipt.message_id)

    async def edited_message(self, update, context):
        if self.remember(update):
            await deliver(
                context.bot,
                update.effective_chat.id,
                "Изменение сообщения в Telegram не меняет переписку заказа. Если нужно что-то исправить, пришлите новое сообщение.",
            )

    async def unknown_command(self, update, context):
        if self.remember(update):
            context.user_data.pop("order_search_until", None)
            self.store.clear_input(update.effective_user.id)
            if self.is_admin(update.effective_user.id):
                self.store.release_claim(update.effective_user.id)
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
                "Не удалось завершить действие. Проверьте заказ и переписку перед повторной отправкой.",
                self.recovery_keyboard(
                    self.is_admin(update.effective_chat.id) and not self.client_mode(update.effective_chat.id)
                ),
            )

    async def sync_profile(self, bot):
        fields = (
            ("name", catalog.PROFILE_NAME, bot.get_my_name, bot.set_my_name),
            ("short_description", catalog.SHORT_DESCRIPTION, bot.get_my_short_description, bot.set_my_short_description),
            ("description", catalog.DESCRIPTION, bot.get_my_description, bot.set_my_description),
        )
        for language in ("", "ru"):
            for attribute, expected, read, write in fields:
                current = await read(language_code=language)
                if getattr(current, attribute) != expected:
                    await write(expected, language_code=language)

    async def post_init(self, application):
        webhook = await application.bot.get_webhook_info()
        if webhook.url:
            raise RuntimeError("У бота подключён другой сервис. Отключите его перед запуском polling.")
        self.store.recover_pending()
        # A restarted bot must never retain an invisible recipient or an old send button.
        with self.store.db:
            self.store.db.execute("DELETE FROM operator_focus")
            self.store.db.execute("DELETE FROM input_drafts")
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
        try:
            # Profile rate limits must not delay accepting orders after a restart.
            await asyncio.wait_for(self.sync_profile(application.bot), timeout=15)
        except (TelegramError, TimeoutError) as exc:
            log.warning("Профиль пока не обновлён; бот продолжает запуск: %s", type(exc).__name__)
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
    application.add_handler(TypeHandler(Update, desk.terms_gate), group=-1)
    application.add_handler(
        CommandHandler(
            [
                "start",
                "help",
                "status",
                "cancel",
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
                "order",
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
