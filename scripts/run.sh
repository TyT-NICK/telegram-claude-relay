#!/usr/bin/env bash
# Run tg_relay.py with whichever Python 3 this machine has.
#
# Hooks call this instead of python3 directly: on Windows, python3 is often the
# Microsoft Store placeholder, and the real interpreter is python or py.
# Exit code 2 would block Claude Code, so failures are reported as 1.

script="$(dirname "$0")/tg_relay.py"
for python in "python3" "python" "py -3"; do
    if $python -c 'import sys; assert sys.version_info >= (3, 8)' </dev/null >/dev/null 2>&1; then
        $python "$script" "$@"
        code=$?
        [ "$code" -eq 2 ] && code=1
        exit "$code"
    fi
done
echo "tg-relay: Python 3.8+ not found (tried python3, python, py)" >&2
exit 1
