"""Stop hook: tell the user Claude finished, and let a Telegram reply continue the session."""

import json
import os
from pathlib import Path

from ..presence import routing
from ..request import Request, callback_payload, project_label, reply_text
from ..telegram import Telegram, button, esc


def last_message_from_transcript(path):
    """Fallback for Claude Code versions that don't send last_assistant_message."""
    try:
        lines = Path(os.path.expanduser(path)).read_text(encoding="utf-8").splitlines()[-300:]
    except (OSError, TypeError):
        return ""
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content") or []
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        if any(texts):
            return "\n".join(texts)
    return ""


def run(cfg, event):
    route = routing(cfg)
    if not route:
        return None
    message = event.get("last_assistant_message") or last_message_from_transcript(
        event.get("transcript_path"))
    text = "✅ <b>%s</b> · Claude finished\n\n%s" % (
        esc(project_label(event)), esc(message or "(no text)", 3000, tail=True))
    if cfg["stop_wait"] <= 0:
        Telegram(cfg).send(text)
        return None

    def handle(update):
        if "callback_query" in update:
            callback_id, payload = callback_payload(update)
            req.tg.answer_callback(callback_id)
            return ("ok",) if payload == "ok" else None
        return ("answer", reply_text(update)) if reply_text(update) else None

    hint = "\n\n<i>Reply to this message to continue the session.</i>"
    with Request(cfg, route, cfg["stop_wait"]) as req:
        message_id = req.send(text + hint, [[button("👍 OK", req.data("ok"))]])
        result = req.wait(handle)

    if result[0] != "answer":
        req.tg.edit(message_id, text)
        return None
    req.tg.edit(message_id, text + "\n\n↪ <b>%s</b>" % esc(result[1], 500))
    return {
        "decision": "block",
        "reason": "The user is away from the keyboard and replied from Telegram. "
                  "Treat this as their next message:\n\n%s" % result[1],
    }
