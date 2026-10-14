"""End-to-end tests: run the hooks as Claude Code would, against a fake Telegram server.

Run: python3 -m unittest discover tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from fake_telegram import CHAT, FakeTelegram

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "tg_relay.py")

Q1 = {"question": "Which framework?", "header": "FW", "multiSelect": False,
      "options": [{"label": "React", "description": "lib"}, {"label": "Vue", "description": "fw"}]}
Q2 = {"question": "Which extras?", "header": "Extras", "multiSelect": True,
      "options": [{"label": "Tests"}, {"label": "Docs"}, {"label": "CI"}]}
EVENT = {"cwd": "/home/u/myproj", "session_id": "s1"}


def ask_event(*questions, **extra):
    return dict(EVENT, tool_input={"questions": list(questions)}, **extra)


def answers(output):
    return output["hookSpecificOutput"]["updatedInput"]["answers"] if output else None


class HookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeTelegram()

    @classmethod
    def tearDownClass(cls):
        cls.fake.stop()

    def setUp(self):
        self.fake.reset()
        self.home = tempfile.mkdtemp(prefix="tgrelay-")
        self.claude_dir = tempfile.mkdtemp(prefix="claude-")
        self.env = dict(os.environ, TG_RELAY_HOME=self.home, CLAUDE_CONFIG_DIR=self.claude_dir,
                        TG_RELAY_BOT_TOKEN="x", TG_RELAY_CHAT_ID=str(CHAT),
                        TG_RELAY_API_BASE=self.fake.url, PYTHONIOENCODING="utf-8")
        for var in list(self.env):
            if var.startswith("CLAUDE_PLUGIN_OPTION_"):
                del self.env[var]
        self.cli("mode", "away")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.claude_dir, ignore_errors=True)

    # ------------------------------------------------------------ helpers

    def cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT] + list(args), env=self.env,
                              capture_output=True, text=True, encoding="utf-8", check=True).stdout

    def start_hook(self, kind, event, **options):
        env = dict(self.env, **{"CLAUDE_PLUGIN_OPTION_" + k.upper(): str(v) for k, v in options.items()})
        proc = subprocess.Popen([sys.executable, SCRIPT, "hook", kind], env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        proc.stdin.write(json.dumps(event))
        proc.stdin.close()
        return proc

    def finish(self, proc):
        with proc.stdout, proc.stderr:
            out = proc.stdout.read()
            err = proc.stderr.read()
        proc.wait(timeout=60)
        self.assertEqual(err.strip(), "")
        return json.loads(out) if out.strip() else None

    def hook(self, kind, event, **options):
        return self.finish(self.start_hook(kind, event, **options))

    def set_presence(self, seconds_ago):
        with open(os.path.join(self.home, "presence"), "w") as fh:
            json.dump({"last_active": time.time() - seconds_ago}, fh)

    # ------------------------------------------------------------ questions

    def test_ask_single_tap(self):
        self.fake.script = [[("tap", "Vue")]]
        out = self.hook("ask", ask_event(Q1))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["questions"], [Q1])
        self.assertEqual(answers(out), {"Which framework?": "Vue"})

    def test_ask_two_questions_with_multiselect(self):
        self.fake.script = [[("tap", "React")], [("tap", "Tests"), ("tap", "CI"), ("tap", "Done")]]
        out = self.hook("ask", ask_event(Q1, Q2))
        self.assertEqual(answers(out), {"Which framework?": "React", "Which extras?": "Tests, CI"})

    def test_ask_free_text_reply(self):
        self.fake.script = [[("reply", "Svelte please")]]
        out = self.hook("ask", ask_event(Q1))
        self.assertEqual(answers(out), {"Which framework?": "Svelte please"})

    def test_ask_at_desk_button_falls_back(self):
        self.fake.script = [[("tap", "At desk")]]
        self.assertIsNone(self.hook("ask", ask_event(Q1)))

    def test_ask_timeout_option(self):
        self.fake.script = [[]]
        start = time.time()
        self.assertIsNone(self.hook("ask", ask_event(Q1), answer_timeout=30))
        self.assertLess(time.time() - start, 45)

    def test_concurrent_prompts(self):
        p1 = self.start_hook("ask", ask_event(Q1))
        time.sleep(1.5)
        p2 = self.start_hook("ask", ask_event(Q2, cwd="/home/u/other"))
        time.sleep(1.5)
        (m1, _, k1), _ = self.fake.sent[-2:]
        self.fake.message("plain answer")  # no reply-to: goes to the newest prompt
        self.fake.tap(m1, k1, "React")     # button: goes to the prompt it belongs to
        self.assertEqual(answers(self.finish(p1)), {"Which framework?": "React"})
        self.assertEqual(answers(self.finish(p2)), {"Which extras?": "plain answer"})

    # ------------------------------------------------------------ permissions

    def test_permission_allow(self):
        self.fake.script = [[("tap", "Allow")]]
        out = self.hook("permission", dict(EVENT, tool_name="Bash", tool_input={"command": "rm -rf build"}))
        self.assertEqual(out["hookSpecificOutput"]["decision"], {"behavior": "allow"})

    def test_permission_always_allow(self):
        suggestions = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "npm test"}],
                        "behavior": "allow", "destination": "localSettings"}]
        self.fake.script = [[("tap", "Always")]]
        out = self.hook("permission", dict(EVENT, tool_name="Bash", tool_input={"command": "npm test"},
                                           permission_suggestions=suggestions))
        self.assertEqual(out["hookSpecificOutput"]["decision"]["updatedPermissions"], suggestions)

    def test_permission_deny_with_reason(self):
        self.fake.script = [[("reply", "use trash instead")]]
        out = self.hook("permission", dict(EVENT, tool_name="Bash", tool_input={"command": "rm -rf build"}))
        decision = out["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "deny")
        self.assertIn("use trash instead", decision["message"])

    def test_permission_leaves_interactive_tools_alone(self):
        self.assertIsNone(self.hook("permission", dict(EVENT, tool_name="AskUserQuestion", tool_input={})))
        self.assertEqual(self.fake.sent, [])

    # ------------------------------------------------------------ finished turns and notifications

    def test_stop_reply_continues(self):
        self.fake.script = [[("reply", "now run the tests")]]
        out = self.hook("stop", dict(EVENT, last_assistant_message="Done. Should I run tests?"))
        self.assertEqual(out["decision"], "block")
        self.assertIn("now run the tests", out["reason"])

    def test_stop_ok_ends(self):
        self.fake.script = [[("tap", "OK")]]
        self.assertIsNone(self.hook("stop", dict(EVENT, last_assistant_message="All done.")))

    def test_stop_wait_zero_only_notifies(self):
        start = time.time()
        self.assertIsNone(self.hook("stop", dict(EVENT, last_assistant_message="All done."), stop_wait=0))
        self.assertLess(time.time() - start, 5)
        self.assertEqual(len(self.fake.sent), 1)
        self.assertIsNone(self.fake.sent[0][2])

    def test_notify_skips_covered_types(self):
        self.hook("notify", dict(EVENT, notification_type="permission_prompt", message="perm"))
        self.hook("notify", dict(EVENT, notification_type="auth_success", message="Signed in"))
        self.assertEqual([t for _, t, _ in self.fake.sent], ["🔔 <b>myproj</b>\n\nSigned in"])

    # ------------------------------------------------------------ settings and modes

    def test_relay_switch_off(self):
        self.assertIsNone(self.hook("ask", ask_event(Q1), relay_questions="false"))
        self.assertEqual(self.fake.sent, [])

    def test_desk_mode_stays_local(self):
        self.cli("mode", "desk")
        self.assertIsNone(self.hook("ask", ask_event(Q1)))
        self.assertEqual(self.fake.sent, [])

    def test_auto_mode_uses_idle_seconds(self):
        self.cli("mode", "auto")
        self.set_presence(60)
        self.assertIsNone(self.hook("ask", ask_event(Q1)))  # default: away after 120 s
        self.assertEqual(self.fake.sent, [])
        self.fake.script = [[("tap", "Vue")]]
        out = self.hook("ask", ask_event(Q1), idle_seconds=30)
        self.assertEqual(answers(out), {"Which framework?": "Vue"})

    def test_auto_mode_reads_plugin_settings_file(self):
        self.cli("mode", "auto")
        self.set_presence(60)
        with open(os.path.join(self.claude_dir, "settings.json"), "w") as fh:
            json.dump({"pluginConfigs": {"telegram-relay@telegram-relay": {"options": {"idle_seconds": 45}}}}, fh)
        self.assertIn("idle_seconds", self.cli("status"))
        self.assertRegex(self.cli("status"), r"idle_seconds\s+45\s+\(plugin settings\)")
        self.fake.script = [[("tap", "React")]]
        self.assertEqual(answers(self.hook("ask", ask_event(Q1))), {"Which framework?": "React"})

    def test_auto_mode_back_at_desk_aborts(self):
        self.cli("mode", "auto")
        self.set_presence(600)
        proc = self.start_hook("ask", ask_event(Q1))
        time.sleep(2)
        self.set_presence(0)
        start = time.time()
        self.assertIsNone(self.finish(proc))
        self.assertLess(time.time() - start, 15)


if __name__ == "__main__":
    unittest.main()
