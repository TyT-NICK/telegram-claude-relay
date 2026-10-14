"""Platform-specific pieces: the Python launcher, process checks and idle detection."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from relay import inbox, presence  # noqa: E402

RUN_SH = os.path.join(ROOT, "scripts", "run.sh")


def dead_pid():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


class ProcessTests(unittest.TestCase):
    def test_pid_alive(self):
        self.assertTrue(inbox.pid_alive(os.getpid()))
        self.assertFalse(inbox.pid_alive(dead_pid()))

    def test_stale_pending_requests_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(inbox, "PENDING", Path(tmp)):
            for rid, pid in (("live", os.getpid()), ("dead", dead_pid())):
                with open(os.path.join(tmp, rid + ".json"), "w") as fh:
                    json.dump({"pid": pid, "created": time.time()}, fh)
            self.assertEqual(list(inbox.live_requests()), ["live"])
            self.assertEqual(os.listdir(tmp), ["live.json"])


class IdleTests(unittest.TestCase):
    def test_detect_idle_on_this_platform(self):
        with mock.patch.object(presence, "presence_file_idle", return_value=None):
            idle, source = presence.detect_idle({"idle_command": ""})
        if sys.platform in ("win32", "darwin"):
            self.assertIsNotNone(idle)
        if idle is not None:
            self.assertGreaterEqual(idle, 0)
            self.assertTrue(source)

    def test_idle_command_wins_over_built_in(self):
        cmd = '"%s" -c "print(4200)"' % sys.executable
        with mock.patch.object(presence, "presence_file_idle", return_value=None):
            self.assertEqual(presence.detect_idle({"idle_command": cmd}), (4.2, "idle_command"))


@unittest.skipUnless(shutil.which("bash"), "bash not installed")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="tgrelay-")
        self.env = dict(os.environ, TG_RELAY_HOME=self.home, PYTHONIOENCODING="utf-8")
        for var in ("TG_RELAY_BOT_TOKEN", "TG_RELAY_CHAT_ID"):
            self.env.pop(var, None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_sh(self, *args, stdin=""):
        return subprocess.run(["bash", RUN_SH] + list(args), input=stdin, env=self.env,
                              capture_output=True, text=True, encoding="utf-8")

    def test_finds_python(self):
        out = self.run_sh("mode")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "auto"))

    def test_unpaired_hook_is_a_no_op(self):
        out = self.run_sh("hook", "stop", stdin=json.dumps({"last_assistant_message": "hi"}))
        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_never_exits_with_blocking_code(self):
        # Python exits 2 when the script is missing; the launcher must not pass that on
        broken = os.path.join(self.home, "run.sh")
        shutil.copy(RUN_SH, broken)
        out = subprocess.run(["bash", broken, "status"], env=self.env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)


if __name__ == "__main__":
    unittest.main()
