# Hosts

A host is where the receiver TUI runs and what the terminal adapters write into. Every host exposes the same
methods: `start`, `pane_pid` (the root process the ownership check descends from), `alive`, `capture`,
`send_literal`, `send_key`, `type_text` (human-proxy typing), `start_recording`, `attach_command`, `stop`; tmux,
zmx and zellij also have `attach_client`/`detach_client` (S8's attached human client in a PTY). The
engine picks the host from the adapter's `host_kind`; `Target.host_ref` is self-contained, so `agentcomms send`
rebuilds the host from the ref alone.

| host | ref | agent TERM | capture | recording | isolation |
|---|---|---|---|---|---|
| `tmux` | `agentcomms:<run>-<agent>` | `tmux-256color` | `capture-pane -p -J` | `pipe-pane` | `-L agentcomms -f tmux.conf` |
| `zmx` | `zmx:/tmp/ac/<run>-zmx:<run>-<agent>` | `xterm-256color` | `zmx history` (plain screen) | `zmx tail` (tracked pid) | `ZMX_DIR`, `HOME`, `XDG_STATE_HOME` under `/tmp/ac/<run>-zmx` |
| `zellij` | `zellij:/tmp/ac/<run>-zj:<run>-<agent>` | `xterm-256color` | `action dump-screen` | `zellij subscribe` (tracked pid) | `HOME`, `ZELLIJ_CONFIG_DIR`, `ZELLIJ_SOCKET_DIR` under `/tmp/ac/<run>-zj` |
| `iterm2` | `iterm2:<session id>` | `xterm-256color` | `async_get_screen_contents` | screen streamer to a text log | tabs of one persistent holder window (`user.agentcomms_holder=1`) |

## zmx

`vendor/bin/zmx` (see `vendor/REVIEW.md`). `zmx attach <name> <argv…>` needs a client terminal, so `start` runs it
in a throwaway 200x50 pty and closes the client once the session is listed; the daemon (parent of the pty child)
is the root pid. `zmx send` writes raw bytes to the session pty. Attach: `ZMX_DIR=… zmx attach <name>`.

## zellij

`vendor/bin/zellij`. `start` creates a background session (`attach --create-background <name> -- <argv…>`), then
attaches a throwaway 200x50 pty client so the session takes that size (a detached session is 50x50), and closes
it. The config dir holds `show_startup_tips false`, `pane_frames false` and a single-pane `bare` layout so no
wizard, bars or frames take input or rows. All actions address `--pane-id terminal_0`; without it, writes go to a
plugin pane and are lost. The root pid is the `zellij --server …/<name>` process.

## iterm2

The `iterm2` Python package talks to the user's running iTerm2 (`/Applications/Development/iTerm.app`, selected
with `IT2_APP_PATH`) over its Unix socket with the cookie from `iterm2.auth` (an AppleScript cookie request; no
prompt appeared on this machine). No iTerm2 preference is changed.

Cells run as tabs of one **holder window**, found by its window variable `user.agentcomms_holder=1`. The holder runs
a year-long `sleep` in a placeholder tab (`user.agentcomms_placeholder=1`) so it outlives its cell tabs. A cell tab
is created with `select=False` and `async_set_grid_size` asks for 200x50 (iTerm2 clamps to the screen).

- The holder persists across cells, runs and matrix processes. Cell cleanup closes only that cell's tab. Only
  `agentcomms cleanup --iterm-holder` closes the holder, and only when it has no cell tabs left.
- `Window.async_create` has no background option: a new window becomes key. So the holder is created only while
  iTerm2 is **not** the frontmost app (`lsappinfo front`, checked immediately before the create). If iTerm2 is
  frontmost the host polls every 2 s for up to 10 minutes, then the cell is an `env_error` with the note
  `iterm-holder-blocked: iTerm2 frontmost`. A creation lock (`/tmp/ac/iterm-holder.lock`) keeps two processes from
  creating two holders.
- `agentcomms iterm-holder [--wait SECONDS]` creates the holder on demand; run it while another app is in front.
- Focus is read (after `app.async_refresh()` and a short settle) before and after creating the holder, creating a
  tab, and closing tabs or the holder. A changed frontmost app is restored with `open`; an iTerm2 window is never
  activated and no window without the holder variable is ever closed or modified. A detected change is recorded as
  `focus_stolen=yes` in the record notes (error records and hostcheck rows included); every start also notes
  `iterm-focus <before> -> <after>`.
