# agentcomms

Harness that measures ways to push a message into a running, human-attachable coding-agent TUI and wake it.
Each delivery mechanism is an adapter (`agentcomms/adapters/`); every test session runs in an isolated home
under `runs/<run_id>/`, never the user's.

Results, comparison and the recommended fleet setup: `REPORT.md`. Design decisions, the rules a re-run must keep and
the ruling ids (R9 … R51) cited here and in `REPORT.md`: `docs/design.md`. Inventory and background research from
before the run: `docs/enumeration.md`, `docs/research-assumptions.md`. Re-test plan for the Mac Studio fleet: `docs/studio-retest.md`.

## Setup

```sh
uv sync
uv run pytest -q && uv run ruff check
```

Requires tmux, `~/ac/bin/sops-exec` (injects agent credentials; `AGENT_REQUIRE_SECRETS=1` makes a missing
store a loud failure), node (Pi runs on the concrete `node` binary that `PATH` resolves to) and the pinned agent
binaries in gitignored `vendor/agents/<agent>-<version>/` (R35). Copy them from the user installs, read only:
`claude-<v>/<v>` from `~/.local/share/claude/versions/<v>`, `codex-<v>/<v>-<target>/` (the whole release dir) from
`~/.codex/packages/standalone/releases/`, `opencode-<v>/opencode` from `~/.opencode/bin/opencode`,
`droid-<v>/droid` from `~/.local/bin/droid` and `pi-<v>/` (the whole package dir) from
`~/.local/share/mise/installs/npm-earendil-works-pi-coding-agent/<v>`. One dir per agent; sources and sha256 are in
`vendor/REVIEW.md`.

## Commands

```sh
uv run agentcomms launch --agent claude|codex|pi|opencode|droid [--mode auto|prompting]   # start a TUI, print run id + attach command
uv run agentcomms send --run <run_id> --agent claude --adapter tmux-paste --text "hello"   # or body on stdin
uv run agentcomms run --stage pilot --agent codex --adapter tmux-paste --scenario S1 [--keep] [--resume [--retry-errors]] [--mode …]
uv run agentcomms matrix --stage pilot --agents claude,codex --adapters tmux-paste \
    [--scenarios S2,S3,…] [--reps 1] [--time-budget 360] [--resume [--retry-errors]] [--max-concurrency 1]
uv run agentcomms matrix --stage extensive --plan cells.json [--resume …]   # explicit {agent, mechanism, scenario, rep} list, run in file order
uv run agentcomms cleanup <run_id>   # an unknown or malformed run id exits 2 ("unknown run id")
uv run agentcomms report          # regenerate results/matrix.md
uv run agentcomms progress        # regenerate results/progress.md
uv run agentcomms hashes          # sha256 of the user's global agent config files
uv run agentcomms shortlist [--write]  # rank the screen survivors (fixed safety denominator 7); --write splices results/shortlist.md
uv run agentcomms cleanup --stale-claude-socks  # remove dead harness Claudes' /tmp/cc-socks/<pid>.sock
uv run agentcomms hostcheck [--hosts tmux,zmx,zellij,iterm2] [--adapters …]   # byte-level host x adapter check
uv run agentcomms s9 --a claude --b codex --fwd codex-queue --back claude-uds-accept   # agent-to-agent round trip
uv run agentcomms scale                                                        # 8 concurrent receivers, 3 messages each (Task 10)
uv run agentcomms user-config-inventory [--agents …] [--mechanisms …]          # names only: what the user's real config loads, R41 run/skip
uv run agentcomms matrix --stage user-config --plan cells.json                 # cells with the user's real global config (R41)
uv run agentcomms nono-preflight [--agents …]                                  # ps, senders, pinned binary, sockets inside each <agent>-local; rewrites only those agents' rows of results/nono-preflight.md
uv run agentcomms matrix --stage nono --sandbox nono --plan cells.json         # receiver, backend and sender under nono
uv run agentcomms iterm-holder                                                 # create the persistent iTerm2 holder window
uv run agentcomms cleanup --iterm-holder                                       # close it (only when it has no cell tabs)
```

`run` launches a fresh isolated session, sends one envelope
(`ACK-REQUEST <token>: reply with exactly "ACK <token>". <body>`), waits for the reply in the transcript,
appends one record to `results/raw.jsonl`, regenerates `results/progress.md` and cleans up (unless `--keep`).
`--resume` skips a cell already recorded (records with `env_error` are re-run); add `--retry-errors` to re-run
cells recorded as `error` too (e.g. after fixing a precondition). Every record carries the message token(s) in
`token` (comma-separated, in send order, when a scenario sends several), so a token can be checked against the
pane afterwards. `--adapter`/`--adapters`, `--agents` and `--scenarios` are validated before anything launches.

A new run refuses to start while any earlier run in `runs/` still has live processes. After `cleanup`, `run` and
`matrix` re-check the run's process groups and stop with exit 9 if any harness process survived.

`matrix` runs every agent × adapter × scenario × rep cell for the agent × adapter pairs the adapter supports (other
pairs are skipped, not recorded), each in its own run (fresh isolated session, cleaned up afterwards), appends each
record to `results/raw.jsonl` as it finishes, regenerates `results/progress.md` at most every 30 min and at batch
end (a hand-written `## Notes` section in it is kept across rewrites), and rewrites `results/matrix.md` after every
cell. `--time-budget` (minutes, default 360) stops scheduling at a cell boundary; `--resume` skips recorded cells. `--plan <file>` replaces
`--agents`/`--adapters`/`--scenarios`/`--reps` with a JSON list of cells (unsupported agent x adapter pairs, entries
that are not cell objects and a `rep` that is not a positive integer are refused with exit 2 before anything launches;
`--rep`/`--reps` below 1 are usage errors). A scenario that does not apply (S3 on Pi, S10 where the agent has no `/clear`/`/compact`
equivalent, S12 with backend `none` and no bridge daemon, or a reason the adapter declares in `scenario_na`, e.g. S3 on
`intercom-accept` Claude, whose `cci --yolo` shows no dialogs, and S6 on csd, agent-deck and gc-nudge, which own the
session lifecycle) is recorded as `n/a` with its reason, without a launch. An `env_error` from sleep or a failed network probe is requeued once. One that pauses the batch (exit 10)
for a later `--resume`: an API error (429/quota/auth, read from the transcript; note `api-error`), a login or auth
screen while waiting for readiness (`auth-required`), or a receiver that died during the cell, outside S6's
deliberate kill (agent pid gone or its tmux pane exited; `receiver-crashed (<cause>; was <verdict>)`). The second
receiver crash recorded for the same cell is terminal instead: `error` with `receiver-crashed-repeatedly (crash
N)`, which `--resume` no longer re-runs. A stop condition (version change 3, auth link 4, global config 5,
ownership 7, cleanup failure 8, leftover processes 9, an earlier run still live 11, harness bug 12) ends the batch
after the running cells; `matrix` also stops between cells when the version of any agent differs from an earlier
record of the batch (3). Creating `runs/STOP` ends a `matrix` batch the same way, after the running cells (`matrix`
never deletes `runs/STOP`: a file left over blocks the next batch before its first cell until the user or the
coordinator removes it; a batch it blocks before the first cell exits 10, a pause). Expected cell failures (launch, tmux, OS, isolation, profile, subprocess, readiness
timeouts) are recorded as `error`/`env_error` with their cause. Any other exception is a harness bug: the cell is
recorded as `error` with `harness-bug: <cause>; traceback=runs/<run_id>/traceback.txt` and the batch stops (12),
so no further paid cells start. A matrix worker that crashes outside a cell's own handling writes
`runs/harness-crash-<ts>.txt`, keeps the record the cell already wrote (or writes one `harness-crash` record) and
also stops. After every cell, the auth-link check and the global-config check run independently; a check that
raises is itself a stop (4 or 5). `progress.md`/`matrix.md` are always written at batch end.
`--max-concurrency N` runs up to N cells at once but never two cells for the same agent, so no shared backend or
auth file sees two cells at a time, and never two cells of one bridge's state at once (an adapter's `shared_state`:
`hcom`, `intercom`/`intercom-accept`, `csd`, `agent-deck`/`agent-deck-composer-fallback`, `gc-nudge`); stage `pilot` is
clamped to 1 and every other stage to at most 3. Inside `matrix`, per-cell cleanup kills only
that cell's tmux session, and the batch stops the idle `agentcomms` tmux server once at the end.

Exit status is the same for `run` and `matrix`: 0 when every final record is a verdict, `n/a` or a requeued
`env_error`; 6 when a cell's record is `error`; 10 when a record paused the batch; the stop codes above take
precedence.

## Scenarios

Every scenario uses the single-line envelope above (S4 adds a multiline payload). Setup prompts and human-proxy
input are typed through the host (`type_text`: 6-character chunks 30 ms apart, 0.4 s before Enter), so they are not
mistaken for a paste. A failed precondition is recorded as `error` with `precondition: <cause>` and a
`pane-<agent>-precondition.txt` snapshot, never as a verdict.

| Id | Mode | Recipe | Precondition | Verdict |
|---|---|---|---|---|
| S1 | auto | send to the idle receiver | ready | delivered / lost / rejected |
| S2 | auto | receiver told to run `cat /tmp/ac/<run_id>.fifo` (a harness FIFO gate); send 10 s after the transcript shows that tool_use with no result and a `cat` reader exists; then write `GATE-OPEN-<run_id>` to release it | gated tool running | `queued` if the turn ended between the gate's tool_result and the token: a turn-end entry (Codex `task_complete`/`turn_aborted`, Claude assistant `stop_reason: end_turn`) or, for readers without one, an assistant reply with no later tool call; otherwise `interrupted` (steered into the running turn) |
| S3 | prompting | receiver asked to create `approved.txt` in its work dir; send while the approval dialog is up (token drawn from `a`–`f` only, so no digit in it can pick a numbered option); after 15 s press Escape (up to 3 times) to deny | dialog visible, file absent | `delivered` (recorded while the dialog was up) / `queued` (after dismissal) / lost; `harmful` if `approved.txt` existed before the harness dismissed the dialog |
| S4 | auto | envelope line plus a deterministic ≥10 KB payload (quotes, backticks, `$VAR`/`$(…)`, tabs, backslashes, unicode, emoji, blank and indented lines) | ready | intact = byte-equal after `unwrap` |
| S5 | auto | ownership checked once, then five sends back to back (window recorded) | ready; the five sends within 1 s (R47): if the adapter's own sends took longer (blocking CLIs, the `-retry` settle; timed around each whole `adapter.send` call, so the adapter's work before it stamps its send time counts and the harness's ownership check and pid tracking do not) the record is `n/a` `adapter cannot burst (window <s>)`, otherwise `error` `precondition: burst-window` | `delivered` only if all 5 are recorded; `intact` only if every envelope equals one received entry exactly; `recv_sha256` covers the received bodies joined in file order (diff on mismatch); notes `burst=k/5`, `order=in-order\|reordered`, `merged=yes\|no`, `merge_count=N` (message boundaries lost), `acks=k/5`, and `order unverifiable` when two receiving entries share a timestamp |
| S6 | auto | warm-up turn; SIGTERM the agent (SIGKILL after 5 s); send while it is down; resume the session (`--resume`/`resume <id>`) in a new tmux session with the adapter's launch args again (and through its launcher for hcom/intercom; an args-in-shim launcher gets the resume args in its PATH shim); re-resolve session id and transcript; send again | warm-up answered | verdict of the post-resume send; notes `down=rejected\|queued\|lost`, `session=same\|new` |
| S7 | auto | type a draft (`DRAFT-<hex> please also look at the`) without Enter; send | draft visible in the input box | `draft_fate`: `merged` (draft and token in one user entry, or both still in the input box), `submitted` (draft in its own entry), `preserved` (draft alone still in the input box), `lost` |
| S8 | auto | attach a client of the receiver's host in a PTY (`attach-<agent>.log`; tmux `attach`, `zmx attach`, `zellij attach`; iTerm2 has none); type a human prompt and wait for its answer; push; detach | human turn answered and rendered in the client | notes `rendered=yes\|reply-only\|no` (`reply-only`: the reply shows but the pushed `ACK-REQUEST <token>` never does, e.g. OpenCode `/synthetic`; scored not good, R25): the reply `ACK <token>` seen in the client's output stream, compared with all whitespace removed (TUIs redraw only changed cells, so blanks drop out or shift), at a place not preceded by the prompt's own `"` (so the echoed envelope does not count); the human turn likewise counts only an occurrence of its marker not preceded by `exactly`. A push the human's thread never records but another transcript of the same work dir received (Codex intercom's bridge thread) is `delivered` with notes `hidden-thread` and `rendered=no` (R33) |
| S10 | auto | warm-up; type `/clear` (Pi/OpenCode `/new`), send to the pre-clear address; type `/compact` (Droid `/compress`), send again | receiver ready after each command | worst of the steps; notes `clear=<verdict>@old-session\|new-session` |
| S11 | auto | type `/model` (OpenCode `/models`); send while the picker is open (digit-free token, as S3); Escape (up to twice) after 8 s | picker visible | `delivered` / `queued` / lost; `harmful` if the shown model changed; `modal-selection-made` when the send made a picker choice (Claude `Set model to …`, Codex moving on to its reasoning-level picker) |
| S12 | backend | adapter's `restart_backend(target)` (part of the `Adapter` protocol; `None` = no backend), then send | backend exists | n/a for backend `none` unless the adapter has a bridge daemon (`bridge_daemon`): intercom stops its broker and waits up to 20 s for a client to respawn it; gc-nudge stops the city's supervisor (process group) and starts it again, then waits for the named session; the new daemon pid is tracked. An agent the restart killed and nobody respawned is `lost` with `agent-lost-by-restart` (R39), not a receiver crash; one a bridge respawned is `agent-respawned-by-bridge`, not good |

Human-proxy text is checked by `s8.safe_human_text` (no leading `/`, `!`, `@`, `#`, no `/loop`, no `import`), so S8
never opens Droid's interactive import screens or `/loop`. When a token is not recorded but is visible in the
receiver's input box, the record keeps `lost` and adds `stuck-in-composer`. Every send, resume, kill and typed
input (setup prompts, drafts, slash commands, Escape dismissals, launch-dialog keys) first checks the target
against the run manifest; a resume also requires the session id to be a manifest target's or one of the run's own
transcripts. Only pushed entry kinds count as received: `user`, `peer`, Pi `custom` and `hook`; a token seen only
in a `tool_result` (the receiver polled for it), a `system` entry or any other kind is not a delivery. A send whose
payload was written but whose reply timed out (`pi-ext`, `codex-remote-*`, the OpenCode HTTP routes) is accepted
with `verdict from the transcript`, so it ends `delivered` or `lost`, never `rejected`.

Scoring (`agentcomms/scoring.py`) counts a record as good per scenario: S1/S4 delivered and intact; S2 queued or
interrupted and intact; S3 delivered or queued and not harmful; S5 delivered, intact, in order and not merged (a merged burst lost its message boundaries); S6 delivered
after resume with `down=rejected|queued`; S7 delivered with `draft_fate=preserved`; S8 delivered and `rendered=yes`; S10
delivered; S11 delivered or queued and not harmful; S12 delivered or queued. `results/matrix.md` shows k/n per
agent × mechanism × host × backend; `error`, `n/a` and `env_error` records are left out of n and listed as
`err N`. `held` records (Claude peer messages parked for a human Deny/Deliver) count in n, are never good, and
are listed as `held N`.

## Attach

Sessions run on a private tmux server (`-L agentcomms`, config `tmux.conf`, never `~/.tmux.conf`):

```sh
tmux -L agentcomms -f ~/wrksp/_scratch/agent-comms/tmux.conf attach -t <run_id>-<agent>
```

Detach with the usual prefix + `d`. `launch` and `run --keep` print the exact command.

## Cleanup

`agentcomms cleanup <run_id>` is idempotent. It stops the run's tracked bridge daemons (identity-checked), kills the
run's tmux sessions and the run's own tmux servers (`/tmp/ac/agentcomms-<run_id>-*`, socket file removed), then every
process in the
recorded process groups and their descendants whose working directory is under `runs/<run_id>/`, plus each
recorded backend or deferred-sender pid whose process identity still matches and its descendants (SIGTERM,
SIGKILL after 5 s), removes recorded sockets, and stops the `agentcomms` tmux server once it has no sessions
(not when called per cell inside `matrix`, where another cell may be starting; `tmux.conf` sets `exit-empty on`, so
the server also exits by itself with its last session).
Harness Claude processes create `/tmp/cc-socks/<pid>.sock`, a directory shared with the user's live Claude sessions.
`cleanup <run_id>` and `cleanup --stale-claude-socks` remove such a socket only when a harness manifest records that
pid as a harness Claude target with a process identity, and no process with that identity is running any more; a pid
that now belongs to another process is reported and left alone, and no other socket in the directory is touched.
It prints the number of remaining harness processes, which should be 0. Once none remain, it deletes the
rows of the `credential` table in each OpenCode `runs/<run_id>/home/opencode/data/opencode/opencode.db`
(secure delete, `VACUUM`, WAL truncated); the transcript tables stay; and it deletes Codex
`shell_snapshots/*.sh` in the run's Codex homes. Like `launch` and `send`, it ends with the bridge-state guard (exit 5
when bridge state in the user's home changed).

## Isolation

| Agent | Home | Auth | Model |
|---|---|---|---|
| Claude | `CLAUDE_CONFIG_DIR=runs/<id>/home/claude` with pre-seeded `.claude.json` (onboarding done, work dir trusted) and `settings.json` (`skipDangerousModePermissionPrompt`; `claudeMdExcludes` lists `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` and `.claude/rules/**` in every ancestor of the work dir and the user's home, plus their resolved paths, so Claude's upward walk no longer loads `~/.claude/CLAUDE.md`) | `CLAUDE_CODE_OAUTH_TOKEN` from `sops-exec` | `haiku` (`--model haiku`) |
| Codex | `CODEX_HOME=runs/<id>/home/codex` with its own `config.toml` (model, effort, trust for `runs/` and the work dir, no notify/hooks) | `auth.json` symlink to `~/.codex/auth.json`, checked after every session | `gpt-6-luna`, reasoning `low` |
| Pi | `PI_CODING_AGENT_DIR=runs/<id>/home/pi` with its own `settings.json` (OpenRouter model, thinking off, no packages or extensions, `defaultProjectTrust: always`); sessions in `--session-dir runs/<id>/home/pi/sessions` with a pre-assigned `--session-id`; `PI_SKIP_VERSION_CHECK=1`, `PI_TELEMETRY=0`; the node process gets `HOME=<home>` (set after `sops-exec`, so HOME-relative reads such as `~/.agents/skills` land in the isolated home). Pi has no separate tool-shell setting, so its bash tool (`/bin/bash -c`) also sees the isolated `HOME`, unlike the other agents' tools, which see the real one: no `~/.gitconfig` (git identity unset), an empty `~`, and mise keeps its state/cache under the isolated home; `git`, `node`, `python3` and `mise` still run from the absolute `PATH` entries | `OPENROUTER_API_KEY` from `sops-exec` | `openrouter/deepseek/deepseek-v4.1-flash`, `--thinking off` |
| OpenCode | `XDG_CONFIG_HOME`/`XDG_DATA_HOME`/`XDG_STATE_HOME`/`XDG_CACHE_HOME` under `runs/<id>/home/opencode/{config,data,state,cache}`, `TMPDIR=…/tmp`, `OPENCODE_TEST_HOME=<home>`, `OPENCODE_DISABLE_AUTOUPDATE=1`; `config/opencode/opencode.json` sets the model and `update: disable`; TUI runs `--standalone` (private `opencode serve --stdio --port 0` child, never the background service) with a pre-assigned `--session ses_…` | `data/opencode/auth.json` symlink to `~/.local/share/opencode/auth.json` (read once into the isolated `opencode.db`), checked after every session | `opencode-go/gpt-6-luna` |
| Droid | `FACTORY_HOME_OVERRIDE=runs/<id>/home/droid` (Droid then uses `<home>/.factory/`) with its own `settings.json` (model, reasoning, `trustedFolders` = work dir and its git root, which is the work dir itself, and `autonomyLevel` `high` in `auto` mode, `off` in `prompting` mode); `FACTORY_DROID_AUTO_UPDATE_ENABLED=false`, `FACTORY_DISABLE_KEYRING=1` | `FACTORY_API_KEY` from `sops-exec` | `gpt-6-luna`, reasoning `low` |

Each receiver work dir (`runs/<id>/work/<agent>`) is `git init`-ed as its own empty repo before launch, so agents
see a clean git root rather than the harness repo (and its uncommitted changes); git is never run against the
harness repo.

Agent processes get a whitelisted environment (`env -i`; `HOME`, `PATH`, `LANG`, SOPS paths) plus
`DISABLE_AUTOUPDATER=1`, `AGENT_REQUIRE_SECRETS=1` and `TMPDIR=<isolated home>/tmp`, so variables from the launching
session do not leak in and agent temp files (Droid's `droid-bg-*.out`) stay in the run. zmx and zellij get
`TMPDIR=<state dir>/tmp` for the same reason.
Baselined on macOS 27.2 with the pinned Claude 2.1.312, Codex 0.165.0, Pi 1.4.0 (node 24.22.0), OpenCode 2.2.0 and
Droid 0.251.0 (`versions.os` is on every record; the matrix has a `macOS` column and counts older records as 26).
Every live command (`launch`, `run`, `matrix`, `s9`, `scale`, `hostcheck`, `iterm-holder`, `probe-bg`,
`probe-claude-link`) refuses to start from a sandboxed coordinator (exit 13; `nono why --self` must say
`NOT SANDBOXED`). The refusal says "is sandboxed" when the probe reports a profile and "could not verify … failing
closed" when the probe times out or prints nothing.
Binaries come from `vendor/agents/` (`profiles.resolve`; the user installs auto-update, which mixed versions into
one stage before pinning): Claude the `claude-<v>/<v>` file, Codex the copied release dir's `bin/codex` (also for
the daemon and app-server backends), Pi the copied package's `cli.js` run by the resolved node binary (node's
version is recorded as `versions.node`), OpenCode (also for its server backends) and Droid their copied binaries.
A pinned dir whose binary reports another version than its name is refused, for all five agents: every resolve runs
`--version` (Claude, Pi via node, OpenCode and Droid with `HOME` and the isolation variables of a launch, including the
autoupdate and keyring switches, pointed at a throwaway dir under `runs/.version-*`; Codex directly) and compares the
reported version with the directory name. Pi's `package.json` version must match too. Auto-update is off in every launch: Claude `DISABLE_AUTOUPDATER=1` and
`autoUpdates: false`, Codex `check_for_update_on_startup = false`, OpenCode `OPENCODE_DISABLE_AUTOUPDATE=1` and
`"update": "disable"`, Droid `FACTORY_DROID_AUTO_UPDATE_ENABLED=false`, Pi `PI_SKIP_VERSION_CHECK=1`.
`run` re-resolves every binary after the cell and stops the batch (exit 3) if anything changed. Codex runs with `--no-daemon` for
the terminal adapters (an embedded app server, no shared daemon); the backend adapters below use a harness-owned
server instead.

Modes: `auto` = Claude `--permission-mode bypassPermissions`, Codex
`--dangerously-bypass-approvals-and-sandbox`, OpenCode `--auto`, Droid `--auto high`; `prompting` = Claude
`default`, Codex `-a on-request -s read-only` (0.164.0 rejects `approval_policy="untrusted"`; Codex shows an approval dialog only when the model asks to escalate
out of the read-only sandbox, so S3's setup prompt on Codex asks for that escalation and its precondition depends on
the model making the request), OpenCode without `--auto`, Droid without
`--auto` and with `autonomyLevel: off` in its settings, so a file write shows an approval dialog (Droid 0.251.0 starts
in `Auto (Med)` when the setting is absent; 0.249.0 started with autonomy off). Pi has no approval modes, so both modes launch it the same way.

`run` hashes the user's global config files before and after a cell. `~/.claude.json` is rewritten every
minute or so by the user's own live Claude sessions, so a changed hash only stops the batch when the file
mentions the harness `runs/` directory. For Pi, OpenCode and Droid it also compares file mtimes under the
user's state dirs (`~/.pi/agent`; `~/.config/opencode`, `~/.local/share/opencode`, `~/.opencode`; `~/.factory`)
and prints a `note: … user state changed during run` line to stderr with the first `~`-relative paths if any
moved. These dirs churn with the user's own live sessions, so the note is not an open issue. A failed cell
is recorded with its cause: deterministic setup failures (cannot isolate: `skipped: cannot isolate; …`, binary
resolution, other errors) as `error`; transient ones (a timed-out version probe or other subprocess failure,
a tmux failure, an `OSError` such as EPERM/EACCES/ENOSPC) as `env_error`, which `--resume` retries. An ownership
check failure records nothing and stops the batch with a `STOP:` line (exit 7). If `cleanup` itself raises,
`run` prints a `STOP:` line (exit 8) and still runs the auth-link, global-config and progress steps; a failed
credential purge is reported as a cleanup note. Record notes and `progress.md` render the user's
home as `~`.

## Readiness

Claude: the isolated registry `<home>/sessions/<pid>.json` reports `status: idle` and the prompt is on screen
(`ready=registry:idle` in the record notes). Codex has no registry, so readiness is the labelled pane regex
(composer `›` plus footer; `ready=pane-regex`) plus the post-bootstrap status line `<model> <effort> · <dir>`, with
no `Waiting for startup` and no `loading` title on screen. Codex 0.164 draws the composer and footer as a
placeholder about 2 s before bootstrap ends, and input typed then is held behind `Waiting for startup`. Pi, OpenCode and Droid also use the labelled pane regex: Pi's
editor border plus the `(<provider>) <model> • thinking <level>` footer, OpenCode's `┃ Build … ·` composer
line plus `ctrl+p commands`, Droid's `│ >` input box plus `? for help`. Known first-run dialogs are answered
inside the isolated home and listed as `dialogs=` in the notes (Droid's folder-trust dialog is pre-empted by
`trustedFolders`; the dialog handler stays as a fallback). A known login/auth screen (e.g. Claude `Select login
method`, Codex `Sign in with ChatGPT`, Droid `Please login with your Factory account`, Pi showing its model without a
provider, which is how Pi 1.4.0 starts with no API key; Pi also draws that footer for a moment on a normal start, so a
screen counts only once it has stayed up for 5 s) ends the wait with `env_error` `auth-required: …`, which pauses a
batch instead of burning each later cell's ready timeout. Reply waits stop early once the receiver's tmux pane is
gone.

After launch, waits for a reply need the transcript to report idle; where it cannot tell (`is_idle()` is `None`,
e.g. Pi after a trailing `custom_message`), the pane-readiness regex decides instead.

## Transcripts

| Agent | Source | Notes |
|---|---|---|
| Claude | `<home>/projects/<cwd>/<session-id>.jsonl` | session id pre-assigned (re-read from the registry after readiness when a bridge assigns its own); `hook_additional_context` attachments are kind `hook` and count as received |
| Codex | `<home>/sessions/**/rollout-*.jsonl` whose `session_meta.cwd` is the work dir | developer messages from hook context (`hooks.additional_context`) are kind `hook` |
| Pi | `<home>/sessions/<ts>_<session-id>.jsonl` whose header `cwd` is the work dir | extension `custom` / `custom_message` entries are kind `custom`; a trailing `custom_message` makes idle unknown (`None`), since the record does not say whether it triggered a turn; the `pi-ext` extension writes `custom` entries `agentcomms-turn` `{"state":"busy"\|"idle"}` on `agent_start`/`agent_end`, and the latest one decides idle when no message follows it |
| OpenCode | `<home>/data/opencode/opencode.db`, opened read-only (`file:…?mode=ro`); `session_v2.directory` is the work dir | `session_message` and the queue tables are read in one read transaction; prompts submitted while busy sit in `session_inbox` (and legacy `session_pending`) first and are reported as kind `queue` until promoted under the same id; a missing queue table, a database not yet initialised (no `session_v2`) or a locked database reads as empty; a missing `session_message` or any other schema error (a renamed column after an OpenCode update) raises, so the cell is `error`, not `lost` |
| Droid | `<home>/.factory/sessions/<cwd-slug>/<id>.jsonl` whose `session_start.cwd` is the work dir | hook records (`hookEventName`) and `visibility` `llm_only`/`user_only`/`hidden` or `<system-reminder>` text are kind `system`, not `user`; `agent_turn_outcome` marks idle |

## Adapters

- `tmux-keys`: `send-keys -l <text>`, then one `Enter`.
- `tmux-paste`: bracketed paste with real ESC bytes (`\x1b[200~…\x1b[201~`, embedded markers stripped), then
  one `Enter`.

Native adapters (Task 4). Each one's sender is a stdlib-only script in `agentcomms/senders/` that reads the
message body on stdin and runs under `python3 -I` (no `uv`, so it also works inside nono); `sender_argv()` returns
it. `launch --adapter <name>` applies the adapter's launch setup, so `launch` + `send` reproduce a cell by hand.

| Adapter | Launch (on top of the isolated profile) | Send | Attach |
|---|---|---|---|
| `claude-uds` | nothing extra (default `crossSessionInbound`) | `senders/claude_uds.py --config-dir <home> --pid <pid>`: JSON lines `{"type":"auth","token":<peerToken>}` then `{"type":"user","message":{"role":"user","content":…},"priority":"next","msgV":1,"msg_id":…}` to the socket named in `<home>/sessions/<pid>.json` (`/tmp/cc-socks/<pid>.sock`); the peer token is read in-process from `<home>/sessions/<pid>.<sha256(socket)>.key` and never printed | tmux |
| `claude-uds-accept` | `--settings '{"crossSessionInbound":"accept"}'` | same | tmux |
| `claude-uds-child` | `--mcp-config <home>/relay-mcp.json`: a stdio MCP server `senders/claude_child_relay.py` that Claude itself spawns, listening on `/tmp/ac/<run>-relay.sock` | `senders/unix_send.py --socket /tmp/ac/<run>-relay.sock`; the relay forwards with `CLAUDE_CODE_MESSAGING_SOCKET`/`_TOKEN` from its own environment (log: `runs/<run>/relay.log`) | tmux |
| `claude-channel` | `--mcp-config <home>/channel-mcp.json --dangerously-load-development-channels server:agentcomms`; the MCP server is `bun run agentcomms/channel/server.ts` (declares `experimental["claude/channel"]`, listens on `/tmp/ac/<run>-ch.sock`); the "Loading development channels" warning is answered with Enter at launch (`dialogs=dev-channels`) | `senders/unix_send.py --socket /tmp/ac/<run>-ch.sock`; the server emits `notifications/claude/channel` (log: `runs/<run>/channel.log`) | tmux |
| `codex-remote-start` | backend `codex app-server --listen unix:///tmp/ac/<run>.sock` (own process group, `CODEX_HOME` isolated); TUI `codex -C <work> --remote unix:///tmp/ac/<run>.sock`; model, approval and sandbox move into the isolated `config.toml` | `senders/codex_remote.py --socket … --thread <uuid> --mode start`: JSON-RPC over a WebSocket on the unix socket (`initialize`, `thread/read`, `turn/start`); when a turn is running (or deferred messages are pending) the message goes to the run's per-thread spool and a tracked drainer delivers it in order (below) | tmux |
| `codex-remote-steer` | same | `--mode steer`: `turn/steer` with the running turn's id (`thread/turns/list`), `turn/start` when idle | tmux |
| `codex-queue` | `CODEX_HOME=<home> codex app-server daemon start` (refused unless the home is under `runs/` and its socket `/private/tmp/codex-daemon-<uid>/<sha256(<home>/app-server-control/app-server-control.sock)>` differs from the user's); bare TUI `codex -C <work>` (no `-c`/`-m`/mode flags, which would force embedded mode) | `senders/codex_queue.py --codex <bin> --codex-home <home> --thread <uuid>` → `codex queue --thread <uuid> --message …` (UUIDs only) | tmux |
| `codex-queue-embedded` | as `codex-queue` but the TUI gets `-c check_for_update_on_startup=false`, which makes it embedded while the isolated daemon runs (probe adapter) | same | tmux |

Backends are started by the engine before the TUI (`runs/<run>/backend.json` holds the spec, `backend.pid` the
current pid, `backend.log` its output) and recorded in the manifest as `<kind>:<pid>` entries plus an identity per
pid in `identities` (sha256 of the process start time and kernel accounting name from `ps -o lstart=,ucomm=`,
taken at track time; agent pids get one too; `ucomm` survives argv[0] rewrites, `comm` does not). `cleanup`, `live_runs` and the new-run refusal treat a backend pid as the run's only
while its current identity matches, so a pid reused by another process is never signalled; entries without an
identity (manifests written before this check) are never treated as owned. A restart replaces the kind's entries
and dead entries are pruned; it signals the old backend's process group only if `backend.pid` still has its
recorded identity, otherwise it only starts the new one. Every backend start, and every `codex app-server daemon` command, first re-checks the
spec from `backend.json`: `CODEX_HOME` must be set, lie under `runs/<run>/home/`, and give a daemon socket that
differs from the user's; a backend kind without such a check is refused. Codex binds even `--listen
unix:///tmp/ac/<run>.sock` as a symlink into `/private/tmp/codex-daemon-<uid>/<sha256(path)>`; `cleanup` removes
that target only when it is derived from the run's own listen socket `/tmp/ac/<run>.sock`, and removes a daemon
socket only for a Codex target the manifest records with backend `codex-daemon` whose home resolves inside the run
(R45). A path derived from a home outside the run (the user's `~/.codex` in user-config cells) is never removed; the
same rule covers the OpenCode service registration and Codex shell snapshots. If the daemon's start check fails, the
harness runs `daemon stop` and stops the pid-file pid when it is the spec's `codex` binary before raising.
`cleanup` also kills tmux sessions on the `agentcomms` server whose panes work inside the run but that no target
records (a bridge whose start timed out after creating its session), and stops the run's zmx and zellij sessions
before their state dirs go; a session that does not stop is reported as a `note:` and its state dir under `/tmp/ac`
is left in place. A pid is tracked only when this run's own code just started it (a backend, recorder or deferred
sender), it descends from the run's process groups, agent pids or already-tracked pids, its program is vendored code
(an executable under `vendor/`, or `node`/`bun`/`deno`/`python`/`sh`/`bash` running a `vendor/` path), or its cwd is inside
the run. Every SIGKILL after a grace period (cleanup sweep, bridge daemons, backend and service stops, S6, the
Claude background-service probe) re-reads the process identity first and spares a pid whose identity changed; for a
process group whose leader already exited, the surviving group is killed. Channel and relay sockets
(`/tmp/ac/<run>-ch.sock`, `-relay.sock`) are recorded in the manifest at launch; the servers also remove them on
exit. `restart_backend()` (S12) is a graceful stop then start from the saved spec (the daemon via `daemon stop`
and `daemon start` in the isolated home, the app server via SIGTERM to its group), not a crash; the record note
gives `stop Xs + start Ys = down Zs`, timed from before the stop. S12 types a warm-up turn first, since a Codex
thread with no turn is not persisted and does not survive a server restart (the TUI shows "This conversation is
unavailable").

`launch` and `send` refuse an adapter that does not support the agent (`launch --agent claude --adapter
codex-remote-start` exits 2 before creating a run). `send` to a target that fails the ownership check (no matching
manifest target, or its agent pid no longer in the run's process groups, e.g. after `cleanup`) prints `refused: …` and
exits 7. A `launch` that fails prints `launch failed for run <id>: <cause>`, cleans that run up and exits 1; it exits 11
while an earlier run still has live processes. `codex-remote-start` defers a send while a turn is running,
or while earlier deferred messages are pending: the message is spooled to `runs/<run>/deferred/<thread>/` and one
drainer per thread (`senders/codex_remote.py --drain`, serialized by a lock on the spool, tracked in the manifest
as `deferred-sender:<pid>` with its identity) delivers them in send order, one turn each, logging every outcome to
`runs/<run>/deferred.log`; records carry `deferred=<ok>/<n>`, plus `deferred-pending=<n>` when spooled messages
are still waiting at the end of the cell. `--drain` accepts only `runs/<run of --socket>/deferred/<--thread>`; a
drainer that cannot start (refused socket, connect or `initialize` failure) logs an `error` line with the cause for
every spooled message. A thread whose first turn is still materializing
(`thread/read` fails with "rollout … is empty" or "not materialized") counts as busy; any other
`thread/read`/`thread/turns/list` error rejects the send. Records also carry `send_s`, the longest
`adapter.send` call in the cell (`codex-queue` spends ~0.7 s in the `codex queue` CLI).

The agent-facing senders check ownership themselves, against the manifest of a run under `<repo>/runs` derived
from their own path: `claude_uds.py` needs `--config-dir` (a run's Claude home) and `--pid` (that run's target,
with a matching process identity), uses only the registry socket `/tmp/cc-socks/<pid>.sock`, and refuses when no
peer key exists; `codex_queue.py` needs `--codex-home` (a run's Codex target home with a live harness daemon);
`codex_remote.py` needs a `/tmp/ac/<run>.sock` listed in the run and a live harness app server; `unix_send.py`
only writes to `/tmp/ac/<run>-<kind>.sock` sockets listed in their run. Each prints `refused: …` and exits 2
otherwise. `sender_argv()` returns `None` until the target has the pid or thread id the sender needs.

Claude peer messages the receiver holds for approval appear as a system `informational` entry ("Held peer
message …"); the reader gives them kind `held`, and a message that only shows up that way is recorded with
delivery `held` (sender accepted, parked visibly for a human Deny/Deliver; not a good outcome) and the note
`held-for-approval`. Channel pushes are recorded as `isMeta` user entries with `origin.kind: channel` and count as
received; the channel server decodes each connection's bytes with one streaming decoder and ignores a connection
that sends nothing. `claude-bg` is not a matrix host: `agentcomms probe-bg` makes one guarded `claude --bg`
launch in an isolated config dir with `disableAgentView: false` (refused if `/tmp/cc-daemon-<uid>` exists; it
compares `~/.claude/daemon` mtimes and the socket dirs before and after, see `results/notes.md`).

Native adapters (Task 5). OpenCode routes were settled from the 2.0.32 source and the `v2.1.4` tag (see
`results/notes.md`): every server route is under `/api/`, there is no `/tui/*`, no `prompt_async` and no
`POST /session/:id/message`. Third-party Pi extensions run from `vendor/` only (`vendor/REVIEW.md`).

| Adapter | Launch (on top of the isolated profile) | Send | Attach |
|---|---|---|---|
| `opencode-server-steer` | backend `sops-exec opencode serve --hostname 127.0.0.1 --port <free port>` with the isolated XDG/`OPENCODE_TEST_HOME` env and `OPENCODE_PASSWORD=<random>` (also written to `<home>/server-password`); the harness creates the session first (`POST /api/session` with the pre-assigned `ses_…` id, the work dir as location and the configured model, since a session created without one gets OpenCode's free default model); TUI `opencode --auto --session <id> --server http://127.0.0.1:<port> <work>` (no `--standalone`) | `senders/opencode_http.py --url … --session <id> --password-file <home>/server-password --route prompt --delivery steer`: `POST /api/session/<id>/prompt` `{"text":…, "delivery":"steer"}` with Basic auth `opencode:<password>` | tmux |
| `opencode-server-queue` | same | `--delivery queue` | tmux |
| `opencode-server-synthetic` | same | `--route synthetic`: `POST /api/session/<id>/synthetic` (a `synthetic` message: the model answers it but the TUI shows only the answer, not the message) | tmux |
| `opencode-service-steer` | the default background-service path, isolated: `<home>/config/opencode/service.json` is pre-seeded with `hostname 127.0.0.1`, a free port and a password, then `sops-exec opencode service start` runs with the isolated env (it spawns a detached `opencode serve --service` whose registration is `<home>/state/opencode/service.json`; its pid is tracked with its identity); TUI `opencode --auto --session <id> <work>` finds it through that registration | as `opencode-server-steer` | tmux |
| `pi-ext` | `-e agentcomms/pi_ext/agentcomms-inbox.ts` with `AGENTCOMMS_PI_SOCKET=/tmp/ac/<run>-pi.sock`; the extension listens there and always calls `pi.sendUserMessage(text, {deliverAs: "followUp"})` (starts a turn when idle, queues behind a running one, so there is no idle-check race); it replies `queued followUp`, or `error compacting` between `session_before_compact` and `session_compact`/`session_compact_failed`, and `error empty message`. Pi reports send failures only asynchronously, so the reply never claims delivery; the verdict comes from the transcript | `senders/unix_send.py --socket /tmp/ac/<run>-pi.sock` (body on stdin, half-close, read the reply) | tmux |
| `pi-session-bridge` | `-e vendor/pi-session-bridge/node_modules/@vanillagreen/pi-session-bridge/extensions/session-bridge.ts` with `PI_BRIDGE_DIR=/tmp/ac/<run>-pb` (socket `pi-<pid>.sock`, registry `instances/<pid>.json`) | `senders/pi_bridge.py --socket /tmp/ac/<run>-pb/pi-<pid>.sock --command prompt`: JSON line `{"id":…,"type":"prompt","message":…}`, reply is the `response` line with that id (the bridge delivers now when idle, `steer` when busy; `steer`/`follow_up` commands force one); the vendored CLI `bin/pi-bridge.js send --socket …` speaks the same protocol | tmux |
| `pi-claude-link` | `-e vendor/pi-claude-link/node_modules/pi-claude-link/index.ts` with `XDG_RUNTIME_DIR=/tmp/ac/<run>-cl` (its socket is `cc-socks/<pid>.sock` there; its registry is `$HOME/.claude/sessions`, i.e. inside the isolated Pi home) | `senders/claude_link.py --socket /tmp/ac/<run>-cl/cc-socks/<pid>.sock`: one Claude peer frame `{"msgV":1,"msg_id":…,"type":"user","priority":"next","message":{"role":"user","content":…}}`, no auth line; Pi records it as a user message framed `[cross-agent message — from a Claude Code session, not your user]\nFrom …\n\n<body>`, which `unwrap` strips | tmux |

`launch --agent opencode --adapter opencode-server-steer` prints the run id; the server URL and session id are the
target's `backend_ref` and `session_id` in `runs/<run>/manifest.json`. The OpenCode backends are checked before
every start: every XDG dir, `OPENCODE_TEST_HOME` and `TMPDIR` must lie under `runs/<run>/home/`, `serve` must bind
`127.0.0.1`, and the service needs its seeded config (loopback, non-default port) and registration under the run's
home. S12 restarts them like the Codex backends (SIGTERM to the owned group, SIGKILL after 5 s; the service is
started again with `service start`). Run-owned socket dirs `/tmp/ac/<run>-*` are removed by `cleanup`; the
sockets inside them are recorded in the manifest after readiness (they are named by the agent pid).

Secret launch env (`OPENCODE_PASSWORD`) never goes into argv or the tmux `pane_start_command`: the engine writes it
to a 0600 `runs/<run>/env-<session>.sh` (`env-backend.sh` for the backend) and the launch becomes `/usr/bin/env -i
<public vars> /bin/sh -c '. "$0" && exec "$@"' <that file> <argv…>`. Launch files (`server-password`, the seeded
`service.json`, MCP configs) are written 0600. `free_port()` never returns OpenCode's service port 49374, and the
`serve` isolation check refuses it. `service start` runs in its own process group with a 150 s limit (OpenCode's
own ensure loop waits up to 120 s); on a timeout, a non-zero exit, a wrong registered URL or an unreachable port the
harness kills that group and stops the registered `serve --service` (pid from the run's registration, cwd inside
the run's home) before raising `BackendError`, and `cleanup` also stops a registered service whose cwd is inside the
run. `restart_backend` fails (S12 `error` with `backend-restart-failed: …`) unless the old backend was running as the
run's own process, is gone after the stop, and the start returned a process with a new identity. Pid-named sockets
(`ready_sockets`) are recorded on every start, so a resumed Pi's new socket is owned too. Isolated Pi settings set
`compaction.keepRecentTokens: 1`, so `/compact` works on a short harness session (S10).

The new senders check ownership like the Task 4 ones: `opencode_http.py` derives the run from `--password-file`
(must be under `runs/`) and needs a loopback URL that is a target's `backend_ref` with that `session_id` and a live
harness OpenCode backend with a matching identity; `pi_bridge.py` and `claude_link.py` need a socket inside
`/tmp/ac/<run>-<kind>/`, listed in that run's manifest, whose file name carries the pid of that run's Pi target with
a matching identity.

`agentcomms probe-claude-link` runs a harness Claude (`crossSessionInbound: accept`, `XDG_RUNTIME_DIR=/tmp/ac/<run>-cl`)
and a Pi with `pi-claude-link` in one run, with `<pi home>/.claude` symlinked to that Claude's isolated config dir so
both see only each other. It refuses before Pi starts unless the Claude socket is in `/tmp/ac/<run>-cl/cc-socks`,
the symlink resolves to the harness config dir and the registry lists only the harness Claude. It then tries Pi→Claude
through Pi's `claude-link` tool, the same wire sent by the package's own `sendToClaude` (run with `bun`), and
Claude→Pi through Claude's `SendMessage`, and writes `runs/<run>/mesh-probe.txt`.

## Hosts and hostcheck

Receivers run in tmux by default; zmx, zellij and iTerm2 are alternative hosts selected by the adapter
(`zmx-send`, `zellij-write`, `iterm2-text` and their `-paste` variants). See `agentcomms/hosts/README.md` and
`agentcomms/adapters/README.md`. `vendor/bin/{zmx,zellij}` are gitignored release binaries (`vendor/REVIEW.md`).

`agentcomms hostcheck` starts `agentcomms/hostcheck/recorder.py` (raw tty, bracketed paste enabled, logs every
`read()` as hex) inside each host and sends fixed payloads (plain, multi-line, quotes/`$VAR`/backticks, trailing
semicolons, tab, unicode+emoji, ~10 KB) and a burst of 5 through every terminal adapter of that host. It writes
`results/hostcheck.md` and `results/hostcheck.json`; raw reads are in `runs/<run_id>/hostcheck-*.json`. Chunk sizes
are the pty's read sizes (about 1 KB), not the host's write sizes. The iTerm2 host needs the iTerm2 Python
API enabled and runs cells in tabs of a persistent holder window that is only created while iTerm2 is not the
frontmost app: pre-create it with `uv run agentcomms iterm-holder`, close it with
`uv run agentcomms cleanup --iterm-holder`. A subset `hostcheck` run merges its rows into the existing
`results/hostcheck.md`.

## Bridges and S9 (Task 7)

Third-party bridges run from `vendor/` only (`vendor/REVIEW.md`); each is a `kind = "bridge"` adapter:

| Adapter | Agents | Launch | Send |
|---|---|---|---|
| `hcom` | Claude, Codex, Pi, OpenCode | `hcom <agent> <agent args>` in the tmux pane (`HCOM_DIR=runs/<id>/hcom`, `HCOM_TEST_ROOT=runs/<id>`) | `hcom send @<name> -b` (name from `hcom list --json` by work dir) |
| `intercom`, `intercom-accept` | Pi, Claude, Codex | Pi `-e vendor/agent-intercom-pi/index.ts`; Claude `cci --tui --transport native` (`-accept` adds `crossSessionInbound: accept`); Codex `coi` with the intercom MCP passed by `-c` | `agentcomms/intercom/send.mts` (vendored broker client, by work dir) |
| `csd` | Claude | `csd launch` (consent, worker dir and `HOME` in the run; `tmux` and `claude` shims) | `csd --worker <name> send` |
| `gc-nudge` | Claude, Codex, Droid | a repo-local city per slot (`runs/<id>/gc/<slot>/`: `gc init --file … --no-start`, `GC_HOME` in the run, own supervisor port, own tmux server `tmux -S /tmp/ac/agentcomms-<run>-<slot>`), `gc supervisor run` | `gc --city <city> session nudge <alias>` |
| `agent-deck` | Claude, Codex, Droid | `agent-deck add -c <shim> --tmux-socket agentcomms` + `session start` (`HOME`/XDG in the run, updates off) | `agent-deck session send <title> --message-file -` |
| `agent-deck-composer-fallback` | Codex | as `agent-deck` | adds `--codex-composer-fallback` |

A bridge either runs the agent through a launcher (`LaunchMods.launcher`; the agent itself is a per-run PATH shim in
`runs/<id>/bin/<slot>/` that execs the pinned binary) or creates the tmux session itself (`start_session`) on
`-L agentcomms` (gc: on its own per-run server, `-S /tmp/ac/agentcomms-<run>-<slot>`). Bridge daemons are tracked as
`bridge-daemon` pids; `cleanup` stops them first, then kills the sessions, the run's own tmux servers (and their
socket files) and vendored bridge processes whose cwd is in the run.

Rule: any tool a bridge tells the agent to run (a beacon, primer, hook or notify command, e.g. gc's "Run `gc prime`",
agent-deck's Codex `notify = ["agent-deck", "codex-notify"]`, hcom's `hcom send`) must resolve, from the agent's
shell, to a run-pinned wrapper of the vendored binary that comes first on the agent's `PATH`
(`runs/<id>/bin/tools-<slot>/<tool>`: `env -i` with the run's `HOME`/state dirs, then `vendor/…`), and the user's own
install of that tool must not be reachable by name. gc cells also run the agent with `HOME` in the run
(`runs/<id>/gc/<slot>/agent-home`, whose `go/bin` and `.local/bin` link to the wrapper for gc's hooks),
`GC_CITY`/`GC_HOME`/`GC_CEILING_DIRECTORIES` pinned, and a `PATH` without any dir that holds `gc` or `mise` or is a
`shims` dir; the user's `PATH` and `HOME` reach only `sops-exec`. `tests/test_task7_containment.py`
(`test_bridge_instructed_tools_resolve_to_vendored_run_pinned_binaries`) checks this for gc, agent-deck and hcom.

gc types a beacon into each session it starts, which begins a `gc prime` turn. Adapters can name such a startup marker
(`startup_marker`); the engine waits for it and for the session to be idle before the scenario starts and records
`startup-turn=<s>` (S9: `a-`/`b-startup-turn`).

Bridge-state guard: `run`, `matrix`, `s9`, `launch`, `send` and `cleanup` compare size and mtime of every entry under
`~/.gc`, `~/.pi/agent/intercom`, `~/.hcom`, `~/.agent-deck`, `~/.config/agent-deck` and `~/Library/LaunchAgents`
before and after, and exit 5 on any change. `~/.gc/events.jsonl` and `~/.gc/supervisor.log`, which the user's own
supervisor appends to, stop the run only if they shrink or are replaced; growth is printed and appended to
`runs/<id>/bridge-guard.txt` with byte deltas and attributed to a running user `gc supervisor run` (not under
`vendor/`) when there is one.

Isolated Codex homes set `[features] shell_snapshot = false` (Codex otherwise writes the exported environment, secrets
included, to `shell_snapshots/*.sh`), and `cleanup` deletes any `shell_snapshots/*.sh` in the run's Codex homes.

`agentcomms s9` launches A with the `--back` adapter and B with `--fwd` (same-agent pairs without shared bridge state
put B in a second run), writes B's message to `runs/<id>/s9/to-b.txt`, and types one instruction into A: run B's
agent-usable sender with that file on stdin, or use a native tool (`SendMessage` for Claude peers, `intercom_send`)
with the text quoted in «». The message asks B to reply `ACK <token>` through A's adapter. The record (agent = A,
mechanism `fwd` or `fwd+back`) is `delivered` when B received it, `held`, `lost` (A ran the send, B never recorded
it) or `error` (`a-did-not-send`), and notes `pair`, `discovery=name|address`, `attribution=mechanism|message|none`,
`roundtrip=yes|no`, `reply-kind`, `roundtrip_s` and `b-replied`. S9 counts as good only with `roundtrip=yes`, which
needs all of: B received the message; A's transcript holds `ACK <token>` as a pushed entry (`user`, `peer`, `custom`,
`hook`; a `tool_result` means A polled); that entry comes after B's receipt; B ran the reply route (a `tool_use` with
the reply marker) in between; and A did not run it itself. Otherwise `no-roundtrip=<reason>` names the failed check.
`discovery` is a property of the route, not of A's behaviour: A is always handed B's name or command, and `name`
means the mechanism addresses B by a bridge name. `attribution` matches whole identities (names, ids, pids) in the
frame around the body, not substrings.


## Task 10: shortlist reps, scale, user config, nono

`scale` (`agentcomms/scale.py`) launches the eight receivers of `scale.MIX` at once, each in its own run with its own
backend (two Claude `claude-channel`, two Codex `codex-remote-start`, two Pi `pi-ext`, one OpenCode
`opencode-server-queue`, one Droid `tmux-paste`), waits for all to be ready, then sends three rounds: in each round
every receiver gets one envelope at the same moment (a barrier) and the round ends when every receiver answered or
timed out. Each message is a `SCALE` record (stage `shortlist`, rep = per-agent ordinal); `results/scale-<first run id>.json` holds
the latency spread and the load samples (`ps -o pid,rss,pcpu` every 2 s on the runs' own pids, owners refreshed every
20 s, launch and message
phases separately). A receiver whose launch or a round fails gets an `error` record and keeps attending the
round barrier, so the others stay synchronized and their records and the scale JSON (`errors` counts uncounted
records) are still written; with no receiver up the message phase is skipped.

`--stage user-config` runs cells with the user's real global config (R41). `agentcomms/userconfig.py` lists what each
agent's config would load (names only), classifies outward-facing integrations and the per-launch switch that turns
each one off, and skips a cell (recorded `n/a` with `skipped: …`) when trust cannot be satisfied without a global
write, when the mechanism would attach to a live user daemon or service, or when an outward integration has no
per-launch switch. A hook, plugin or other integration that is not on the reviewed list
(`userconfig.REVIEWED_LOCAL`) is "unclassified" and skips the cell (`user-config-inventory` prints it as `unclassified`). Each declared switch is verified in the argv and
env the overlay actually built (`userconfig.verify`, R48: the `-c` pair in both TUI and backend argv, `XDG_STATE_HOME`
inside the run, the no-op `rl` shim first on `PATH`); a switch that is not there skips the cell as `n/a` before
anything starts. The Codex plugin and MCP `-c` switches are pinned in argv, not live-verified to take effect. Each
cell lists the files it created or changed in the user's stores (`~/.codex`, `~/.pi/agent`, `~/.config/opencode`
including `node_modules`) in `runs/<id>/user-store-writes.txt` and notes `user-store-writes=<n>`. Codex runs with `CODEX_HOME=~/.codex` and `-c` switches on both the TUI and its run-owned app
server (only `codex app-server --listen unix:///tmp/ac/<run>.sock` is allowed with the user's home); Pi runs with the
default `~/.pi/agent` and `HOME`, sessions still in the run (`--session-dir`); OpenCode reads the user's config dir
while data, state and cache stay in the run (the user's service database is never opened). `XDG_STATE_HOME` points
into the run so hooklinesinker hooks find no consumers. Work dirs stay under `runs/`.

`--sandbox nono` (`agentcomms/sandbox.py`) reproduces `_agent_sandboxed` from `~/ac/.airc.d/05-sandbox.zsh`:
`sops-exec nono run [--silent for claude/opencode] -p <agent>-local -- <pinned binary>` with the launcher env
(`PATH` with `~/ac/bin/sandbox-shims` and `~/ac/bin` first, `AGENT_HARNESS`, `AGENT_SANDBOX=1`,
`AGENT_SANDBOX_PROFILE`, `DOCKER_HOST`, `OTHER_SWIFT_FLAGS`, `AGENT_BROWSER_ARGS`, `VHS_NO_SANDBOX`,
`DISABLE_AUTOUPDATER=1`, `SSL_CERT_FILE=/etc/ssl/cert.pem`). Differences: `--no-audit` (fewer writes into nono's
state dir), `NONO_NO_UPDATE_CHECK=1` for nono only, and the agent's isolated `XDG_*` dirs are hidden from nono (which
would otherwise look for its profiles there) and restored for the agent by an inner `/usr/bin/env`. Backends
(`codex app-server`, `opencode serve`, the Codex daemon and OpenCode service starts) run under the same profile, and
the harness-side sends run the adapter's stdlib sender (`sender_argv`, message on stdin) under `nono run -p
<receiver agent>-local`; tmux adapters run their `tmux` commands there. nono keeps its session records in
`~/.local/state/nono/sessions/` and refuses a state dir inside any granted path (the repo and `/tmp` are granted), so
every `nono run` leaves one session file there (`results/notes.md` lists them).
