# Design decisions

Why the harness works the way it does, and what a later run (e.g. on the Mac Studio) must keep. How things work is in
`docs/harness.md`; results are in `REPORT.md`.

The harness, `REPORT.md` and `results/` cite rulings from the build run by id (R9 … R51). Those ids resolve here, in
parentheses after the decision they name. Ids that appear nowhere in this file were about running the build (commit
policy, task chunking, fix rounds) and do not constrain later work.

## Scope

- A receiver is an interactive TUI a human can attach to and type into. Any host and launch-time setup is allowed;
  the attach command is recorded. Headless modes (`claude -p`, `codex exec`, `pi --mode rpc`, `droid exec`), ACP and
  `@microsoft/tui-test` are inventory only (`docs/enumeration.md`).
- Same machine only. Cross-machine claims are recorded in the adapter's `claims_cross_machine` (quote and source),
  never tested.
- Queueing until the turn boundary is the preferred mid-turn behaviour; interrupting is recorded as a capability.
- Cheapest model per agent. ACK compliance is model behaviour, not mechanism: an intact delivery without the ACK
  (`model_noncompliant`) still scores good (R10).
- iTerm2 is a lower-priority host (the fleet uses tmux): hostcheck and spot cells only, `n/a` in screen (R32).

## Constraints a re-run must keep

- **Writable:** the repo (`runs/`, `vendor/`, `results/`) and `/tmp/ac/` for sockets. Socket paths stay short
  (`sun_path` is at most 104 bytes on macOS), which is why sockets live in `/tmp/ac/<run>…` and not under `runs/`.
- **Read-only:** the user's agent configs and stores (`~/.claude*`, `~/.codex`, `~/.pi`, `~/.config/opencode`,
  `~/.local/share/opencode`, `~/.factory`), `~/ac`, `~/rc`, `~/.gc`, `~/wrksp/_external/*` (copy into `vendor/` to
  build) and plugin caches. Pinned agent binaries are copies (`docs/harness.md` Setup), never the live installs.
- **Never run:** `codex app-server daemon stop|restart|update|bootstrap` against the user's daemon; `claude
  stop|respawn|rm` on a session the manifest does not own; `opencode service …` outside an isolated home; any `gc`
  command against the user's city (`tmux -L cadet-city`); `tmux kill-server` on any server but `-L agentcomms` and
  the run's own `-S /tmp/ac/agentcomms-<run>-*` servers.
- **Coordinator unsandboxed** (R21). Live commands refuse to start under nono (exit 13). Receivers inherit the
  coordinator's Seatbelt profile, so a sandboxed coordinator would label records `raw` while they ran under its
  profile, and the nono pass cannot nest `nono run`. The nono pass sandboxes receiver, backend and sender itself.
- **nono:** do not edit the `<agent>-local` profiles or add grants; the pass measures the user's real launcher.
  Every `nono run` leaves a session file in `~/.local/state/nono/sessions/`; this is unavoidable. The pass starts
  with `nono-preflight` (R19): agent-run senders depend on `ps`, which a profile might block.
- **Third-party code** runs from `vendor/` only, after its install and hook scripts were read and recorded in
  `vendor/REVIEW.md` with version and sha256. npm uses `vendor/.npm-cache` (the first `npm pack` without it wrote to
  `~/.npm`); `pi-session-bridge` installs with `--ignore-scripts` (its `postinstall` writes
  `~/.pi/agent/APPEND_SYSTEM.md`). A bridge that needs a write to global config is skipped and recorded.
- **Secrets:** never print tokens or key-file contents. Claude peer keys inside the isolated home are read in-process
  only.
- An agent that cannot be isolated is skipped (`skipped: cannot isolate; …`), not run against the user's home.

## Isolation

Every test session gets an isolated home under `runs/<run_id>/home/<agent>/` (table in `docs/harness.md`). Decisions
beyond that table:

- Isolated Claude excludes every ancestor `CLAUDE.md` (R9). The upward walk from `runs/` reached the user's
  `~/.claude/CLAUDE.md`, which steers ACK compliance and verbosity and holds private instructions. Claude cells before
  the fix ran with it loaded.
- Receiver work dirs are their own empty git repos (R12), so trust and project config resolve to the run dir and
  agents do not see the harness repo's uncommitted changes.
- Codex homes disable shell snapshots (R29): Codex otherwise writes the sops-injected environment to 0644 files.
- Bridge-instructed tools resolve to run-pinned wrappers (R28). Bridges tell the agent to run their CLI by name
  (`gc prime`, `hcom send`, agent-deck's notify hook); before the fix a gc receiver's shell found the user's real
  `gc`. Agents in bridge cells therefore get a run-local `HOME`, per-run tool shims first on `PATH` and no user
  gc/mise/shims dirs; the bridge-state guard (exit 5) catches anything that still reaches the user's bridge state.
  The price is a slightly different shell environment than a fleet would give the agent.
- Known limits, accepted: Droid's interactive import screens and `/loop` read `~/.claude/*` and `~/.agents/commands`
  even with `FACTORY_HOME_OVERRIDE` (R7), so human-proxy input never opens them (`s8.safe_human_text`). Harness Claude
  sockets still land in the shared `/tmp/cc-socks` (cleanup handles them by identity). The user's
  `disableAgentView: true` leaks through `CLAUDE_CONFIG_DIR`, so the `claude --bg` host is untested (R16).
- The user's shared Codex daemon was down for the whole run. Terminal adapters run Codex with `--no-daemon`;
  `codex-queue` starts its own daemon in the isolated home and refuses to start if the socket would be the user's.

## Versions and re-baselining

- Agents run from pinned copies with auto-update off (R35). Codex, Droid and OpenCode auto-updated mid-stage once;
  a 15 h stage on live installs keeps drifting, and Droid 0.251 changed S3 behaviour (new default autonomy), so drift
  is real, not cosmetic. The version guard stops a batch when a version changes (exit 3).
- A version change mid-stage supersedes that agent's old-version verdicts for the stage, which are re-run (R32, R35).
  Older pilot and S9 records keep their versions and are labelled.
- Codex is pinned by its concrete release dir, never `current`; Pi by the install the user's wrapper actually runs.
- After an OS or agent update, re-baseline before new stages (added after the macOS 26 to 27.2 move, R20): re-run S1
  for every mechanism × agent plus a few safety cells, one at a time, and compare verdicts with the old records
  (`results/notes.md` "Task 4b re-baseline"). Fix harness drift (readiness regexes, dialogs, version parsing) with
  regression tests; record real behaviour changes as drift, not as fixes.
- Audit every agent's ready signal against its pane log after an update (R14): Codex 0.164 drew its composer as a
  placeholder before bootstrap ended, so cells sent during startup and their evidence had to be re-run.

## Records

- `results/raw.jsonl` is append-only evidence. A record produced by a harness bug, the wrong version or user
  interference is moved to `runs/<id>/superseded-record.jsonl` and listed in `results/notes.md`, never edited or
  silently deleted (R11). A relabel is done by a re-run that supersedes the old record (R17). `runs/` is gitignored,
  so superseded records exist only on the machine that made them.
- When a rule changes, existing records may be re-derived from their stored evidence, with a note appended to each
  changed record (R47, R50).
- Records whose isolation failed keep their data with a note saying what happened (R43); they must not claim
  isolation.
- Counts are k/n, never percentages. Most cells have n = 1 to 5, so only frequent failures are detectable.
- `latency_s` is send time to the first receiver-side record of the token; `null` when not delivered.
- The envelope puts the ACK instruction before the body (`ACK-REQUEST <token>: reply with exactly "ACK <token>".
  <body>`), so trailing payload characters cannot hide it. Tokens are 8 hex chars; S3 and S11 draw them from `a`–`f`
  so no digit can pick a numbered dialog option.

## Verdicts

| value | meaning | why it exists |
|---|---|---|
| `delivered` / `queued` / `interrupted` | recorded now / after the turn, prompt or modal ended / steered the running turn | queued vs interrupted is the mid-turn property the fleet cares about |
| `rejected` | sender got an explicit failure | loud failure, recoverable by the sender |
| `lost` | sender reported success, receiver never recorded it | silent failure; includes text left in the composer (`stuck-in-composer`, R4) |
| `held` | receiver parked it visibly for a human Deny/Deliver (Claude default inbound) | visible to the human, unlike `lost`; never good (R17) |
| `error` / `env_error` | harness failure or failed precondition / sleep, network, quota, auth | never a verdict on the mechanism; `env_error` is retried |

Rules behind the scoring in `docs/harness.md`:

- **Receipt allowlist** (R50, R30): only pushed entry kinds (`user`, `peer`, Pi `custom`, `hook`) count as received.
  A token seen only in a `tool_result` means the receiver polled for it, which is not a push. The same rule applies to
  old and new records.
- **Harm:** S3 is harmful when the send approved the permission dialog; S11 only when the shown model changed. A
  picker selection with no model change is a note (`modal-selection-made`), not harm (R10).
- **S5 burst** (R47): the five sends must go out within 1 s, since a slow burst is not a burst. An adapter whose own
  sends take longer by design records `n/a` ("adapter cannot burst"); a window missed for any other reason is `error`
  (`burst-window`). The adapter's share is the time inside each whole `adapter.send` call, so a pre-send CLI round
  trip (intercom's `--list`) is the adapter's and the harness's ownership check and pid tracking are not. A merged burst is not good, because message boundaries are lost and attribution breaks (R10).
  `codex-queue` lost its S5 coverage to this rule and needs a re-test.
- **S8 visibility:** the pushed prompt itself must render in the attached TUI, not only the reply (R25,
  `rendered=reply-only`). A push answered in a thread the human cannot see is `delivered` with `rendered=no` (R33).
  Both score not good: the human must be able to follow the session. The render wait is 45 s, for slow-relay hosts
  (zmx relays OpenCode screens in ~30 s bursts, R32).
- **S1 is idle wake without a warm-up turn** (R31). agent-deck never sees a fresh Codex TUI go idle (its notify hook
  needs a completed turn), so its Codex S1 stays `lost`.
- **S12** needs the same session to survive: an agent the restart killed is `lost` (`agent-lost-by-restart`), one a
  bridge respawned is not good (`agent-respawned-by-bridge`, context lost) (R39, R46). Codex S12 types a warm-up
  turn first, since a thread with no turn does not survive a restart (R18).
- **S10** on address-based routes: when the push after `/new` lands in the old session, the compact step says nothing
  about compaction and is reported as "not exercised" (R40).
- **Droid through a bridge** (agent-deck, gc-nudge) is terminal injection, since the bridge types into Droid's pane
  (R31).
- **Enter:** baseline terminal adapters send exactly one Enter. Only `tmux-paste-retry` retries, and only while the
  receiver is confirmed idle with an empty input box, because a blind extra Enter can approve a dialog or submit a
  human's draft.
- **S3 recipes:** Codex 0.164 rejects `approval_policy="untrusted"`, so prompting mode is `-a on-request -s
  read-only`, which shows a dialog only when the model asks to escalate; Codex's S3 setup prompt therefore adds
  "request approval to run the write outside the sandbox". Droid prompting mode sets `autonomyLevel: off`. Pi has no
  approvals (S3 `n/a`).
- **`n/a` by construction** (R36), declared in each adapter's `scenario_na`: S6 for bridges that own the session
  lifecycle (csd, agent-deck, gc-nudge) and Codex intercom (`coi … resume` rejected); S3 where the launch shows no
  dialogs (Claude `intercom-accept` with `--yolo`, csd with `--dangerously-skip-permissions`) or the startup turn never
  settles in prompting mode (gc-nudge); S12 for daemonless bridges and Claude's stdio channel and relay children.
  Codex intercom S2 is `delivered` in a parallel thread, scored not good like R33.

## Stages and ranking

- Ramp: pilot (S1, one cell at a time) → screen (S1, S4, S7, S8, 1 rep) → extensive (all applicable scenarios on
  survivors; 3 reps for S2, S5, S7) → shortlist (5 reps of S1, S2, S5, S7; scale; user-config; nono). Each stage
  starts after the previous stage's harness issues are fixed.
- Survivor = a good S1 outcome and no harmful outcome.
- Concurrency: one receiver in pilot, at most 3 otherwise, never two cells on one agent or one bridge's state, because
  backends, auth files and bridge registries are shared per agent.
- Extensive reuses screen records as the S1, S4, S8 rep and S7 rep 1 (R34). zmx and zellij terminal adapters are
  byte-identical to tmux per hostcheck, so they run only the host-sensitive S2×3, S5×3 and S6; the rest borrows the
  tmux adapter's verdict (`(eq)`), unless a host-sensitive result differs. Typed adapters on zmx/zellij were
  screened, not borrowed; `intercom-accept` was screened on Claude only, its launch and sender being identical
  elsewhere (R32).
- Safety is ranked first, over a fixed denominator of 7: S2×3, S3×1, S7×3 (R37). An `n/a` safety cell counts as not
  shown safe; a shrinking denominator had ranked a mechanism with structurally `n/a` S3 first. Ties then break on
  total k/n, fewer harmful outcomes, larger n (`results/shortlist.md` "Ranking basis", `agentcomms/shortlist.py`).
- Shortlist = top 2 per agent, plus every mechanism that passed S9 on the pinned versions (R38). S9-only entries are
  agent-to-agent options and get no delivery reps, user-config or nono cells (R44).

## S9 agent-to-agent

- "A↔B" runs both directions where routes exist, A first; the record's agent is A (R30). Same-agent native pairs use
  two runs; bridges with shared state (hcom, intercom, gc) put both in one run with slots. `codex-queue-embedded` is
  out of S9 (a probe adapter; it did not survive the screen).
- Round trip needs B's receipt, B's own reply send, and the reply pushed into A after that receipt, neither sent by A
  nor polled through a `tool_result` (R30). The earlier classifier credited replies B never sent.
- Both agents run in isolated homes, so their own discovery (Claude `ListAgents`, bridge registries) only sees
  harness sessions; the recipient must be harness-owned.
- If Pi as sender fails on malformed tool arguments with the cheapest model, one extra rep runs with the
  next-cheapest OpenRouter model that handles tool calls, recorded on the record; mechanism and model verdicts are
  reported separately (R24).

## User-config cells

Stage `user-config` loads the user's real global config to catch interference from hooks and plugins. It is the only
place real config is used, and it trades coverage for safety:

- No outward contact, no attach to the user's live daemons or services, no global writes; trust is satisfied without
  writing global config or the cell is skipped; every file a cell creates in the user's stores is recorded, not
  deleted (R41).
- A "disable" counts only when it verifiably applies (R42): OpenCode's MCP disable did not, and `context7` started
  in 5 cells. Verification inspects the argv and env the harness actually built, and an integration not on the
  reviewed list is unclassified and skips the cell (R48). Switches are pinned in argv, not live-verified.
- Current coverage and why: Claude and Droid skip (no trust path without a global write); Pi skips (it rewrote
  `~/.pi/agent/settings.json`); Codex app connectors cause a skip (openai/codex#17588), Codex plugins are disabled
  with `-c`.

## Accepted trade-offs

- The per-run OpenCode server password sits in gitignored `runs/<id>/backend.json` and the isolated home, and under
  plain `serve` the agent's own tools inherit it (R23). It is a random per-run secret for a 127.0.0.1 backend, and
  it is what lets an agent send to another OpenCode session.
- Claude `crossSessionInbound: accept` delivers frames from any same-user process without a token (R26). The harness
  measures it as one route among three; the fleet choice between accept, the channel and the child relay is open
  (`REPORT.md` section 13).

## Hosts

- iTerm2 cells run as unselected tabs of one persistent holder window, created only while iTerm2 is not frontmost
  and closed only by `cleanup --iterm-holder` (R27). New windows took key focus and the user's typing landed in test
  sessions.

## Ownership and cleanup

- Every send, resume, kill, typed input and cleanup checks the target against the run manifest. Pids are owned only while their recorded process identity (start time and `ucomm`)
  still matches, so a reused pid is never signalled.
- Cleanup never derives a path from a home outside the run (R45): a derived Codex daemon socket, service
  registration or shell snapshot is removed only for a home that resolves inside `runs/<run_id>/`. The old
  derivation could have named the user's real daemon socket.
- A spawned pid is adopted only if it descends from this run's own processes or runs a `vendor/` program (executable under `vendor/`, or an interpreter running a `vendor/` path). Accepted residual (R51): a concurrent run's vendored daemon can be adopted after pid reuse; requiring a run path or run cwd would leave the real intercom broker (cwd in `vendor/`, no run path in its args) untracked and leaked.
- Spawn with `start_new_session=True` and kill by process group. The tmux pane's pid is `sops-exec`; walk the
  process tree to find the agent.

## Stops, pauses and exit codes

A stop ends the batch after the running cells so no further paid cells start; a pause is for conditions a later
`--resume` can fix. Details per code are in `docs/harness.md` Commands.

| code | meaning | kind |
|---|---|---|
| 0 | every record is a verdict, `n/a` or requeued `env_error` | |
| 1 | `launch` failed (run cleaned up) | |
| 2 | usage error: unknown agent/adapter/scenario, unsupported pair, bad plan entry, unknown run id (R49); senders' ownership refusal | |
| 3 | an agent version changed | stop |
| 4 | auth symlink replaced or its check raised (`codex login` may be needed) | stop |
| 5 | user global config or bridge state changed | stop |
| 6 | a cell recorded `error` | |
| 7 | ownership check failed | stop |
| 8 | cleanup raised | stop |
| 9 | harness processes survived cleanup | stop |
| 10 | quota/auth/API error, auth screen, receiver crash, or `runs/STOP` present before the first cell (R49) | pause |
| 11 | an earlier run still has live processes | stop |
| 12 | harness bug (unexpected exception) | stop |
| 13 | coordinator is sandboxed or the check could not verify (fails closed, R49) | refuse |

`runs/STOP` ends a `matrix` batch after the running cells. `matrix` never deletes it, so a leftover file blocks the
next batch: a stop request is cleared by whoever made it, not by the harness.
