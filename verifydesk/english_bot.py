"""English copy for bot commands, notifications, operator actions and system events."""

TRANSLATIONS: dict[str, str] = {
    # Telegram profile and command menu
    "KYC и верификация · EVERYKYC": "KYC and verification · EVERYKYC",
    "Помощь с верификацией аккаунта в Claude, Bybit, Alipay и других сервисах. Цены и связь с оператором в Telegram.":
        "Get help verifying your Claude, Bybit, Alipay or other account. See prices and chat with an operator in Telegram.",
    "Поможем разобраться с проверкой личности (KYC) в вашем аккаунте.": "Get help with identity verification (KYC) for your account.",
    "Выберите Claude, Bybit, Alipay или другой сервис в каталоге. Стоимость указана в карточке. "
    "Оператор уточнит условия для вашей страны и поможет с вопросами.":
        "Choose Claude, Bybit, Alipay or another service from the catalog to see the price. "
        "An operator will explain the requirements for your country and answer your questions.",
    "Вы проходите проверку сами на официальной площадке. Решение принимает платформа.":
        "You verify your identity yourself on the official platform. The platform makes the final decision.",
    "Нажмите «Начать», чтобы открыть EVERYKYC.": "Tap Start to open EVERYKYC.",
    "Следующий заказ": "Next order",
    "Найти заказ по номеру": "Find an order by number",
    "Текущее меню": "Open the current menu",
    "Перейти в режим клиента": "Switch to customer view",
    "Карточки клиентов": "Customer profiles",
    "Главное меню": "Main menu",
    "Мой заказ": "My order",
    "Обычные кнопки для старых версий Telegram": "Use classic buttons for older Telegram versions",
    "Вернуть новое оформление": "Switch back to the modern layout",
    # Modes, access, stale messages and navigation
    "👀 ПРЕДПРОСМОТР · без создания заказа": "👀 PREVIEW · no order will be placed",
    "👀 ПРЕДПРОСМОТР": "👀 PREVIEW",
    "Режим админа · просмотр клиента": "Admin mode · customer view",
    "В предпросмотре заказы и сообщения не отправляются, выбор не сохраняется.":
        "In preview mode, orders and messages are not sent and selections are not saved.",
    "Сейчас вы в режиме клиента. Для работы с клиентами вернитесь в кабинет оператора.":
        "You’re in customer view. Open the operator dashboard to manage customers.",
    "Сейчас вы в режиме клиента. Для работы с заказами вернитесь в кабинет оператора.":
        "You’re in customer view. Open the operator dashboard to manage orders.",
    "Эта команда доступна только оператору.": "Only operators can use this command.",
    "Доступ к кабинету оператора закрыт.": "Only operators can open the operator dashboard.",
    "Ваш Telegram ID:": "Your Telegram ID:",
    "Теперь сообщения отправляются прямо в чат. Старый черновик не отправлен.":
        "Messages now go straight to the chat. Your old draft was not sent.",
    "Данные обновились. Откройте актуальную карточку или меню.":
        "This view is out of date. Reopen the order or return to the menu.",
    "Отдельные обсуждения опта больше не открываются.": "New wholesale chats are no longer available.",
    "Отменить заказ №{number}?": "Cancel order #{number}?",
    "Переписка останется в истории. При необходимости можно оформить новый заказ.":
        "The conversation will stay in your history. You can place another order if needed.",
    "🔒 После отправки чека самостоятельная отмена закрыта. По этому заказу поможет оператор.":
        "🔒 You’ve already sent a receipt. Ask the operator if you need to cancel this order.",
    "Активных заказов пока нет": "No active orders",
    "Выберите услугу в каталоге.": "Choose a service from the catalog.",
    "Этот заказ недоступен.": "This order is unavailable.",
    "Такой команды нет. Выберите действие ниже.": "Unknown command. Choose an option below.",
    "Не удалось завершить действие. Проверьте заказ и переписку перед повторной отправкой.":
        "The action could not be completed. Check the order and chat before trying again.",
    "На главную": "Home",
    "‹ Главная": "‹ Home",
    "‹ Помощь": "‹ Help",
    "Вернуться к услуге": "Back to service",
    "‹ К заказу": "‹ Order",
    "⬅️ К заказу": "⬅️ Order",
    "❌ Да, отменить": "❌ Yes, cancel",
    "← Назад": "← Back",
    "Далее →": "Next →",
    "Отменить обсуждение": "Cancel conversation",
    "Клиент получит сообщение:": "The customer will be notified:",
    "💬 Открыть и ответить": "💬 Open and reply",
    # Operator workspace and queue
    "🧑‍💻 В кабинет": "🧑‍💻 Dashboard",
    "🧑‍💻 Кабинет оператора": "🧑‍💻 Dashboard",
    "➡️ Следующий заказ": "➡️ Next order",
    "📥 Очередь": "📥 Queue",
    "📥 Проверить очередь": "📥 Check queue",
    "№{number} уже отвечает другой оператор": "Another operator is handling #{number}",
    "Ваше сообщение не отправлено. Возьмите следующее обращение.":
        "Your message was not sent. Open the next request.",
    "📥 Новые обращения в очереди": "📥 New requests in the queue",
    "Сообщения сохранены. Нажмите «➡️ Следующий заказ», чтобы ответить.":
        "Messages saved. Tap “➡️ Next order” to reply.",
    "При большом потоке уведомления объединяются.": "Notifications are grouped when the queue is busy.",
    "Клиент оформил заказ и ждёт ответа.": "The customer has placed an order and is waiting for a reply.",
    "Ответ · ": "Reply · ",
    "Пишите текст, присылайте фото или файл — сообщения сразу уйдут этому клиенту.":
        "Send text, a photo or a file. It goes straight to this customer.",
    "Можно писать несколько сообщений подряд. Для смены получателя откройте другой заказ.":
        "You can send several messages in a row. To reply to someone else, open their order.",
    "Других свободных заказов сейчас нет. Можно вернуться в очередь.":
        "There are no other unassigned orders. You can return to the queue.",
    "Свободных заказов сейчас нет. Заказы с ожиданием оплаты и заказы других операторов доступны в списке.":
        "There are no unassigned orders. The full list includes orders awaiting payment and orders assigned to other operators.",
    "✅ Очередь пуста. Новых обращений, ожидающих ответа, пока нет.":
        "✅ The queue is empty. No new requests are waiting for a reply.",
    "Новый": "New",
    "Ждём ответ": "Awaiting reply",
    "Выполнен": "Completed",
    "Отменён": "Canceled",
    "Диалог": "Chat",
    "Другой чек": "New receipt",
    "Чек": "Receipt",
    "Оплата": "Payment",
    "🆕 Новые": "🆕 New",
    "💳 Чеки": "💳 Receipts",
    "🛠 В работе": "🛠 In progress",
    "⏳ Ждём оплату": "⏳ Awaiting payment",
    "🗂 Завершённые": "🗂 Closed",
    "📋 Все заказы": "📋 All orders",
    "Требуют внимания": "Needs attention",
    "Активные обращения": "Open requests",
    "Новые обращения": "New requests",
    "Проверка оплаты": "Payment review",
    "Заказы в работе": "Orders in progress",
    "Ожидаем оплату или чек": "Awaiting payment or receipt",
    "Завершённые обращения": "Closed requests",
    "Страница {page} из {pages} · Всего {total}": "Page {page} of {pages} · Total {total}",
    "● Новые сообщения · 🔒 Отвечает другой оператор.": "● New messages · 🔒 Another operator is replying.",
    "Здесь пока пусто.": "Nothing here yet.",
    "Заказ не найден.": "Order not found.",
    "Заказ не найден. Введите другой номер, например <b>123</b>.":
        "Order not found. Enter a different number, such as <b>123</b>.",
    "🔎 Найти заказ": "🔎 Find an order",
    "Введите номер, например <b>123</b> или <b>№0123</b>.":
        "Enter an order number, such as <b>123</b> or <b>#0123</b>.",
    "Назад к заказам": "Back to orders",
    " · {count} заказов": " · Orders: {count}",
    "👥 Клиенты · ": "👥 Customers · ",
    "Карточка объединяет обращения, текущий заказ и вашу заметку.":
        "Open a profile to see the customer’s requests, current order and your private note.",
    "Клиенты появятся здесь, когда откроют бота.": "Customers will appear here once they open the bot.",
    "Карточка пока не найдена.": "Customer profile not found.",
    "📝 Приватная заметка · ": "📝 Private note · ",
    "ID клиента:": "Customer ID:",
    "Ответьте на это сообщение. Заметку увидит только оператор; клиенту она не отправляется. "
    "До 1200 символов. Для очистки пришлите минус: −":
        "Reply to this message with a private operator note of up to 1,200 characters. "
        "The customer cannot see it. Send a minus sign (−) to clear the note.",
    "Заметка только для оператора": "Private operator note",
    "Сократите заметку до 1200 символов и ответьте на то же приглашение.":
        "Shorten the note to 1,200 characters and reply to the same prompt.",
    "Отзыв клиента": "Customer review",
    # Order notifications, receipts and media relays
    "📎 Сообщение от ": "📎 Message from ",
    " · сообщение</b>": " · message</b>",
    "Показать вложение": "Show attachment",
    "‹ Переписка": "‹ Chat",
    "💬 Переписка": "💬 Chat",
    "Вложение не удалось показать. Откройте сообщение ещё раз, чтобы повторить загрузку.":
        "The attachment could not be loaded. Reopen the message to try again.",
    "Вложение доступно в обычном режиме заказа.": "Open the order outside preview mode to see the attachment.",
    "…Полный текст — в переписке.": "…The full message is in the chat.",
    "Ответьте на это сообщение в Telegram или выберите переписку на главной.":
        "Reply to this message in Telegram or select a conversation from the home screen.",
    "Чтобы ответить в эту переписку, используйте «Ответить» в Telegram или откройте её на главной.":
        "Use Telegram’s Reply action or open this conversation from the home screen.",
    "💬 Пишите прямо сюда. Сообщения уйдут в эту переписку.": "💬 Reply here to send a message to this conversation.",
    "🧾 Подтверждение · заказ №{number}": "🧾 Receipt · order #{number}",
    "🔎 Проверка оплаты · заказ №{number}": "🔎 Payment review · order #{number}",
    "Подтверждение {current} из {total}": "Receipt {current} of {total}",
    "Проверьте подтверждение. Только после вашего решения заказ перейдёт в работу.":
        "Check the receipt. The order moves to In progress when you confirm payment.",
    "⚠️ Скриншот не загрузился. Откройте проверку ещё раз, чтобы увидеть его.":
        "⚠️ The screenshot could not be loaded. Reopen the payment review to see it.",
    "🔄 Показать скриншот": "🔄 Show screenshot",
    "🧾 Подтверждение оплаты пока не прислано.": "🧾 The customer has not sent a receipt yet.",
    "✅ Оплата получена": "✅ Payment received",
    "↩️ Запросить другой чек": "↩️ Request new receipt",
    "← Раньше": "← Earlier",
    "К последнему →": "Latest →",
    "⚠️ Доставка уведомления об оплате не подтверждена. Статус сохранён в заказе.":
        "⚠️ The payment status was saved, but delivery of the notification could not be confirmed.",
    "↩️ Оператор попросил другое подтверждение. Пришлите новый скриншот или ссылку на чек.":
        "↩️ The operator requested a new receipt. Send a new screenshot or a link to the receipt.",
    "✅ Оплата подтверждена. Ожидайте сообщения от оператора.":
        "✅ Payment confirmed. The operator will message you here.",
    "⚠️ Статус сохранён. Доставка уведомления клиенту не подтверждена.":
        "⚠️ The status was saved, but delivery of the customer notification could not be confirmed.",
    "Подтверждение сохранено для проверки оператором.": "Receipt saved for the operator to review.",
    "Сообщение сохранено. Оператор ответит здесь.": "Message saved. The operator will reply here.",
    "📷 Фото": "📷 Photo",
    "📎 Файл": "📎 File",
    # Order chat, reviews and recovery
    "Пришлите текст, фото или файл.": "Send a text message, photo or file.",
    "Разделите сообщение на части до {limit} символов.": "Split your message into parts of up to {limit} characters.",
    "Пришлите файл размером до 20 МБ.": "Send a file no larger than 20 MB.",
    "🔒 <b>Ссылку проверки не отправляйте.</b>\nПроверку проходите самостоятельно. Опишите ошибку без документов и кодов входа.":
        "🔒 <b>Keep your verification link private.</b>\nComplete verification yourself. "
        "Describe the error without sharing identity documents or login codes.",
    "Вы в режиме клиента. Ответ на сообщение из кабинета оператора не отправлен.":
        "You’re in customer view. Your reply to the operator dashboard message was not sent.",
    "💛 Спасибо! Оценка и комментарий сохранены.": "💛 Thank you! Your rating and comment were saved.",
    "💛 Спасибо за оценку!": "💛 Thank you for your rating!",
    "💛 Ваш отзыв уже сохранён.": "💛 Your review has already been saved.",
    "Этот отзыв уже сохранён. Откройте нужную переписку из меню.":
        "This review has already been saved. Open the conversation you need from the menu.",
    "Напишите комментарий текстом до 1200 символов или сохраните только оценку.":
        "Enter a comment of up to 1,200 characters or save just your rating.",
    "Эта переписка уже закрыта или недоступна. Сообщение не отправлено.":
        "This conversation is closed or unavailable. Your message was not sent.",
    "Выберите переписку, затем отправьте сообщение ещё раз.": "Choose a conversation, then send your message again.",
    "Сообщение оператору не отправлено. Сначала оформите заказ.": "Your message was not sent. Place an order first to contact an operator.",
    "Сообщение пока не отправлено. Выберите заказ и нажмите «Ответить».":
        "Your message was not sent. Choose an order and tap Reply.",
    "Заказ №{number} закрыт. Ответ клиенту не отправлен.": "Order #{number} is closed. Your reply was not sent to the customer.",
    "Переписка №{number} обновилась": "Conversation #{number} has changed",
    "Другой оператор уже отправил ответ. Ваше сообщение не отправлено.":
        "Another operator has already replied. Your message was not sent.",
    "Откройте актуальную переписку перед следующим ответом.": "Reopen the conversation before replying again.",
    "Изменение сообщения в Telegram не меняет переписку заказа. Если нужно что-то исправить, пришлите новое сообщение.":
        "Editing a Telegram message does not change the saved conversation. To correct something, send a new message.",
    # Stored system events remain readable in either language.
    "💳 Ожидает оплаты. Оператор принял заказ.": "💳 Awaiting payment. The operator accepted the order.",
    "🔎 Подтверждение оплаты получено. Ожидает проверки.": "🔎 Receipt received. Awaiting review.",
    "✅ Оплата подтверждена оператором. 🛠 В работе.": "✅ The operator confirmed payment. 🛠 In progress.",
    "💳 Оплата не подтверждена. Нужно новое подтверждение.": "💳 Payment could not be confirmed. A new receipt is needed.",
    # Source report
    "Источники заявок": "Request sources",
    "За всё время · запуски с меткой. Входы операторов исключены.":
        "All time · starts from tagged links. Operator activity is excluded.",
    "Запусков с распознанной меткой пока нет.": "No one has started the bot with a recognized tag yet.",
    "Публикации в Telegram": "Telegram posts",
    "Ссылка в профиле": "Profile link",
    "Страница о Claude": "Claude page",
    "Страница об Alipay": "Alipay page",
    "Партнёрская ссылка": "Partner link",
    "Запустили: {started} · С заявкой: {requested} · Заявок: {tickets}":
        "Started the bot: {started} · Made a request: {requested} · Requests: {tickets}",
    "Запуски и клиенты считаются по людям, заявки — по обращениям.":
        "Starts and customers count unique people. Requests count individual submissions.",
    "Учитывается первая распознанная метка. Старые заявки не приписываются новой ссылке.":
        "The first recognized tag is used. A new link does not change the source of earlier requests.",
    "Это не просмотры, позиции в поиске или оплаты. Непомеченные входы здесь не учтены.":
        "This report excludes untagged starts and does not track views, search rankings or payments.",
    # Operator theme checks, including the Telegram probe message.
    "Оформление ": "Appearance · ",
    "Для премиум-эмодзи Telegram требует Premium у владельца бота или дополнительный username на Fragment. "
    "Основные кнопки работают и без них.":
        "To display premium emoji, Telegram requires the bot owner to have Premium or an additional username on Fragment. "
        "The buttons also work without premium emoji.",
    "Иконки бирж · GentleeChron": "Exchange icons · GentleeChron",
    "Проверяем, поддерживает ли Telegram иконки на кнопках этого бота. Названия бирж остаются видны в любом случае.":
        "Checking whether Telegram supports icons on this bot’s buttons. Exchange names are always visible.",
    "Иконки бирж в GentleeChron не найдены. Оставлены обычные подписи.":
        "No exchange icons were found in GentleeChron. The buttons will keep their text labels.",
    "Иконки бирж включены: {count}.": "Exchange icons enabled: {count}.",
    "Telegram не подтвердил премиум-эмодзи. Оставлены обычные символы.":
        "Telegram did not confirm premium emoji support. Standard symbols will be used.",
    "Telegram отклонил премиум-эмодзи. Используется обычное оформление.":
        "Telegram rejected the premium emoji. Standard formatting will be used.",
    "Telegram не подтвердил проверку оформления. Повтор автоматически не отправляется.":
        "Telegram did not confirm the appearance check. It will not be retried automatically.",
    "Премиум-эмодзи сейчас недоступны. Используется обычное оформление.":
        "Premium emoji are currently unavailable. Standard formatting will be used.",
}

BUTTON_TRANSLATIONS = {
    "🔄 Показать скриншот": "🔄 Retry image",
    "✅ Оплата получена": "✅ Mark as paid",
    "↩️ Запросить другой чек": "↩️ Request receipt",
}
