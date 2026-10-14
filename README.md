# Telegram Relay for Claude Code

Answer Claude Code from your phone while you're away from the keyboard. If your watch shows your phone's notifications, you'll see the messages there too.

| When Claude… | You get in Telegram | You can… |
| --- | --- | --- |
| asks you to pick options (`AskUserQuestion`) | the question with one button per option | tap an option (multi-select: toggle, then **Done**), or reply with your own answer |
| asks permission to run a tool | the tool and its command or file | **Allow**, **Deny**, **Always allow** (when Claude Code offers a rule for it), or reply with text to deny and say what to do instead |
| finishes its turn | the end of Claude's last message | reply to keep the session going, or tap **👍 No reply needed** to end the turn |
| sends any other notification | a plain alert | — |

Questions and permission prompts also have a **💻 At desk** button, which closes the Telegram prompt and shows the normal one in Claude Code. If nobody answers in time, the prompt goes back to Claude Code the same way, so nothing gets stuck.

It is built on Claude Code [hooks](https://code.claude.com/docs/en/hooks), so it works wherever Claude Code runs hooks: the terminal CLI, the VS Code extension and the desktop app.

**Requirements**
- Claude Code v2.1.271 or later
- Python 3.8+ (standard library only)
- a Telegram bot
- on Windows, Git Bash, which Claude Code uses to run hooks there

Linux, macOS and Windows are supported.

## Setup

1. **Create a bot.** In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token. Use a bot that nothing else reads updates from: two programs polling one bot steal each other's messages.

2. **Pair it with your chat.** On the machine where Claude Code runs, get a copy of this repo and run setup once:

   ```bash
   git clone https://github.com/TyT-NICK/telegram-claude-relay.git
   python3 telegram-claude-relay/scripts/tg_relay.py setup
   ```

   On Windows, use `python` (or `py`) instead of `python3`.

   Paste the token when asked. It isn't shown as you type. In a classic Windows console, Ctrl+V reads the token from the clipboard, and right-click pastes as well. Run `setup --show` to see what you type. Then send your bot the `/pair <code>` message that setup prints.

   The token and chat id are saved to `~/.config/tg-relay/config.json`, which on Linux and macOS is readable only by you. You can supply them through the environment instead: `TG_RELAY_BOT_TOKEN`, `TG_RELAY_CHAT_ID`.

3. **Install the plugin.** Inside Claude Code:

   ```
   /plugin marketplace add TyT-NICK/telegram-claude-relay
   /plugin install telegram-relay@telegram-relay
   ```

   Or from a shell: `claude plugin marketplace add TyT-NICK/telegram-claude-relay`, then `claude plugin install telegram-relay@telegram-relay`. Choose user scope so it applies to every project. Then run `/reload-plugins`, or restart Claude Code.

   The defaults are fine to start with. See [Settings](#settings) to change them.

4. **Try it.**

   ```bash
   python3 telegram-claude-relay/scripts/tg_relay.py test     # sends a sample question
   python3 telegram-claude-relay/scripts/tg_relay.py status   # pairing, mode, presence detection
   ```

   Or run `/telegram-relay:status` in Claude Code.

### Updating

`/reload-plugins` reloads the installed copy; it doesn't check GitHub. To get a new version:

1. Run `/plugin marketplace update telegram-relay`.
2. Update the plugin from the **Installed** tab of `/plugin`.

If the version still doesn't change, remove the marketplace, add it again, and reinstall. Your pairing is kept in `~/.config/tg-relay`, so it survives a reinstall.

## Modes

Switch with `/telegram-relay:mode <mode>` in Claude Code, or `tg_relay.py mode <mode>` in a shell. The mode is stored in `~/.config/tg-relay/mode`, so it applies to every Claude Code session on that machine and survives restarts.

| Mode | Behaviour |
| --- | --- |
| `auto` (default) | Telegram once you've had no keyboard or mouse input for `idle_seconds`. If you come back while a question or permission prompt is waiting, it moves back to Claude Code within about 10 seconds. |
| `away` | Everything goes to Telegram. |
| `desk` | Everything stays in Claude Code. |
| `off` | The plugin does nothing. |

### How `auto` detects that you're away

The first source that answers wins:

1. The **presence file** `~/.config/tg-relay/presence`, if it was written in the last 90 s: `{"last_active": <epoch seconds>}`. Any tool, such as an editor extension or a script, can keep it updated.
2. Your own `idle_command`, which prints idle time in milliseconds.
3. The system's idle time:
   - **Windows**: `GetLastInputInfo`
   - **macOS**: `HIDIdleTime` from `ioreg`
   - **Linux**: a locked screen first (`loginctl` `LockedHint` or the GNOME screensaver; always counts as away), then **GNOME** (Wayland or X11) `org.gnome.Mutter.IdleMonitor`, then **X11** `xprintidle`

If none of these work, `when_unknown` decides. The default `desk` keeps prompts in Claude Code, so you switch to `away` when you leave. This is typical over Remote-SSH, where hooks run on the remote host. Run `status` to see which source is used.

KDE example for `idle_command`: `qdbus org.freedesktop.ScreenSaver /ScreenSaver GetSessionIdleTime`. Check the unit on your system; the script expects milliseconds.

## Settings

Change them with `/plugin configure telegram-relay@telegram-relay`, or in the terminal's `/config` panel, where each setting is a row. Claude Code saves them in `~/.claude/settings.json` under `pluginConfigs` → `telegram-relay@telegram-relay` → `options`, and you can edit them there too. If a change doesn't apply right away, run `/reload-plugins`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `idle_seconds` | `120` | Seconds without keyboard or mouse input before `auto` counts you as away (10–86400) |
| `when_unknown` | `desk` | What `auto` does when idle time can't be detected: `desk` or `away` |
| `idle_command` | empty | Shell command that prints idle time in milliseconds |
| `answer_timeout` | `1800` | Seconds a question or permission prompt waits for Telegram before going back to Claude Code (30–3500) |
| `stop_wait` | `600` | Seconds to wait for a reply after Claude finishes. `0` = notify only (0–3500) |
| `relay_questions` | `true` | Send multiple-choice questions to Telegram |
| `relay_permissions` | `true` | Send permission prompts to Telegram |
| `relay_finished` | `true` | Send a message when Claude finishes |
| `relay_notifications` | `true` | Forward other notifications |

Run `tg_relay.py status` to see the value in effect for each setting and where it came from.

Each setting is resolved in this order, later ones winning:

1. built-in default
2. `~/.config/tg-relay/config.json`, using the same keys. This is useful when you install the hooks without the plugin system.
3. the plugin settings above

`config.json` also holds what `setup` stores: `bot_token` and `chat_id`. The environment variables `TG_RELAY_BOT_TOKEN` and `TG_RELAY_CHAT_ID` override those two.

Two more keys can only be set in `config.json`:
- `notify_skip`: notification types that aren't forwarded. The default is `["permission_prompt", "idle_prompt"]`, because the other hooks already cover them.
- `api_base`: the address of a Bot API proxy.

Set `TG_RELAY_HOME` to move the whole state directory.

Waits are capped at 3500 s to stay under the 3600 s hook timeout in `hooks/hooks.json`.

## Without the plugin system

Add the hooks to `~/.claude/settings.json` yourself. Copy the `hooks` object from [hooks/hooks.json](hooks/hooks.json) and replace `${CLAUDE_PLUGIN_ROOT}` with the absolute path of your clone. The `/telegram-relay:*` commands come with the plugin, so use `tg_relay.py mode` and `tg_relay.py status` instead.

The hooks call `scripts/run.sh`, which picks the first working Python (`python3`, `python`, then `py -3`). That skips the Microsoft Store placeholder that `python3` often is on Windows. It also never exits with code 2, which Claude Code would read as "block".

## Good to know

- **Replying after Claude finishes.** A reply can only reach Claude while its turn is still open, so the Stop hook keeps the turn open for `stop_wait` seconds after the "Claude finished" message. During that time Claude Code shows the session as busy. Tap **👍 No reply needed** to end it early. Each reply continues the turn, and Claude Code ends the turn anyway after 8 continuations in a row.
- **Several sessions at once.** One process polls Telegram and the others share its updates through `~/.config/tg-relay/run/inbox`. A button press always reaches the prompt it belongs to. A swipe-reply reaches the message you reply to, and a plain message goes to the newest prompt. Message titles show the project folder name.
- **Watches.** The messages appear on a smartwatch like any other phone notification. Telegram's buttons may not be available on the watch, so you may need the phone to answer.
- **Formatting.** Claude's Markdown is converted to Telegram formatting: bold, italic, code and code blocks, links and quotes. Headings become bold lines, lists get bullets, and each table row becomes a `• first cell — other cells` line, since Telegram has no tables. If Telegram still rejects a message's formatting, it is resent as plain text.
- **Errors.** If a hook fails, Claude Code shows its normal prompt. Errors are logged to `~/.config/tg-relay/run/error.log`.
- **Security.** Only the paired chat is accepted, and anyone in that chat can approve tool use. Anyone holding the bot token could read the prompts, so keep it private.

## Layout

```
.claude-plugin/plugin.json       plugin manifest, including the settings (userConfig)
.claude-plugin/marketplace.json  lets this repo be added as a marketplace
hooks/hooks.json                 hook registrations
commands/                        /telegram-relay:mode and /telegram-relay:status
scripts/run.sh                   launcher used by the hooks: finds Python, never exits 2
scripts/tg_relay.py              entry point
scripts/relay/
  config.py                      settings and mode
  presence.py                    idle detection, decides whether a prompt goes to Telegram
  telegram.py                    Bot API client, Telegram's nesting rules, plain-text fallback
  markdown.py                    Markdown to Telegram HTML
  inbox.py                       one update stream shared by all waiting hooks
  request.py                     one prompt waiting for an answer
  storage.py                     state directory, file helpers, lock
  winapi.py                      Windows idle time, process checks and clipboard (ctypes)
  cli.py                         setup, status, mode, test
  hooks/                         ask, permission, stop, notify: one module per hook
tests/                           python3 -m unittest discover -s tests
```

The tests run the hooks against a fake Telegram server that enforces Telegram's formatting rules, so they need no bot or network. Adding a setting takes two edits: `OPTIONS` in `scripts/relay/config.py` and `userConfig` in `plugin.json`. A test checks that the two match.

## License

[MIT](LICENSE)
