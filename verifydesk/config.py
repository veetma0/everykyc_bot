from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import os
import re

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent.parent


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: tuple[int, ...]
    data_dir: Path
    title: str = "Эврикус"
    timezone: str = "Asia/Amman"

    @classmethod
    def load(cls, env_file: Path | None = None):
        env_file = env_file or PROJECT_DIR / ".env"
        load_dotenv(env_file, override=False)
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{30,}", token):
            raise ConfigurationError("Добавьте токен BotFather в BOT_TOKEN в файле .env.")
        try:
            admins = tuple(
                dict.fromkeys(int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip())
            )
        except ValueError as exc:
            raise ConfigurationError(
                "ADMIN_IDS должен содержать числовые Telegram ID через запятую."
            ) from exc
        if not admins or any(x <= 0 for x in admins):
            raise ConfigurationError("Укажите свой положительный числовой Telegram ID в ADMIN_IDS.")
        timezone = os.environ.get("BOT_TIMEZONE", "Asia/Amman")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError("Неизвестный часовой пояс BOT_TIMEZONE.") from exc
        data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        if not data_dir.is_absolute():
            data_dir = env_file.parent / data_dir
        title = os.environ.get("BOT_TITLE", "Эврикус").strip()
        if not 1 <= len(title) <= 64:
            raise ConfigurationError("Название BOT_TITLE должно содержать от 1 до 64 символов.")
        return cls(token, admins, data_dir.resolve(), title, timezone)
