"""State directory, small file helpers and the cross-process lock.

State lives in $TG_RELAY_HOME, default ~/.config/tg-relay.
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt

HOME = Path(
    os.environ.get("TG_RELAY_HOME")
    or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tg-relay"
)
CONFIG_FILE = HOME / "config.json"
MODE_FILE = HOME / "mode"
PRESENCE_FILE = HOME / "presence"
RUN = HOME / "run"
INBOX = RUN / "inbox"
PENDING = RUN / "pending"
OFFSET_FILE = RUN / "offset"
LOCK_FILE = RUN / "poll.lock"
LOG_FILE = RUN / "error.log"


def ensure_dirs():
    for d in (HOME, RUN, INBOX, PENDING):
        d.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        pass


def write_atomic(path, text, mode=None):
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def log_error(message):
    try:
        ensure_dirs()
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass
    print("tg-relay: %s" % message, file=sys.stderr)


class FileLock:
    """Non-blocking exclusive lock, held by whichever process is polling Telegram."""

    def __init__(self, path):
        self.path = path
        self.fh = None

    def acquire(self):
        self.fh = open(self.path, "a+")
        try:
            if fcntl:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def release(self):
        if not self.fh:
            return
        try:
            if fcntl:
                fcntl.flock(self.fh, fcntl.LOCK_UN)
            else:
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.fh.close()
        self.fh = None
