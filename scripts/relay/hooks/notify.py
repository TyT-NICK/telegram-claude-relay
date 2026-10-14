"""Notification hook: forward other Claude Code notifications as plain alerts."""

from ..presence import routing
from ..request import project_label
from ..telegram import Telegram, esc


def run(cfg, event):
    if event.get("notification_type") in (cfg.get("notify_skip") or []):
        return None
    if not routing(cfg):
        return None
    body = event.get("message") or event.get("title") or "Claude Code needs your attention."
    Telegram(cfg).send("🔔 <b>%s</b>\n\n%s" % (esc(project_label(event)), esc(body, 3000)))
    return None
