"""English copy for trusted text produced by the storefront and operator screens.

Names, amounts, chat messages and notes supplied by people are not translation keys.
The renderer matches the longest source phrase first and preserves surrounding markup.
"""

TRANSLATIONS = {
    # Catalog, service cards and help
    "Каталог услуг": "Service catalog",
    "Каталог": "Catalog",
    "Выберите раздел.": "Choose a category.",
    "Биржи": "Exchanges",
    "Маркетплейсы": "Marketplaces",
    "Кошельки": "Wallets",
    "Telegram и боты": "Telegram and bots",
    "Казино": "Casinos",
    "Другие сервисы": "Other services",
    "Страница {page} из {pages}": "Page {page} of {pages}",
    "На кнопке — стоимость сопровождения. Доступность для вашей страны уточнит оператор.":
        "Each button shows the support fee. An operator will confirm availability in your country.",
    "Предыдущая": "Previous",
    "Следующая": "Next",
    "Верификация": "Verification",
    "Сервис прекратил работу. Открыть новый заказ на верификацию здесь уже нельзя.":
        "This service has shut down. Verification support is no longer available.",
    "Оператор подскажет, как пройти проверку вашего аккаунта, и разберёт текст ошибки.":
        "An operator will guide you through account verification and help explain any error messages.",
    "Стоимость сопровождения": "Support fee",
    "Доступность для вашей страны и условия уточнит оператор до оплаты.":
        "Before you pay, an operator will confirm availability in your country and explain the terms.",
    "Точная стоимость зависит от задачи.": "The final price depends on what you need.",
    "Подписка Claude оплачивается отдельно.": "The Claude subscription is billed separately.",
    "Проверку вы проходите сами на свои данные в официальном сервисе.":
        "Complete verification yourself through the official service using your own details.",
    "Оформляя заказ, подтверждаете, что аккаунт ваш.": "By placing an order, you confirm that the account is yours.",
    "Оформление без списаний.": "You won't be charged when you place the order.",
    "Заказать · от $": "Order from $",
    "Заказать ·": "Order ·",
    " · от $": " from $",
    "от $": "from $",
    "По согласованию": "Price to be agreed",
    "Сопровождение": "Verification support",
    "В каталог": "View catalog",
    "Как это работает": "How it works",
    "Выберите сервис.": "Choose a service.",
    "Узнайте цену в карточке, оформите заказ и напишите свой вопрос.":
        "Check the price on the service page, place an order and send your question.",
    "Согласуйте условия.": "Agree on the terms.",
    "Оператор уточнит вашу страну и задачу.": "An operator will ask about your country and what you need.",
    "После согласования он отправит реквизиты в этот чат.": "Once you agree, the operator will send payment details here.",
    "Получите помощь.": "Get help.",
    "Пришлите чек после оплаты. Когда оператор подтвердит его, он подскажет следующий шаг.":
        "After paying, send your receipt. The operator will check it and explain the next step.",
    "Откройте раздел проверки личности в своём аккаунте и следуйте подсказкам оператора.":
        "Open the identity verification section in your account and follow the operator’s instructions.",
    "Если возникла ошибка, пришлите её текст в этот чат без личных данных.":
        "If you see an error, send its text here with any personal details removed.",
    "Проверку проходите самостоятельно на свои данные в официальном сервисе.":
        "Complete verification yourself through the official service using your own details.",
    "Ссылку KYC, документы, селфи, пароли и коды входа сюда не отправляйте.":
        "Keep verification links, identity documents, selfies, passwords and login codes out of this chat.",
    "Услуга недоступна": "Service unavailable",
    "Выберите другое направление в каталоге.": "Choose another service in the catalog.",
    "Как связаться с оператором?": "How do I contact an operator?",
    "Выберите услугу и оформите заказ. Если заказ уже открыт, просто напишите сюда.":
        "Choose a service and place an order. If you already have an open order, send a message here.",
    "Когда платить?": "When do I pay?",
    "Оператор пришлёт реквизиты, когда вы согласуете задачу, цену и условия.":
        "Once you agree on the work, price and terms, the operator will send payment details.",
    "Куда отправлять документы?": "Where do I send my documents?",
    "Загружайте их только на официальной странице проверки аккаунта. Для разбора ошибки достаточно её текста.":
        "Upload documents only on the service’s official verification page. To get help with an error, send its text.",
    "Помощь с верификацией": "Verification support",
    "Выберите сервис в каталоге или напишите его название в чат. Бот покажет цену и условия.":
        "Choose a service from the catalog or type its name here to see the price and terms.",
    "Новый заказ можно оформить после завершения текущего.": "You can place a new order once your current order is closed.",
    "Главная": "Home",
    "История заказов": "Order history",
    "История": "History",
    "Помощь": "Help",
    "Выбрать услугу": "Choose a service",
    "Мои данные": "My data",
    "Правила": "Terms",
    # Customer order and payment
    "Переписка с оператором": "Operator chat",
    "Сообщения в этой переписке получает оператор. Цены и условия услуг смотрите в каталоге.":
        "Messages in this chat go to an operator. You can find prices and terms in the catalog.",
    "Открыть чат": "Open chat",
    "Продолжить заказ": "Resume order",
    "Откройте заказ, чтобы продолжить переписку с оператором.": "Open your order to continue chatting with the operator.",
    "Заменить чек": "Replace receipt",
    "Откройте заказ и пришлите новый чек.": "Open your order and send a new receipt.",
    "Перейти к оплате": "Go to payment",
    "Откройте оплату, чтобы выбрать сеть USDT или посмотреть реквизиты заказа.":
        "Open payment to choose a USDT network or see your payment details.",
    "Оператор проверяет чек. Ответ придёт в переписку заказа.":
        "The operator is reviewing your receipt and will reply in the order chat.",
    "Ваш заказ": "Your order",
    "Заказ №": "Order #",
    "заказ №": "order #",
    "Переписка №": "Chat #",
    "Опт №": "Wholesale #",
    "Перед оформлением заказа": "Before you order",
    "Проверку вы проходите сами на свои данные.": "Complete verification yourself using your own details.",
    "Документы и селфи — только на официальной странице.":
        "Upload documents and selfies only on the official verification page.",
    "Оператор поможет с шагами и ошибками.": "An operator can explain the steps and help with errors.",
    "Оформляя заказ, вы подтверждаете, что аккаунт ваш. Затем напишите вопрос в этот чат.":
        "By placing an order, you confirm that the account is yours. You can then send your question here.",
    "Оформить заказ": "Place order",
    "Назад": "Back",
    "Выбранная сеть": "Selected network",
    "Ранее открытая переписка с оператором.": "This is your earlier chat with the operator.",
    "Напишите сообщение в этот чат. Оператор ответит здесь.": "Send your message here. The operator will reply in this chat.",
    "Обсуждение завершено. Переписка сохранена.": "This conversation is closed. The messages are saved.",
    "Напишите прямо в этот чат, на каком шаге возник вопрос. Если появилась ошибка, пришлите её текст.":
        "Tell us which step you need help with. If you see an error, send its text here.",
    "Оператор уточнит вашу страну и условия до оплаты.": "Before you pay, the operator will ask about your country and confirm the terms.",
    "Ожидайте сообщения от оператора.": "Wait for the operator’s message.",
    "Он подскажет следующий шаг самостоятельной проверки.": "The operator will explain your next verification step.",
    "Ссылку KYC, документы и коды входа сюда не отправляйте.": "Keep verification links, identity documents and login codes out of this chat.",
    "Оператор ждёт ваш ответ. Напишите его в этом чате.": "The operator is waiting for your reply. Send it here.",
    "Сопровождение завершено. Спасибо за обращение!": "Your support order is complete. Thank you for getting in touch!",
    "Заказ отменён.": "Your order was canceled.",
    "Подтверждение оплаты отправлено оператору. Ожидайте его ответа.":
        "Your proof of payment was sent to the operator. You’ll receive a reply here.",
    "Следующие шаги": "Next steps",
    "Чат и реквизиты": "Chat and payment details",
    "Сменить сеть": "Change network",
    "Выбрать сеть": "Choose network",
    "Отменить заказ": "Cancel order",
    "По предыдущему чеку оператор не смог подтвердить оплату.": "The operator couldn't verify the payment using your previous receipt.",
    "Пришлите новый скриншот, файл или ссылку на чек в этот чат.":
        "Send a new screenshot, file or receipt link here.",
    "Если не знаете, что исправить, уточните у оператора.": "If you're unsure what to change, ask the operator.",
    "Повторно платить без согласования с оператором не нужно.": "Check with the operator before making another payment.",
    "Для оплаты в USDT укажите сеть.": "To pay in USDT, choose a network.",
    "Оператор принял заказ.": "The operator accepted your order.",
    "Дождитесь реквизитов и итоговой суммы в переписке заказа.": "Wait for payment details and the final amount in your order chat.",
    "После оплаты пришлите сюда фото, файл или ссылку на чек.": "After paying, send a receipt photo, file or link here.",
    "Скройте лишние личные данные. Оператор проверит оплату.": "Hide any unnecessary personal details. The operator will verify the payment.",
    "После отправки чека отменить заказ сможет только оператор.": "Once you send a receipt, only the operator can cancel the order.",
    "Выбор сети USDT": "Choose a USDT network",
    "Все сети USDT": "All USDT networks",
    "Другие токены": "Other tokens",
    "Сети USDT": "USDT networks",
    "Сети USDT0": "USDT0 networks",
    "Другие версии токена": "Other token versions",
    "USDT (мост)": "Bridged USDT",
    "Укажите сеть, через которую хотите оплатить заказ.": "Choose the network you’d like to use for payment.",
    "Оператор подтвердит доступность и пришлёт реквизиты в переписке заказа.":
        "The operator will confirm availability and send payment details in your order chat.",
    "Ваш выбор": "Your choice",
    "Сбросить выбор": "Clear selection",
    "К выбору сети": "Network list",
    "К заказу": "Back to order",
    "Выберите сеть для токена USDT0.": "Choose a network for USDT0.",
    "Выберите сеть для мостовой версии токена.": "Choose a network for the bridged token.",
    "Сеть выбрана": "Network selected",
    "Оператор увидит ваш выбор в заказе. Дождитесь подтверждения сети, суммы и адреса в переписке.":
        "The operator can see your choice. Wait for them to confirm the network, amount and address in your order chat.",
    # Statuses, rating and order list
    "Ожидает оператора": "Waiting for an operator",
    "В работе": "In progress",
    "Заказ выполнен": "Order complete",
    "Заказ отменён": "Order canceled",
    "Опт · ожидает оператора": "Wholesale · waiting for an operator",
    "Опт · диалог с оператором": "Wholesale · chatting with an operator",
    "Обсуждение опта завершено": "Wholesale conversation complete",
    "Обсуждение опта закрыто": "Wholesale conversation closed",
    "Нужен другой чек": "New receipt needed",
    "Ожидает оплаты": "Awaiting payment",
    "Проверяем оплату": "Reviewing payment",
    "Как всё прошло?": "How did it go?",
    "Оцените работу от 1 до 5 звёзд. После оценки можно добавить комментарий.":
        "Rate the service from 1 to 5 stars. You can add a comment after you rate it.",
    "Не сейчас": "Not now",
    "спасибо за оценку!": "thanks for your rating!",
    "Напишите комментарий одним сообщением или сохраните оценку без комментария.":
        "Send your comment in one message or save your rating without a comment.",
    "Без комментария": "Skip comment",
    "Заказов пока нет.": "No orders yet.",
    "Здесь появятся завершённые и отменённые заказы.": "Your completed and canceled orders will appear here.",
    "Всего {count}": "{count} total",
    "Переписка об опте": "Wholesale chat",
    "Выберите заказ, чтобы открыть детали и переписку.": "Choose an order to see its details and messages.",
    "Далее": "Next",
    # Operator and message history
    "Кабинет оператора": "Operator dashboard",
    "К ответу:": "Awaiting reply:",
    "💳 Чеки на проверке:": "💳 Receipts to review:",
    "Сначала — чеки, затем заказы в работе и новые обращения.":
        "Receipts come first, followed by orders in progress and new requests.",
    "Следующее обращение": "Next request",
    "Обращения": "Requests",
    "По номеру": "Find by number",
    "Ещё": "More",
    "Дополнительно": "More options",
    "Очередь ответов": "Reply queue",
    "Архив заказов": "Order archive",
    "Клиенты": "Customers",
    "Иконки бирж": "Exchange icons",
    "Предпросмотр": "Preview",
    "Режим клиента": "Customer view",
    "В кабинет": "Dashboard",
    "Кабинет": "Dashboard",
    "Карточка клиента": "Customer profile",
    "Текущий заказ": "Current order",
    "Активных заказов пока нет.": "No open orders.",
    "Всего заказов": "Total orders",
    "Завершено": "Completed",
    "С нами с": "Customer since",
    "Личная заметка · только вам": "Private note · visible only to you",
    "Пока нет.": "None yet.",
    "Открыть заказ": "Open order",
    "Заметка": "Note",
    "К клиентам": "Customers",
    "К клиенту": "Customer profile",
    "Полностью — в переписке.": "Read the full message in the chat.",
    "Объясните клиенту через «Ответить», что нужно исправить в чеке.":
        "Choose “Reply” to tell the customer what needs to change on the receipt.",
    "Отправьте клиенту реквизиты и согласованные условия через «Ответить».":
        "Choose “Reply” to send the customer the payment details and agreed terms.",
    "Принять заказ": "Accept order",
    "Оплата получена": "Payment received",
    "Запросить другой чек": "Request new receipt",
    "Проверить чек": "Review receipt",
    "Ответить": "Reply",
    "Завершить заказ": "Complete order",
    "Завершить обсуждение": "End conversation",
    "Нажмите «Ответить» или ответьте на это сообщение в Telegram.":
        "Choose “Reply” or reply to this message in Telegram.",
    "Переписка": "Chat",
    "Подробнее": "Details",
    "подробности": "details",
    "Следующий": "Next",
    "Клиент": "Customer",
    "Подтверждения оплаты": "Payment receipts",
    "Изменить статус": "Change status",
    "USDT · демо:": "USDT · demo:",
    "сеть выбрана": "network selected",
    "Это тестовый выбор сети, без оплаты.": "This network was selected in a demo. No payment was made.",
    "Ответ отправлен": "Reply sent",
    "Можно продолжать писать этому клиенту в чат.": "You can continue messaging this customer here.",
    "Дополнить": "Add a reply",
    "Telegram не подтвердил доставку: сообщение могло дойти.":
        "Telegram hasn’t confirmed delivery. The message may have reached the customer.",
    "Ответ сохранён. Автоматического повтора не будет.": "The reply was saved and won’t be resent automatically.",
    "Статус:": "Status:",
    "Проверить переписку": "Check chat",
    "Ответ сохранён, но отправить его не удалось.": "Your reply was saved, but it couldn’t be delivered.",
    "Клиент сможет прочитать его в переписке заказа.": "The customer can read it in the order chat.",
    "Начать работу": "Start work",
    "Закрыть обсуждение": "Close conversation",
    "статус": "status",
    "Сейчас:": "Current status:",
    "реквизиты и переписка": "payment details and chat",
    "переписка": "chat",
    "Реквизиты для оплаты оператор отправляет здесь после согласования суммы.":
        "The operator will send the payment details here once you agree on the amount.",
    "последние сообщения": "latest messages",
    "Сообщений пока нет.": "No messages yet.",
    "Вы": "You",
    "Оператор": "Operator",
    "Событие": "Event",
    "доставка в чат не подтверждена": "chat delivery unconfirmed",
    "Раньше": "Earlier",
    "Позже": "Later",
    # Instruction and privacy pages
    "Наша инструкция": "Verification guide",
    "Дождитесь оператора — он объяснит порядок действий.": "Wait for the operator to explain the steps.",
    "Откройте проверку в своём аккаунте на официальном сайте сервиса и проходите её самостоятельно на свои настоящие данные.":
        "Open verification in your own account on the service’s official website and complete it yourself using your real details.",
    "Если возникла ошибка, напишите её текст в этот чат без личных данных.":
        "If you see an error, send the text here with any personal details removed.",
    "Строго следуйте нашей инструкции; вопросы уточняйте у оператора.":
        "Follow these steps and ask the operator if anything is unclear.",
    "Документы и селфи — только на официальной странице проверки.":
        "Upload documents and selfies only on the official verification page.",
    "Подписку Claude вы оплачиваете самостоятельно. Сопровождение не включает её стоимость.":
        "You pay for your Claude subscription separately. The support fee covers guidance only.",
    "Какие данные хранит бот": "What data the bot stores",
    "Telegram ID, имя, username, язык интерфейса, выбранную услугу, сообщения, статусы и заметки оператора.":
        "The bot stores your Telegram ID, name, username, language preference, selected service, messages, order statuses and operator notes.",
    "Переписки по сделке и опту хранятся отдельно.": "Order chats and wholesale conversations are stored separately.",
    "Сохраняются выбранная сеть USDT, выбранная переписка, версия правил, время согласия, оценки и комментарии к отзывам.":
        "It also stores your selected USDT network and chat, the version of the terms you accepted, the time you accepted them, ratings and review comments.",
    "Если вы пришли по ссылке с меткой, сохраняется её источник.": "If you used a tagged link, the bot records its source.",
    "Фото и файлы из переписки передаются оператору.": "Photos and files you send in chat are forwarded to the operator.",
    "Бот сохраняет текст и идентификатор файла Telegram; сам файл на диск не скачивается.":
        "The bot saves the text and Telegram file ID. It does not download the file to disk.",
    "Чеки оператор проверяет вручную.": "An operator checks receipts manually.",
    "Не отправляйте документы для KYC, селфи, ссылки проверки, пароли и коды входа.":
        "Keep identity documents, selfies, verification links, passwords and login codes out of this chat.",
    "Документы для проверки личности направляйте только через официальный интерфейс платформы.":
        "Submit identity documents only through the platform’s official verification page.",
    "Перед отправкой чека закройте лишние личные и платёжные данные.":
        "Before sending a receipt, hide any unnecessary personal and payment details.",
    "Это независимый сервис сопровождения. Решение о проверке принимает соответствующая платформа.":
        "We provide independent support. The platform makes the verification decision.",
    "Если нужно удалить данные из переписки, напишите оператору.": "To request deletion of chat data, contact the operator.",
    # Old orders can retain these system events when reopened in English.
    "Открыто обсуждение опта.": "Wholesale conversation opened.",
    "Заказ создан. Пользователь подтвердил проверку своего аккаунта на собственные данные.":
        "Order created. The customer confirmed that they would verify their own account using their own details.",
    "Оплата подтверждена оператором.": "The operator confirmed the payment.",
    "Оплата не подтверждена. Нужно новое подтверждение.": "Payment could not be verified. A new receipt is needed.",
    "Подтверждение оплаты получено. Ожидает проверки.": "Proof of payment received. Awaiting review.",
}

BUTTON_TRANSLATIONS = {
    "Чат и реквизиты": "Payment chat",
    "Telegram и боты": "Telegram & bots",
    "Выбрать услугу": "Find a service",
    "Запросить другой чек": "Request receipt",
}
