#!/usr/bin/env python3
"""Relay Claude Code prompts to Telegram. Run without arguments for usage; see README.md."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from relay.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
