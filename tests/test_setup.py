"""The token prompt of `setup`: validation and Ctrl+V in a classic Windows console."""

import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from relay import cli  # noqa: E402

TOKEN = "123456789:" + "A" * 35
CTRL_V = chr(0x16)


def read_token(typed, current="", show=False, clipboard=None):
    """Run read_token with these answers typed; return (result, printed text)."""
    out = io.StringIO()
    patches = [mock.patch("builtins.input" if show else "getpass.getpass", side_effect=typed)]
    if os.name == "nt":
        from relay import winapi

        patches.append(mock.patch.object(winapi, "clipboard_text", return_value=clipboard))
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(out):
        for patch in patches:
            stack.enter_context(patch)
        return cli.read_token(current, show=show), out.getvalue()


class ReadTokenTests(unittest.TestCase):
    def test_valid_token(self):
        self.assertEqual(read_token([TOKEN])[0], TOKEN)

    def test_surrounding_spaces_are_ignored(self):
        self.assertEqual(read_token(["  %s \n" % TOKEN])[0], TOKEN)

    def test_empty_answer_keeps_current(self):
        self.assertEqual(read_token([""], current="old")[0], "old")

    def test_show_reads_visibly(self):
        self.assertEqual(read_token([TOKEN], show=True)[0], TOKEN)

    def test_gives_up_after_three_bad_answers(self):
        token, printed = read_token(["nope", "123", "abc:def"])
        self.assertIsNone(token)
        self.assertEqual(printed.count("isn't a bot token"), 3)

    def test_retry_after_bad_answer(self):
        self.assertEqual(read_token(["nope", TOKEN])[0], TOKEN)

    @unittest.skipUnless(os.name == "nt", "Ctrl+V reaches getpass only in a Windows console")
    def test_ctrl_v_pastes_clipboard(self):
        self.assertEqual(read_token([CTRL_V], clipboard=TOKEN + "\r\n")[0], TOKEN)

    @unittest.skipUnless(os.name == "nt", "Ctrl+V reaches getpass only in a Windows console")
    def test_ctrl_v_with_empty_clipboard(self):
        token, printed = read_token([CTRL_V, CTRL_V, CTRL_V], clipboard=None)
        self.assertIsNone(token)
        self.assertEqual(printed.count("clipboard has no text"), 3)

    def test_control_characters_get_a_hint(self):
        with mock.patch.object(cli, "paste_clipboard", side_effect=lambda text: text):
            token, printed = read_token([CTRL_V, TOKEN])
        self.assertEqual(token, TOKEN)
        self.assertIn("control characters", printed)


if __name__ == "__main__":
    unittest.main()
