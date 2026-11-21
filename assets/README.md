# Оформление EVERYKYC

## Комплект от 21 ноября 2026 года

Графитовый фон, светлая типографика и бирюзовая рамка сканирования объединяют профиль и меню. В каталоге у каждого раздела свой предметный образ. Цена и действия отображаются обычными элементами Telegram.

| Файл | Размер | Где используется |
| --- | --- | --- |
| [Аватар](showcase/avatar.jpg) | 800 × 800 | Монограмма для круглого фото профиля |
| [Обложка профиля](showcase/welcome.jpg) | 640 × 360 | Изображение приветствия до первого запуска |
| [Главная](showcase/home.jpg) | 1120 × 500 | Главная после принятия правил |
| [Каталог](showcase/catalog.jpg) | 1120 × 450 | Выбор раздела или быстрого предложения |
| [Биржи](showcase/exchanges.jpg) · [Маркетплейсы](showcase/marketplaces.jpg) · [Кошельки](showcase/wallets.jpg) | 1120 × 450 | Раздел и карточки его сервисов |
| [Telegram и боты](showcase/telegram.jpg) · [Казино](showcase/casinos.jpg) · [Другие сервисы](showcase/other.jpg) | 1120 × 450 | Раздел и карточки его сервисов |
| [Мои заказы](showcase/profile.jpg) · [Помощь](showcase/help.jpg) | 1120 × 450 | Короткие карточки заказа и справки |

Бот выбирает обложку по открытому разделу и длине подписи. Полные правила, длинная переписка и файлы клиентов сохраняют собственный формат. [Выбор обложек в приложении](../verifydesk/media.py) · [Все обложки разделов](../artifacts/showcase.jpg).

### Как создавалась серия

Исходники сгенерированы в ImageGen по аватару и баннеру EVERYKYC от 6 ноября. Для портрета использовалось задание «человек строго со спины справа, чёрная техническая куртка, графитовая студия, тонкий ледяной контур вокруг головы, слева EVERYKYC и Помощь с верификацией». Для аватара — «сохранить силуэт двух полос и угловой галочки, матовая светлая керамика, четыре бирюзовых уголка на графите, фронтально, с полями для круглого кадрирования».

Предметные кадры сгенерированы единой сеткой 3 × 3 с одинаковым студийным светом. Карты, металлические стрелки, корзина, кожаный кошелёк, сложенный самолёт, игральные кости, модульный куб, папка и гарнитура соответствуют девяти разделам. Каждый кадр получил отдельный заголовок шрифтом Inter при экспорте.

## Архив EVERYKYC от 6 ноября 2026 года

Файлы `everykyc-avatar.*`, `everykyc-banner.png` и `everykyc-welcome-640x360.png` относятся к прошлому комплекту. Описание его производства сохранено рядом. [Промпт аватара](everykyc-avatar-prompt.md) · [Промпт баннера](everykyc-banner-prompt.md).

## Архив бренда «Эврикус»

Ниже описана прежняя версия; её публикация не подтверждает публикацию нового оформления.

Создано встроенным Imagegen по двум визуальным референсам владельца. Референсы использованы для фактуры и палитры; знак создан заново. Отдельная проверка товарных знаков не выполнялась.

## Файлы

- `evrikus-avatar.png` — квадратный исходник логотипа.
- `evrikus-avatar.jpg` — аватар для Telegram; опубликован через Telegram Bot API.
- `evrikus-banner.png` — исходный широкий баннер.
- `evrikus-welcome-640x360.png` — баннер для BotFather, 640×360.

Концепция: рамка сканирования, три штриха и отметка проверки; ледяное бело-бирюзовое свечение с зернистостью на чёрном фоне. Логотип и баннер используют один знак и фактуру. Это собственная марка сервиса сопровождения, не официальный значок платформы.

Баннер опубликован через официальный BotFather Mini App и проверен после повторного открытия. Скриншот подтверждения: `telegram-brand-published.png`.

## Промпт логотипа

Use case: logo-brand. Create ONE finished square Telegram avatar / brand logo for Эврикус, a service guiding owners through identity verification (KYC) of their own accounts. The two attached images are STYLE REFERENCES ONLY: black negative space, luminous icy aqua-white phosphor grain, subtle cobalt fringes and tactile analog CRT bloom. Do not copy their lettering or emblem. Invent an original compact geometric monogram: a custom Cyrillic Э implied by an open rounded scanning frame with three bold horizontal strokes, whose lower stroke resolves into a subtle checkmark. Unify identity scan + confirmation into ONE simple emblem, not a collection of icons. Strong distinctive silhouette recognizable at 48 px. Centered at about 62% of square with generous black margins for Telegram circular crop. Dense bright core, restrained aqua halo, fine granular edges, slightly imperfect optical texture, crisp silhouette, pure black background. It should feel experimental premium graphic design, no glossy 3D chrome, no gradients across backdrop, no padlocks, shields, fingerprints, human faces, passport documents, no stars, no particles outside halo, no extra text, no watermark. Output only the clean final avatar artwork, square 1024 by 1024 if possible.

## Промпт баннера

Use case: logo-brand. Produce ONE final landscape Telegram bot profile banner for Russian KYC guidance brand «Эврикус». The attached image is the newly approved original emblem: preserve its exact distinctive scan-frame + three bars + checkmark silhouette, black backdrop and icy aqua white granular phosphor with tiny cobalt fringes. Make a matching finished banner, 16:9 composition, ideally 1280x720. Place that same emblem on the left, about 29% canvas width; on the right large tall condensed custom Cyrillic typography reading exactly «ЭВРИКУС» (Э В Р И К У С), and beneath in smaller clean highly legible Cyrillic «ПОМОЩЬ С KYC». Only these two text strings, no other text. Pure black background, bold icy cyan/white luminous type with restrained analog grain inspired by the emblem; no chrome, no glossy 3D objects, no borders, no fake UI, no prices, no claims of official partnership, no extra decorative elements. Spacious balanced editorial layout, generous 8% safe margins on every edge, logo and wordmark fully visible and readable at 640×360. Same brand system and phosphor texture across logo and lettering. Do not redraw logo into a different symbol. Output artwork only, no mockup.
