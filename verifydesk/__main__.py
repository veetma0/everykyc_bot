import argparse
import fcntl
import logging
import os
from pathlib import Path
import sys

from .config import Config, ConfigurationError
from .deployment import check_storage, DeploymentError
from .store import Store


class SingleInstance:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = (directory / "bot.lock").open("a+")
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError("Этот бот уже работает. Второй экземпляр запускать не нужно.") from None

    def close(self):
        fcntl.flock(self.file, fcntl.LOCK_UN)
        self.file.close()


class PrivateFormatter(logging.Formatter):
    def __init__(self, token):
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self.token = token

    def format(self, record):
        return super().format(record).replace(self.token, "[TOKEN]")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Telegram-бот сопровождения верификации")
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и Telegram без запуска")
    args = parser.parse_args()
    try:
        config = Config.load()
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    handler = logging.StreamHandler()
    handler.setFormatter(PrivateFormatter(config.token))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for name in ("httpx", "httpcore", "telegram"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if args.check:
        import asyncio
        from telegram import Bot

        async def check():
            try:
                async with Bot(config.token) as bot:
                    me = await bot.get_me()
                    webhook = await bot.get_webhook_info()
                    if webhook.url:
                        print("Проверка не пройдена: у бота подключён другой сервис.")
                        return 1
                    print(
                        f"Telegram отвечает. Бот: @{me.username}. Администраторов: {len(config.admin_ids)}."
                    )
                    return 0
            except Exception as exc:
                print(f"Не удалось подключиться к Telegram: {type(exc).__name__}.")
                return 1

        return asyncio.run(check())
    from .bot import build_application

    lock = None
    store = None
    try:
        check_storage(config)
        lock = SingleInstance(config.data_dir)
        store = Store(config.data_dir / "desk.sqlite3")
        application = build_application(config, store)
        application.run_polling(
            allowed_updates=["message", "edited_message", "callback_query"],
            drop_pending_updates=False,
            bootstrap_retries=0,
        )
        return 0
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Запуск остановлен: %s",
            str(exc) if isinstance(exc, (RuntimeError, DeploymentError)) else type(exc).__name__,
        )
        return 1
    finally:
        if store:
            store.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
