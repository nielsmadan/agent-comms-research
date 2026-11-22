# Matrix

Updated: 2026-10-29 03:32:05 · all stages

Cells are k/n: k good outcomes (per `agentcomms/scoring.py`) out of n verdicts. `error` (harness failure or failed precondition), `n/a` and `env_error` records are not counted in n; `err N` and `harm N` list them; `held N` counts messages the receiver parked for a human Deny/Deliver (counted in n, never good). The `macOS` column is the major version from `versions.os`; records written before it existed count as 26. `condition` is `raw` (no sandbox, isolated homes), `nono` (receiver, backend and harness-side sender under the user's `nono run -p <agent>-local` launcher) or `raw + user config` (the user's real global config loaded, Task 10). Only frequent failures are detectable at these rep counts.

| agent | mechanism | host | backend | macOS | condition | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S9 | S10 | S11 | S12 | SCALE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude | agent-deck | tmux | none | 27 | raw | 2/2 | 3/3 | 1/1 | 0/1 | 0/0 · err 3 | n/a | 0/3 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| claude | claude-channel | tmux | none | 26 | raw | 2/2 | - | - | 1/1 | - | - | - | - | - | - | - | - | - |
| claude | claude-channel | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| claude | claude-channel | tmux | none | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | 12/12 |
| claude | claude-channel | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| claude | claude-uds | tmux | none | 26 | raw | 0/1 · held 1 | - | - | - | - | - | - | - | - | - | - | - | - |
| claude | claude-uds | tmux | none | 27 | raw | 0/2 · held 2 | - | - | 0/1 · held 1 | - | - | 0/1 · held 1 | 0/1 · held 1 | 1/1 | - | - | - | - |
| claude | claude-uds-accept | tmux | none | 26 | raw | 2/2 | - | - | - | - | - | - | - | - | - | - | - | - |
| claude | claude-uds-accept | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| claude | claude-uds-accept | tmux | none | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| claude | claude-uds-accept | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| claude | claude-uds-child | tmux | none | 26 | raw | 2/2 | - | - | - | - | - | - | - | - | - | - | - | - |
| claude | claude-uds-child | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| claude | claude-uds-child | tmux | none | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| claude | claude-uds-child | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| claude | codex-queue+claude-uds-accept | tmux | codex-daemon | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | codex-remote-start+claude-uds-accept | tmux | codex-app-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | codex-remote-steer+claude-uds-accept | tmux | codex-app-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | csd | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 0/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 0/1 | 0/1 | n/a | - |
| claude | gc-nudge | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 0/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 1/1 | 0/1 | 1/1 | - |
| claude | hcom | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 | 1/1 | 0/3 | 1/1 | 3/3 | 1/1 | 2/2 | 1/1 | 1/1 | n/a | - |
| claude | intercom | tmux | none | 27 | raw | 0/2 · held 2 | - | - | 0/1 · held 1 | - | - | 0/1 · held 1 | 0/1 · held 1 | - | - | - | - | - |
| claude | intercom-accept | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 1/1 | n/a | 1/1 | 3/3 | 0/1 | - | 1/1 | 1/1 | 0/1 | - |
| claude | iterm2-paste | iterm2 | none | 27 | raw | 1/1 | - | - | 0/1 | - | - | 0/1 | - | - | - | - | - | - |
| claude | iterm2-text | iterm2 | none | 27 | raw | 0/2 | - | - | 0/1 | - | - | 0/1 | - | - | - | - | - | - |
| claude | pi-claude-link+claude-uds-accept | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | pi-ext+claude-uds-accept | tmux | none | 27 | nono | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | pi-ext+claude-uds-accept | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | pi-session-bridge+claude-uds-accept | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| claude | tmux-buffer | tmux | none | 27 | raw | 2/2 | 3/3 | 0/2 · harm 2 | 0/1 | 3/3 | 1/1 | 0/4 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| claude | tmux-keys | tmux | none | 26 | raw | 1/1 | - | - | - | - | - | - | - | - | - | - | - | - |
| claude | tmux-keys | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/1 | 2/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| claude | tmux-paste | tmux | none | 26 | raw | 3/3 | 1/1 | 0/2 · harm 2 | 0/1 | 1/1 | 1/1 | 0/1 | 1/1 | - | 1/1 | 0/1 | - | - |
| claude | tmux-paste | tmux | none | 27 | raw | 4/4 | 3/3 | 0/3 · harm 3 | 0/1 | 3/3 | 1/1 | 0/5 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| claude | tmux-paste-retry | tmux | none | 27 | raw | 2/2 | 3/3 | 0/2 · harm 2 | 0/1 | n/a | 1/1 | 0/4 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| claude | zellij-paste | zellij | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/2 | 3/3 | 0/1 | 0/4 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| claude | zellij-write | zellij | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/2 | 3/3 | 0/1 | 0/4 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| claude | zmx-paste | zmx | none | 27 | raw | 2/2 | 3/3 | - | 0/3 | 3/3 | 1/1 | 0/2 | 1/1 | - | - | - | - | - |
| claude | zmx-send | zmx | none | 27 | raw | 2/2 | 3/3 | - | 0/2 | 2/3 | 1/1 | 0/2 | 1/1 | - | - | - | - | - |
| codex | agent-deck | tmux | none | 27 | raw | 0/2 | - | - | 0/1 | - | - | 0/1 | 1/1 | - | - | - | - | - |
| codex | agent-deck+codex-queue | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | agent-deck-composer-fallback | tmux | none | 27 | raw | 0/2 | - | - | 0/1 | - | - | 0/1 | 1/1 | - | - | - | - | - |
| codex | claude-channel+codex-queue | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | claude-uds-accept+codex-queue | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | claude-uds-child+codex-queue | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | codex-queue | tmux | codex-daemon | 26 | raw | 2/2 | - | - | - | - | - | - | 1/1 | - | - | - | 2/2 | - |
| codex | codex-queue | tmux | codex-daemon | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| codex | codex-queue | tmux | codex-daemon | 27 | raw | 6/6 | 5/5 | 0/1 | 1/1 | 0/0 · err 5 | 1/1 | 1/5 | 1/1 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | - |
| codex | codex-queue | tmux | codex-daemon | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| codex | codex-queue-embedded | tmux | codex-daemon | 27 | raw | 0/1 | - | - | 0/1 | - | - | 0/1 | 1/1 | - | - | - | - | - |
| codex | codex-remote-start | tmux | codex-app-server | 26 | raw | 3/3 | - | - | - | 1/1 | - | - | 1/1 | - | - | - | 1/1 | - |
| codex | codex-remote-start | tmux | codex-app-server | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| codex | codex-remote-start | tmux | codex-app-server | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 3/5 | 1/1 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 12/12 |
| codex | codex-remote-start | tmux | codex-app-server | 27 | raw + user config | 1/1 | - | - | - | - | - | 1/1 | - | - | - | - | - | - |
| codex | codex-remote-steer | tmux | codex-app-server | 26 | raw | 2/2 | - | - | - | - | - | - | 1/1 | - | - | - | 1/1 | - |
| codex | codex-remote-steer | tmux | codex-app-server | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| codex | codex-remote-steer | tmux | codex-app-server | 27 | raw | 6/6 | 5/5 | 0/1 | 1/1 | 5/5 | 1/1 | 3/5 | 1/1 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | - |
| codex | codex-remote-steer | tmux | codex-app-server | 27 | raw + user config | 1/1 | - | - | - | - | - | 1/1 | - | - | - | - | - | - |
| codex | csd+codex-queue | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | gc-nudge | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 1/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 1/1 | 0/1 | 0/1 · respawned 1 | - |
| codex | hcom | tmux | none | 27 | raw | 2/2 | 3/3 | 1/1 | 0/1 | 0/3 | 0/1 | 0/3 | 1/1 | 2/2 | 1/1 | 1/1 | n/a | - |
| codex | intercom | tmux | codex-app-server | 27 | raw | 2/2 | 0/3 | 1/1 | 1/1 | n/a | n/a | 3/3 | 0/1 | - | 1/1 | 1/1 | 1/1 | - |
| codex | intercom-accept | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 0/1 | - | - | - | - |
| codex | iterm2-paste | iterm2 | none | 27 | raw | 1/1 | - | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| codex | iterm2-text | iterm2 | none | 27 | raw | 0/1 | - | - | 0/1 | - | - | 0/1 | - | - | - | - | - | - |
| codex | opencode-server-queue+codex-queue | tmux | opencode-server | 27 | nono | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | opencode-server-queue+codex-queue | tmux | opencode-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | opencode-server-steer+codex-queue | tmux | opencode-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | opencode-server-synthetic+codex-queue | tmux | opencode-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | opencode-service-steer+codex-queue | tmux | opencode-service | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| codex | tmux-buffer | tmux | none | 27 | raw | 2/2 | 3/3 | 0/2 · harm 2 | 1/1 | 3/3 | 1/1 | 0/4 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| codex | tmux-keys | tmux | none | 26 | raw | 0/2 | - | - | - | - | - | - | - | - | - | - | - | - |
| codex | tmux-keys | tmux | none | 27 | raw | 0/2 | - | - | 0/1 | - | - | 0/1 | 0/1 | - | - | - | - | - |
| codex | tmux-paste | tmux | none | 26 | raw | 1/1 | 1/1 | 0/1 · harm 1 | 1/1 | 0/1 | 1/1 | 0/1 | 1/1 | - | 1/1 | 0/1 | - | - |
| codex | tmux-paste | tmux | none | 27 | raw | 2/2 | 4/4 | 0/2 · harm 2 | 1/1 | 3/3 | 1/1 | 0/4 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| codex | tmux-paste-retry | tmux | none | 27 | raw | 2/2 | 3/3 | 0/2 · harm 2 | 1/1 | n/a | 1/1 | 0/4 | 1/1 | - | 1/1 | 0/2 | n/a | - |
| codex | zellij-paste | zellij | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 2/2 | 3/3 | 0/1 | 0/4 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| codex | zellij-write | zellij | none | 27 | raw | 0/2 | - | - | 0/2 | - | - | 0/2 | 0/1 | - | - | - | - | - |
| codex | zmx-paste | zmx | none | 27 | raw | 2/2 | 3/3 | - | 1/2 | 3/3 | 1/1 | 0/2 | 1/1 | - | - | - | - | - |
| codex | zmx-send | zmx | none | 27 | raw | 0/2 | - | - | 0/2 | - | - | 0/2 | 0/1 | - | - | - | - | - |
| droid | agent-deck | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 1/1 | 0/0 · err 3 | n/a | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | gc-nudge | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 1/1 | n/a | n/a | 0/3 | 1/1 | - | 1/1 | 0/1 | 1/1 | - |
| droid | pi-claude-link+agent-deck | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| droid | pi-ext+agent-deck | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| droid | pi-session-bridge+agent-deck | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| droid | tmux-buffer | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| droid | tmux-buffer | tmux | none | 27 | raw | 6/6 | 5/5 | 0/1 · harm 1 | 1/1 | 5/5 | 1/1 | 0/5 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | tmux-buffer | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| droid | tmux-keys | tmux | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | tmux-paste | tmux | none | 26 | raw | 3/3 | - | - | - | - | - | - | - | - | - | - | - | - |
| droid | tmux-paste | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| droid | tmux-paste | tmux | none | 27 | raw | 6/6 | 5/5 | 0/1 · harm 1 | 1/1 | 5/5 | 1/1 | 0/5 | 1/1 | - | 1/1 | 0/1 | n/a | 6/6 |
| droid | tmux-paste | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| droid | tmux-paste-retry | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 0/1 | - | - | - | - | - | - |
| droid | tmux-paste-retry | tmux | none | 27 | raw | 6/6 | 5/5 | 0/1 · harm 1 | 1/1 | 5/5 | 1/1 | 0/5 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | tmux-paste-retry | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| droid | zellij-paste | zellij | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | zellij-write | zellij | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | zmx-paste | zmx | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 0/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| droid | zmx-send | zmx | none | 27 | raw | 1/1 | 3/3 | - | 0/1 | 3/3 | 1/1 | 0/1 | 1/1 | - | - | - | - | - |
| opencode | codex-queue+opencode-server-steer | tmux | codex-daemon | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| opencode | codex-remote-start+opencode-server-steer | tmux | codex-app-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| opencode | codex-remote-steer+opencode-server-steer | tmux | codex-app-server | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| opencode | gc-nudge+opencode-server-steer | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| opencode | hcom | tmux | none | 27 | raw | 2/2 | 3/3 | 1/1 | 1/1 | 0/3 | 0/1 | 0/3 | 1/1 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | n/a | - |
| opencode | opencode-server-queue | tmux | opencode-server | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| opencode | opencode-server-queue | tmux | opencode-server | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 2/2 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 2/2 | 6/6 |
| opencode | opencode-server-queue | tmux | opencode-server | 27 | raw + user config | 1/1 | - | - | - | - | - | 1/1 | - | - | - | - | - | - |
| opencode | opencode-server-steer | tmux | opencode-server | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| opencode | opencode-server-steer | tmux | opencode-server | 27 | raw | 7/7 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 2/2 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 2/2 | - |
| opencode | opencode-server-steer | tmux | opencode-server | 27 | raw + user config | 1/1 | - | - | - | - | - | 1/1 | - | - | - | - | - | - |
| opencode | opencode-server-synthetic | tmux | opencode-server | 27 | raw | 2/2 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 0/2 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 2/2 | - |
| opencode | opencode-service-steer | tmux | opencode-service | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| opencode | opencode-service-steer | tmux | opencode-service | 27 | raw | 6/6 | 5/5 | 1/1 | 1/1 | 5/5 | 1/1 | 5/5 | 2/2 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 3/3 | - |
| opencode | opencode-service-steer | tmux | opencode-service | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| opencode | tmux-buffer | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | tmux-keys | tmux | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 0/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | tmux-paste | tmux | none | 26 | raw | 3/3 | - | - | - | - | - | - | - | - | - | - | - | - |
| opencode | tmux-paste | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | tmux-paste-retry | tmux | none | 27 | raw | 2/2 | 3/3 | 0/1 · harm 1 | 0/1 | n/a | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | zellij-paste | zellij | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | zellij-write | zellij | none | 27 | raw | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 0/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| opencode | zmx-paste | zmx | none | 27 | raw | 1/1 | 3/3 | - | 0/1 | 3/3 | 1/1 | 0/1 | 1/1 | - | - | - | - | - |
| opencode | zmx-send | zmx | none | 27 | raw | 1/1 | 3/3 | - | 0/1 | 0/3 | 1/1 | 0/1 | 1/1 | - | - | - | - | - |
| pi | agent-deck+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 2/2 | - | - | - | - |
| pi | claude-channel+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| pi | claude-uds-accept+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| pi | claude-uds-child+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| pi | csd+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| pi | gc-nudge+pi-ext | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 2/2 | - | - | - | - |
| pi | hcom | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 1/1 | 0/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| pi | intercom | tmux | codex-app-server | 27 | raw | - | - | - | - | - | - | - | - | 2/2 | - | - | - | - |
| pi | intercom | tmux | none | 27 | nono | - | - | - | - | - | - | - | - | 1/1 | - | - | - | - |
| pi | intercom | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 1/1 | n/a | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | - |
| pi | intercom-accept | tmux | none | 27 | raw | - | - | - | - | - | - | - | - | 2/2 | - | - | - | - |
| pi | pi-claude-link | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| pi | pi-claude-link | tmux | none | 27 | raw | 6/6 | 5/5 | n/a | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| pi | pi-claude-link | tmux | none | 27 | raw + user config | 0/0 · err 1 | - | - | - | - | - | n/a | - | - | - | - | - | - |
| pi | pi-ext | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| pi | pi-ext | tmux | none | 27 | raw | 6/6 | 6/6 | n/a | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 2/2 | 1/1 | n/a | 12/12 |
| pi | pi-ext | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| pi | pi-session-bridge | tmux | none | 27 | nono | 1/1 | 1/1 | - | 1/1 | - | - | 1/1 | - | - | - | - | - | - |
| pi | pi-session-bridge | tmux | none | 27 | raw | 6/6 | 5/5 | n/a | 1/1 | 5/5 | 1/1 | 5/5 | 1/1 | 1/1 | 1/1 | 1/1 | n/a | - |
| pi | pi-session-bridge | tmux | none | 27 | raw + user config | n/a | - | - | - | - | - | n/a | - | - | - | - | - | - |
| pi | tmux-buffer | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | tmux-keys | tmux | none | 27 | raw | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | tmux-paste | tmux | none | 26 | raw | 3/3 | - | - | - | - | - | - | - | - | - | - | - | - |
| pi | tmux-paste | tmux | none | 27 | raw | 3/3 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | tmux-paste-retry | tmux | none | 27 | raw | 2/2 | 3/3 | n/a | 0/1 | n/a | 1/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | zellij-paste | zellij | none | 27 | raw | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | zellij-write | zellij | none | 27 | raw | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | - | 1/1 | 0/1 | n/a | - |
| pi | zmx-paste | zmx | none | 27 | raw | 1/1 | 3/3 | - | 0/1 | 3/3 | 1/1 | 0/1 | 1/1 | - | - | - | - | - |
| pi | zmx-send | zmx | none | 27 | raw | 1/1 | 3/3 | - | 0/1 | 3/3 | 1/1 | 0/1 | 1/1 | - | - | - | - | - |

By equivalence (R34): `zmx-send` = `tmux-keys`, `zellij-write` = `tmux-keys`, `zmx-paste` = `tmux-paste`, `zellij-paste` = `tmux-paste` for S3, S7 reps 2-3, S10, S11, S12 in the extensive stage. These pairs deliver byte-identical input to their tmux adapter (`results/hostcheck.md`), so only the host-sensitive S2, S5 and S6 were run on them; read the tmux row for the rest (no records are written for them). A pair whose host-sensitive result differed from tmux got the full set and has its own cells (`results/shortlist.md`).
