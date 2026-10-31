"""Service offers and non-payable payment previews. No wallet addresses or invoices."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Offer:
    service: str
    plan: str
    title: str
    detail: str
    price_usd: str | None = None
    demo: bool = False
    category: str = "other"
    price_from: bool = False
    available: bool = True


CATEGORIES = {
    "exchanges": "📈 Биржи",
    "marketplaces": "🛒 Маркетплейсы",
    "wallets": "👛 Кошельки",
    "telegram": "✈️ Telegram и боты",
    "casinos": "🎰 Казино",
    "other": "✨ Прочее",
}

# Prices supplied by the owner, including the requested $20 increase.
_SERVICE_ROWS = {
    "exchanges": (
        ("bybit", "Bybit", 50), ("kraken", "Kraken", 45),
        ("whitebit", "WhiteBIT", 45), ("mexc", "MEXC", 45),
        ("bitget", "Bitget", 45), ("okx", "OKX", 45),
        ("kucoin", "KuCoin", 45), ("bingx", "BingX", 45),
        ("s1lkpay", "S1LKPAY", 60), ("paxful", "Paxful", 45),
        ("coinlist", "CoinList", 50), ("htx", "HTX (Huobi)", 45),
        ("bitpapa", "Bitpapa", 45), ("okcoin", "OKCoin", 45),
        ("gate", "Gate.io", 45), ("crypto_com", "Crypto.com", 45),
        ("localbitcoins", "LocalBitcoins", 45), ("garantex", "Garantex", 40),
        ("in1", "IN1", 65),
    ),
    "marketplaces": (
        ("eldorado", "Eldorado", 80), ("g2g_skrill", "G2G + Skrill", 70),
        ("igvault", "IGVault", 45), ("z2u", "Z2u", 45),
        ("u7buy", "U7Buy", 45), ("g2g", "G2G", 45),
    ),
    "wallets": (
        ("alipay", "Alipay", 50), ("webmoney", "WebMoney", 50),
        ("advcash", "Advcash", 70), ("lava", "Lava", 70),
    ),
    "telegram": (
        ("fragment", "Telegram Fragment", 45), ("telegram_wallet", "Telegram Wallet", 45),
        ("cryptobot", "Cryptobot", 45),
    ),
    "casinos": (
        ("stake", "Stake", 40), ("bcgame", "BC GAME", 45),
        ("megadice", "MEGADICE", 45), ("mellstroy", "MELLSTROY", 45),
        ("cloudbet", "CLOUDBET", 45), ("dragon_money", "DRAGON MONEY", 45),
        ("pm_by", "PM BY", 45), ("1win", "1WIN", 45), ("luckybird", "LUCKYBIRD", 45),
    ),
    "other": (
        ("claude", "Claude AI", 45), ("hetzner", "Hetzner", 100),
        ("fansly", "Fansly", 60), ("webshare", "Webshare", 45),
        ("soax", "Soax", 50), ("fanvue", "Fanvue", 60),
        ("iproyal", "IPRoyal", 45), ("astroproxy", "AstroProxy", 45),
        ("openloot", "OPENLOOT", 40), ("lis_skins", "Lis-skins", 45),
        ("csfloat", "CSFloat", 45), ("cs_money", "CS Money", 45),
        ("csgo_roll", "CSGO Roll", 45), ("clash_gg", "Clash.gg", 45),
        ("rain_gg", "Rain.gg", 45), ("roblox", "Roblox", 45), ("faceit", "FACEIT", 35),
    ),
}

OFFERS = {
    (code, "standard"): Offer(
        code, "standard", title,
        "Поможем разобраться в шагах и ошибках проверки вашего аккаунта.",
        f"{price:.2f}", category=category, price_from=code == "eldorado",
        available=code != "localbitcoins",
    )
    for category, rows in _SERVICE_ROWS.items()
    for code, title, price in rows
}
RETIRED_SERVICES = {"chatgpt": "ChatGPT", "gemini": "Gemini"}
HISTORICAL_TITLES = {("claude", "armenia"): "Claude", ("claude", "europe"): "Claude"}


def offer(service: str, plan: str) -> Offer:
    return OFFERS[(service, plan)]


def service_title(service: str, plan: str):
    historical = HISTORICAL_TITLES.get((service, plan))
    found = OFFERS.get((service, plan)) or OFFERS.get((service, "standard"))
    return historical or (found.title if found else RETIRED_SERVICES.get(service, "Сопровождение"))


def offer_price(selected: Offer):
    return ("от " if selected.price_from else "") + dollars(selected.price_usd)


def dollars(value: str | None):
    if value is None:
        return "По согласованию"
    number = Decimal(value)
    rendered = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"${rendered}"


@dataclass(frozen=True)
class Network:
    code: str
    title: str
    group: str


NETWORKS = (
    tuple(
        Network(f"usdt_{slug}", title, "usdt")
        for slug, title in (
            ("tron", "TRON · TRC20"),
            ("ethereum", "Ethereum · ERC20"),
            ("ton", "TON"),
            ("solana", "Solana"),
            ("avalanche", "Avalanche C-Chain"),
            ("aptos", "Aptos"),
            ("celo", "Celo"),
            ("kaia", "Kaia"),
            ("kava", "Kava"),
            ("liquid", "Liquid"),
            ("near", "NEAR"),
            ("polkadot", "Polkadot Asset Hub"),
            ("tezos", "Tezos"),
        )
    )
    + tuple(
        Network(f"usdt0_{slug}", title, "usdt0")
        for slug, title in (
            ("arbitrum", "Arbitrum"),
            ("berachain", "Berachain"),
            ("conflux", "Conflux"),
            ("flare", "Flare"),
            ("hypercore", "HyperCore"),
            ("hyperevm", "HyperEVM"),
            ("hedera", "Hedera"),
            ("ink", "Ink"),
            ("iota", "IOTA"),
            ("mantle", "Mantle"),
            ("megaeth", "MegaETH"),
            ("monad", "Monad"),
            ("morph", "Morph"),
            ("optimism", "Optimism"),
            ("plasma", "Plasma"),
            ("polygon", "Polygon"),
            ("rootstock", "Rootstock"),
            ("sei", "Sei"),
            ("stable", "Stable"),
            ("stellar", "Stellar"),
            ("tempo", "Tempo"),
            ("unichain", "Unichain"),
            ("xlayer", "X Layer"),
        )
    )
    + (Network("bridged_bnb", "BNB Smart Chain · BEP20", "bridged"),)
)
NETWORK_BY_CODE = {network.code: network for network in NETWORKS}
NETWORK_GROUPS = {"usdt": "USD₮ · прямой выпуск", "usdt0": "USDT0", "bridged": "Другие версии токена"}

PROFILE_NAME = "Эврикус · помощь с верификацией"
SHORT_DESCRIPTION = "Помощь с верификацией: биржи, кошельки, Alipay, Claude и другие сервисы. Оператор в этом чате."
DESCRIPTION = (
    "Помогаем с верификацией своего аккаунта: биржи, маркетплейсы, кошельки, Telegram, казино и другие сервисы.\n\n"
    "Ознакомьтесь с правилами → выберите услугу → оформите заказ.\n\n"
    "Гео уточняйте у оператора. Проверку вы проходите самостоятельно на свои данные. "
    "Решение принимает соответствующая платформа.\n\n"
    "Нажмите «Начать» 👇"
)
