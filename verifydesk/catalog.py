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


OFFERS = {
    ("claude", "armenia"): Offer(
        "claude",
        "armenia",
        "Claude · Армения",
        "Поможем пройти KYC своего аккаунта: разобраться в шагах и ошибках. Для проживающих в Армении.",
        "35.00",
    ),
    ("claude", "europe"): Offer(
        "claude",
        "europe",
        "Claude · Европа",
        "Поможем разобраться в KYC своего аккаунта. Страну и доступность проверит оператор до начала работы.",
        "50.00",
    ),
}

# Keep old records readable; these services cannot receive new requests.
RETIRED_SERVICES = {"alipay": "Alipay", "chatgpt": "ChatGPT", "gemini": "Gemini"}


def offer(service: str, plan: str) -> Offer:
    return OFFERS[(service, plan)]


def service_title(service: str, plan: str):
    found = OFFERS.get((service, plan))
    return found.title if found else {"claude": "Claude", **RETIRED_SERVICES}.get(service, "Сопровождение")


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

PROFILE_NAME = "Эврикус · KYC Claude"
SHORT_DESCRIPTION = (
    "Помощь с проверкой личности в своём аккаунте Claude. Инструкции и оператор — в одном чате."
)
DESCRIPTION = (
    "Помогаем разобраться с KYC — проверкой личности в своём аккаунте Claude.\n\n"
    "Выберите условия сопровождения → создайте заявку → дождитесь ответа оператора здесь.\n\n"
    "Проверку вы проходите самостоятельно на свои данные. Решение принимает Claude.\n\n"
    "Нажмите «Начать» 👇"
)
