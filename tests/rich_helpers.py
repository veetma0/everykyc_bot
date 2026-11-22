"""The Bot API accepts HTML input and returns structured RichMessage blocks."""

from hashlib import sha256
import re
from xml.etree import ElementTree


def rich_root(params):
    markup = re.sub(r"<br\s*/?>", "<br/>", params["rich_message"]["html"])
    return ElementTree.fromstring(f"<root>{markup}</root>")


def rich_text(element):
    parts = [element.text] if element.text else []
    tags = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic", "u": "underline",
            "s": "strikethrough", "code": "code"}
    for child in element:
        nested = rich_text(child)
        if child.tag == "br":
            parts.append("\n")
        elif child.tag == "tg-emoji":
            parts.append({"type": "custom_emoji", "custom_emoji_id": child.attrib["emoji-id"],
                          "alternative_text": nested})
        elif child.tag == "a":
            parts.append({"type": "url", "url": child.attrib["href"], "text": nested})
        else:
            parts.append({"type": tags[child.tag], "text": nested})
        if child.tail:
            parts.append(child.tail)
    return parts[0] if len(parts) == 1 else parts or ""


def rich_button(element):
    attrs = element.attrib
    assert all(child.tag == "tg-emoji" for child in element), "Unsupported formatting on Telegram button"
    button = {"text": rich_text(element)}
    if attrs["type"] == "callback_data":
        button["callback_data"] = attrs["data"]
    elif attrs["type"] == "url":
        button["url"] = attrs["url"]
    elif attrs["type"] == "copy_text":
        button["copy_text"] = {"text": attrs["text"]}
    else:
        raise AssertionError(f"Unexpected button {attrs['type']}")
    if "style" in attrs:
        button["style"] = attrs["style"]
    return button


def response_blocks(params, multipart):
    media = {attachment["id"]: attachment["media"] for attachment in params["rich_message"].get("media", [])}
    blocks = []
    for element in rich_root(params):
        if element.tag == "img":
            ref = element.attrib["src"].removeprefix("tg://photo?id=")
            file_id = media[ref]["media"]
            if file_id.startswith("attach://"):
                file_content = multipart[file_id.removeprefix("attach://")][1]
                file_id = "photo-" + sha256(file_content).hexdigest()[:12]
            sizes = [{"file_id": file_id, "file_unique_id": "unique-" + file_id, "width": 1120, "height": 450}]
            blocks.append({"type": "photo", "photo": sizes})
        elif element.tag == "tg-button-row":
            blocks.append({"type": "buttons", "buttons": [rich_button(child) for child in element]})
        else:
            assert element.tag == "p"
            blocks.append({"type": "paragraph", "text": rich_text(element)})
    return blocks


def rendered_panel(params):
    """Expose the visible body and buttons to existing journey assertions only."""
    root = rich_root(params)
    labels = []
    for row in root.findall("tg-button-row"):
        buttons = []
        for e in row:
            button = rich_button(e)
            button["text"] = "".join(e.itertext())
            icon = e.find("tg-emoji")
            if icon is not None:
                button["icon_custom_emoji_id"] = icon.attrib["emoji-id"]
                button["text"] = (icon.tail or "").lstrip()
            buttons.append(button)
        labels.append(buttons)
    body = "\n\n".join(re.findall(r"<p>(.*?)</p>", params["rich_message"]["html"], re.DOTALL))
    body = re.sub(r"<br\s*/?>", "\n", body)
    labels.extend(params.get("reply_markup", {}).get("inline_keyboard", []))
    return {**params, "text": body, "reply_markup": {"inline_keyboard": labels}}
