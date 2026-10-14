"""One prompt sent to Telegram and waiting for an answer."""

import json
import os
import secrets
import time
from pathlib import Path

from .config import MAX_WAIT
from .inbox import Inbox, live_requests
from .presence import user_is_back
from .storage import PENDING, ensure_dirs, write_atomic
from .telegram import Telegram

POLL_SECONDS = 5

# Results of Request.wait() when no answer came from Telegram
TIMEOUT = ("timeout",)
DESK = ("desk",)
BACK = ("back",)

CLOSE_NOTES = {
    TIMEOUT: "⌛ No answer in time. Answer at the desk.",
    DESK: "💻 Moved to the desk.",
    BACK: "💻 You're back at the desk. Answer there.",
}


class Request:
    """Register a waiting prompt, send its messages, and collect the updates addressed to it.

    Button presses carry "<request id>:..." in their callback data. Text messages belong
    to the prompt they reply to; a plain message goes to the newest waiting prompt.
    """

    def __init__(self, cfg, route, timeout):
        ensure_dirs()
        self.cfg = cfg
        self.route = route
        self.tg = Telegram(cfg)
        self.inbox = Inbox(self.tg)
        self.rid = secrets.token_hex(4)
        self.created = time.time()
        self.deadline = self.created + max(1, min(int(timeout), MAX_WAIT))
        self.message_ids = set()
        self.pending_file = PENDING / ("%s.json" % self.rid)
        write_atomic(self.pending_file, json.dumps({"pid": os.getpid(), "created": self.created}))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.pending_file.unlink(missing_ok=True)

    def data(self, *parts):
        """Callback data for a button of this prompt."""
        return ":".join([self.rid] + [str(p) for p in parts])

    def send(self, text, buttons=None):
        message_id = self.tg.send(text, buttons)
        self.message_ids.add(message_id)
        return message_id

    def is_newest(self):
        live = live_requests()
        return not live or max(live, key=live.get) == self.rid

    def match(self, update):
        cq = update.get("callback_query")
        if cq:
            return (cq.get("data") or "").split(":")[0] == self.rid
        msg = update.get("message") or {}
        text = msg.get("text") or ""
        if not text or text.startswith("/"):
            return False
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        if reply_to is not None:
            return reply_to in self.message_ids
        # Allow some clock skew between this machine and Telegram
        return msg.get("date", 0) >= self.created - 30 and self.is_newest()

    def wait(self, handle):
        """Feed updates to handle() until it returns a result, the user is back, or time runs out."""
        last_presence = time.time()
        while time.time() < self.deadline:
            update = self.inbox.take(self.match)
            if update is not None:
                result = handle(update)
                if result is not None:
                    return result
                continue
            if self.route == "auto" and time.time() - last_presence >= POLL_SECONDS:
                last_presence = time.time()
                if user_is_back(self.cfg, self.created):
                    return BACK
            self.inbox.sweep()
            remaining = int(self.deadline - time.time())
            if remaining > 0:
                self.inbox.pump(min(POLL_SECONDS, remaining))
        return TIMEOUT

    def close_message(self, message_id, text, result):
        """Remove the buttons and note why the prompt went back to Claude Code."""
        note = CLOSE_NOTES.get(result)
        self.tg.edit(message_id, text + ("\n\n<i>%s</i>" % note if note else ""))


def project_label(event):
    return Path(event.get("cwd") or os.getcwd()).name or "Claude Code"


def callback_payload(update):
    """Return (callback id, data without the request id) of a button press."""
    cq = update["callback_query"]
    return cq["id"], (cq.get("data") or "").split(":", 1)[-1]


def reply_text(update):
    return ((update.get("message") or {}).get("text") or "").strip()
