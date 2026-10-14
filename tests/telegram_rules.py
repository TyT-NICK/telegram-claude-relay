"""Telegram's HTML formatting rules as a checker for tests.

From core.telegram.org/bots/api#formatting-options: bold, italic, underline,
strikethrough and spoiler can contain and be part of anything except pre and code;
blockquotes can't be nested; all other entities can't contain each other, except that
<code> inside <pre> sets the language. <, > and & must be escaped outside tags.
"""

import html
import re

TAG = re.compile(r"<(/?)([a-z-]+)[^>]*>")
ALLOWED = {"b", "i", "u", "s", "a", "code", "pre", "blockquote", "tg-spoiler"}
STYLE = {"b", "i", "u", "s", "tg-spoiler"}
BARE_AMPERSAND = re.compile(r"&(?!(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);)")
MAX_LENGTH = 4096


def problems(text):
    """Reasons Telegram would reject this HTML message; empty if it would accept it."""
    found, stack = [], []
    for match in TAG.finditer(text):
        closing, name = match.group(1) == "/", match.group(2)
        if name not in ALLOWED:
            found.append("unsupported tag <%s>" % name)
            continue
        if closing:
            if not stack or stack[-1] != name:
                found.append("misnested </%s>" % name)
            else:
                stack.pop()
            continue
        others = [n for n in stack if n not in STYLE]
        if name in STYLE:
            if others and others[-1] in ("code", "pre"):
                found.append("<%s> inside <%s>" % (name, others[-1]))
        elif name == "code" and stack and stack[-1] == "pre" and others == ["pre"]:
            pass
        elif others:
            found.append("<%s> inside <%s>" % (name, others[-1]))
        elif name in ("code", "pre") and stack:
            found.append("<%s> inside <%s>" % (name, stack[-1]))
        stack.append(name)
    if stack:
        found.append("unclosed <%s>" % stack[-1])
    outside = TAG.sub("", text)
    if "<" in outside or ">" in outside:
        found.append("unescaped < or >")
    if BARE_AMPERSAND.search(outside):
        found.append("unescaped &")
    if len(html.unescape(outside)) > MAX_LENGTH:
        found.append("longer than %d characters" % MAX_LENGTH)
    return found
