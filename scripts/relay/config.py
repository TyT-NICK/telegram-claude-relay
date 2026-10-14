"""Settings and mode.

Each option is resolved from these layers; later layers win:
    1. built-in defaults (OPTIONS below)
    2. config.json in the state directory
    3. plugin settings saved by Claude Code (/config, or pluginConfigs in ~/.claude/settings.json)
    4. CLAUDE_PLUGIN_OPTION_<KEY> environment variables, which Claude Code passes to plugin hooks

The bot token and chat id are not plugin options: `setup` stores them in config.json,
and TG_RELAY_BOT_TOKEN / TG_RELAY_CHAT_ID override them.
"""

import json
import os
from collections import namedtuple
from pathlib import Path

from .storage import CONFIG_FILE, MODE_FILE, ensure_dirs, log_error, read_json, write_atomic

PLUGIN_NAME = "telegram-relay"
MODES = ("auto", "away", "desk", "off")
# Hooks must finish before the timeout set in hooks/hooks.json
MAX_WAIT = 3500

Option = namedtuple("Option", "key type default min max choices", defaults=(None, None, None))

# Keep in sync with userConfig in .claude-plugin/plugin.json (tests/test_config.py checks it)
OPTIONS = (
    Option("idle_seconds", "number", 120, 10, 86400),
    Option("when_unknown", "string", "desk", choices=("desk", "away")),
    Option("idle_command", "string", ""),
    Option("answer_timeout", "number", 1800, 30, MAX_WAIT),
    Option("stop_wait", "number", 600, 0, MAX_WAIT),
    Option("relay_questions", "boolean", True),
    Option("relay_permissions", "boolean", True),
    Option("relay_finished", "boolean", True),
    Option("relay_notifications", "boolean", True),
)
OPTIONS_BY_KEY = {o.key: o for o in OPTIONS}

# Settings that only config.json and the environment can set
BASE = {
    "bot_token": "",
    "chat_id": None,
    "api_base": "https://api.telegram.org",
    # Notification types skipped because another hook already covers them
    "notify_skip": ["permission_prompt", "idle_prompt"],
}
ENV_OVERRIDES = {
    "bot_token": "TG_RELAY_BOT_TOKEN",
    "chat_id": "TG_RELAY_CHAT_ID",
    "api_base": "TG_RELAY_API_BASE",
}


def coerce(option, value):
    """Convert a stored or environment value to the option's type; raise ValueError if invalid."""
    if option.type == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise ValueError("expected true or false")
    if option.type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number")
        number = int(float(value))
        return max(option.min, min(option.max, number))
    text = str(value)
    if option.choices and text not in option.choices:
        raise ValueError("expected one of: %s" % ", ".join(option.choices))
    return text


def plugin_settings():
    """Options saved by Claude Code's plugin configuration dialog (user settings only)."""
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    settings = read_json(claude_dir / "settings.json", {})
    configs = settings.get("pluginConfigs") if isinstance(settings, dict) else None
    for plugin_id, entry in (configs or {}).items():
        if plugin_id.split("@")[0] == PLUGIN_NAME and isinstance(entry, dict):
            return entry.get("options") or {}
    return {}


def plugin_env():
    values = {}
    for option in OPTIONS:
        var = "CLAUDE_PLUGIN_OPTION_" + option.key.upper()
        if var in os.environ:
            values[option.key] = os.environ[var]
    return values


def load_config():
    """Return the effective settings. cfg["_sources"] maps each option to the layer it came from."""
    cfg = dict(BASE, notify_skip=list(BASE["notify_skip"]))
    sources = {}
    for option in OPTIONS:
        cfg[option.key] = option.default
        sources[option.key] = "default"

    stored = read_json(CONFIG_FILE, {})
    layers = (
        ("config.json", stored if isinstance(stored, dict) else {}),
        ("plugin settings", plugin_settings()),
        ("plugin settings", plugin_env()),
    )
    for source, values in layers:
        for key, value in values.items():
            option = OPTIONS_BY_KEY.get(key)
            if option is None:
                if source == "config.json" and key in BASE:
                    cfg[key] = value
                continue
            try:
                cfg[key] = coerce(option, value)
            except (TypeError, ValueError) as err:
                log_error("ignoring %s=%r from %s: %s" % (key, value, source, err))
                continue
            sources[key] = source

    for key, var in ENV_OVERRIDES.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    if cfg["chat_id"] is not None:
        cfg["chat_id"] = int(cfg["chat_id"])
    cfg["_sources"] = sources
    return cfg


def save_config(updates):
    """Merge updates into config.json, keeping only keys that were set explicitly."""
    ensure_dirs()
    stored = read_json(CONFIG_FILE, {})
    if not isinstance(stored, dict):
        stored = {}
    stored.update(updates)
    write_atomic(CONFIG_FILE, json.dumps(stored, indent=2) + "\n", mode=0o600)


def configured(cfg):
    return bool(cfg["bot_token"]) and cfg["chat_id"] is not None


def read_mode():
    try:
        mode = MODE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "auto"
    return mode if mode in MODES else "auto"


def write_mode(mode):
    ensure_dirs()
    write_atomic(MODE_FILE, mode + "\n")
