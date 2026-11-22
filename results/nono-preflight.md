# nono preflight

Updated: 2026-10-28 19:03:35 · nono 0.80.0 · profiles `<agent>-local` from `~/.config/nono/profiles` (read only, not edited) · launcher env from `~/ac/.airc.d/05-sandbox.zsh` (`agentcomms/sandbox.py`)

Each check runs inside `nono run -p <agent>-local -- …` from an unsandboxed coordinator (R19/N7).

| agent | check | ok | detail |
|---|---|---|---|
| claude | nono why --self --path /Users/nielsmadan/wrksp/_scratch/agent-comms/runs/nono-preflight-20261028-190314-655f --op readwrite | yes | exit 0: ALLOWED Reason: granted_path Granted by: /Users/nielsmadan/wrksp Access: read+write Source: profile |
| claude | ps (sender guard: ps -A -o pid,lstart,ucomm) | yes | exit 0: 0 2067 |
| claude | pinned claude 2.1.312 --version from vendor/agents | yes | exit 0: 2.1.312 (Claude Code) |
| claude | sender claude_uds.py --help | yes | exit 0: this help message and exit --config-dir CONFIG_DIR the receiver's CLAUDE_CONFIG_DIR, under the harness runs/ --pid PID the receiver's Claude pid (a target of that run) --from-mode {bypass,prompting} assert the sender's permission-mode class |
| claude | sender claude_link.py --help | yes | exit 0: k.py [-h] --socket SOCKET send stdin as a Claude peer frame to a harness Pi running pi-claude-link options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest |
| claude | sender codex_queue.py --help | yes | exit 0: read THREAD queue stdin for a harness Codex thread via `codex queue` (UUID only) options: -h, --help show this help message and exit --codex CODEX --codex-home CODEX_HOME CODEX_HOME of the harness daemon that owns the thread --thread THREAD |
| claude | sender codex_remote.py --help | yes | exit 0: turn/start once idle; steer: turn/steer into a running turn, else turn/start --wait-s WAIT_S start mode: how long to wait for the thread to idle --drain DRAIN deliver this run's spooled messages for the thread (runs/<run>/deferred/<thread>) |
| claude | sender opencode_http.py --help | yes | exit 0: it --url URL http://127.0.0.1:<port> of the run's opencode server --session SESSION ses_… id of the target session --password-file PASSWORD_FILE runs/<run_id>/home/opencode/server-password --route {prompt,synthetic} --delivery {steer,queue} |
| claude | sender pi_bridge.py --help | yes | exit 0: _up}] send stdin to a harness-owned Pi session through pi-session-bridge options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest --command {prompt,steer,follow_up} |
| claude | sender unix_send.py --help | yes | exit 0: sage: unix_send.py [-h] --socket SOCKET write stdin to a harness run socket (agentcomms channel server or relay) options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest |
| claude | bind unix socket /tmp/ac/nono-preflight-20261028-190314-655f-claude-bind.sock | yes | exit 0: bound |
| claude | connect unix socket /tmp/ac/nono-preflight-20261028-190314-655f-listen.sock | yes | exit 0: connected |
| claude | tcp listen + connect 127.0.0.1 | yes | exit 0: tcp ok |
| claude | tmux -L agentcomms list-sessions | yes | exit 0: nono-preflight-20261028-190314-655f-tmux: 1 windows (created Wed Oct 28 19:03:14 2026) |
| claude | node + vendored tsx (intercom sender runtime) | yes | exit 0: tsx ok |
| codex | nono why --self --path /Users/nielsmadan/wrksp/_scratch/agent-comms/runs/nono-preflight-20261028-190314-655f --op readwrite | yes | exit 0: ALLOWED Reason: granted_path Granted by: /Users/nielsmadan/wrksp Access: read+write Source: profile |
| codex | ps (sender guard: ps -A -o pid,lstart,ucomm) | yes | exit 0: 0 2065 |
| codex | pinned codex 0.165.0 --version from vendor/agents | yes | exit 0: codex-cli 0.165.0 |
| codex | sender claude_uds.py --help | yes | exit 0: this help message and exit --config-dir CONFIG_DIR the receiver's CLAUDE_CONFIG_DIR, under the harness runs/ --pid PID the receiver's Claude pid (a target of that run) --from-mode {bypass,prompting} assert the sender's permission-mode class |
| codex | sender claude_link.py --help | yes | exit 0: k.py [-h] --socket SOCKET send stdin as a Claude peer frame to a harness Pi running pi-claude-link options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest |
| codex | sender codex_queue.py --help | yes | exit 0: read THREAD queue stdin for a harness Codex thread via `codex queue` (UUID only) options: -h, --help show this help message and exit --codex CODEX --codex-home CODEX_HOME CODEX_HOME of the harness daemon that owns the thread --thread THREAD |
| codex | sender codex_remote.py --help | yes | exit 0: turn/start once idle; steer: turn/steer into a running turn, else turn/start --wait-s WAIT_S start mode: how long to wait for the thread to idle --drain DRAIN deliver this run's spooled messages for the thread (runs/<run>/deferred/<thread>) |
| codex | sender opencode_http.py --help | yes | exit 0: it --url URL http://127.0.0.1:<port> of the run's opencode server --session SESSION ses_… id of the target session --password-file PASSWORD_FILE runs/<run_id>/home/opencode/server-password --route {prompt,synthetic} --delivery {steer,queue} |
| codex | sender pi_bridge.py --help | yes | exit 0: _up}] send stdin to a harness-owned Pi session through pi-session-bridge options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest --command {prompt,steer,follow_up} |
| codex | sender unix_send.py --help | yes | exit 0: sage: unix_send.py [-h] --socket SOCKET write stdin to a harness run socket (agentcomms channel server or relay) options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest |
| codex | bind unix socket /tmp/ac/nono-preflight-20261028-190314-655f-codex-bind.sock | yes | exit 0: bound |
| codex | connect unix socket /tmp/ac/nono-preflight-20261028-190314-655f-listen.sock | yes | exit 0: connected |
| codex | tcp listen + connect 127.0.0.1 | yes | exit 0: tcp ok |
| codex | tmux -L agentcomms list-sessions | yes | exit 0: nono-preflight-20261028-190314-655f-tmux: 1 windows (created Wed Oct 28 19:03:14 2026) |
| codex | node + vendored tsx (intercom sender runtime) | yes | exit 0: tsx ok |
| pi | nono why --self --path /Users/nielsmadan/wrksp/_scratch/agent-comms/runs/nono-preflight-20261028-190314-655f --op readwrite | yes | exit 0: ALLOWED Reason: granted_path Granted by: /Users/nielsmadan/wrksp Access: read+write Source: profile |
| pi | ps (sender guard: ps -A -o pid,lstart,ucomm) | yes | exit 0: 0 2066 |
| pi | pinned pi 1.4.0 --version from vendor/agents | yes | exit 0: 1.4.0 |
| pi | sender claude_uds.py --help | yes | exit 0: this help message and exit --config-dir CONFIG_DIR the receiver's CLAUDE_CONFIG_DIR, under the harness runs/ --pid PID the receiver's Claude pid (a target of that run) --from-mode {bypass,prompting} assert the sender's permission-mode class |
| pi | sender claude_link.py --help | yes | exit 0: k.py [-h] --socket SOCKET send stdin as a Claude peer frame to a harness Pi running pi-claude-link options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest |
| pi | sender codex_queue.py --help | yes | exit 0: read THREAD queue stdin for a harness Codex thread via `codex queue` (UUID only) options: -h, --help show this help message and exit --codex CODEX --codex-home CODEX_HOME CODEX_HOME of the harness daemon that owns the thread --thread THREAD |
| pi | sender codex_remote.py --help | yes | exit 0: turn/start once idle; steer: turn/steer into a running turn, else turn/start --wait-s WAIT_S start mode: how long to wait for the thread to idle --drain DRAIN deliver this run's spooled messages for the thread (runs/<run>/deferred/<thread>) |
| pi | sender opencode_http.py --help | yes | exit 0: it --url URL http://127.0.0.1:<port> of the run's opencode server --session SESSION ses_… id of the target session --password-file PASSWORD_FILE runs/<run_id>/home/opencode/server-password --route {prompt,synthetic} --delivery {steer,queue} |
| pi | sender pi_bridge.py --help | yes | exit 0: _up}] send stdin to a harness-owned Pi session through pi-session-bridge options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest --command {prompt,steer,follow_up} |
| pi | sender unix_send.py --help | yes | exit 0: sage: unix_send.py [-h] --socket SOCKET write stdin to a harness run socket (agentcomms channel server or relay) options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest |
| pi | bind unix socket /tmp/ac/nono-preflight-20261028-190314-655f-pi-bind.sock | yes | exit 0: bound |
| pi | connect unix socket /tmp/ac/nono-preflight-20261028-190314-655f-listen.sock | yes | exit 0: connected |
| pi | tcp listen + connect 127.0.0.1 | yes | exit 0: tcp ok |
| pi | tmux -L agentcomms list-sessions | yes | exit 0: nono-preflight-20261028-190314-655f-tmux: 1 windows (created Wed Oct 28 19:03:14 2026) |
| pi | node + vendored tsx (intercom sender runtime) | yes | exit 0: tsx ok |
| opencode | nono why --self --path /Users/nielsmadan/wrksp/_scratch/agent-comms/runs/nono-preflight-20261028-190314-655f --op readwrite | yes | exit 0: ALLOWED Reason: granted_path Granted by: /Users/nielsmadan/wrksp Access: read+write Source: profile |
| opencode | ps (sender guard: ps -A -o pid,lstart,ucomm) | yes | exit 0: 0 2066 |
| opencode | pinned opencode 2.2.0 --version from vendor/agents | yes | exit 0: opencode v2.2.0 |
| opencode | sender claude_uds.py --help | yes | exit 0: this help message and exit --config-dir CONFIG_DIR the receiver's CLAUDE_CONFIG_DIR, under the harness runs/ --pid PID the receiver's Claude pid (a target of that run) --from-mode {bypass,prompting} assert the sender's permission-mode class |
| opencode | sender claude_link.py --help | yes | exit 0: k.py [-h] --socket SOCKET send stdin as a Claude peer frame to a harness Pi running pi-claude-link options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest |
| opencode | sender codex_queue.py --help | yes | exit 0: read THREAD queue stdin for a harness Codex thread via `codex queue` (UUID only) options: -h, --help show this help message and exit --codex CODEX --codex-home CODEX_HOME CODEX_HOME of the harness daemon that owns the thread --thread THREAD |
| opencode | sender codex_remote.py --help | yes | exit 0: turn/start once idle; steer: turn/steer into a running turn, else turn/start --wait-s WAIT_S start mode: how long to wait for the thread to idle --drain DRAIN deliver this run's spooled messages for the thread (runs/<run>/deferred/<thread>) |
| opencode | sender opencode_http.py --help | yes | exit 0: it --url URL http://127.0.0.1:<port> of the run's opencode server --session SESSION ses_… id of the target session --password-file PASSWORD_FILE runs/<run_id>/home/opencode/server-password --route {prompt,synthetic} --delivery {steer,queue} |
| opencode | sender pi_bridge.py --help | yes | exit 0: _up}] send stdin to a harness-owned Pi session through pi-session-bridge options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest --command {prompt,steer,follow_up} |
| opencode | sender unix_send.py --help | yes | exit 0: sage: unix_send.py [-h] --socket SOCKET write stdin to a harness run socket (agentcomms channel server or relay) options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest |
| opencode | bind unix socket /tmp/ac/nono-preflight-20261028-190314-655f-opencode-bind.sock | yes | exit 0: bound |
| opencode | connect unix socket /tmp/ac/nono-preflight-20261028-190314-655f-listen.sock | yes | exit 0: connected |
| opencode | tcp listen + connect 127.0.0.1 | yes | exit 0: tcp ok |
| opencode | tmux -L agentcomms list-sessions | yes | exit 0: nono-preflight-20261028-190314-655f-tmux: 1 windows (created Wed Oct 28 19:03:14 2026) |
| opencode | node + vendored tsx (intercom sender runtime) | yes | exit 0: tsx ok |
| droid | nono why --self --path /Users/nielsmadan/wrksp/_scratch/agent-comms/runs/nono-preflight-20261028-190314-655f --op readwrite | yes | exit 0: ALLOWED Reason: granted_path Granted by: /Users/nielsmadan/wrksp Access: read+write Source: profile |
| droid | ps (sender guard: ps -A -o pid,lstart,ucomm) | yes | exit 0: 0 2067 |
| droid | pinned droid 0.251.0 --version from vendor/agents | yes | exit 0: 0.251.0 |
| droid | sender claude_uds.py --help | yes | exit 0: this help message and exit --config-dir CONFIG_DIR the receiver's CLAUDE_CONFIG_DIR, under the harness runs/ --pid PID the receiver's Claude pid (a target of that run) --from-mode {bypass,prompting} assert the sender's permission-mode class |
| droid | sender claude_link.py --help | yes | exit 0: k.py [-h] --socket SOCKET send stdin as a Claude peer frame to a harness Pi running pi-claude-link options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-cl/cc-socks/<pi pid>.sock, listed in that run's manifest |
| droid | sender codex_queue.py --help | yes | exit 0: read THREAD queue stdin for a harness Codex thread via `codex queue` (UUID only) options: -h, --help show this help message and exit --codex CODEX --codex-home CODEX_HOME CODEX_HOME of the harness daemon that owns the thread --thread THREAD |
| droid | sender codex_remote.py --help | yes | exit 0: turn/start once idle; steer: turn/steer into a running turn, else turn/start --wait-s WAIT_S start mode: how long to wait for the thread to idle --drain DRAIN deliver this run's spooled messages for the thread (runs/<run>/deferred/<thread>) |
| droid | sender opencode_http.py --help | yes | exit 0: it --url URL http://127.0.0.1:<port> of the run's opencode server --session SESSION ses_… id of the target session --password-file PASSWORD_FILE runs/<run_id>/home/opencode/server-password --route {prompt,synthetic} --delivery {steer,queue} |
| droid | sender pi_bridge.py --help | yes | exit 0: _up}] send stdin to a harness-owned Pi session through pi-session-bridge options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-pb/pi-<pid>.sock, listed in that run's manifest --command {prompt,steer,follow_up} |
| droid | sender unix_send.py --help | yes | exit 0: sage: unix_send.py [-h] --socket SOCKET write stdin to a harness run socket (agentcomms channel server or relay) options: -h, --help show this help message and exit --socket SOCKET /tmp/ac/<run_id>-<kind>.sock, listed in that run's manifest |
| droid | bind unix socket /tmp/ac/nono-preflight-20261028-190314-655f-droid-bind.sock | yes | exit 0: bound |
| droid | connect unix socket /tmp/ac/nono-preflight-20261028-190314-655f-listen.sock | yes | exit 0: connected |
| droid | tcp listen + connect 127.0.0.1 | yes | exit 0: tcp ok |
| droid | tmux -L agentcomms list-sessions | yes | exit 0: nono-preflight-20261028-190314-655f-tmux: 1 windows (created Wed Oct 28 19:03:14 2026) |
| droid | node + vendored tsx (intercom sender runtime) | yes | exit 0: tsx ok |
