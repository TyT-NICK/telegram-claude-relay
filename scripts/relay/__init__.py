"""Relay Claude Code prompts to Telegram and answer them from your phone.

Modules:
    storage     state directory, small file helpers, cross-process lock
    config      settings (defaults < config.json < plugin settings < environment) and mode
    presence    idle detection and the decision to route a prompt to Telegram
    telegram    Bot API client and message formatting helpers
    inbox       one Telegram update stream shared by all waiting hook processes
    request     one prompt waiting for an answer
    hooks/      one module per Claude Code hook
    cli         command line: setup, status, mode, test, hook
"""
