"""Markdown to Telegram HTML: conversion, nesting fixes, and the plain-text fallback."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from fake_telegram import CHAT, FakeTelegram  # noqa: E402
from relay.markdown import inline, to_html  # noqa: E402
from relay.telegram import Telegram, fix_nesting, plain_text  # noqa: E402
from telegram_rules import problems  # noqa: E402

NBSP = " "

# A real end-of-turn message, as Telegram showed it with raw Markdown
REAL_MESSAGE = """You don't have to tap it. 👍 OK just ends the wait early. If you ignore the message, the session ends by itself after `stop_wait`, 10 minutes by default.

**Why there's a wait at all:** a hook can only act while Claude Code is running it. The cost is that the app shows the session as busy during the wait.

**If that's annoying, your options:**
1. **Notify only:** set `stop_wait` to `0`. You get "Claude finished" with no wait and no OK button.
2. **Shorter wait:** for example, `stop_wait` = `120`.
3. **Wait only when Claude ends with a question** (code change): if the last message ends with "?", wait for a reply.

I'd go with option 3; it's a small change. Should I make it? Options 1 and 2 are just the `stop_wait` setting, in `~/.claude/settings.json` under `pluginConfigs`."""


def render(markdown, limit=None):
    """Convert and apply Telegram's nesting rules, failing on anything Telegram would reject."""
    out = fix_nesting(to_html(markdown, limit))
    found = problems(out)
    if found:
        raise AssertionError("%s in %r" % (found, out))
    return out


class InlineTests(unittest.TestCase):
    def test_styles(self):
        self.assertEqual(render("**a**, *b*, __c__, _d_ and ~~e~~"),
                         "<b>a</b>, <i>b</i>, <b>c</b>, <i>d</i> and <s>e</s>")

    def test_identifiers_and_arithmetic_stay_plain(self):
        self.assertEqual(render("set idle_seconds and stop_wait, 2 * 3 * 4"),
                         "set idle_seconds and stop_wait, 2 * 3 * 4")

    def test_html_is_escaped(self):
        self.assertEqual(render("a < b & c > d"), "a &lt; b &amp; c &gt; d")
        self.assertEqual(render("`<b>` & **x**"), "<code>&lt;b&gt;</code> &amp; <b>x</b>")

    def test_code_inside_bold_is_split_out(self):
        self.assertEqual(render("**see `x` now**"), "<b>see </b><code>x</code><b> now</b>")
        self.assertEqual(render("**`x`**"), "<code>x</code>")

    def test_markers_inside_code_are_kept(self):
        self.assertEqual(render("`**not bold**`"), "<code>**not bold**</code>")

    def test_links(self):
        self.assertEqual(render("[docs](https://example.com/a?b=1&c=2)"),
                         '<a href="https://example.com/a?b=1&amp;c=2">docs</a>')
        self.assertEqual(render("see [README.md](../README.md)"), "see README.md")

    def test_inline_limit(self):
        self.assertEqual(inline("**abcdef**", 4), "**ab…")


class BlockTests(unittest.TestCase):
    def test_headings_and_lists(self):
        self.assertEqual(render("## Setup\n- one\n  - two\n1. first"),
                         "<b>Setup</b>\n• one\n%s• two\n1. first" % (NBSP * 2))

    def test_code_block_with_language(self):
        self.assertEqual(render("```bash\necho 'hi' && ls\n```"),
                         '<pre><code class="language-bash">echo \'hi\' &amp;&amp; ls</code></pre>')

    def test_code_block_without_language_keeps_markdown(self):
        self.assertEqual(render("```\n**x** `y`\n```"), "<pre>**x** `y`</pre>")

    def test_indented_code_block_in_a_list(self):
        self.assertEqual(render("1. Run:\n   ```\n   make\n   ```"), "1. Run:\n\n<pre>make</pre>")

    def test_unclosed_code_block(self):
        self.assertEqual(render("```python\nx = 1"), '<pre><code class="language-python">x = 1</code></pre>')

    def test_table(self):
        table = "| Mode | What happens |\n|---|---|\n| `auto` | **Idle** detection |\n| `away` | Always |"
        self.assertEqual(render(table),
                         "<i>Mode · What happens</i>\n"
                         "• <code>auto</code> — <b>Idle</b> detection\n"
                         "• <code>away</code> — Always")

    def test_table_right_after_a_line(self):
        self.assertEqual(render("Options:\n| a | b |\n|---|---|\n| 1 | 2 |"),
                         "Options:\n<i>a · b</i>\n• <b>1</b> — 2")

    def test_blockquote_drops_code_style(self):
        self.assertEqual(render("> use `x` and [y](https://e.com)"), "<blockquote>use x and y</blockquote>")

    def test_rule(self):
        self.assertEqual(render("a\n\n---\n\nb"), "a\n\n──────────\n\nb")

    def test_real_message(self):
        out = render(REAL_MESSAGE)
        self.assertNotIn("**", out)
        self.assertNotIn("`", out)
        self.assertIn("<b>Why there's a wait at all:</b>", out)
        self.assertIn("1. <b>Notify only:</b> set <code>stop_wait</code> to <code>0</code>.", out)


class LimitTests(unittest.TestCase):
    def test_keeps_the_last_blocks(self):
        markdown = "\n\n".join("paragraph %d" % i for i in range(100))
        out = render(markdown, limit=60)
        self.assertTrue(out.startswith("…\n\n"))
        self.assertTrue(out.endswith("paragraph 99"))
        self.assertNotIn("paragraph 90", out)

    def test_long_code_block_keeps_its_end_and_stays_valid(self):
        markdown = "```python\n" + "\n".join("line_%d = %d" % (i, i) for i in range(500)) + "\n```"
        out = render(markdown, limit=200)
        self.assertTrue(out.startswith('…\n\n<pre><code class="language-python">'))
        self.assertIn("line_499 = 499", out)
        self.assertLess(len(out), 400)

    def test_fits_telegram_after_the_header(self):
        out = render("x" * 10000 + "\n\n" + "**y** " * 2000, limit=3000)
        self.assertLessEqual(len(plain_text(out)), 3100)


class NestingTests(unittest.TestCase):
    def test_pre_with_language_is_kept(self):
        text = '<pre><code class="language-py">x</code></pre>'
        self.assertEqual(fix_nesting(text), text)

    def test_code_in_nested_styles(self):
        self.assertEqual(fix_nesting("<b>a <i>b <code>c</code> d</i></b>"),
                         "<b>a <i>b </i></b><code>c</code><b><i> d</i></b>")

    def test_link_inside_quote_keeps_text(self):
        self.assertEqual(fix_nesting('<blockquote>q <a href="u">l</a></blockquote>'),
                         "<blockquote>q l</blockquote>")

    def test_plain_text(self):
        self.assertEqual(plain_text("<b>a &amp; b</b> &lt;c&gt;"), "a & b <c>")


class FallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeTelegram()
        cls.tg = Telegram({"api_base": cls.fake.url, "bot_token": "x", "chat_id": CHAT})

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.reset()

    def test_rejected_html_is_resent_as_plain_text(self):
        self.tg.send("<u><s>x</u></s> &amp; y")
        self.assertEqual(len(self.fake.rejected), 1)
        self.assertEqual(self.fake.sent[-1][1], "x & y")

    def test_valid_html_is_sent_as_is(self):
        self.tg.send("<b>see <code>x</code></b>")
        self.assertEqual(self.fake.rejected, [])
        self.assertEqual(self.fake.sent[-1][1], "<b>see </b><code>x</code>")


if __name__ == "__main__":
    unittest.main()
