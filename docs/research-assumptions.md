# Research: riskiest assumptions of the agent-comms test harness

Pre-run research. The run settled several points differently: the tested versions are in `REPORT.md`; the user's
shared Codex daemon (pid 81588 below) was already down, so the harness runs Codex embedded (`--no-daemon`) or against
its own isolated daemon; Codex 0.164.0 rejects `approval_policy="untrusted"` (`docs/harness.md` Isolation).

Date: 2026-10-23. Method: local inspection (live files, `--help`, `strings`, `lsof`, read-only sqlite) plus official docs and `gh` (openai/codex). No agent sessions started, nothing installed. One-cycle scope; done by me directly (no workers).
Legend: [V] verified on this machine or from primary text pasted below. [S] from source/docs only. [U] unverified / inference.

Version note [V]: `claude --version` here prints `2.1.308 (Claude Code)`, not 2.1.303. `codex --version` = 0.163.0, but the managed daemon runs 0.164.0 (`codex app-server daemon version` -> `"cliVersion":"0.163.0","appServerVersion":"0.164.0"`), so CLI/daemon skew exists on this box.

---------------------------------------------------------------------------
## Q1. Transcript location, incremental write, session-id discovery

Write-latency evidence [V]: last-line timestamp vs file mtime, same second, for Codex (`2026-10-23T18:51:49.210Z` vs mtime `13:51:49` at UTC-5), Droid (`2026-10-21T23:31:40.883Z` vs mtime `18:31:40-0500`), and Claude (this very session's file already contained the just-submitted prompt, mid-turn). So all three append per event.

| Agent | Transcript | Live append? | Session id from outside |
|---|---|---|---|
| Claude Code | `~/.claude/projects/<cwd, "/" and "_" -> "-">/<sessionId>.jsonl` (e.g. `-Users-nielsmadan-wrksp--scratch-agent-comms/8a01ffcc-....jsonl`) | Yes [V] | (a) pid registry `~/.claude/sessions/<pid>.json`; (b) launch with `--session-id <uuid>` [V in --help] |
| Codex 0.163 | `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<threadId>.jsonl` (lines carry `"ordinal":N`), plus `thread_history_1.sqlite` (tables `thread_items`, `thread_turns`, 292k rows) | Yes [V] | filename = thread id; `lsof -p <tui pid>` shows open rollout(s) for embedded TUIs; `state_5.sqlite` `threads` table; `session_index.jsonl` |
| Pi 1.3.0 | `~/.pi/agent/sessions/--<cwd with / \ : -> "-">--/<timestamp>_<sessionId>.jsonl` | Yes [S], see below | launch with `--session-id <id>` / `--session-dir <dir>` / `PI_CODING_AGENT_SESSION_DIR`; env `PI_SESSION_ID`/`PI_SESSION_FILE` only reach children of Pi's bash tool |
| OpenCode 2.0.32 | SQLite `~/.local/share/opencode/opencode.db` (`opencode debug paths` -> `db /Users/nielsmadan/.local/share/opencode/opencode.db`) | DB, see below | launch with `--session`/`-s <id>` ("Session ID to continue, or to create if it does not exist") |
| Droid 0.244 | `~/.factory/sessions/<cwd-encoded>/<sessionId>.jsonl` + `<id>.settings.json` | Yes [V] | filename = id; no flag to pre-set id for interactive start; env `FACTORY_SESSION_ID` only in child processes |

### Claude Code
- Registry [V], paste of `~/.claude/sessions/27079.json`:
  `{"pid":27079,"sessionId":"a503e35d-...","cwd":"/Users/nielsmadan/wrksp/loadout/dev4","startedAt":1792173580534,"version":"2.1.301","peerProtocol":1,"peerFeatures":["notify_idle","reply_across_default_dirs","artifact_yield"],"kind":"interactive","entrypoint":"cli","messagingSocketPath":"/tmp/cc-socks/27079.sock","name":"lo4","status":"idle","updatedAt":...}`
  So pid -> sessionId, cwd, `status` (idle/busy) all discoverable without parsing the transcript. `kind` distinguishes interactive. All 36 registry files had live pids when checked, but treat stale pid files as possible (pid reuse): cross-check `kill -0` and `startedAt`.
- `claude --help` has `--session-id <uuid>  Use a specific session ID for the...` [V]. Simplest robust route: harness pre-assigns the uuid and reads `<projects>/<enc-cwd>/<uuid>.jsonl`.
- Gotcha: `CLAUDE_CONFIG_DIR` relocates all of this. Gotcha: sub-agent/sidechain output goes to separate files; match on top-level user entries.

### Codex
- Rollout is appended live; the first line is `session_meta` with `id`, `cwd`, `originator` (`codex_exec` vs interactive), `source` [V].
- pid -> session: embedded TUIs hold their rollout open. `lsof -p 70662` showed `.../sessions/2026/10/21/rollout-2026-10-21T22-16-28-01a1619c-...jsonl` and a second rollout (one process can own several threads: resume, subagents), so pid -> thread is one-to-many; disambiguate by cwd in `session_meta`. A TUI attached to the shared daemon does NOT hold the rollout (the daemon pid 81588 did; see Q2), so lsof on the TUI pid fails in that mode. [V for embedded; U for attached]
- 0.163 also keeps a paginated store in `thread_history_1.sqlite`; `codex migrate-rollouts` exists ("Inspect or migrate legacy local sessions to paginated thread history"). The rollout JSONL is still written for new threads today [V], but the JSONL could stop being the primary store in a later version; `thread_items(thread_id, rollout_ordinal, item_type, item_json)` with a partial index on `item_type='userMessage'` is a reader-friendly alternative [V schema].

### Pi 1.3.0
- Docs `docs/session-format.md`: "`~/.pi/agent/sessions/--<path>--/<timestamp>_<session-id>.jsonl`. By default, `<session-id>` is a UUID. Callers can supply a custom ID through the SDK or `--session-id`."
- `docs/environment-variables.md`: "Commands run by the `bash` and `powershell` tools receive the current Pi session state: `PI_SESSION_ID` ... `PI_SESSION_FILE` | Absolute path to the current session JSONL file". Only visible inside the agent's own shell tool, not via the Pi process env.
- Incremental write [S], `dist/core/session-manager.js` `_persist`: the file is created on the first persist where `_hasConversation()` is true, and `_hasConversation()` is `fileEntries.some(e => e.type === "message" && (e.message.role === "user" || e.message.role === "assistant"))`. So a submitted user message creates the file (older Pi waited for an assistant message; 1.3.0 does not). After that it is `appendFileSync` per entry. Open-append-close per entry means `lsof` will rarely show the file open: use `--session-id`/`--session-dir`.
- Not exercised live (no recent Pi interactive session on disk to compare timestamps) [U for latency; code is unambiguous].

### OpenCode 2.0.32
- Storage is SQLite [V]. DB path logic, `packages/cli/src/database-path.ts`: `process.env.OPENCODE_DB ?? (["latest","dev","beta","next","prod"].includes(OPENCODE_CHANNEL) ... ? "opencode.db" : "opencode-<channel>.db")`. `OPENCODE_DB=:memory:` is a supported value. Here the file is `opencode.db` (94 MB, WAL mode: `opencode.db-wal`, `-shm`), readable read-only with `sqlite3 -readonly` while the app runs.
- v2 schema [V] (migrations from v1; the old `session`/`message`/`part` tables are legacy and hold the pre-v2 data): `session_v2`(id `ses_...`, directory, title, agent, model, time_created/updated, time_idle, idle_outcome) and `session_message`(id, session_id, `type`, `seq`, time_created, time_updated, `data` JSON). Types seen: `user`(307) `assistant`(1668) `system` `synthetic` `idle` `agent-switched`. A user row `data` = `{"time":{"created":...},"text":"Read-only consultation..."}`. Also `session_inbox` and `session_pending` (both empty here) - [U] whether a just-submitted prompt appears in `session_message` immediately or first lands in `session_inbox`/`session_pending` (event-sourced input; migration names `event_sourced_session_input`, `simplify_session_input`). Needs one live check; poll both tables.
- Query: `select seq,type,data from session_message where session_id=? and type='user' order by seq`.
- Official read paths (no DB access needed) [V --help]: `opencode session export [<session>]` ("Export session data as JSON"; `--standalone`, `--server`, `--sanitize`), `opencode session list`, and `opencode api <operationId | method path>` against the running server. HTTP route from `packages/protocol/src/groups/message.ts`: `GET /api/session/:sessionID/message` (operation `session.message.list`, cursor paged, `type` filter), and `POST /api/session/:sessionID/prompt` (`session.prompt`) in `groups/session.ts`; inbox routes `GET /api/session/:sessionID/inbox`, `DELETE|PATCH .../inbox/:inboxID`.
- Architecture gotcha [V --help]: default is a shared "background service" (`opencode service start|status|stop|restart`; flags `--standalone` "Run with a private server instead of the background service", `--server <url>`). Currently `opencode service status` -> `stopped`. For isolation use `--standalone` or a separate `OPENCODE_DB` path plus separate XDG data dir; otherwise the harness shares the user's background server and DB.
- pid -> session: none on disk. Pre-assign with `--session <id>` (create-if-missing) [V --help]; this is the only reliable correlation.

### Droid 0.244.0
- Layout [V]: `~/.factory/sessions/-Users-nielsmadan-wrksp-someproject/e5dbc60c-....jsonl`, first line `{"type":"session_start","id":...,"cwd":...,"owner":...,"version":2}`, then `{"type":"message","id":...,"timestamp":...,"message":{"role":...,"content":[...]}}`.
- Parser gotcha [V]: many `role:"user"` entries are NOT human prompts: hook records with `"content":[],"visibility":"user_only","hookEventName":"SessionStart"|"PreToolUse"...`, and a `<system-reminder>` user message with the subagent list precedes the real prompt. Filter on non-empty `content[].text`, no `hookEventName`, not starting with `<system-reminder>`.
- `droid --help`: `-r, --resume [sessionId]`, `--fork`, `--cwd`; `droid exec -s/--session-id <id> "Existing session to continue"`. No pre-set id for a fresh interactive start. Harness approach: record launch time, take the newest `<enc-cwd>/*.jsonl` created after it (cwd encoding is not a pure `/`->`-` substitution for all paths, e.g. a `_` in `_scratch` becomes `-`; glob rather than compute). `FACTORY_HOME_OVERRIDE` string exists in the binary [U semantics], `droid search <query>` searches local sessions.

---------------------------------------------------------------------------
## Q2. Codex 0.163.0 shared app-server daemon, `codex queue`, isolation

### Does plain interactive `codex` attach to the daemon? Yes by default, but many invocations are silently excluded
Source `codex-rs/tui/src/daemon_startup.rs` (openai/codex main, f970f4be) [S]:
```
pub(super) fn exclusion(...) -> Option<&'static str> {
    if cli.no_daemon { Some("--no-daemon") }
    else if cli.oss { Some("--oss") }
    else if workload_identity_selected { ... }
    else if exec_server_url.is_some() { Some("executor selection (CODEX_EXEC_SERVER_URL)") }
    else if cli.agents_overview { None }
    else if cli.config_profile_v2.is_some() { Some("--profile") }
    else { config_exclusion(...) }
```
and `config_exclusion` returns `Some("command-line configuration overrides (-c, --enable, --disable, or --search)")` unless the override keys are only `features.*` bools / two tui bools; also excludes a custom loader, `--strict-config`, `--dangerously-bypass-hook-trust`. Header comment: "Explicit embedded launches never discover or start a daemon; ... automatic launches require a compatible shared server and a successful connection". README: "If an implicitly discovered daemon cannot initialize the connection, the TUI starts an embedded server instead."
- Empirical confirmation [V]: the user's 4 live TUIs are launched `codex -c sandbox_mode="danger-full-access" -c approval_policy="never"` and are all embedded: each process itself holds `queue_1.sqlite` and its own `rollout-*.jsonl` open, while daemon pid 81588 (`codex app-server --listen unix:// --analytics-default-enabled --managed-daemon`, started 00:39 today) holds no rollouts. So a harness that passes any `-c` (sandbox/approval/model overrides!) gets an EMBEDDED TUI; a bare `codex` (or one using only config.toml / env) attaches to the daemon.
- Release notes: `--no-daemon` added by PR #46088 (merged 2026-09-17): "Run with `--no-daemon` without starting or probing the shared server ... Reject combinations with `--remote`, `codex agents`, and `codex queue`". 0.163.0 notes: "Restart a managed background server from `/daemon`." Local `--help`: "`--no-daemon` Run without the shared background server, even if it is already running".
- Daemon socket: `~/.codex/app-server-control/app-server-control.sock` -> `/private/tmp/codex-daemon-501/<hash>`; state in `~/.codex/app-server-daemon/` (pid, lock, updater).

### Does `codex queue` deliver live?
- Mechanism [S+V]: `codex queue --thread <uuid|exact name> --message <text>` calls app-server `thread/queue/add`, which inserts a row in `~/.codex/queue_1.sqlite` (`queued_items`, with trigger-maintained `queued_thread_revisions` so other processes can notice changes; the DB is opened by every TUI and the daemon on this box). Output: `Queued message <id> for thread <uuid>.`
- It is a FOLLOW-UP queue, not a steer: issue #48928 (open): "`codex queue` always creates a follow-up (`queued_items`) that starts only after the current turn ends." #52705 (open, 2026-10-09): "The Desktop drains the queue (`thread/queue/start`) only while the thread is idle"; an active `/goal` starves it; "`codex queue` exits 0 once the item is stored, so the sender cannot tell 'stored' from 'taken'". #41060 (open, 0.150.1): for `codex exec` threads, queued messages are never delivered and can be lost. #54252 (open) describes the opposite wording ("a queued message is delivered into the running turn rather than starting a new one") on 0.162.1 - conflicting; treat delivery timing as unverified and have the harness confirm by watching the rollout/`thread_items` for the user message.
- So: for an idle interactive TUI the item should start a new turn promptly; for a busy one it waits for the turn to end. Whether an EMBEDDED TUI (daemon-less, like the user's) drains rows that the daemon-side `queue` call inserted is [U]: the shared SQLite + revision triggers suggest yes, but the code also contains a guard error "cannot queue through an embedded app server while a local app-server daemon is running; remove configuration overrides or use --remote", and `--no-daemon cannot be used with codex queue. Queuing must discover the shared server to avoid writing through a separate server.` Needs one live test.

### Cross-session blast radius on the user's daemon
1. Addressing is by thread: `thread/queue/add` takes `thread_id`; with a UUID it can only hit that thread. With a NAME the lookup spans all Active sessions of that CODEX_HOME (`SessionCollection::Active`) - a name collision with a user session would deliver into the wrong one. Always pass UUIDs.
2. `codex agents` ("Browse all agent sessions on the shared local app-server daemon") and any raw JSON-RPC client on the control socket (`turn/start`, `turn/steer`, `thread/list`) see and can address EVERY thread on the daemon, user's included. Harness must only use ids it created.
3. Shared env: README: "Shared clients use the environment inherited when the daemon started. Opening a new terminal or clearing variables there does not clear the running daemon's environment; per-client environment isolation is not provided." A harness TUI attached to the user's daemon runs tools with the USER daemon's env, not the harness env.
4. Feature-flag mismatch can restart the daemon: `compatibility_warning` returns `restart_features` when a session's `--enable/--disable features.x` differs from the daemon; a restart/`daemon stop|restart|update` ("A running daemon restarts, so active or queued work may be interrupted") would interrupt the user's live work. Never run `codex app-server daemon restart|stop|update` against the real CODEX_HOME. The daemon also self-updates (hourly), which restarts it (`shutdownGraceSeconds` default 60).
5. Version skew: CLI 0.163.0 vs daemon 0.164.0 here; the queue path errors "the local app-server daemon does not support thread/queue/add; update or restart" only when the daemon is older.

### Isolated daemon
- Per-CODEX_HOME [S]: daemon state is `CODEX_HOME/app-server-daemon/` and `CODEX_HOME/app-server-control/`; README: "Use a shorter `CODEX_HOME` to share the daemon" (socket address derived from the canonical CODEX_HOME; AF_UNIX path limit). So `CODEX_HOME=/some/short/dir` gives a separate daemon, separate `queue_1.sqlite`, separate sessions dir. Needs `auth.json` (and config.toml) copied/symlinked in. Local binary also references `CODEX_HOME` and "failed to canonicalize CODEX_HOME" [V strings].
- Explicit lifecycle under the isolated home: `CODEX_HOME=<dir> codex app-server daemon start` / `stop` (commands listed in `codex app-server daemon --help` [V]); `daemon bootstrap` copies the invoking package into `CODEX_HOME/packages/app-server-daemon`.
- Alternative: `--listen unix://PATH` for a private `codex app-server` and `--remote unix://PATH` for the TUI and `codex queue` (`--remote <ADDR>` accepted forms `ws://`, `wss://`, `unix://`, `unix://PATH` [V --help]). Explicit remote is authoritative (no embedded fallback).
- Recommended harness config: isolated short CODEX_HOME + `codex app-server daemon start` there + bare `codex` (no `-c`; put sandbox/approval in that home's config.toml) so the TUI attaches and `codex queue` goes through the same daemon. [U end-to-end: not run.]

---------------------------------------------------------------------------
## Q3. Claude Code development channels flag

- Exists and is current in the installed binary (2.1.308) [V strings]: `--dangerously-load-development-channels <servers...>`, also `--channels <servers...>`; message: "`--dangerously-load-development-channels` is for local channel development only. Do not use this option to run channels you have downloaded off the internet." Neither flag is listed in `claude --help` (my grep of help returned nothing) - docs say so too.
- Docs (code.claude.com/docs/en/channels-reference, "Test during the research preview"): "`claude --dangerously-load-development-channels server:webhook`" for a bare `.mcp.json` server, "`plugin:yourplugin@yourmarketplace`" for a plugin. "Claude Code first shows a full-screen warning dialog listing the development channels you're loading. Select **I am using this for local development** to continue, or **Exit** to quit." Also "The first time you start a session in this project, Claude Code also asks for consent before using the new server from `.mcp.json`" ("New MCP server found in this project"). A harness must auto-answer both dialogs (keystrokes) - there is no non-interactive bypass: "If you pass it in non-interactive mode with `-p` or through the Agent SDK, Claude Code ignores the flag and the channel doesn't register."
- Bypass is per entry: "Combining this flag with `--channels` doesn't extend the bypass to the `--channels` entries." "This flag skips the allowlist only. The `channelsEnabled` organization policy still applies."
- Auth/policy (code.claude.com/docs/en/channels): "They require Anthropic authentication through claude.ai or a Console API key, and are not available on Amazon Bedrock, Google Cloud's Agent Platform, or Microsoft Foundry." "Pro and Max users without an organization skip these checks entirely." Team/Enterprise: blocked until an Owner sets `channelsEnabled: true` (admin console or managed settings); Console API-key orgs allowed by default unless managed settings are deployed, then blocked until the key is set. `allowedChannelPlugins` replaces the allowlist; "If you set an empty array, you block all channel plugins from the allowlist, but `--dangerously-load-development-channels` can still bypass that block". Binary strings agree: "channels not enabled by org policy (set channelsEnabled: true in managed settings)"; "is not on the approved channels allowlist (use --dangerously-load-development-channels for local dev)".
- Semantics: server declares `capabilities.experimental['claude/channel']`, emits `notifications/claude/channel` with `{content, meta}`, arrives as `<channel source="webhook" ...>`. "Claude Code doesn't acknowledge notifications ... If the session hasn't loaded your server as a channel, or the organization policy blocks it, Claude Code drops the events silently" - the harness must verify delivery from the transcript, not from `await notification()`. Events "queue into the session and are processed in order. If several notifications arrive while Claude is busy, they're delivered together on the next turn". Needs v2.1.234+ for permission-relay behavior changes. On the "v2 MCP client runtime" a server negotiating protocol revision 2026-07-28 is not registered as a channel (docs line) - [U] whether this machine is on that runtime.
- This account already runs a channel plugin (Telegram: the `telegram@claude-plugins-official` plugin appears in this session's MCP list), so `channelsEnabled` is evidently not blocking this login [U which login/plan].

---------------------------------------------------------------------------
## Q4. iTerm2 Python API

- "Enable Python API" is required [V]: iTerm2 binary string `Authentication failed. Ensure iTerm2 Python API is enabled: Settings > General > Magic > Enable Python API`; this machine: `defaults read com.googlecode.iterm2` -> `EnableAPIServer = 1` (iTerm at `/Applications/Development/iTerm.app`; socket `~/Library/Application Support/iTerm2/iterm2-daemon-1.socket`). The Python `iterm2` module is NOT installed for system `python3` here (`ModuleNotFoundError: No module named 'iterm2'`), and `it2api` just says "Please run: python3 -m pip install iterm2" (it needs that module).
- Auth prompt for external scripts (official docs, iterm2.com/python-api/tutorial/running.html): "When you run a script from the command line on iTerm2 version 3.3.9 or later you will be prompted for permission. This is a security measure to ensure that scripts not launched by iTerm2 are not being run without your knowledge." "To circumvent the dialog, use the it2run script provided in iTerm.app/Resources/it2run to launch it. The it2run script uses osascript to ask iTerm2 to launch your Python script. macOS will ask for a one-time grant of permission for osascript to control iTerm2."
- Cookie route [V binary + `it2 auth cookie --help`]:
  ```
  Request a cookie and key from iTerm2.
  Prints ITERM2_COOKIE=... ITERM2_KEY=... to stdout.
  By default, requests a reusable cookie. An announcement in iTerm2
  lets the user choose the duration (24 hours, forever, etc.).
  Usage:  export $(it2 auth cookie)
  USAGE: it2 auth cookie [--single-use]
  ```
  So non-interactive operation needs a one-time human click in an iTerm2 announcement (or the macOS Automation grant for osascript on the `it2run` route). A later script with a valid `ITERM2_COOKIE`/`ITERM2_KEY` env connects without the dialog. The binary also has the dialog options "Always Allow" / "Always allow %@" / "Always Allow All Apps" and the message "Although you have chosen to allow connections automatically, this script has not presented a valid cookie." - i.e. a persisted "allow all" mode exists but the cookie is still checked in the stricter modes [U exact preference name and semantics; not tested]. If Application Support moves "the authentication mechanism ... has been reverted to always require Automation permission".
- In this Claude Code Bash tool env: `ITERM_SESSION_ID=w1t0p0:CBDFC0FB-...` is set, `ITERM2_COOKIE` is not. Scripts started by iTerm2 itself (Scripts menu / AutoLaunch / `it2run`) get a cookie automatically; arbitrary child processes of a shell do not.
- Sandbox caveat [U]: sandboxed (nono) sessions need access to the Unix socket in `~/Library/Application Support/iTerm2/`; check with `nono why --self --path <socket> --op readwrite` before assuming.

---------------------------------------------------------------------------
## Biggest risks, ranked
1. Codex: any `-c` override makes the TUI embedded and bypasses the daemon; `codex queue` then relies on the shared `queue_1.sqlite` drain (unverified) and `--no-daemon` is incompatible with queue. Pick one mode deliberately, in an isolated CODEX_HOME.
2. Codex `queue` is follow-up-only and returns success on "stored", not "delivered"; verify delivery from the rollout.
3. Droid and Claude transcripts contain non-prompt "user" records; Droid cannot pre-set its session id.
4. OpenCode: shared background service + one DB for everything; confirm whether a fresh prompt shows in `session_message` immediately (check `session_inbox`/`session_pending` too).
5. Claude channels flag needs two interactive dialogs and silently drops events when blocked.
6. iTerm2 needs a one-time human approval (cookie announcement or osascript Automation grant); API must stay enabled.

Sources: code.claude.com/docs/en/channels, .../channels-reference; iterm2.com/python-api/tutorial/running.html; github.com/openai/codex PR #46088, issues #41060 #48928 #52705 #54252, files codex-rs/tui/src/daemon_startup.rs, codex-rs/tui/src/session_queue_commands.rs, codex-rs/app-server-daemon/README.md, codex-rs/state/queue_migrations/0002_queued_thread_revisions.sql, release notes rust-v0.163.0; Pi docs `docs/session-format.md`, `docs/environment-variables.md`, `dist/core/session-manager.js` (local package); OpenCode source `~/wrksp/_scratch/opencode-v2.0.32` (packages/cli/src/database-path.ts, packages/protocol/src/groups/message.ts, session.ts) and the live `opencode.db`.
