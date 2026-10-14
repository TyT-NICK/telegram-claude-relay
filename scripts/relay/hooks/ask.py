"""PreToolUse hook for AskUserQuestion: pick the options from Telegram.

Claude Code accepts the answer when the hook returns permissionDecision "allow"
with the original questions plus an "answers" map in updatedInput.
"""

from ..presence import routing
from ..request import DESK, Request, callback_payload, project_label, reply_text
from ..telegram import button, esc


def run(cfg, event):
    tool_input = event.get("tool_input") or {}
    questions = tool_input.get("questions") or []
    route = routing(cfg)
    if not questions or not route:
        return None
    answers = {}
    with Request(cfg, route, cfg["answer_timeout"]) as req:
        for index, question in enumerate(questions):
            answer = ask_question(req, project_label(event), question, index, len(questions))
            if answer is None:
                return None
            answers[question.get("question", "")] = answer
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "updatedInput": dict(tool_input, answers=answers),
    }}


def format_question(label, question, index, total):
    multi = bool(question.get("multiSelect"))
    lines = ["❓ <b>%s</b>%s" % (esc(label), " · %d/%d" % (index + 1, total) if total > 1 else "")]
    lines += ["", "<b>%s</b>" % esc(question.get("question"), 1000)]
    for i, opt in enumerate(question.get("options") or []):
        line = "%d. <b>%s</b>" % (i + 1, esc(opt.get("label"), 200))
        if opt.get("description"):
            line += " — %s" % esc(opt["description"], 300)
        lines.append(line)
    hint = "Tap the options, then Done" if multi else "Tap an option"
    lines += ["", "<i>%s, or reply to this message with your own answer.</i>" % hint]
    return "\n".join(lines)


def ask_question(req, label, question, index, total):
    """Ask one question; return the answer string, or None to fall back to Claude Code."""
    options = question.get("options") or []
    multi = bool(question.get("multiSelect"))
    chosen = set()
    text = format_question(label, question, index, total)

    def keyboard():
        rows = []
        for i, opt in enumerate(options):
            mark = ("☑ " if i in chosen else "☐ ") if multi else ""
            rows.append([button(mark + (opt.get("label") or "Option %d" % (i + 1)),
                                req.data(index, i))])
        last = [button("💻 At desk", req.data("desk"))]
        if multi:
            last.insert(0, button("✔ Done", req.data(index, "done")))
        rows.append(last)
        return rows

    message_id = req.send(text, keyboard())

    def handle(update):
        if "callback_query" not in update:
            reply_to = (update["message"].get("reply_to_message") or {}).get("message_id")
            if reply_to not in (None, message_id):
                return None  # a reply to an earlier question of this prompt
            return ("answer", reply_text(update)) if reply_text(update) else None
        callback_id, payload = callback_payload(update)
        if payload == "desk":
            req.tg.answer_callback(callback_id)
            return DESK
        parts = payload.split(":")
        if len(parts) != 2 or parts[0] != str(index):
            req.tg.answer_callback(callback_id, "This question is closed.")
            return None
        if parts[1] == "done":
            if not chosen:
                req.tg.answer_callback(callback_id, "Pick at least one option.")
                return None
            req.tg.answer_callback(callback_id)
            return ("answer", ", ".join(options[i].get("label", "") for i in sorted(chosen)))
        try:
            i = int(parts[1])
            options[i]
        except (ValueError, IndexError):
            req.tg.answer_callback(callback_id)
            return None
        req.tg.answer_callback(callback_id)
        if not multi:
            return ("answer", options[i].get("label", ""))
        chosen.symmetric_difference_update({i})
        req.tg.edit(message_id, buttons=keyboard())
        return None

    result = req.wait(handle)
    if result[0] == "answer":
        req.tg.edit(message_id, text + "\n\n✅ <b>%s</b>" % esc(result[1], 500))
        return result[1]
    req.close_message(message_id, text, result)
    return None
