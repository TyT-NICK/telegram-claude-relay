"""Claude Code hook entry points.

Each hook module has run(cfg, event), which returns the JSON object to print for
Claude Code, or None to let Claude Code handle the prompt as usual.
"""

import json
import sys

from ..config import configured, load_config, read_mode
from ..storage import log_error
from . import ask, notify, permission, stop

# hook name -> (module, option that turns it on)
HOOKS = {
    "ask": (ask, "relay_questions"),
    "permission": (permission, "relay_permissions"),
    "stop": (stop, "relay_finished"),
    "notify": (notify, "relay_notifications"),
}


def run(kind):
    """Run one hook with the event JSON on stdin. Never blocks Claude Code on errors."""
    if kind not in HOOKS:
        print("usage: tg_relay.py hook {%s}" % ",".join(HOOKS), file=sys.stderr)
        return 0
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except ValueError:
        return 0
    module, switch = HOOKS[kind]
    cfg = load_config()
    if not configured(cfg) or not cfg[switch] or read_mode() == "off":
        return 0
    try:
        output = module.run(cfg, event)
    except Exception as err:  # fall back to the local prompt on any failure
        log_error("hook %s failed: %r" % (kind, err))
        return 0
    if output:
        sys.stdout.write(json.dumps(output))
    return 0
