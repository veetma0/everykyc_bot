# Telegram и демонстрационный USDT · 25 октября 2026

## Оформление

В установленной библиотеке **python-telegram-bot 22.8** есть `Bot.set_my_profile_photo` и `InputProfilePhotoStatic`. Аватар можно загрузить токеном; статическое изображение должно быть JPG. Метода `setMyDescriptionPhoto` в текущем Bot API нет. Для баннера описания официальный путь — **@BotFather → /mybots → бот → Edit Bot → Edit Description Picture**. Подготовить файл 640×360 и сверить требование с ответом BotFather. Это отдельное действие от смены аватара. [Bot API](https://core.telegram.org/bots/api#setmyprofilephoto), [описание и медиа бота](https://core.telegram.org/bots/features#about-text-description-and-profile-media).

Официальная альтернатива — [BotFather Mini App](https://t.me/botfather?startapp), прямо связанная со страницы Telegram Features. Путь в текущем интерфейсе: **выбрать бота → Edit Info → Set Welcome Picture → загрузить → Update**; он описан в [официальном репозитории Telegram Desktop](https://github.com/telegramdesktop/tdesktop/issues/31444). Команда `/setdescriptionpic` встречается в сторонних руководствах, но не подтверждена публичной документацией Telegram: актуальный список нужно смотреть через ввод `/` у самого BotFather. Подтверждённой официальной клавиатурной комбинации для нажатия inline callback-кнопок не найдено.

Премиум-эмодзи в прямых сообщениях и `icon_custom_emoji_id` в кнопках доступны, если **владелец бота** имеет Telegram Premium либо у бота куплен дополнительный username на Fragment. `User.is_premium` администратора не доказывает владение ботом. Флага `can_send_custom_emoji` в `getMe` нет. [Ограничения и формат](https://core.telegram.org/bots/api#formatting-options).

Для иконок используйте данные, возвращённые официальным `getForumTopicIconStickers`: выбрать по `.emoji` подходящие ⚡, 💎, 💡 и взять `.custom_emoji_id`. Конкретный публичный пример в документации — `5368324170671202286` для 👍. Можно также получить ID из присланных владельцем `MessageEntity` и проверить `getCustomEmojiStickers`. [Иконки Telegram](https://core.telegram.org/bots/api#getforumtopiciconstickers).

Проверка возможности — одно превью оператору с последующим контролем `custom_emoji` в возвращённых entities. Альтернативный символ должен совпадать с `Sticker.emoji`, иначе сервер может проигнорировать entity. При подтверждённом отказе использовать обычный Unicode; при неопределённой сетевой ошибке сообщение автоматически не повторять. [Поведение custom emoji](https://core.telegram.org/api/custom-emoji).

## USDT — только демонстрация

Telegram требует Stars для продажи цифровых товаров и услуг внутри ботов и прямо исключает криптовалюту вместо Stars. Демонстрационный выбор USDT не должен создавать реальный счёт, адрес, QR, платёж или статус «оплачено». Перед включением реальной оплаты определить применимость правил к конкретной услуге. [Правила цифровых платежей](https://core.telegram.org/bots/payments-stars#can-i-accept-payment-in-cryptocurrency-instead-of-telegram-stars).

Страница Tether содержит разные активы: **BNB Smart Chain там сейчас приведена для XAU₮**, поэтому её нельзя автоматически считать прямой сетью USD₮. Ниже перечислены записи именно USD₮. Старые сети на той же странице оставлены для истории. [Протоколы Tether](https://tether.to/en/supported-protocols/).

```python
TETHER_USDT = (
    ('ethereum', 'Ethereum · ERC-20'), ('tron', 'Tron · TRC-20'),
    ('avalanche', 'Avalanche C-Chain'), ('kava', 'Kava / Cosmos'),
    ('celo', 'Celo'), ('kaia', 'Kaia'), ('liquid', 'Liquid'),
    ('solana', 'Solana · SPL'), ('polkadot', 'Polkadot AssetHub'),
    ('tezos', 'Tezos'), ('near', 'NEAR'), ('ton', 'TON · Jetton'),
    ('aptos', 'Aptos'),
)
HISTORICAL = ('kusama', 'bitcoin_cash_slp', 'omni', 'eos', 'algorand')
```

USDT0 следует показывать отдельной категорией, сохраняя название варианта токена. Текущая официальная страница содержит 24 записи, включая Ethereum как канонический adapter/lockbox; Ethereum не нужно дублировать как отдельный USDT0-токен. [Развёртывания USDT0](https://docs.usdt0.to/technical-documentation/deployments).

```python
USDT0_NETWORKS = (
    'arbitrum', 'berachain', 'conflux', 'flare', 'hypercore', 'hyperevm',
    'hedera', 'ink', 'iota', 'mantle', 'megaeth', 'monad', 'morph',
    'optimism', 'plasma', 'polygon', 'rootstock', 'sei', 'stable',
    'stellar', 'tempo', 'unichain', 'xlayer',
)
```

Это каталог демонстрационных вариантов, а не обещание поддержки переводов. В основном экране достаточно трёх распространённых сетей и кнопки «Все сети» с пагинацией. Исторические варианты не должны выглядеть доступным способом оплаты.

## Доступность сервисов

Армения есть в официальном списке доступности Claude. «Европа» не является отдельным разрешением: доступность нужно сверять по конкретной стране. Указанные владельцем $35/$50 — цена сопровождения, не тариф Claude. [Список стран](https://support.claude.com/en/articles/8461763-where-can-i-access-claude).

Для Alipay официальная инструкция описывает выбор региона, персональные сведения и проверку документа/лица в самом Alipay. Она не подтверждает одинаковые требования для всех стран и не определяет цену сопровождения. Точный текущий сценарий следует читать в приложении пользователя; документы в Telegram-бот не собирать. [Официальная справка Alipay](https://cschannel.alipay.com/mobile/helpDetail.htm?help_id=215132).
