# Telegram Relay for Claude Code

Answer Claude Code from your phone while you're away from the keyboard. If your watch mirrors phone notifications, you'll see the alerts there too.

| When Claude… | You get in Telegram | You can… |
| --- | --- | --- |
| asks you to pick options (`AskUserQuestion`) | the question with one button per option | tap an option (multi-select: toggle, then **Done**), or reply with your own answer |
| asks permission to run a tool | the tool and its command or file | **Allow**, **Always allow**, **Deny**, or reply with text to deny and say what to do instead |
| finishes its turn | the end of Claude's last message | reply to keep the session going, or tap **👍 OK** |
| sends any other notification | a plain alert | — |

Every prompt also has a **💻 At desk** button. It closes the Telegram prompt and shows the normal one in Claude Code. A prompt nobody answers in time falls back to Claude Code the same way, so nothing gets stuck.

It works the same in the VS Code extension, the terminal CLI and the Claude desktop app, because it is built on Claude Code [hooks](https://code.claude.com/docs/en/hooks). It runs on Linux, macOS and Windows and needs only Python 3.8+ (standard library) and a Telegram bot. On Windows, hooks run through Git Bash, which Claude Code normally uses there.

## Setup

1. **Create a bot.** In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the token. Use a bot that nothing else reads updates from: two programs polling one bot steal each other's messages.

2. **Pair it with your chat.** On the machine where Claude Code runs, get a copy of this repo and run setup once:

   ```bash
   git clone https://github.com/TyT-NICK/telegram-claude-relay.git
   python3 telegram-claude-relay/scripts/tg_relay.py setup
   ```

   On Windows, run it in PowerShell with `python` (or `py`) instead of `python3`.

   Paste the token when asked. It isn't echoed. Then send the `/pair <code>` message it prints to your bot. The token and chat id are saved to `~/.config/tg-relay/config.json` with `600` permissions. You can supply them through the environment instead: `TG_RELAY_BOT_TOKEN`, `TG_RELAY_CHAT_ID`.

3. **Install the plugin.** Inside Claude Code (in the desktop app too):

   ```
   /plugin marketplace add TyT-NICK/telegram-claude-relay
   /plugin install telegram-relay@telegram-relay
   ```

   Or from a shell: `claude plugin marketplace add TyT-NICK/telegram-claude-relay`, then `claude plugin install telegram-relay@telegram-relay`. A local clone also works as a marketplace, for example `/plugin marketplace add ./telegram-claude-relay`, where the client allows local paths. Pick user scope so it applies to every project. Claude Code then shows the plugin's [settings](#settings). The defaults are fine to start with. Restart Claude Code, or run `/reload-plugins`.

4. **Try it.**

   ```bash
   python3 telegram-claude-relay/scripts/tg_relay.py test     # sends a sample question
   python3 telegram-claude-relay/scripts/tg_relay.py status   # pairing, mode, presence detection
   ```

   Or run `/telegram-relay:status` in Claude Code.

## Modes

Switch with `/telegram-relay:mode <mode>` in Claude Code, or `tg_relay.py mode <mode>` in a shell.

| Mode | Behaviour |
| --- | --- |
| `auto` (default) | Telegram once you've had no keyboard or mouse input for `idle_seconds`. If you come back while a prompt is waiting, it moves back to Claude Code within a few seconds. |
| `away` | Everything goes to Telegram. |
| `desk` | Everything stays in Claude Code. |
| `off` | The plugin does nothing. |

### How `auto` detects that you're away

The first source that answers wins:

1. The **presence file** `~/.config/tg-relay/presence`, if it was written in the last 90 s: `{"last_active": <epoch seconds>}`. An editor extension or any other tool can keep it updated.
2. Your own `idle_command`, which prints idle time in milliseconds.
3. The system's idle time:
   - **Windows**: `GetLastInputInfo`
   - **macOS**: `HIDIdleTime` from `ioreg`
   - **Linux**: a locked screen first (`loginctl` `LockedHint` or the GNOME screensaver; always counts as away), then **GNOME** (Wayland or X11) `org.gnome.Mutter.IdleMonitor`, then **X11** `xprintidle`

If none of these work, `when_unknown` decides. The default `desk` keeps prompts local, so you then use `away` when you leave. That is the usual situation over Remote-SSH, because hooks run on the remote host. Run `status` to see which source is used.

KDE example for `idle_command`: `qdbus org.freedesktop.ScreenSaver /ScreenSaver GetSessionIdleTime`. Check the unit on your system; the script expects milliseconds.

## Settings

Change these in Claude Code with `/config`, where each one appears as a row. Claude Code saves them in `~/.claude/settings.json` under `pluginConfigs` → `telegram-relay@telegram-relay` → `options`, and you can edit them there too. If a change doesn't apply right away, run `/reload-plugins`.

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

`config.json` also holds what `setup` stores: `bot_token` and `chat_id`. The environment variables `TG_RELAY_BOT_TOKEN` and `TG_RELAY_CHAT_ID` override those two. Two extra keys can be set there: `notify_skip`, the notification types not forwarded (default `["permission_prompt", "idle_prompt"]`, which the other hooks already cover), and `api_base` for a Bot API proxy. Set `TG_RELAY_HOME` to move the whole state directory.

Waits are capped at 3500 s to stay under the 3600 s hook timeout in `hooks/hooks.json`.

## Without the plugin system

Add the hooks to `~/.claude/settings.json` yourself. Copy the `hooks` object from [hooks/hooks.json](hooks/hooks.json) and replace `${CLAUDE_PLUGIN_ROOT}` with the absolute path of this repo.

The hooks call `scripts/run.sh`, which picks the first working Python (`python3`, `python`, then `py -3`). That skips the Microsoft Store placeholder that `python3` often is on Windows. It also never exits with code 2, which Claude Code would read as "block".

## Good to know

- **Several sessions at once.** One process polls Telegram and the others share its updates through `~/.config/tg-relay/run/inbox`. Buttons always reach the right prompt. Replies reach the prompt you reply to (swipe-reply in Telegram). A plain message goes to the newest prompt. Message titles show the project folder name.
- **Chatting after Claude finishes.** Each reply continues the turn through the Stop hook. Claude Code ends the turn anyway after 8 continuations in a row; the next prompt starts a fresh count.
- **Watches.** Phone notifications are mirrored to the watch, including Huawei/HarmonyOS watches through the Huawei Health app. Telegram's inline buttons don't show on most watches, so you tap on the phone.
- **Errors.** Any failure makes the hook fall back to the normal prompt. Errors are logged to `~/.config/tg-relay/run/error.log`.
- **Security.** Only the paired chat is accepted. Anyone holding the bot token could read the prompts, so keep it private.

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
  telegram.py                    Bot API client, message formatting
  inbox.py                       one update stream shared by all waiting hooks
  request.py                     one prompt waiting for an answer
  storage.py                     state directory, file helpers, lock
  winapi.py                      Windows idle time and process checks (ctypes)
  cli.py                         setup, status, mode, test
  hooks/                         ask, permission, stop, notify: one module per hook
tests/                           python3 -m unittest discover -s tests
```

The tests run the hooks against a fake Telegram server, so they need no bot or network. Adding a setting takes two edits: `OPTIONS` in `scripts/relay/config.py` and `userConfig` in `plugin.json`. A test checks that the two match.
