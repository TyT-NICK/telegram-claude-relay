"""tg-relay: answer Claude Code prompts from Telegram.

usage:
    tg_relay.py setup         store the bot token and pair your Telegram chat
    tg_relay.py status        show pairing, mode, presence detection and settings
    tg_relay.py mode [MODE]   show or set the mode: auto | away | desk | off
    tg_relay.py test          send a sample question and print what you tap
    tg_relay.py hook KIND     run a Claude Code hook: ask | permission | stop | notify
"""

import getpass
import os
import secrets
import signal
import socket
import sys
import time

from . import hooks
from .config import MODES, OPTIONS, configured, load_config, read_mode, save_config, write_mode
from .hooks.ask import ask_question
from .inbox import read_offset
from .presence import detect_idle, routing
from .request import Request
from .storage import CONFIG_FILE, LOCK_FILE, OFFSET_FILE, FileLock, ensure_dirs
from .telegram import Telegram, TelegramError, esc

PAIR_SECONDS = 300


def wait_for_pairing(tg, code):
    """Poll the bot until /pair <code> arrives in a private chat; return that chat id or None."""
    lock = FileLock(LOCK_FILE)
    deadline = time.time() + PAIR_SECONDS
    while time.time() < deadline:
        if not lock.acquire():
            time.sleep(1)
            continue
        try:
            offset = read_offset()
            updates = tg.call("getUpdates", _timeout=30, offset=offset, timeout=20,
                              allowed_updates=["message"])
            chat_id = None
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                msg = update.get("message") or {}
                if (msg.get("text") or "").strip() == "/pair %s" % code \
                        and msg.get("chat", {}).get("type") == "private":
                    chat_id = msg["chat"]["id"]
            OFFSET_FILE.write_text(str(offset))
            if chat_id is not None:
                return chat_id
        finally:
            lock.release()
    return None


def cmd_setup(args):
    ensure_dirs()
    cfg = load_config()
    token = os.environ.get("TG_RELAY_BOT_TOKEN") or getpass.getpass(
        "Bot token from @BotFather (hidden; Enter keeps the current one): ").strip()
    token = token or cfg["bot_token"]
    if not token:
        print("No token given.")
        return 1
    cfg["bot_token"] = token
    tg = Telegram(cfg)
    try:
        bot = tg.call("getMe")
    except (TelegramError, OSError) as err:
        print("Telegram rejected the token: %s" % err)
        return 1

    code = "%06d" % secrets.randbelow(10 ** 6)
    print("\nIn Telegram, open @%s and send this message within %d minutes:\n\n    /pair %s\n"
          % (bot["username"], PAIR_SECONDS // 60, code))
    try:
        chat_id = wait_for_pairing(tg, code)
    except (TelegramError, OSError) as err:
        print("getUpdates failed: %s" % err)
        if "webhook" in str(err).lower() or "conflict" in str(err).lower():
            print("Another program is reading this bot's updates. Use a separate bot.")
        return 1
    if chat_id is None:
        print("No pairing message arrived. Run setup again.")
        return 1
    save_config({"bot_token": token, "chat_id": chat_id})
    cfg["chat_id"] = chat_id
    Telegram(cfg).send("✅ Paired with Claude Code on <b>%s</b>." % esc(socket.gethostname()))
    print("Paired. Saved to %s\n" % CONFIG_FILE)
    return cmd_status([])


def cmd_status(args):
    cfg = load_config()
    paired = "yes (chat %s)" % cfg["chat_id"] if configured(cfg) else "no, run: tg_relay.py setup"
    print("paired:    %s" % paired)
    print("mode:      %s" % read_mode())
    idle, source = detect_idle(cfg)
    if idle is None:
        print("presence:  unknown (in auto mode prompts stay %s)"
              % ("on Telegram" if cfg["when_unknown"] == "away"
                 else "local; use 'mode away' when you leave"))
    else:
        print("presence:  idle %s via %s"
              % ("∞" if idle == float("inf") else "%ds" % idle, source))
    print("routing:   %s" % ("Telegram" if configured(cfg) and routing(cfg) else "local"))
    print("\nsettings (change with /config in Claude Code, or in %s):" % CONFIG_FILE)
    width = max(len(o.key) for o in OPTIONS)
    for option in OPTIONS:
        value = cfg[option.key]
        shown = str(value).lower() if isinstance(value, bool) else (str(value) or '""')
        print("  %s  %-8s  (%s)" % (option.key.ljust(width), shown, cfg["_sources"][option.key]))
    return 0


def cmd_mode(args):
    if not args:
        print(read_mode())
        return 0
    mode = args[0].strip().lower()
    if mode not in MODES:
        print("Unknown mode %r. Use one of: %s" % (mode, ", ".join(MODES)))
        return 1
    write_mode(mode)
    print({
        "auto": "Mode auto: prompts go to Telegram after %ds without input."
                % load_config()["idle_seconds"],
        "away": "Mode away: all prompts go to Telegram.",
        "desk": "Mode desk: prompts stay in Claude Code.",
        "off": "Mode off: tg-relay does nothing.",
    }[mode])
    return 0


def cmd_test(args):
    cfg = load_config()
    if not configured(cfg):
        print("Not paired yet. Run: tg_relay.py setup")
        return 1
    question = {
        "question": "tg-relay test: which option do you pick?",
        "header": "Test",
        "multiSelect": False,
        "options": [
            {"label": "Option A", "description": "The first choice"},
            {"label": "Option B", "description": "The second choice"},
        ],
    }
    print("Sent a test question to Telegram. Tap an option or reply (5 minutes)...")
    with Request(cfg, "away", 300) as req:
        answer = ask_question(req, socket.gethostname(), question, 0, 1)
    print("Answer: %s" % answer if answer is not None else "No answer.")
    return 0


def cmd_hook(args):
    return hooks.run(args[0] if args else "")


COMMANDS = {"setup": cmd_setup, "status": cmd_status, "mode": cmd_mode, "test": cmd_test,
            "hook": cmd_hook}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 0 if not argv else 1
    # Never crash on a console that can't show emoji (e.g. a Windows pipe in cp1252)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    # Let `with` blocks clean up when Claude Code stops a waiting hook
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))
    try:
        return COMMANDS[argv[0]](argv[1:])
    except KeyboardInterrupt:
        return 130
