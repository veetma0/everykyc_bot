import json
from itertools import count
from types import SimpleNamespace

import pytest
from telegram import Update
from telegram.request import BaseRequest

from verifydesk.bot import build_application
from verifydesk import catalog
from verifydesk.config import Config
from verifydesk.store import Store


ADMIN = 9001
CLIENT = 101
OTHER = 102
TOKEN = "123456:abcdefghijklmnopqrstuvwxyz0123456789ABCDE"
BOT_USER = {"id": 123456, "is_bot": True, "first_name": "Test", "username": "test_verify_bot"}


class FakeTelegram(BaseRequest):
    def __init__(self):
        self.calls = []
        self.ids = count(1000)
        self.fail_chat = None
        self.fail_error = None
        self.webhook = False

    async def initialize(self):
        pass

    async def shutdown(self):
        pass

    @property
    def read_timeout(self):
        return 5

    async def do_request(self, url, method, request_data=None, **kwargs):
        name = url.rsplit("/", 1)[-1]
        params = request_data.parameters if request_data else {}
        self.calls.append((name, params))
        if name == "getMe":
            result = BOT_USER
        elif name == "getMyName":
            result = {"name": catalog.PROFILE_NAME}
        elif name == "getMyShortDescription":
            result = {"short_description": catalog.SHORT_DESCRIPTION}
        elif name == "getMyDescription":
            result = {"description": catalog.DESCRIPTION}
        elif name == "getWebhookInfo":
            result = {
                "url": "https://example.org" if self.webhook else "",
                "has_custom_certificate": False,
                "pending_update_count": 0,
            }
        elif name in {"sendMessage", "editMessageText", "sendPhoto", "sendDocument"}:
            if self.fail_chat == params["chat_id"] and self.fail_error:
                raise self.fail_error
            result = {
                "message_id": params.get("message_id", next(self.ids)),
                "date": 1700000000,
                "chat": {"id": params["chat_id"], "type": "private", "first_name": "Test"},
                "from": BOT_USER,
                "text": params.get("text", params.get("caption", "")),
            }
            if "inline_keyboard" in params.get("reply_markup", {}):
                result["reply_markup"] = params["reply_markup"]
        else:
            result = True
        return 200, json.dumps({"ok": True, "result": result}).encode()


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "desk.sqlite3")
    yield result
    result.close()


@pytest.fixture
async def env(store, tmp_path):
    request = FakeTelegram()
    config = Config(TOKEN, (ADMIN,), tmp_path)
    app = build_application(config, store, request=request)
    errors = []

    async def collect_error(update, context):
        errors.append(context.error)

    app.add_error_handler(collect_error)
    await app.initialize()
    ids = count(1)

    async def message(
        uid, text=None, reply_to=None, photo=False, edited=False, message_id=None, chat_type="private",
        caption=None, document=None,
    ):
        user = {"id": uid, "is_bot": False, "first_name": f"Клиент {uid}", "username": f"user{uid}"}
        number = next(ids)
        data = {
            "message_id": message_id or number,
            "date": 1700000000,
            "from": user,
            "chat": {"id": uid, "type": chat_type, "first_name": "Test"},
        }
        if text is not None:
            data["text"] = text
            if text.startswith("/"):
                data["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        if reply_to:
            data["reply_to_message"] = {
                "message_id": reply_to,
                "date": 1700000000,
                "chat": data["chat"],
                "from": BOT_USER,
                "text": "Карточка",
            }
        if photo:
            data["photo"] = [
                {"file_id": "secret_document", "file_unique_id": "unique", "width": 400, "height": 400}
            ]
        if caption is not None:
            data["caption"] = caption
        if document is not None:
            data["document"] = document
        update = Update.de_json(
            {"update_id": number, "edited_message" if edited else "message": data}, app.bot
        )
        await app.process_update(update)

    async def callback(uid, data, card=500, chat_type="private"):
        number = next(ids)
        update = Update.de_json(
            {
                "update_id": number,
                "callback_query": {
                    "id": str(number),
                    "from": {"id": uid, "is_bot": False, "first_name": f"Клиент {uid}"},
                    "chat_instance": "test",
                    "data": data,
                    "message": {
                        "message_id": card,
                        "date": 1700000000,
                        "from": BOT_USER,
                        "chat": {"id": uid, "type": chat_type, "first_name": "Test"},
                        "text": "Карточка",
                    },
                },
            },
            app.bot,
        )
        await app.process_update(update)

    result = SimpleNamespace(
        store=store, app=app, request=request, message=message, callback=callback, errors=errors
    )
    yield result
    await app.shutdown()
    assert not errors, [type(error).__name__ for error in errors]
