"""Convert the Markdown Claude writes into the HTML subset Telegram accepts.

Telegram has bold, italic, strikethrough, code, pre, links and quotes, but no headings,
lists or tables. Headings become bold lines, list markers become bullets, and each
table row becomes a "• first cell — other cells" line. telegram.fix_nesting() then
enforces Telegram's nesting rules on the result.
"""

import html
import re
import textwrap

FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)[\s#]*$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")

INLINE_CODE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
PLACEHOLDER = re.compile("\x00(\\d+)\x00")
STYLES = (
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)"), r"<b>\1</b>"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~"), r"<s>\1</s>"),
    (re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])"), r"<i>\1</i>"),
    (re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])"), r"<i>\1</i>"),
)


def esc(text):
    return html.escape(text, quote=False)


def cut(text, limit):
    return text if not limit or len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------- inline


def inline(text, limit=None):
    """Convert one line of Markdown: code spans, links, bold, italic, strikethrough."""
    stash = []

    def keep(snippet):
        stash.append(snippet)
        return "\x00%d\x00" % (len(stash) - 1)

    def link(m):
        label, url = m.group(1), m.group(2)
        if not re.match(r"https?://", url):
            return label  # a file path link: keep just its text
        return keep('<a href="%s">' % html.escape(url, quote=True)) + label + keep("</a>")

    text = INLINE_CODE.sub(lambda m: keep("<code>%s</code>" % esc(m.group(1))), cut(text, limit))
    text = esc(LINK.sub(link, text))
    for pattern, repl in STYLES:
        text = pattern.sub(repl, text)
    return PLACEHOLDER.sub(lambda m: stash[int(m.group(1))], text)


# ---------------------------------------------------------------- blocks


def split_blocks(text):
    """Split Markdown into ("code", lines) for fenced code and ("text", lines) paragraphs."""
    blocks, current, fence = [], [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if fence:
            current.append(line)
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                blocks.append(("code", current))
                current, fence = [], None
            continue
        match = FENCE.match(line)
        if match:
            if current:
                blocks.append(("text", current))
            current, fence = [line], match.group(1)
        elif stripped:
            current.append(line)
        elif current:
            blocks.append(("text", current))
            current = []
    if current:
        blocks.append(("code" if fence else "text", current))
    return blocks


def render_code(lines):
    fence, lang = FENCE.match(lines[0]).groups()
    body = lines[1:]
    if body and body[-1].strip().startswith(fence) and not body[-1].strip().strip(fence[0]):
        body = body[:-1]
    code = esc(textwrap.dedent("\n".join(body)).strip("\n"))
    if lang:
        return '<pre><code class="language-%s">%s</code></pre>' % (lang, code)
    return "<pre>%s</pre>" % code


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [cell.strip() for cell in line.split("|")]


def render_table(lines):
    header, rows = split_row(lines[0]), [split_row(line) for line in lines[2:]]
    out = []
    if any(header):
        out.append("<i>%s</i>" % " · ".join(inline(c) for c in header if c))
    for row in rows:
        cells = [c for c in row if c]
        if not cells:
            continue
        line = "• <b>%s</b>" % inline(cells[0])
        if cells[1:]:
            line += " — " + " · ".join(inline(c) for c in cells[1:])
        out.append(line)
    return "\n".join(out)


def render_lines(lines):
    out, quote = [], []

    def flush_quote():
        if quote:
            out.append("<blockquote>%s</blockquote>" % "\n".join(quote))
            quote.clear()

    for line in lines:
        match = QUOTE.match(line)
        if match:
            quote.append(inline(match.group(1)))
            continue
        flush_quote()
        if RULE.match(line):
            out.append("──────────")
        elif HEADING.match(line):
            out.append("<b>%s</b>" % inline(HEADING.match(line).group(1)))
        elif BULLET.match(line):
            indent, item = BULLET.match(line).groups()
            out.append("%s• %s" % (" " * len(indent), inline(item)))
        elif NUMBERED.match(line):
            indent, number, item = NUMBERED.match(line).groups()
            out.append("%s%s. %s" % (" " * len(indent), number, inline(item)))
        else:
            out.append(inline(line.strip()))
    flush_quote()
    return "\n".join(out)


def render_text(lines):
    for i in range(len(lines) - 1):
        if "|" in lines[i] and "|" in lines[i + 1] and TABLE_SEPARATOR.match(lines[i + 1]):
            end = i + 2
            while end < len(lines) and "|" in lines[end]:
                end += 1
            parts = (render_lines(lines[:i]), render_table(lines[i:end]), render_text(lines[end:]))
            return "\n".join(p for p in parts if p)
    return render_lines(lines)


def tail_block(kind, lines, limit):
    """The end of a single block too long to send whole."""
    head = lines[:1] if kind == "code" else []
    kept, size = [], 0
    for line in reversed(lines[len(head):]):
        if size + len(line) + 1 > limit:
            break
        kept.append(line)
        size += len(line) + 1
    if not kept:
        kept = ["…" + lines[-1][-limit:]]
    return head + kept[::-1]


def to_html(text, limit=None):
    """Convert a Markdown message. With a limit, keep the last blocks that fit."""
    blocks = split_blocks(text or "")
    shortened = False
    if limit:
        kept, size = [], 0
        for kind, lines in reversed(blocks):
            length = sum(len(line) + 1 for line in lines)
            if size + length > limit:
                if not kept:
                    kept.append((kind, tail_block(kind, lines, limit)))
                shortened = True
                break
            kept.append((kind, lines))
            size += length
        blocks = kept[::-1]
    rendered = [render_code(lines) if kind == "code" else render_text(lines) for kind, lines in blocks]
    return ("…\n\n" if shortened else "") + "\n\n".join(r for r in rendered if r)
