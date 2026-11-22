# Terminal adapters (Task 6)

Terminal adapters write the payload into a host (`send_literal`, or a buffer paste for `tmux-buffer` and
`zellij-paste`) and then press Enter with `send_key("Enter")`; they differ in what bytes reach the receiver. `agentcomms hostcheck` records exactly which (`results/hostcheck.md`).

| adapter | host | bytes written | then |
|---|---|---|---|
| `tmux-keys` | tmux | `send-keys -l <text>` | one Enter |
| `tmux-paste` | tmux | `send-keys -l ESC[200~ <text> ESC[201~` | one Enter |
| `tmux-paste-retry` | tmux | as `tmux-paste` | Enter, then up to 3 more Enters (see below) |
| `tmux-buffer` | tmux | `load-buffer -b <name> -` + `paste-buffer -p -d -b <name>` | one Enter |
| `zmx-send` / `zmx-paste` | zmx | `zmx send <text>` / bracketed `zmx send` | one Enter (`\r`) |
| `zellij-write` / `zellij-paste` | zellij | `action write-chars` / `action paste` (native bracketed paste) | one Enter (`write 13`) |
| `iterm2-text` / `iterm2-paste` | iterm2 | `async_send_text(<text>)` / bracketed | one Enter (`\r`) |

## tmux-paste-retry

Before sending, the pane is captured. Enter is retried only if the receiver was then confirmed idle (ready
prompt and footer, no dialog) with an empty input box (blank composer after removing box characters and known
placeholders such as Codex's "Ask Codex to do anything"). After the first Enter, every 1.5 s the pane is captured
again; if the composer still holds the last 16 non-blank characters of the message (or a paste placeholder such
as `[Pasted text`), and no dialog is showing, one more Enter is sent, at most 3 times. A human draft before the
send, a dialog, or an unreadable pane disables retries (`detail` says `retry-disabled`). The receipt carries the
retry count; the record's `retries` field is that count.

## tmux-buffer

tmux replaces each LF in a buffer with CR when it pastes (unless `paste-buffer -r`), so multi-line text reaches
the receiver with CR line breaks; hostcheck shows the effect.
