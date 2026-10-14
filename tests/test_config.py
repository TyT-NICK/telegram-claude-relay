"""Unit tests for settings: value parsing, layering, and plugin.json staying in sync."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from relay import config  # noqa: E402


class CoerceTests(unittest.TestCase):
    def test_numbers_are_clamped(self):
        option = config.OPTIONS_BY_KEY["idle_seconds"]
        self.assertEqual(config.coerce(option, "300"), 300)
        self.assertEqual(config.coerce(option, "45.0"), 45)
        self.assertEqual(config.coerce(option, 1), option.min)
        with self.assertRaises(ValueError):
            config.coerce(option, "soon")

    def test_booleans(self):
        option = config.OPTIONS_BY_KEY["relay_finished"]
        self.assertIs(config.coerce(option, "false"), False)
        self.assertIs(config.coerce(option, "True"), True)
        self.assertIs(config.coerce(option, True), True)
        with self.assertRaises(ValueError):
            config.coerce(option, "maybe")

    def test_choices(self):
        option = config.OPTIONS_BY_KEY["when_unknown"]
        self.assertEqual(config.coerce(option, "away"), "away")
        with self.assertRaises(ValueError):
            config.coerce(option, "sometimes")


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_file = os.path.join(self.tmp.name, "config.json")
        self.claude_dir = os.path.join(self.tmp.name, "claude")
        os.mkdir(self.claude_dir)
        patches = [
            mock.patch.object(config, "CONFIG_FILE", config.Path(self.config_file)),
            mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.claude_dir}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        for var in [v for v in os.environ if v.startswith(("CLAUDE_PLUGIN_OPTION_", "TG_RELAY_"))]:
            self.addCleanup(os.environ.__setitem__, var, os.environ.pop(var))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, data):
        with open(path, "w") as fh:
            json.dump(data, fh)

    def test_defaults(self):
        cfg = config.load_config()
        self.assertEqual(cfg["idle_seconds"], 120)
        self.assertEqual(cfg["_sources"]["idle_seconds"], "default")

    def test_later_layers_win(self):
        self.write(self.config_file, {"idle_seconds": 60, "stop_wait": 5, "bot_token": "t", "chat_id": "7"})
        self.write(os.path.join(self.claude_dir, "settings.json"),
                   {"pluginConfigs": {"telegram-relay@somewhere": {"options": {"idle_seconds": 90}}}})
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_STOP_WAIT": "0"}):
            cfg = config.load_config()
        self.assertEqual(cfg["idle_seconds"], 90)
        self.assertEqual(cfg["_sources"]["idle_seconds"], "plugin settings")
        self.assertEqual(cfg["stop_wait"], 0)
        self.assertEqual((cfg["bot_token"], cfg["chat_id"]), ("t", 7))

    def test_invalid_value_keeps_lower_layer(self):
        self.write(self.config_file, {"idle_seconds": 60})
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_OPTION_IDLE_SECONDS": "later"}), \
                mock.patch.object(config, "log_error"):
            cfg = config.load_config()
        self.assertEqual(cfg["idle_seconds"], 60)
        self.assertEqual(cfg["_sources"]["idle_seconds"], "config.json")

    def test_save_config_keeps_only_explicit_keys(self):
        with mock.patch.object(config, "ensure_dirs"):
            config.save_config({"bot_token": "t", "chat_id": 7})
        with open(self.config_file) as fh:
            self.assertEqual(json.load(fh), {"bot_token": "t", "chat_id": 7})


class PluginManifestTests(unittest.TestCase):
    def test_user_config_matches_options(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            user_config = json.load(fh)["userConfig"]
        self.assertEqual(list(user_config), [o.key for o in config.OPTIONS])
        for option in config.OPTIONS:
            entry = user_config[option.key]
            self.assertEqual(entry["type"], option.type, option.key)
            self.assertEqual(entry["default"], option.default, option.key)
            self.assertEqual(entry.get("min"), option.min, option.key)
            self.assertEqual(entry.get("max"), option.max, option.key)
            self.assertEqual(tuple(entry.get("options") or ()) or None, option.choices, option.key)


if __name__ == "__main__":
    unittest.main()
