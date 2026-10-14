"""PermissionRequest hook: allow or deny a tool call from Telegram."""

import json

from ..presence import routing
from ..request import DESK, Request, callback_payload, project_label, reply_text
from ..telegram import button, esc

# Tools that need their own interaction; they stay with Claude Code's UI
INTERACTIVE_TOOLS = {"AskUserQuestion", "ExitPlanMode"}

VERDICTS = {"allow": "✅ Allowed", "always": "✅ Always allowed", "deny": "❌ Denied"}


def describe_tool(tool_input):
    for key in ("command", "file_path", "notebook_path", "url", "pattern", "prompt"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            desc = tool_input.get("description")
            return value + ("\n\n# %s" % desc if isinstance(desc, str) and desc else "")
    return json.dumps(tool_input, indent=2, ensure_ascii=False)


def run(cfg, event):
    tool = event.get("tool_name") or "?"
    if tool in INTERACTIVE_TOOLS:
        return None
    route = routing(cfg)
    if not route:
        return None
    suggestions = event.get("permission_suggestions") or []
    text = "🔐 <b>%s</b> · permission\n\n<b>%s</b>\n<pre>%s</pre>\n\n<i>%s</i>" % (
        esc(project_label(event)), esc(tool),
        esc(describe_tool(event.get("tool_input") or {}), 2500),
        "Reply to this message to deny and tell Claude what to do instead.",
    )

    def handle(update):
        if "callback_query" not in update:
            return ("deny", reply_text(update)) if reply_text(update) else None
        callback_id, payload = callback_payload(update)
        req.tg.answer_callback(callback_id)
        return {"allow": ("allow",), "always": ("always",), "deny": ("deny", ""),
                "desk": DESK}.get(payload)

    with Request(cfg, route, cfg["answer_timeout"]) as req:
        rows = [[button("✅ Allow", req.data("allow")), button("❌ Deny", req.data("deny"))]]
        if suggestions:
            rows.append([button("✅ Always allow", req.data("always"))])
        rows.append([button("💻 At desk", req.data("desk"))])
        message_id = req.send(text, rows)
        result = req.wait(handle)

    if result[0] not in VERDICTS:
        req.close_message(message_id, text, result)
        return None
    verdict = VERDICTS[result[0]]
    if result[0] == "deny" and result[1]:
        verdict += ": %s" % esc(result[1], 500)
    req.tg.edit(message_id, text + "\n\n<b>%s</b>" % verdict)

    decision = {"behavior": "deny" if result[0] == "deny" else "allow"}
    if result[0] == "always":
        decision["updatedPermissions"] = suggestions
    if result[0] == "deny":
        decision["message"] = (
            "The user denied this from Telegram and said: %s" % result[1]
            if result[1] else "The user denied this from Telegram."
        )
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
