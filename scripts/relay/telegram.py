"""Minimal Telegram Bot API client and message formatting helpers."""

import html
import json
import re
import urllib.error
import urllib.request

TAG = re.compile(r"<(/?)([a-z-]+)[^>]*>")
# Telegram lets these contain, and sit inside, anything except code and pre
STYLE_TAGS = {"b", "i", "u", "s", "tg-spoiler"}
EMPTY_TAG = re.compile(r"<(b|i|u|s|a)(?:\s[^>]*)?>(\s*)</\1>")


def fix_nesting(text):
    """Make HTML follow Telegram's nesting rules, which reject the whole message otherwise.

    Code inside bold or italic: close the styles around the code and reopen them after.
    Code, pre, links and quotes can't contain each other (except pre > code), so an
    inner one of those loses its tag and keeps its text.
    """
    out, stack, actions, pos = [], [], [], 0
    for match in TAG.finditer(text):
        out.append(text[pos:match.start()])
        pos = match.end()
        closing, name, tag = match.group(1) == "/", match.group(2), match.group(0)
        if name in STYLE_TAGS:
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        del stack[i]
                        break
            else:
                stack.append((name, tag))
            out.append(tag)
            continue
        if not closing:
            others = [n for n, _ in stack if n not in STYLE_TAGS]
            if name == "code" and others[-1:] == ["pre"]:
                action = "keep"
            elif others:
                action = "drop"
            elif stack and name in ("code", "pre"):
                action = "split"
            else:
                action = "keep"
            actions.append((action, list(stack)))
            if action == "drop":
                continue
            if action == "split":
                out.extend("</%s>" % n for n, _ in reversed(stack))
            out.append(tag)
            stack.append((name, tag))
            continue
        if not actions:
            continue  # a stray closing tag
        action, saved = actions.pop()
        if action == "drop":
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == name:
                del stack[i]
                break
        out.append(tag)
        if action == "split":
            out.extend(t for n, t in saved if n in STYLE_TAGS)
    out.append(text[pos:])
    return EMPTY_TAG.sub(r"\2", "".join(out))


def plain_text(text):
    """HTML message as plain text, for when Telegram rejects the formatting anyway."""
    return html.unescape(TAG.sub("", text))


def is_format_error(err):
    return "can't parse entities" in str(err).lower()


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

    def call_html(self, method, text, **params):
        """Call a method with HTML text; resend as plain text if Telegram can't parse it."""
        try:
            return self.call(method, text=fix_nesting(text), parse_mode="HTML", **params)
        except TelegramError as err:
            if not is_format_error(err):
                raise
            return self.call(method, text=plain_text(text), **params)

    def send(self, text, buttons=None, reply_to=None):
        params = {"chat_id": self.chat_id, "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = {"inline_keyboard": buttons}
        if reply_to:
            params["reply_parameters"] = {"message_id": reply_to}
        return self.call_html("sendMessage", text, **params)["message_id"]

    def edit(self, message_id, text=None, buttons=None):
        """Best effort: replace a message's text and/or keyboard."""
        markup = {"inline_keyboard": buttons or []}
        try:
            if text is None:
                self.call("editMessageReplyMarkup", chat_id=self.chat_id,
                          message_id=message_id, reply_markup=markup)
            else:
                self.call_html("editMessageText", text, chat_id=self.chat_id,
                               message_id=message_id, disable_web_page_preview=True,
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
