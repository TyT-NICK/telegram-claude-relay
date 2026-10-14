"""Minimal Telegram Bot API client and message formatting helpers."""

import html
import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, cfg):
        self.base = "%s/bot%s/" % (cfg["api_base"].rstrip("/"), cfg["bot_token"])
        self.chat_id = cfg["chat_id"]

    def call(self, method, _timeout=15, **params):
        req = urllib.request.Request(
            self.base + method,
            data=json.dumps(params).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_timeout) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as err:
            try:
                body = json.load(err)
            except ValueError:
                raise TelegramError("%s: HTTP %d" % (method, err.code))
        if not body.get("ok"):
            raise TelegramError("%s: %s" % (method, body.get("description")))
        return body["result"]

    def send(self, text, buttons=None, reply_to=None):
        params = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to}
        return self.call("sendMessage", **params)["message_id"]

    def edit(self, message_id, text=None, buttons=None):
        """Best effort: replace a message's text and/or keyboard."""
        markup = {"inline_keyboard": buttons or []}
        try:
            if text is None:
                self.call("editMessageReplyMarkup", chat_id=self.chat_id,
                          message_id=message_id, reply_markup=markup)
            else:
                self.call("editMessageText", chat_id=self.chat_id, message_id=message_id,
                          text=text, parse_mode="HTML", disable_web_page_preview=True,
                          reply_markup=markup)
        except (TelegramError, OSError):
            pass

    def answer_callback(self, callback_id, text=""):
        try:
            self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except (TelegramError, OSError):
            pass


def button(text, data):
    return {"text": text, "callback_data": data}


def esc(text, limit=None, tail=False):
    """HTML-escape text for parse_mode=HTML, cut to `limit` characters (keeping the end if tail)."""
    text = str(text or "")
    if limit and len(text) > limit:
        text = "…" + text[-limit:] if tail else text[:limit] + "…"
    return html.escape(text, quote=False)


def update_chat(update):
    """Return (chat id, sender id) of an update."""
    if "callback_query" in update:
        cq = update["callback_query"]
        return (cq.get("message") or {}).get("chat", {}).get("id"), cq.get("from", {}).get("id")
    msg = update.get("message") or {}
    return msg.get("chat", {}).get("id"), msg.get("from", {}).get("id")
