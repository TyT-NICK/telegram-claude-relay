"""Is the user at the keyboard? Decides whether a prompt goes to Telegram."""

import os
import re
import subprocess
import sys
import time

from .config import read_mode
from .storage import PRESENCE_FILE, read_json

# A presence file older than this is ignored (its writer has stopped)
PRESENCE_FRESH = 90

GNOME_IDLE = [
    "gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
    "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
    "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime",
]
GNOME_LOCKED = [
    "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
    "--object-path", "/org/gnome/ScreenSaver", "--method", "org.gnome.ScreenSaver.GetActive",
]


def run_probe(cmd, shell=False):
    try:
        out = subprocess.run(cmd, shell=shell, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def last_number(text):
    # gdbus prints "(uint64 12345,)", so take the last number
    numbers = re.findall(r"\d+", text or "")
    return int(numbers[-1]) if numbers else None


def presence_file_idle():
    """Idle seconds from the heartbeat file, or None if it is missing or stale.

    Any tool (an editor extension, a script) can write {"last_active": <epoch seconds>}
    there at least every 60 seconds while it runs.
    """
    try:
        if time.time() - PRESENCE_FILE.stat().st_mtime >= PRESENCE_FRESH:
            return None
        data = read_json(PRESENCE_FILE, {})
        return max(0.0, time.time() - float(data["last_active"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def linux_screen_locked():
    session = os.environ.get("XDG_SESSION_ID")
    if session:
        out = run_probe(["loginctl", "show-session", session, "-p", "LockedHint", "--value"])
        if out == "yes":
            return True
    out = run_probe(GNOME_LOCKED)
    return out is not None and "true" in out


def linux_idle():
    if linux_screen_locked():
        return float("inf"), "screen locked"
    for name, cmd in (("gnome", GNOME_IDLE), ("xprintidle", ["xprintidle"])):
        millis = last_number(run_probe(cmd))
        if millis is not None:
            return millis / 1000.0, name
    return None, None


def macos_idle():
    match = re.search(r'"HIDIdleTime" = (\d+)', run_probe(["ioreg", "-c", "IOHIDSystem", "-d", "4"]) or "")
    if match:
        return int(match.group(1)) / 1e9, "ioreg"
    return None, None


def windows_idle():
    try:
        from . import winapi

        idle = winapi.idle_seconds()
    except (OSError, AttributeError):
        idle = None
    return (idle, "GetLastInputInfo") if idle is not None else (None, None)


def detect_idle(cfg):
    """Return (seconds since the last input at this machine, source), or (None, None) if unknown."""
    idle = presence_file_idle()
    if idle is not None:
        return idle, "presence file"
    if cfg.get("idle_command"):
        millis = last_number(run_probe(cfg["idle_command"], shell=True))
        if millis is not None:
            return millis / 1000.0, "idle_command"
    if sys.platform == "win32":
        return windows_idle()
    if sys.platform == "darwin":
        return macos_idle()
    return linux_idle()


def routing(cfg):
    """Return "away" (forced), "auto" (idle detected) or None (handle the prompt locally)."""
    mode = read_mode()
    if mode == "away":
        return "away"
    if mode != "auto":
        return None
    idle, _ = detect_idle(cfg)
    if idle is None:
        return "away" if cfg.get("when_unknown") == "away" else None
    return "auto" if idle >= cfg["idle_seconds"] else None


def user_is_back(cfg, since):
    """True if there was keyboard or mouse input after the epoch time `since`."""
    idle, _ = detect_idle(cfg)
    return idle is not None and idle < time.time() - since - 1
