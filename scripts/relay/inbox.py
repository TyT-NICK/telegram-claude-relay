"""One Telegram update stream shared by every hook process on this machine.

Only the process holding the poll lock calls getUpdates. It writes every update from
the paired chat into the inbox directory. Each waiting process claims the updates
addressed to it by renaming the file, so no update is handled twice.
"""

import json
import os
import time

from .config import MAX_WAIT
from .storage import INBOX, LOCK_FILE, OFFSET_FILE, PENDING, FileLock, log_error, read_json, write_atomic
from .telegram import TelegramError, update_chat

# An update nobody claims within this many seconds gets an "expired" answer
STRAY_AFTER = 15


def pid_alive(pid):
    if os.name == "nt":  # os.kill(pid, 0) would send CTRL_C_EVENT on Windows
        from . import winapi

        return winapi.pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def live_requests():
    """Map request id -> creation time for prompts whose process is still waiting."""
    live = {}
    for path in PENDING.glob("*.json"):
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            continue
        info = read_json(path, {})
        if not info or age > MAX_WAIT + 300 or not pid_alive(int(info.get("pid", 0))):
            path.unlink(missing_ok=True)
            continue
        live[path.stem] = float(info.get("created", 0))
    return live


def read_offset():
    try:
        return int(OFFSET_FILE.read_text().strip())
    except (OSError, ValueError):
        return 0


class Inbox:
    def __init__(self, tg):
        self.tg = tg
        self.lock = FileLock(LOCK_FILE)
        self.last_sweep = 0.0

    def pump(self, poll_seconds):
        """Long-poll Telegram once if no other process is doing it, and store new updates."""
        if not self.lock.acquire():
            time.sleep(1)
            return
        try:
            offset = read_offset()
            try:
                updates = self.tg.call(
                    "getUpdates", _timeout=poll_seconds + 10, offset=offset,
                    timeout=poll_seconds, allowed_updates=["message", "callback_query"],
                )
            except (TelegramError, OSError) as err:
                log_error("getUpdates failed: %s" % err)
                time.sleep(3)
                return
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                if self.tg.chat_id in update_chat(update):
                    name = "%012d.json" % update["update_id"]
                    write_atomic(INBOX / name, json.dumps(update))
            OFFSET_FILE.write_text(str(offset))
        finally:
            self.lock.release()

    def _claim(self, path):
        claimed = path.with_name("%s.%d.claimed" % (path.stem, os.getpid()))
        try:
            os.rename(path, claimed)
        except OSError:
            return False
        claimed.unlink(missing_ok=True)
        return True

    def take(self, match):
        """Remove and return the first stored update that match(update) accepts."""
        for path in sorted(INBOX.glob("*.json")):
            update = read_json(path)
            if update is None or not match(update):
                continue
            if self._claim(path):
                return update
        return None

    def sweep(self):
        """Answer updates nobody claimed, so a late tap or reply doesn't vanish silently."""
        if time.time() - self.last_sweep < 3:
            return
        self.last_sweep = time.time()
        for path in sorted(INBOX.glob("*.json")):
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                continue
            if age < STRAY_AFTER:
                continue
            update = read_json(path)
            if update is None or not self._claim(path):
                continue
            if "callback_query" in update:
                self.tg.answer_callback(update["callback_query"]["id"], "This prompt has expired.")
                continue
            msg = update.get("message") or {}
            if time.time() - msg.get("date", 0) < 600 and not msg.get("text", "").startswith("/"):
                try:
                    self.tg.send("Nothing in Claude Code is waiting for a reply right now.",
                                 reply_to=msg.get("message_id"))
                except (TelegramError, OSError):
                    pass
