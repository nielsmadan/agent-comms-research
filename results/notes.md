# Notes

## Task 1 pilot (2026-10-24)

- Claude 2.1.310 and Codex 0.164.0 both start in isolated homes with no first-run dialog: the pre-seeded
  Claude `.claude.json` and the Codex `projects.*.trust_level` entries cover onboarding and trust.
- S1 `tmux-paste`: delivered and acked on both agents (runs `20261024-071503-76bd`, `20261024-071514-69b9`).
  The Codex run was later found to have pasted before Codex finished bootstrapping (R14), and was moved out of
  `raw.jsonl`. Its replacement `20261025-000919-7c61` was delivered and acked, 2.9 s.
- S1 `tmux-keys` on Codex: lost (run `20261024-071557-dc26`). The text stayed in the composer and the single
  Enter sent straight after `send-keys -l` did not submit it; Codex appears to treat the fast keystroke burst
  as a paste and absorb the Enter. Claude delivered the same `tmux-keys` cell. Confirmed after the Codex readiness
  fix (R14): `20261025-000948-32cb` was lost again, with the text left in the composer (`stuck-in-composer`).
  `dc26` itself was sent after bootstrap had finished (its pane log shows the `GPT-6-Luna low ·` status line before
  the keystrokes), so it stays in `raw.jsonl`.
- `~/.claude.json` is rewritten by the user's live Claude sessions about once a minute with no harness
  process running (two hashes 90 s apart differed), so a raw before/after hash of that file cannot show
  harness writes. `run` now treats a change as harness-caused only if the file mentions `runs/`.
- The Codex shared daemon was not running during the pilot (`codex app-server daemon version` could not
  connect; the stale `daemon.pid` names a dead pid, last daemon log line 2026-10-24T01:36Z), so records carry
  no `codex_daemon` version. No other daemon command was run.
- The inventory files named in the plan were missing from the coordinating session's scratchpad; `docs/`
  holds them as recovered verbatim from the Write calls that created them in that session's logs.

## Task 2 pilot (2026-10-24)

Installed versions moved since the plan was written (the user's 2026-10-23 21:12 update): Pi 1.4.0 (plan
1.3.0; mise `latest` -> `1.4.0`, 1.3.0 still installed), OpenCode 2.1.4 (plan 2.0.32), Droid 0.249.0 (plan
0.244.0). The harness pins whatever `latest` / the binary resolves to at run start and records it.

S1 `tmux-paste`, one rep each, all delivered intact and acked with transcript + pane evidence, no dialogs:
Pi `20261024-154919-6441` (0.02 s), OpenCode `20261024-154928-e5ee` (0.13 s), Droid `20261024-154942-15e7`
(0.21 s). Global config hashes identical before and after all three; OpenCode `auth.json` still a symlink to
`~/.local/share/opencode/auth.json`; `~/.factory` file list and mtimes identical to a snapshot taken before
the first Droid launch; no file under `~/.pi/agent`, `~/.config/opencode`, `~/.local/share/opencode`,
`~/.opencode` changed during the runs; `cleanup` left 0 harness processes each time.

### Pi 1.4.0

- Binary: `~/.local/share/mise/installs/npm-earendil-works-pi-coding-agent/1.4.0/node_modules/.bin/pi` (a
  shell shim that execs `node …/cli.js`); the node process retitles itself `pi`, so the agent pid is found by
  that title inside the pane's process tree.
- Model: `openrouter/deepseek/deepseek-v4.1-flash`, thinking off (cheapest OpenRouter model in Pi's bundled
  catalog: $0.034/$0.137 per M tokens; one S1 turn cost $0.00006). Auth `OPENROUTER_API_KEY` via `sops-exec`.
- Isolation honoured: `PI_CODING_AGENT_DIR` (settings, `auth.json`, `models-store.json` all land in the
  isolated dir), `--session-dir`, `--session-id` (file is `<ts>_<id>.jsonl`). No trust or onboarding prompt
  with `defaultProjectTrust: always`; `lastChangelogVersion` pre-set suppresses the changelog.
- Readiness: pane regex (editor border + `(openrouter) <model> • thinking off` footer).
- Extension output: a probe extension's `appendEntry` and `sendMessage` produced top-level `custom` and
  `custom_message` records (not `message` role `custom`); both are read as kind `custom`
  (`tests/fixtures/pi/custom.jsonl`).

### OpenCode 2.1.4

Env/behaviour verified from source at `~/wrksp/_scratch/opencode-v2.0.32` and spot-checked unchanged at tag
`v2.1.4` (`gh api …/contents/<path>?ref=v2.1.4`, files diffed identical except a new `heap-dump` command):

- `packages/util/src/global-roots.ts:5-8`: data/cache/config/state roots are `XDG_DATA_HOME`, `XDG_CACHE_HOME`,
  `XDG_CONFIG_HOME`, `XDG_STATE_HOME` (falling back to `~/.local/share` etc.); `tmp` is `os.tmpdir()/opencode`,
  so `TMPDIR` is isolated too.
- `packages/util/src/global.ts:17`: `home` is `OPENCODE_TEST_HOME ?? os.homedir()`; it roots `~/.agents`,
  `~/.claude` config discovery (`core/src/config/discovery.ts:69-70`) and `~/.opencode/plan`
  (`core/src/plugin/plan.ts:31`), so the harness sets it to the isolated home. `global.ts:79`: config dir can
  also be overridden by `OPENCODE_CONFIG_DIR` (not used).
- `packages/cli/src/services/server-connection.ts:41-43`: `--standalone` (or service config `disabled`)
  starts a private server via `Standalone.start()`; otherwise `Service.ensure` talks to the background
  service, and the TUI handler passes `mismatch: "replace"` (`commands/handlers/default.ts:35-38`), i.e. it
  would restart a background service of another version. The harness always passes `--standalone`.
- `packages/cli/src/services/standalone.ts:17-32`: the private server is `<self> serve --stdio --port 0`, a
  child whose lease ends on stdin EOF; observed as `opencode serve --stdio --port 0` listening on
  `127.0.0.1:<random>` with the TUI as its only client.
- `packages/cli/src/services/updater.ts:534` + `commands/handlers/default.ts:69-86`: the TUI runs an update
  check every 10 minutes that can install a new binary (a write to `~/.opencode/bin`); disabled by
  `OPENCODE_DISABLE_AUTOUPDATE=1` and `update: "disable"` in the isolated `opencode.json`.
- `core/src/database/migration/20260805200742_import_legacy_credentials.ts:39-48`: `<data>/auth.json` is read
  once (read-only) and copied into the isolated `opencode.db` `credential` table, so the symlink is never
  written. The isolated DB therefore holds a credential copy; it stays under gitignored `runs/` and is never
  used as a fixture (fixtures are rebuilt from four session tables only).
- `packages/cli/src/database-path.ts:4-12`: DB is `<data>/opencode.db` on the `latest` channel.
- Model: `opencode-go/gpt-6-luna` ($0.10/$0.50 per M on models.dev, cheapest non-free `opencode-go/` model;
  the free `*-free` / `beam-free` entries were skipped to keep to a paid, stable model). The root command has no
  `--model` flag, so the model comes from the isolated config.
- `--session <id>` creates a session with a caller-chosen `ses_…` id on the first prompt
  (`default.ts:53-61,114-115`); the harness pre-assigns one in OpenCode's descending-id format.
- Where a prompt lands: idle TUI submit goes straight to `session_message` (type `user`). A submit while the
  agent is busy (mid `sleep 25` tool call) appeared first in `session_inbox` (type `user`, `delivery: steer`)
  and moved to `session_message` under the same `msg_…` id at the next step boundary. `session_pending`
  exists in the schema but stayed empty in every probe. The reader reports inbox/pending rows as kind
  `queue` (not counted as delivered) and drops them once the same id is in `session_message`.
- Readiness: pane regex (`┃ Build auto · GPT-6 Luna …` composer line + `ctrl+p commands`). No onboarding.
- Side effect before isolation was in place: one bare `~/.opencode/bin/opencode --version` run while
  exploring appended one `cli starting` line to the user's `~/.local/share/opencode/log/opencode.log`
  (20:31:48Z). The harness now runs every OpenCode/Droid version check with throwaway XDG/home dirs under
  `runs/.version-*`.

### Droid 0.249.0

- Binary `~/.local/bin/droid`. `FACTORY_HOME_OVERRIDE` replaces the home directory, not the `.factory` dir:
  everything lands in `<home>/.factory/` (settings, sessions, logs, cache, state, host.json). Also set:
  `FACTORY_DROID_AUTO_UPDATE_ENABLED=false` (parsed `false`/`0` disables the auto-updater, which would
  replace `~/.local/bin/droid`) and `FACTORY_DISABLE_KEYRING=1` (keeps credentials off the macOS Keychain).
- Model: `gpt-6-luna`, reasoning low (token multiplier 0.04; only `gpt-5-nano` and the `-flex` tier are
  cheaper, flex was avoided for latency). Auth `FACTORY_API_KEY` via `sops-exec`.
- Trust: the folder-trust dialog asks about the git root (`~/wrksp/_scratch/agent-comms`), not the work dir.
  Answering it once in a probe wrote only to the isolated `settings.json`; the harness now pre-seeds
  `trustedFolders` with the work dir and its git root, and the pilot showed no dialog.
- Sessions: `<home>/.factory/sessions/<cwd with / -> ->/<uuid>.jsonl` plus `<uuid>.settings.json`; no way to
  pre-assign an id, so the id is read from `session_start` after the first prompt.
- Transcript records: the context message (`id: context-…`, `visibility: llm_only`) carries six
  `<system-reminder>` blocks; hook runs are `message` records with role `user`, empty `content`,
  `visibility: user_only` and `hookEventName`/`hookResults` (observed with SessionStart and UserPromptSubmit
  hooks configured in an isolated `hooks.json`; `tests/fixtures/droid/hooks.jsonl`); `agent_turn_outcome`
  (no timestamp) closes each turn.
- Readiness: pane regex (`│ >` input box + `? for help`).

### Task 2 review fixes (2026-10-24)

- Droid `prompting`: the isolated `settings.json` no longer carries `sessionDefaultSettings.autonomyLevel`
  (only `auto` writes `high`). Manual check, run `20261024-161427-4d63` (`launch --agent droid --mode
  prompting`, one `tmux-paste` asking for `approved.txt`): Droid showed `Edit approved.txt` with a
  `Yes, allow` / `Yes, and always allow low impact commands` / `No, cancel` approval dialog
  (`runs/20261024-161427-4d63/pane-droid-prompting-dialog.txt`), the work dir stayed empty, and the dialog was
  left unanswered before `cleanup` (0 processes left).
- Pi now runs as `env HOME=<isolated home> NODE_PATH=<as the mise shim sets it> <node> <cli.js>` after
  `sops-exec`, with node resolved once from `PATH` to its concrete install
  (`~/.local/share/mise/installs/node/24.22.0/bin/node`) and recorded as `versions.node`. `sops-exec` still
  sees the real `HOME`; a node probe through the same wrapper printed the isolated dir for both `$HOME` and
  `os.homedir()`. `OPENROUTER_API_KEY` auth unaffected.
- OpenCode `credential` table: 0 rows in every isolated DB so far (runs `20261024-154209-3fff`,
  `20261024-154928-e5ee`, `20261024-161552-e99a`) although `import_legacy_credentials` is in `migration`, and
  OpenCode still authenticated, so the provider key evidently arrives another way (not investigated). `cleanup`
  now deletes that table's rows anyway once a run's processes are gone.
- Droid's startup banner shows `Skills (22)` in both the earlier and the new pilot. That matches none of
  `~/.factory/skills` or `~/.claude/skills` (62 skills with `SKILL.md` each) or `~/.agents/skills` (empty),
  and the isolated `.factory/skills` is empty, so it is most likely Droid's built-in set; not verified further.
- Re-run S1 `tmux-paste` after the fixes, all delivered intact and acked, no dialogs, no user-state note,
  global config hashes identical before and after, `cleanup` left 0 processes: Pi `20261024-161518-95c1`
  (0.02 s, versions `pi 1.4.0`, `node 24.22.0`), OpenCode `20261024-161552-e99a` (0.12 s; `auth.json` still a
  symlink to `~/.local/share/opencode/auth.json`), Droid `20261024-161619-d1e8` (0.20 s; notes now carry the
  `~-…` slug).

### Task 2 re-review fixes (2026-10-24)

- Pi's bash tool runs `/bin/bash -c` with Pi's own environment (`utils/shell.js` `getShellConfig` /
  `getShellEnv`), so since the `HOME` override its tools see `runs/<id>/home/pi` while the other agents' tools
  see the real home. Kept deliberately: the override is what keeps `~/.agents/skills` and the trust store out
  of the user's home, and Pi has no separate setting for the tool shell. A check that reproduced the tool
  shell's env (harness `base_env` plus the isolated `HOME`, `/bin/bash -c`, no agent launched) found
  `git --version` worked (2.54.0), `ls ~` succeeded on the empty home, `node` 24.22.0, `python3` and `mise`
  resolved from absolute `PATH` entries, and `git config user.name` was unset (no `~/.gitconfig`, so a
  `git commit` by Pi would fail). mise wrote `.local/state/mise` and `Library/Caches/mise` under the
  isolated home. Also visible: the harness passes its own `PATH`, which under `uv run` starts with the repo's
  `.venv/bin`, for every agent.
- Pi 1.4.0 `custom_message` entries carry only `customType`, `content`, `display` and `details`
  (`session-manager.js` `appendCustomMessageEntry`). `triggerTurn` is an option of `sendMessage` and is not
  persisted, so a turn-triggering message cannot be told apart from a display-only one. A trailing
  `custom_message` therefore makes `is_idle()` return `None`.

## Task 3 scenario pilot (2026-10-24)

One rep each of S2–S8, S10, S11 with `tmux-paste` on Claude 2.1.310 (`haiku`) and Codex 0.164.0 (`gpt-6-luna`
low) via `matrix`, one cell at a time. Every record below met its precondition. The first Codex column was sent
while Codex was still bootstrapping. Its readiness regex matched a placeholder frame (R14), so all nine original
Codex cells were moved out of `raw.jsonl` and re-run after the fix. The table shows the re-runs. `cleanup` left 0 processes
after every cell; the only global-config note was the usual `~/.claude.json` churn from the user's own sessions.

| Scenario | Claude | Codex |
|---|---|---|
| S2 mid-turn | interrupted, intact, acked (`20261024-223654-8c84`) | interrupted, intact, model_noncompliant (`20261025-001310-2c6c`) |
| S3 permission prompt | lost, **harmful** (`20261024-223716-1ae0`) | lost, **harmful** (`20261025-002721-99d5`) |
| S4 10 KB payload | delivered, **not intact** (tabs → 4 spaces), acked (`20261024-224041-a8e9`) | delivered, intact, acked, 2.9 s (`20261025-001809-da0d`) |
| S5 burst of 5 | 5/5 in order, not merged, 5/5 acks (`20261024-224049-2057`) | 5/5, not merged, **reordered**, 2/5 acks (`20261025-001821-3de5`) |
| S6 kill/resume | down-send rejected, resumed same session, delivered (`20261024-224058-0d2c`) | same (`20261025-002128-b4d2`) |
| S7 draft present | delivered, draft **merged** (`20261024-224127-d3e3`) | delivered, draft **merged** (`20261025-002200-5d82`) |
| S8 attach/type/push | delivered, rendered in the attached client (`20261024-224136-a57b`) | same (`20261025-002212-74bb`) |
| S10 stale address | `/clear` → new session, delivered; `/compact` → same session, delivered (`20261024-231232-e1e3`) | same with `/clear` and `/compact` (`20261025-002226-0b63`) |
| S11 model picker | lost; the send picked the highlighted model (`20261024-224958-9eb2`) | lost; the send picked the highlighted model and opened the reasoning picker (`20261025-002252-89a8`) |

Mechanism findings for `tmux-paste` (one rep each, so these are behaviours seen once, not rates):

- Mid-turn (S2): neither agent queues to the turn boundary. Claude logs the paste as `queue-operation enqueue`
  straight away, then folds it into the running turn at the next tool result (`queue-operation remove`,
  `reason: absorbed_mid_turn`, plus an `attachment` of type `queued_command` rendered as a system reminder "The
  user sent a new message while you were working"). Codex steers: Enter during a turn ends the current
  code-mode tool cell early ("Script running with cell ID 1" after 0.9 s) and puts the user message into the same
  turn. In the first rep Codex then waited for the gate and answered only `DONE`, so the token arrived intact but
  was never acked. The post-fix re-run did the same: the message was recorded 0.03 s after the send, right after
  "Script running with cell ID 1". Codex then answered `DONE` without acking, while the gate was still closed.
- Permission prompt (S3): both are harmful. The send approved the dialog, so `approved.txt` was created with nobody
  approving it, and the pasted text itself disappeared (no transcript record, nothing in the composer). The
  first records did not store the token, so a digit in it (Claude's dialog binds `1.`/`2.`) could not be ruled
  out. Fix round: S3/S11 tokens now use only `a`–`f`, and every record stores its token. The Claude re-run
  `20261024-234346-598e` (token `abdceffb`, no digits) was harmful again, with "1. Yes" highlighted and the
  dialog closed by the send. A manual probe on an isolated prompting-mode Claude (`20261024-234730-0101`, not a
  matrix record) settled it: the bracketed paste alone (digit-free envelope) left the dialog open with no file
  (`probe-after-paste.txt`), and the single Enter then approved it and created `approved.txt`
  (`probe-after-enter.txt`). So on Claude the paste's Enter confirms the highlighted "Yes". For Codex the pane
  says "You approved codex to run … this time". `p` ("don't ask again") comes before `y` in the envelope word
  "reply", so letter shortcuts did not fire, which leaves Enter (not separately probed). Codex's re-run after the
  readiness fix first failed its precondition (`20261025-001632-8ba8`). With `-a on-request` the model simply
  reported the read-only sandbox and never asked to escalate. The Codex setup prompt now adds "Your sandbox is
  read-only, so request approval to run the write outside the sandbox." The re-run `20261025-002721-99d5` (token
  `efcffaae`) was harmful in the same way ("You approved codex to run printf 'ok\n' > approved.txt this time"). The earlier Claude side
  panel ("+32 files edited before this session") listed the harness repo's own uncommitted changes, because the
  work dir sat inside the `agent-comms` repo. With each work dir now its own git repo (R12), the re-run showed no
  panel. What opened the panel in the first run was not determined.
- Payload (S4): Claude wraps a large paste as `<pasted_content id="…">…</pasted_content id="…">` (now stripped by
  the tmux adapters' `unwrap`) and turns every tab into four spaces, so the body is not intact. Codex kept it
  byte-identical.
- Burst (S5): Claude recorded five separate prompts in order. Codex, on a ready receiver (`20261025-001821-3de5`),
  kept all five as separate, intact user messages but **reordered** them:
  - Message 1 started turn 1.
  - Messages 3, 4 and 5 were steered into turn 1 about 1.2 s later.
  - Message 2 was held as a follow-up and became turn 2.
  - Only 1 and 2 were acked.

  The first rep's "five pastes glued into one prompt" (`20261024-230013-d05e`) was a startup artefact. Each
  Enter met `Waiting for startup`, so the pastes piled up in the composer. It is not evidence about `tmux-paste`
  on a running Codex.
- Latency: the first Codex turn after launch takes about 2.9 s from Enter to transcript (S1 2.9, S4 2.9, S5 3.8,
  S7 2.8 s); later turns take 0.03–0.05 s (S2, S8), against 0.03 s on Claude. The 6–7.5 s seen before the fix
  was Codex bootstrapping (model refresh, prewarm, remote plugin sync) while the harness waited, charged to the
  mechanism. The remaining ~2 s on the first turn is Codex work after the first frame: in the isolated
  `logs_2.sqlite` of `20261025-000919-7c61`, the submission is logged 1.2 s after `tui startup initial frame`, and
  turn dispatch waits about 2 s more for `thread/start` work. That is receiver startup, not paste handling, so
  first-turn latencies on Codex should not be compared with later turns.
- Kill (S6): with tmux as host, a send to a dead receiver fails loudly, because the tmux server exits with its
  last session (`no server running`). Both agents resumed the same session id.
- Draft (S7): both insert the paste at the cursor after the draft and submit the two together
  (`DRAFT-… please also look at theACK-REQUEST …`): `draft_fate=merged`, body not intact.
- Modal (S11): both pickers take the paste's Enter as "select the highlighted entry" (the current model, so no
  model change) and swallow the text. Claude also saves that choice as the default for new sessions in the
  isolated config. Codex moves on to its "Select Reasoning Level" picker. The post-fix Codex re-run
  (`20261025-002252-89a8`, `/model` typed on a ready receiver) behaved the same way.
- Human typing through the host (`type_text`, 6-char chunks at 30 ms, 0.4 s before Enter) submitted reliably on
  Codex, unlike the burst `send-keys -l` of the `tmux-keys` adapter. Setup prompts and S7/S8 drafts use it.

Harness changes made during the pilot (each record from before a fix was moved out of `raw.jsonl` to
`runs/<run_id>/superseded-record.jsonl`):

- Codex 0.164.0 refuses `approval_policy="untrusted"` ("is no longer supported") and exits. Prompting mode is now
  `-a on-request -s read-only`, so a file write in the work dir asks for approval.
- The Claude reader now parses `attachment`/`queued_command` records as user input, timestamped in file order
  (`20261024-223513-2f6f` had recorded a delivered mid-turn message as lost).
- `/compact` on Claude kept both transcript and pane looking idle while it ran, so the first S10 send queued
  behind compaction (`20261024-224147-9e8a`). S10 now waits for the pane to show "compacted" (Claude
  "Compacted", Codex "Context compacted"). Claude idle detection now skips local-command echoes and treats
  `compact_boundary` as idle. Without that, the retry recorded `error` "receiver not ready after /compact"
  (`20261024-224632-9280`). That was a harness idle-detection bug, so the record was moved to
  `runs/20261024-224632-9280/superseded-record.jsonl` like the others (fix round, R11).
- S11 model detection had matched Claude's "Get to finished work sooner with Opus 5.5" banner and falsely
  reported a model change (`20261024-224215-0752`). Codex's reasoning-level picker was not recognised as a
  modal (`20261024-230440-e459`).

Read-only isolation gap found: the isolated Claude loads the user's `~/.claude/CLAUDE.md` as a "Project"
instructions file (`attachment` type `instructions`). Claude walks up from the work dir, and `$HOME` is an
ancestor of `runs/`. The skills Claude lists are its built-ins, not `~/.claude/skills`. Nothing is written. Every
Claude cell before the fix round (Task 1, Task 2 and the Task 3 pilot above) ran with the user's global
instructions in context. Fixed in the Task 3 fix round (R9): the isolated `settings.json`
sets `claudeMdExcludes` (Claude 2.1.310 documents it as "Glob patterns or absolute paths of CLAUDE.md files to
exclude from loading", for User/Project/Local memory) to every ancestor's `CLAUDE.md`/`CLAUDE.local.md`/
`.claude/CLAUDE.md`/`.claude/rules/**`, including `~/.claude/CLAUDE.md`. Checked on
`20261024-234202-cdbe` by path only: its transcript has no `instructions` attachment and never mentions
`~/.claude/CLAUDE.md`, while `20261024-231232-e1e3` has an `instructions` attachment listing that path as type
`Project`.

## Task 3 fix round (2026-10-24)

Classifier and harness fixes from the Task 3 review (F1–F15, R9, R12). Records written before the fixes stay
in `raw.jsonl` as they were, with these known gaps:

- S5 Codex `20261024-230013-d05e` had `intact: true` and `recv_sha256 == sent_sha256` although its five
  envelopes were glued into one entry. S5 now sets `intact` only when each envelope equals one received entry,
  stores the hash of the bodies actually received and adds `merge_count`. That record was later moved out
  anyway as a startup artefact (round 2 below).
- S8 `20261024-224136-a57b` and `20261024-230400-dfa7` were judged with a check the echoed prompt could satisfy.
  Re-checked against their `attach-*.log` with the new check (reply occurrence not preceded by the prompt's
  `"`; human marker not preceded by `exactly`): both still render the reply and the human turn.
- Records before the fix round carry no `token` field.

Pilot S1 re-run with `tmux-paste` after the fixes (work dirs now their own git repos; Claude without the user's
`CLAUDE.md`), one cell at a time, global config hashes unchanged before/after, 0 processes left after each:

| Agent | Run | Delivery | Ack | Latency |
|---|---|---|---|---|
| Claude | `20261024-234202-cdbe` | delivered, intact | acked | 0.03 s |
| Codex | `20261024-234250-88c7` (moved out in round 2; replaced by `20261025-000919-7c61`, 2.9 s) | delivered, intact | acked | 7.5 s |
| Pi | `20261024-234309-578f` | delivered, intact | acked | 0.02 s |
| OpenCode | `20261024-234314-3614` | delivered, intact | acked | 0.12 s |
| Droid | `20261024-234324-6c32` | delivered, intact | acked | 0.23 s |

Claude S3 re-run: `20261024-234346-598e`, lost, harmful (see the S3 bullet above for what approved the dialog).

## Task 3 fix round 2 (2026-10-25, R14)

Codex readiness bug. Codex 0.164 draws its composer (`› Ask Codex to do anything`) and `? for shortcuts` as a
placeholder about 2 s before bootstrap ends. The ready regex matched that placeholder, so every Codex cell's first
input was typed during startup and met `Waiting for startup`. Codex readiness now also requires the post-bootstrap
status line (`<model> <effort> · <dir>`), with no `Waiting for startup` or `loading` title on screen. The fixtures
are real capture-pane frames of both states (`tests/fixtures/codex/pane-startup.txt`, `pane-ready.txt`).

Readiness audit. Each agent was launched once with the pane captured every 0.1 s (`runs/<id>/ready-probe.json`).
The table compares "declared ready" with the first frame that matches the settled screen; seconds are from tmux
start. The S1 re-run pane logs were checked the same way: for Claude, Pi, OpenCode and Droid the settled startup
frame precedes the first paste echo in the raw pane log, while for Codex `234250-88c7` the paste echo came before
`Waiting for startup` and the `permissions:` header.

| Agent | Probe run | Old rule ready at | Declared ready (old) | Real first frame | Gap (declared − real) |
|---|---|---|---|---|---|
| Codex | `20261025-000139-d175` | 0.49 s | 1.74 s | 3.49–3.63 s (log `tui startup initial frame` 3.05 s after process start) | **−1.8 s (too early)** |
| Claude | `20261025-000230-81ff` | 2.76 s | 2.82 s (registry idle) | 2.76 s | +0.06 s |
| Pi | `20261025-000244-b787` | 0.49 s | 1.82 s | 0.49 s | +1.33 s |
| OpenCode | `20261025-000257-f116` | 3.88 s | 4.98 s | 3.88 s | +1.10 s |
| Droid | `20261025-000312-335b` | 3.11 s | 4.45 s | 3.11 s (after `Checking authentication...`) | +1.34 s |

Only Codex was declared ready before it could take input. The others' S1 latencies (0.02–0.23 s) agree, so no other
agent's readiness changed and no other agent's cells were re-run. Droid's settled frame lists "Skills (22) ✓" in
the isolated home, which was not investigated in this round.

Auth screens, captured with no credentials in an isolated home (no `sops-exec`):
- Droid (`20261025-000745-68d7`) shows "Please login with your Factory account to continue." with a Login menu.
  The old Droid pattern did not match this; it was fixed, and the screen is a fixture.
- Pi (`20261025-000806-2f60`) starts normally but shows its model without the `(openrouter)` provider. That is now
  an auth signal; ready panes do not match it.
- Claude and Codex logged-out screens were not captured, because without the injected token they may fall back
  to the macOS keychain or the user's login. Their patterns stay unverified.

Codex re-runs after the fix (`tmux-paste` unless noted; one at a time, 0 processes left after each):

| Scenario | Run | delivery / intact / draft_fate / ack / harmful | Latency |
|---|---|---|---|
| S1 | `20261025-000919-7c61` | delivered / true / n/a / acked / false | 2.93 s |
| S1 `tmux-keys` | `20261025-000948-32cb` | lost / – / n/a / none / false (`stuck-in-composer`) | – |
| S2 | `20261025-001310-2c6c` | interrupted / true / n/a / model_noncompliant / false | 0.03 s |
| S3 | `20261025-002721-99d5` | lost / – / n/a / none / **true** | – |
| S4 | `20261025-001809-da0d` | delivered / true / n/a / acked / false | 2.86 s |
| S5 | `20261025-001821-3de5` | delivered / true / n/a / model_noncompliant / false (reordered, not merged, 2/5 acks) | 3.82 s |
| S6 | `20261025-002128-b4d2` | delivered / true / n/a / acked / false (down=rejected, same session) | 1.35 s |
| S7 | `20261025-002200-5d82` | delivered / false / merged / acked / false | 2.80 s |
| S8 | `20261025-002212-74bb` | delivered / true / n/a / acked / false (rendered=yes) | 0.05 s |
| S10 | `20261025-002226-0b63` | delivered / true / n/a / acked / false (clear@new, compact@old) | – |
| S11 | `20261025-002252-89a8` | lost / – / n/a / none / false (modal-selection-made) | – |

Superseded Codex records moved to `runs/<run_id>/superseded-record.jsonl` (R11):
- Sent during Codex startup: `20261024-071514-69b9` and `20261024-073131-9782` (S1 `tmux-paste`), plus
  `20261024-225312-f67b` (S2), `20261024-225635-c2ba` (S3), `20261024-230002-0ec9` (S4), `20261024-230013-d05e` (S5),
  `20261024-230316-17da` (S6), `20261024-230348-3251` (S7), `20261024-230400-dfa7` (S8), `20261024-230414-39ec` (S10),
  `20261024-230915-1e59` (S11) and `20261024-234250-88c7` (S1).
- Superseded by the S3 recipe fix: `20261025-001632-8ba8` (S3 precondition error: Codex never asked to escalate).

Codex findings that changed: S5, where the merge was a startup artefact and the ready receiver reorders instead
(2 held as a follow-up, 3–5 steered into turn 1); and latency, where 6–7.5 s became about 2.9 s on the first turn
and 0.03–0.05 s after that. Unchanged: S1 `tmux-paste` delivered; `tmux-keys` lost (stuck in composer); S2
interrupted and not acked; S3 harmful (Enter confirms the dialog); S6, S7, S8 and S10 as before; S11 lost
because the picker takes the Enter.

Other round-2 harness changes:
- S8 `rendered` is matched with all whitespace removed, and is tested on real pane and attach streams.
- An unexpected exception in a cell writes `traceback.txt` and stops the batch (exit 12).
- The auth-link and global-config checks run independently even when one of them raises.
- A second receiver crash on the same cell becomes the terminal `error` `receiver-crashed-repeatedly`.
- `init_work_repo` takes the environment as a parameter.
- `adapter_backend` reads a class method instead of constructing a host.

## Task 4 native adapters: Claude and Codex (2026-10-25)

Claude 2.1.310 (`haiku`), Codex 0.164.0 (`gpt-6-luna` low). One cell at a time; `cleanup` left 0 processes after
every cell; the only global-config change was the usual `~/.claude.json` churn from the user's own sessions.

### What the binaries say (verified, not assumed)

- Claude peer inbox, from strings in the 2.1.310 binary: the socket is `/tmp/cc-socks/<pid>.sock`
  (`XDG_RUNTIME_DIR`/`CLAUDE_CODE_TMPDIR` can move it; hidden `--messaging-socket-path`), named in the isolated
  registry `<CLAUDE_CONFIG_DIR>/sessions/<pid>.json` as `messagingSocketPath`. Wire format is JSON lines; the
  binary's own hint: `{ echo '{"type":"auth","token":"'"$CLAUDE_CODE_MESSAGING_TOKEN"'"}'; echo
  '{"type":"user","message":{"role":"user","content":"hello"}}'; } | socat - UNIX-CONNECT:…`. Peers authenticate with
  `peerToken` from `<config>/sessions/<pid>.<sha256(socket path)>.key` (JSON `{peerToken, procStart, pidDomain}`);
  the session's own children get `CLAUDE_CODE_MESSAGING_SOCKET`/`CLAUDE_CODE_MESSAGING_TOKEN` (`childToken`).
  Real `SendMessage` frames add `msgV`, `msg_id`, `priority`, `from` (reply address), `from_mode` and wrap the body
  as `<cross-session-message from=… from-mode=…>`.
- Inbound policy (`crossSessionInbound`, settings description): "'accept' delivers them, 'hold' parks them for your
  review without letting Claude act, 'refuse' opts this session out. An explicit value always wins. Unset (mode
  parity): a message auto-delivers only when the sending session's permission-mode class matches yours
  (bypass↔bypass or prompting↔prompting); a mismatched sender's message is held for your approval; a sender that
  asserts no class is held only while this session bypasses permission prompts." Read from policy, `--settings`
  (flag) and user settings; repo settings can only tighten it. In the decision code a `selfSent` message (sender is
  a descendant of the receiver, checked by a process-ancestry walk on the verified peer pid on macOS, or the child
  token when there is no evidence) is accepted before mode parity is consulted.
- Claude channels: `--dangerously-load-development-channels server:<name>` exists (hidden). The server must declare
  `capabilities.experimental["claude/channel"]` and emit `notifications/claude/channel` `{content, meta}`; Claude
  frames it as `<channel source="<name>" k="v">\n…\n</channel>`. A connection whose protocol revision has no channel
  path is skipped ("era"); the harness server answers `2025-06-18`.
- `claude --bg`: the background service is per config dir in the code: state `<CLAUDE_CONFIG_DIR>/daemon/`,
  sockets `/tmp/cc-daemon-<uid>/<sha256(config dir)[:8]>` (config dir = `CLAUDE_CONFIG_DIR ?? ~/.claude`).
  `daemonColdStart: transient|ask` / `CLAUDE_CODE_DAEMON_COLD_START` decides whether a missing service is
  spawned for the login session or offered as a persistent install.
- Codex app-server: `--listen unix://PATH` speaks **WebSocket** over the unix socket (HTTP `101 Switching
  Protocols`, header `x-codex-websocket-max-unfragmented-message-bytes`), not raw JSON lines; a raw line gets the
  connection closed. Requests are JSON-RPC without the `jsonrpc` field. Schema from `codex app-server
  generate-json-schema --experimental`: `turn/start {threadId, input}`, `turn/steer {threadId, expectedTurnId,
  input}` ("Required active turn id precondition"), `thread/loaded/list`, `thread/read`, `thread/turns/list`,
  `thread/queue/add|start|list|…` (experimental). `thread/turns/list` fails on a thread with no turn yet ("not
  materialized yet"); `thread/read` status works.
- Codex sockets: even an explicit `--listen unix:///tmp/ac/<run>.sock` is created as a symlink to
  `/private/tmp/codex-daemon-<uid>/<sha256(path)>`; the managed daemon's socket is
  `/private/tmp/codex-daemon-<uid>/<sha256(<CODEX_HOME>/app-server-control/app-server-control.sock)>` (the user's
  `ee61a2ac…` matches that formula). Both are removed by Codex on SIGTERM.

### Pilot records

| Adapter | S1 | S8 | S12 |
|---|---|---|---|
| `claude-uds` | held, `held-for-approval` (`20261025-094649-e6fc`; R17 re-run of `lost` `20261025-085154-fb63`) | – | n/a (no backend) |
| `claude-uds-accept` | delivered, intact, acked, 0.02 s (`20261025-085608-d231`) | – | n/a |
| `claude-uds-child` | delivered, intact, acked, 0.08 s (`20261025-085622-016f`) | – | n/a |
| `claude-channel` | delivered, intact, acked, 0.02 s, `dialogs=dev-channels` (`20261025-085809-84c6`) | – | n/a (the server is a session-owned MCP child) |
| `codex-remote-start` | delivered, intact, acked, 4.8 s (`20261025-090212-bf23`) | delivered, rendered, 0.04 s (`20261025-090804-6076`) | delivered, acked, 0.9 s (`20261025-090708-cf1c`) |
| `codex-remote-steer` | delivered, intact, acked, 4.5 s (`20261025-090244-ea91`) | delivered, rendered, 0.05 s (`20261025-090826-8cb5`) | delivered, acked, 5.3 s (`20261025-090855-a1b6`) |
| `codex-queue` | delivered, intact, acked, 3.7 s (`20261025-091010-5967`) | delivered, rendered, 0.09 s (`20261025-091229-8bda`) | delivered, acked, 4.0 s, daemon down 32.2 s (`20261025-095032-fd14`, re-run of `20261025-091256-4169`) |

First-turn Codex latencies (3.7–4.8 s) include the thread's first-turn startup, as with `tmux-paste` (2.9 s).

- Default inbound holds an external sender. The receiver runs `bypassPermissions`, the harness asserts no mode, so
  the message is parked: a system `informational` entry "Held peer message — from an unidentified session
  [verified pid …]; preview: «…» … not delivered to Claude (1 held). The sender did not attest its permission mode
  and this session bypasses prompts", plus a Deny / "Deliver this message to Claude" picker in the pane. A manual
  probe (`20261025-091539-9a41`, not a matrix record) sent `from_mode: "bypass"` with the same peer token: still held
  as "from an unidentified session". So a non-Claude sender cannot get past the default by asserting a mode; it
  needs `crossSessionInbound: accept` on the receiver, or the child path.
- Accepted peer messages are recorded as `isMeta` user entries with `origin {kind: "peer", from: "unknown",
  verifiedPeerPid}` and framed by the receiver: `Another Claude session sent a message:\n<body>\n\nThis came from
  another Claude session — not typed by your user, … that's permission laundering.` `unwrap` strips that frame (and
  a `<cross-session-message>` envelope if a sender adds one).
- **`claude-uds-child` bypasses the hold.** The relay is an MCP stdio server that the receiver Claude spawns
  itself; it got `CLAUDE_CODE_MESSAGING_SOCKET` and `_TOKEN` in its environment (`relay.log`: `child_socket=yes
  child_token=yes`) and forwarded with the child token. The receiver had no `crossSessionInbound` setting, yet
  delivered the message with `origin.selfSent: true`. The relay is both a descendant and a child-token holder, so
  this cell does not separate the ancestry check from the token.
- `claude-channel` works with the injected credential (the TUI header reads "Haiku 5.5 · Claude API"); no policy
  block. The channel push is an `isMeta` user entry with `origin {kind: "channel", server: "agentcomms"}`, rendered
  in the pane as `← agentcomms: …`. Launch shows one dialog ("WARNING: Loading development channels … 1. I am using
  this for local development / 2. Exit"), answered with Enter; `--mcp-config` avoids the project MCP consent dialog.
- Codex `--remote` TUI: renders turns started by another client on the same app server (S1/S8 panes show the pushed
  `› ACK-REQUEST …` and the reply). After a server restart (S12) the TUI reconnects by itself and later pushes render.
- Codex managed daemon in an isolated home: `daemon start` printed `Installing daemon from CLI version 0.164.0 into
  <home>/packages/app-server-daemon` and started a daemon plus a `daemon-updater` (both pids from
  `<home>/app-server-daemon/*.pid`, tracked as backends and killed by `cleanup`). A bare `codex -C <work>` with
  model/approval/sandbox in `config.toml` attached to it (the daemon's `thread/loaded/list` listed the TUI's
  thread). S12's restart is a graceful `daemon stop` then `daemon start`, not a crash; the daemon was down 32.2 s
  (stop 31.8 s, start 0.3 s; `20261025-095032-fd14`), and the TUI stayed usable and the queued message was delivered.
- **An embedded TUI drains the daemon's queue.** Probe `20261025-091104-bad0` (adapter `codex-queue-embedded`, not a
  matrix record): with the isolated daemon running, a TUI launched with `-c …` ran embedded (startup warning
  "Running without the shared background server: command-line configuration overrides (-c, --enable, --disable, or
  --search) requires embedded mode"; the daemon listed no loaded thread). After a typed warm-up turn, `codex queue
  --thread <uuid>` through the daemon returned "Queued message … for thread …" and the embedded TUI picked it up and
  acked within ~2 s. Both share `<CODEX_HOME>/queue_1.sqlite`.
- A Codex thread with no turn does not survive an app-server restart: the first S12 attempt (restart before any
  turn) left the TUI on "This conversation is unavailable … input is paused" and the sender found no thread. S12
  now types a warm-up turn first; that record was moved out (below).

### claude-bg: untested

`claude --bg` in an isolated config dir (`20261025-091430-bgpr`, probe only, `CLAUDE_CODE_DAEMON_COLD_START=transient`,
`daemonColdStart: transient`) failed: "warning: --bg manages the session id; ignoring --session-id … Starting
background service… Couldn't reach the background service (background service exited before it became reachable
(exit code 0): claude daemon: background agents disabled (3P/opt-out))". In the binary that message comes from
`claude daemon run` when `CLAUDE_CODE_DISABLE_AGENT_VIEW` is set or `settings.disableAgentView === true`. Neither the
harness env nor the isolated `settings.json` sets them; the user's `~/.claude/settings.json` has
`"disableAgentView": true`. So the spawned service most likely read the user's settings rather than the isolated
config dir, i.e. it may not honour `CLAUDE_CONFIG_DIR` (unverified). No service state was written: `~/.claude/daemon`
is unchanged (Sep 7), no `/tmp/cc-daemon-<uid>` exists, no process was left. Retried once under R16, below.

### Cross-machine claims (recorded, not tested)

- Claude settings schema: `isolatePeerMachines` "Require explicit approval before SendMessage can reach a peer
  session on another machine via Remote Control".
- Codex: `--remote` accepts `ws://host:port` and `wss://host:port`; `app-server --listen ws://IP:PORT` with
  `--ws-auth capability-token|signed-bearer-token`; `codex remote-control` and `app-server daemon
  enable-remote-control`.

### Superseded records (R11)

- `20261025-084754-83bf` (`claude-uds` S1): the held-message preview contained the token and was counted as a
  delivery; the reader now gives "Held peer message" entries kind `held`.
- `20261025-085534-4304` (`claude-uds-accept` S1): `intact: false` only because `unwrap` did not strip the
  receiver's peer frame.
- `20261025-085827-3b90` (`codex-remote-start` S1): the sender called `thread/turns/list` on a thread with no turn
  and got an error; it now reads `thread/read` status first.
- `20261025-090315-9f9e` (`codex-remote-start` S12): S12 recipe fix (warm-up before restart), see above.
- `20261025-085154-fb63` (`claude-uds` S1, `lost`): a held message is now `held` (R17); re-run `20261025-094649-e6fc`.
- `20261025-091256-4169` (`codex-queue` S12): its restart note timed only the start ("0.4s"); re-run
  `20261025-095032-fd14` times from before the graceful stop.
- `20261025-095211-5e81`, `20261025-095402-d540`, `20261025-095816-545b` (`codex-remote-start` S5, review-fix
  verification): the first had its send window stretched past 1 s by a slow multi-pid `ps` in the new identity
  tracking; the other two were `rejected` because the harness sender treated a `thread/read` error during the
  thread's first turn as a send failure. Re-run `20261025-100150-cfb3`.

### User state

The user's Codex daemon was down before Task 4 (`~/.codex/app-server-daemon/daemon.pid` names pid 81588, not
running; control socket link dangling) and is unchanged after it (same files and mtimes, no `app-server` process).
No daemon command ran without an isolated `CODEX_HOME`; the harness refuses one unless the home is under `runs/` and
its socket differs from the user's. Every Task 4 Codex home still has `auth.json` → `~/.codex/auth.json`.

### Task 4 review fixes (2026-10-25)

Live-pid audit before any change: the 12 Task 4 manifests with backends held 20 `backends` pids (38784–91765); the run
manifests also held 195 distinct pgids and agent pids. None was alive and no live process had one of those pgids. Nothing
was signalled.

- Backend pids now carry a process identity (start time + executable, recorded when tracked); `run_pids`,
  `live_runs` and `cleanup` only treat a backend or deferred-sender pid as the run's while it matches. Old
  manifests have no identities, so their entries are never owned. Restart replaces the entries; dead ones are
  pruned. macOS `ps -o … -p a,b` takes ~0.6 s for any multi-pid list, so a multi-pid lookup reads the whole table
  (~0.1 s).
- Every backend start and every `codex app-server daemon` command re-checks `backend.json`: `CODEX_HOME` set,
  under `runs/<run>/home/`, daemon socket differs from the user's. `launch`/`send` refuse an adapter the agent
  does not support.
- Channel server: one streaming `TextDecoder` per connection (a test splits an emoji across two writes), empty
  connections are ignored, and the socket is removed on exit; channel and relay sockets are in the manifest.
  `claude-channel` S4 re-run `20261025-094831-a6ec`: delivered, intact (10413-byte payload), acked, 0.03 s.
- `codex-remote-start` deferral is one drainer per thread over a spool (send order, one turn each, outcomes in
  `deferred.log`, drainer tracked with its identity). Verified with S5 `20261025-100150-cfb3`: 5/5 in order, no
  merges, 5/5 acks, `deferred=4/4`. Mechanism detail found on the way: while a thread's first turn is starting,
  `thread/read` fails with "failed to read thread: … rollout … is empty", so a sender racing a fresh thread's first
  turn must treat that as busy.
- Agent-facing senders check ownership against the run manifest (see README); verified live on a launched
  `claude-uds-accept` session: the harness Claude pid delivered, a non-target pid and `--config-dir ~/.claude` were
  refused with exit 2, and the recorded identity still matched after the session had been up.
- `codex queue` itself takes ~0.7 s (`send_s=0.74` on `20261025-094939-4877`); records now carry `send_s`. All
  other native sends were ≤ 0.01 s.
- A Claude peer send with no key file is now `rejected` (was sent unauthenticated and counted accepted).

R16 (`agentcomms probe-bg`, run `20261025-100432-4867`): before, no `/tmp/cc-daemon-501`; `~/.claude/daemon`
mtimes 1788772447 (dir), control.key 1788767137, dispatch 1788770955, roster.json 1788770976. With
`"disableAgentView": false` and `"daemonColdStart": "transient"` in the isolated `settings.json` (plus
`CLAUDE_CODE_DAEMON_COLD_START=transient`), `claude --bg` again printed "Starting background service… Couldn't
reach the background service (background service exited before it became reachable (exit code 0): claude daemon:
background agents disabled (3P/opt-out))" and exited 1. After: still no `/tmp/cc-daemon-501`, same
`~/.claude/daemon` mtimes, global config hashes unchanged, 0 processes left. Per R16 this is recorded as the user's
`disableAgentView` leaking through `CLAUDE_CONFIG_DIR`, and the `claude-bg` host is untested. The agent-view gate
found in the binary is `CLAUDE_CODE_DISABLE_AGENT_VIEW` or `settings.disableAgentView === true`: the harness env
does not set the variable, there is no managed settings file, the isolated settings say `false`, and only the
user's `~/.claude/settings.json` says `true`. The "3P" in the message was not traced to a separate condition.

R18: the S12 warm-up and "a Codex thread with no turn does not survive an app-server restart (TUI: conversation
unavailable)" are in the Task 4 notes above and in the README backend paragraph.

Re-runs after the fixes (pilot, one cell at a time, `cleanup` left 0 processes each):

| Run | Adapter | Scenario | Delivery | Intact | Ack | Latency |
|---|---|---|---|---|---|---|
| `20261025-094649-e6fc` | `claude-uds` | S1 | held | – | none | – |
| `20261025-094738-3f15` | `claude-uds-accept` | S1 | delivered | yes | acked | 0.02 s |
| `20261025-094752-c4c6` | `claude-uds-child` | S1 | delivered | yes | acked | 0.06 s |
| `20261025-094810-a2f0` | `claude-channel` | S1 | delivered | yes | acked | 0.02 s |
| `20261025-094831-a6ec` | `claude-channel` | S4 | delivered | yes | acked | 0.03 s |
| `20261025-094851-a9f1` | `codex-remote-start` | S1 | delivered | yes | acked | 3.8 s |
| `20261025-094916-1fdf` | `codex-remote-steer` | S1 | delivered | yes | acked | 4.3 s |
| `20261025-094939-4877` | `codex-queue` | S1 | delivered | yes | acked | 5.4 s |
| `20261025-095032-fd14` | `codex-queue` | S12 | delivered | yes | acked | 4.0 s |
| `20261025-100150-cfb3` | `codex-remote-start` | S5 | delivered | yes | acked | 4.1 s |

User state after the fixes: the user's Codex daemon is still down and unchanged (`daemon.pid` names dead pid
81588, files and mtimes as before), `~/.claude/daemon` unchanged, no `/tmp/cc-daemon-501`; every daemon command
ran with a `CODEX_HOME` under its run.

### Task 4 review fixes, round 3 (2026-10-25, R19)

- Process identity is now `sha256(lstart, ucomm)`. macOS `comm` follows argv[0] rewrites (a test renames a perl
  process with `$0`: `comm` changes, the identity does not); `ucomm` is the kernel accounting name. Manifests from
  earlier rounds stored `comm`-based identities, so like pre-identity manifests their entries are now never owned
  (all their processes are dead).
- `backends.stop` (restart) signals the old backend's group only if `backend.pid` still has its recorded identity;
  a reused pid gets no signal and the restart only starts. Live check on a launched `codex-remote-start` run
  (`20261025-102508-ca05`): its app server was recognised as owned.
- The probe's service start times are parsed as UTC (`calendar.timegm`).
- Only "rollout … is empty" / "not materialized" errors count as a busy thread; other `thread/read` or
  `thread/turns/list` errors reject the send at once instead of deferring it for up to 600 s.
- `--drain` must be `runs/<run of --socket>/deferred/<--thread>`. A drainer that cannot start logs one `error`
  line with the cause per spooled message; records add `deferred-pending=N` if messages are still spooled at the
  end of the cell.
- Scoring: `held_or_delivered` is renamed `queued_or_delivered`; matrix cells show `held N`.
- N7 (agent-run senders need `ps`, which nono may block) is carried to Task 10's preflight (R19).

Re-runs (verdicts unchanged, so nothing superseded): `20261025-102321-a720` `codex-remote-start` S1 delivered,
intact, acked, 5.5 s; `20261025-102346-64a5` `codex-queue` S12 delivered, intact, acked, 1.2 s, daemon down
33.6 s (stop 33.3 s + start 0.3 s). `cleanup` left 0 processes after each.


## Task 4b re-baseline (macOS 27.2)

The laptop moved from macOS 26 (Darwin 25.6) to macOS 27.2 (build 26B123, Darwin 27.2); Claude updated 2.1.310 to
2.1.311. Codex 0.164.0, Pi 1.4.0 (node 24.22.0), OpenCode 2.1.4 and Droid 0.249.0 are unchanged. Every record now
carries `versions.os` (`27.2 (26B123)`); older records have no `os` and the matrix counts them as macOS 26.

Pinned binaries (all resolved to concrete paths; `run` re-resolves after each cell):

| agent | version | pin |
|---|---|---|
| claude | 2.1.311 | `~/.local/share/claude/versions/2.1.311` |
| codex | 0.164.0 | `~/.codex/packages/standalone/releases/0.164.0-aarch64-apple-darwin/bin/codex` (`~/.local/bin/codex` goes through `current`; the release dir is pinned and its name must match `--version`) |
| pi | 1.4.0 | mise npm install `npm-earendil-works-pi-coding-agent/1.4.0` run by node 24.22.0. `pi` on `PATH` and `mise which pi` resolve there and `~/.config/mise/config.toml` lists only the npm package; the aqua install (`aqua-earendil-works-pi`, 1.2.0) is an unused leftover |
| opencode | 2.1.4 | `~/.opencode/bin/opencode` (version probed with a throwaway home) |
| droid | 0.249.0 | `~/.local/bin/droid` (version probed with a throwaway home) |

### Drift table

One fresh pilot record per cell, run one cell at a time with `cleanup` after each (0 harness processes left every
time). Old verdict is the latest macOS 26 record for the cell.

| agent | mechanism | scenario | old (macOS 26) | new (macOS 27.2) | versions old | versions new |
|---|---|---|---|---|---|---|
| claude | `tmux-paste` | S1 | delivered (`20261024-234202-cdbe`) | delivered (`20261027-111724-f411`) | claude 2.1.310 | claude 2.1.311 |
| codex | `tmux-paste` | S1 | delivered (`20261025-000919-7c61`) | delivered (`20261027-111738-c8a7`) | codex 0.164.0 | codex 0.164.0 |
| pi | `tmux-paste` | S1 | delivered (`20261024-234309-578f`) | delivered (`20261027-111747-0d14`) | pi 1.4.0, node 24.22.0 | pi 1.4.0, node 24.22.0 |
| opencode | `tmux-paste` | S1 | delivered (`20261024-234314-3614`) | delivered (`20261027-111753-6a12`) | opencode 2.1.4 | opencode 2.1.4 |
| droid | `tmux-paste` | S1 | delivered (`20261024-234324-6c32`) | delivered (`20261027-111801-eb18`) | droid 0.249.0 | droid 0.249.0 |
| claude | `tmux-keys` | S1 | delivered (`20261024-071552-5f6d`) | delivered (`20261027-111816-88f0`) | claude 2.1.310 | claude 2.1.311 |
| codex | `tmux-keys` | S1 | lost (`20261025-000948-32cb`) | lost (`20261027-111822-6719`) | codex 0.164.0 | codex 0.164.0 |
| claude | `claude-uds` | S1 | held (`20261025-094649-e6fc`) | held (`20261027-112128-7fcd`) | claude 2.1.310 | claude 2.1.311 |
| claude | `claude-uds-accept` | S1 | delivered (`20261025-094738-3f15`) | delivered (`20261027-112153-7861`) | claude 2.1.310 | claude 2.1.311 |
| claude | `claude-uds-child` | S1 | delivered (`20261025-094752-c4c6`) | delivered (`20261027-112158-546f`) | claude 2.1.310 | claude 2.1.311 |
| claude | `claude-channel` | S1 | delivered (`20261025-094810-a2f0`) | delivered (`20261027-112205-6888`) | claude 2.1.310 | claude 2.1.311 |
| codex | `codex-remote-start` | S1 | delivered (`20261025-102321-a720`) | delivered (`20261027-112218-02de`) | codex 0.164.0 | codex 0.164.0 |
| codex | `codex-remote-steer` | S1 | delivered (`20261025-094916-1fdf`) | delivered (`20261027-112230-b2a3`) | codex 0.164.0 | codex 0.164.0 |
| codex | `codex-queue` | S1 | delivered (`20261025-094939-4877`) | delivered (`20261027-112241-a44f`) | codex 0.164.0, codex_daemon 0.164.0 | codex 0.164.0, codex_daemon 0.164.0 |
| claude | `tmux-paste` | S3 | lost (harmful) (`20261024-234346-598e`) | lost (harmful) (`20261027-112257-c480`) | claude 2.1.310 | claude 2.1.311 |
| claude | `tmux-paste` | S7 | delivered, draft merged, body-mismatch (`20261024-224127-d3e3`) | delivered, draft merged, body-mismatch (`20261027-112620-17f5`) | claude 2.1.310 | claude 2.1.311 |
| codex | `tmux-paste` | S2 | interrupted (`20261025-001310-2c6c`) | interrupted (`20261027-112628-e8d3`) | codex 0.164.0 | codex 0.164.0 |

No verdict changed, so no genuine behaviour drift and no harness drift: readiness regexes, trust/onboarding
dialogs and version parsing all worked unchanged on macOS 27.2 (Claude `claude-channel` still shows the
`dev-channels` dialog; Claude `claude-uds` is still `held`; Codex `tmux-keys` is still `lost` with the text stuck in
the composer; Claude S3 is still harmful, the dialog closed by the send and `approved.txt` created; Claude S7 still
merges the draft). No records were superseded.

### Harness changes

- `resolve_codex` refuses a binary that does not resolve into a `releases/<v>-<target>/bin` dir or whose dir name
  does not start with the reported version.
- `versions.os` from `sw_vers` on every record (launched and unlaunched).
- R21 preflight: `run`, `matrix` and `launch` exit 13 when `nono why --self` reports anything but `NOT SANDBOXED`
  (a missing `nono` counts as unsandboxed); `--sandbox nono` is a placeholder that skips it for Task 10.
- The matrix has a `macOS` column so the two eras are not merged.

User state: the user's Codex daemon was down before and after (`daemon.pid` names dead pid 81588, unchanged), no
daemon command ran outside an isolated `CODEX_HOME`; global config hashes unchanged.

## Task 5 native adapters: OpenCode, Pi, Droid (2026-10-27)

OpenCode 2.1.4 (`opencode-go/gpt-6-luna`), Pi 1.4.0 on node 24.22.0 (`openrouter/deepseek/deepseek-v4.1-flash`),
Droid 0.249.0, Claude 2.1.311 (`haiku`, mesh probe only), macOS 27.2. Cells ran one at a time; `cleanup` left
0 processes after each. Before and after, the global config hashes differed only in `~/.claude.json`, which the
user's own sessions rewrite; it has no `agent-comms/runs` reference. 13/13 OpenCode `auth.json` links in today's
runs still point to `~/.local/share/opencode/auth.json`. No Codex cell ran.

### OpenCode routes (from source)

Read in `~/wrksp/_scratch/opencode-v2.0.32`. The files that matter were then fetched at tag `v2.1.4` with `gh api
…/contents/<path>?ref=v2.1.4` and diffed. `env.ts`, `services/server-connection.ts`, `server/src/auth.ts` and
`schema/src/session-inbox.ts` are identical. `protocol/src/groups/session.ts`, `core/src/session/prompt.ts`,
`core/src/session/inbox.ts` and `cli/src/server-process.ts` differ only in imports, list-query schemas, row
decoding and a guarded `chdir`. The endpoint list and the payloads below are the same in both.

- Prompt route: `POST /api/session/:sessionID/prompt` (`protocol/src/groups/session.ts:396` in 2.0.32, `:335` in
  2.1.4). Payload `{id?, text, files?, agents?, skills?, metadata?, delivery?: "steer"|"queue", resume?}`. The
  OpenAPI description is "Durably admit one session input and schedule agent-loop execution unless resume is
  false". `delivery` defaults to `steer` (`core/src/session/prompt.ts:50`).
- Inbox semantics (`core/src/session/inbox.ts:44-48`, `:494-522`): a `steer` item is promoted at the next step
  boundary while the agent is working. A `queue` item is taken only by the turn-boundary ("input") scope, one at a
  time, and only when no steers are pending. `PATCH /api/session/:id/inbox/:inboxID {delivery}` switches a pending
  item; its description says "Steering wakes session execution". `GET`/`DELETE` list and cancel items.
- Other admission routes: `POST /api/session/:id/synthetic` (`session.ts:457`; `{text, description?, metadata?,
  delivery?, resume?}`, a `synthetic` message) and `POST /api/session/:id/command` (runs a slash command).
  `GET /api/session/:id/message` only lists messages.
- Every route in `packages/protocol/src/groups/*.ts` (2.0.32) is under `/api/`. The group list at `v2.1.4` is
  identical and has no `tui` group. There is no `/tui/append-prompt`, `/tui/submit-prompt`, `prompt_async` or
  `POST /session/:id/message`, so the `tui-*` and legacy variants in the plan do not exist.
- Auth: `serve` always runs with a password, `OPENCODE_PASSWORD` (or the legacy `OPENCODE_SERVER_PASSWORD`) or a
  random one (`cli/src/server-process.ts:80-92`). The random one is printed to stdout only in foreground mode and
  only when it did not come from the environment (`:203`). Clients use Basic auth with user `opencode`
  (`server/src/auth.ts`), and `--server` clients send `OPENCODE_PASSWORD` (`services/server-connection.ts:25-31`).
  Only `--stdio` mode deletes the password from `process.env`, so under a plain `serve` the agent's own tools
  inherit `OPENCODE_PASSWORD`.
- `--session <id>` opens an existing session, otherwise the id becomes the id of the session the first prompt
  creates (`commands/handlers/default.ts:53-61,114-115`). The adapters therefore create the session over the API
  before the TUI starts. A session created without a model ran on OpenCode's free default ("Big Pickle"), so
  creation passes the configured model.
- Provider auth comes from the environment `sops-exec` injects. A backend started without `sops-exec` answered
  `Model unavailable: opencode-go/gpt-6-luna`, and started through it the backend worked. That explains the Task 2
  observation that the isolated `credential` table stays empty.
- Background service (`cli/src/services/service-config.ts:41-56,115-150`, `client/src/service-contender.ts`): the
  config is `$XDG_CONFIG_HOME/opencode/service.json` (keys `disabled, remote, hostname, port, password, cors,
  env`). The registration (`{url, pid, version, password}`, mode 0600) is `$XDG_STATE_HOME/opencode/service.json`.
  The default port is 0xC0DE (49374). `service start` spawns detached contenders `opencode serve --service`. Nothing
  registers with launchd. In service mode the process `chdir`s to `OPENCODE_TEST_HOME`. The user's service was not
  running (nothing listening on 49374). The isolated one bound `127.0.0.1:<seeded port>`, ran with its cwd in the
  run's home and was reparented to pid 1 with its own process group. Listings of `~/.local/state/opencode` and
  `~/.config/opencode` were identical before and after.

### Pi API (from `dist/core/extensions/types.d.ts`, Pi 1.4.0)

`ExtensionAPI.sendUserMessage(content, options?: {deliverAs?: "steer" | "followUp"; expandPromptTemplates?})`, documented as
"Always triggers a turn" (l. 1263-1267). `sendMessage(…, {triggerTurn?, deliverAs?: "steer"|"followUp"|"nextTurn"})`
(l. 1258). `ExtensionContext.isIdle()` (l. 236). `appendEntry(customType, data?)` (l. 1272). Extensions load with
`-e <path>` (`docs/cli.md`). Pi gives extensions `typebox` and `@earendil-works/pi-coding-agent` as virtual modules.

### Pilot records

| Adapter | S1 | S8 | S12 |
|---|---|---|---|
| `opencode-server-steer` | delivered, intact, acked, 0.017 s (`20261027-120331-0b62`) | delivered, rendered, 0.008 s (`20261027-120400-0955`) | delivered, acked, 0.011 s; down 5.3 s (`20261027-120417-53fc`) |
| `opencode-server-queue` | delivered, intact, acked, 0.016 s (`20261027-120502-0f02`) | delivered, rendered, 0.009 s (`20261027-125947-2d48`) | delivered, acked, 0.013 s; down 5.3 s (`20261027-130004-0b7f`) |
| `opencode-server-synthetic` | delivered, intact, acked, 0.016 s (`20261027-120515-8bcd`) | delivered, `rendered=reply-only` (not good, R25), 0.008 s (`20261027-130033-65c4`; supersedes `-120528-1384`) | delivered, acked, 0.012 s; down 5.3 s (`20261027-130057-045a`) |
| `opencode-service-steer` | delivered, intact, acked, 0.013 s (`20261027-120601-cc44`) | delivered, rendered, 0.007 s (`20261027-120635-cc4f`) | delivered, acked, 0.012 s; down 0.5 s (`20261027-120647-ea60`) |
| `pi-ext` | delivered, intact, acked, 0.003 s (`20261027-125354-e868`; supersedes `-115657-a114`, pre-fix extension) | n/a (no backend) | n/a |
| `pi-session-bridge` | delivered, intact, acked, 0.004 s (`20261027-115725-a000`) | – | n/a |
| `pi-claude-link` | delivered, intact, acked, 0.003 s (`20261027-115755-373e`; harness sends the Claude peer frame) | – | n/a |

Mechanism findings (one rep each):

- A TUI attached with `--server`, and a TUI that found the isolated service, both render turns posted by another
  client: the prompt and the reply show in the pane. A `synthetic` message is answered, but the TUI shows only the
  answer. Someone watching sees a reply with no visible prompt.
- S12 `opencode serve`: SIGTERM to the group did not end it within the 5 s grace, so it was SIGKILLed: down
  5.3 s. The group leader is the `sops-exec` wrapper; why SIGTERM was not enough was not investigated. The TUI reconnected by itself and rendered the post-restart turn. The isolated
  service stopped and restarted in 0.5 s, and its TUI kept working.
- Pi `pi-ext`: an idle send becomes an ordinary `user` message. The extension's `agentcomms-turn` markers bracket
  the turn (`custom` busy, then system/user/assistant, then `custom` idle; `tests/fixtures/pi/ext-turn.jsonl`), so
  the reader knows idle without the pane. The busy path (`deliverAs: "followUp"`) is covered by a no-model test
  against the extension under bun. It was not run live (S2 is Task 8).
- `pi-session-bridge`: its `prompt` request delivers now when idle and `steer` when busy (`sendPrompt` in
  `extensions/session-bridge.ts`). It writes an ordinary user message and adds a `bridge:<pid>` footer status.
- `pi-claude-link` records the inbound message as a user message behind its own frame. `unwrap` strips the frame
  (`tests/fixtures/pi/claude-link.jsonl`).
- Agent-facing senders, checked live on launched sessions (`20261027-122326-a876`, `-122338-5cfc`, `-122350-6bd5`,
  `-122402-5f50`): each owned target got the message (token found in its transcript). A socket not listed in the
  run, a foreign session id and a foreign URL were each refused with exit 2.

### pi-claude-link safety and Claude↔Pi probe

How pi-claude-link discovers peers, and the safety verdict, are in `vendor/REVIEW.md`. In short, the registry is
`os.homedir()/.claude/sessions` and the socket dir is the dirname of the first registry entry, else
`$XDG_RUNTIME_DIR/cc-socks`, else `/tmp/cc-socks`. It never scans a socket dir. Since Pi runs with
`HOME=<isolated home>`, both can be redirected. It was run. `/tmp/cc-socks` was listed before and after every
pi-claude-link run and did not change, and no `/tmp/pi-claude-link-debug.*` file appeared.

`agentcomms probe-claude-link` ran three times (`20261027-120906-7975`, `-121239-100d`, `-121604-7b41`). Each time
the harness Claude registered `/tmp/ac/<run>-cl/cc-socks/<pid>.sock` (Claude 2.1.311 honours `XDG_RUNTIME_DIR` for
its peer socket). Pi registered next to it as `pi-pi` in the Claude config dir's `sessions/`. The pre-launch safety
check passed.

- Claude→Pi (`SendMessage` to `uds:<pi sock>`): 3/3 delivered. The message reached Pi's transcript as a user
  message 5.7–7.6 s after the instruction was typed into Claude, which includes Claude's own turn. Pi acked, and
  pi-claude-link relayed Pi's answer back to Claude, where it shows as a peer message ("Message from @pi-pi"). Its
  `delivered` receipt shows in Claude as "Cross-session message released after approval". That is Claude's text for
  a `delivered` status, which reads as if a held message had been approved, though nothing was held.
- Pi→Claude through Pi's `claude-link` tool: 0/3, all model errors. deepseek-v4.1-flash called the tool with only
  `action` (7 calls over the first two probes; the tool answered "Error: 'to' is required."). In the third probe it
  wrapped `to` in extra quotes, so no session matched. The mechanism was never reached that way.
- Pi→Claude wire: the package's own `sendToClaude` (run with `bun` from the run dir; envelope with `from=uds:<pi
  sock>` and `from-name="pi-pi"`, no auth line) was delivered into Claude as a peer message 0.1 s after the send,
  under `crossSessionInbound: accept`. Claude answered in its own session but did not message Pi back. So Claude
  2.1.311 accepts an unauthenticated peer frame from an unregistered local process when the receiver says
  `accept`. Under the default policy it would presumably be held, as in the `claude-uds` cells (not run here).

### Droid daemon probe

`droid --help` and every subcommand's `--help` (`resume`, `exec`, `daemon`, `search`, `computer`, `doctor`, `mcp`,
`plugin`; `computer register`/`list`, `mcp add` and `plugin install` print the root help) were run with a throwaway
`FACTORY_HOME_OVERRIDE` under `runs/.probe-t5/`. The interactive TUI has no flag that connects to a daemon or
attaches to a daemon-owned session. Its flags are `--resume`, `--fork`, `--cwd`, `--auto`, `--settings` and so on.
The only daemon-related `--…` strings in the 290 MB binary are `--remote-control`/`--remote-access`, which are
`droid daemon` options.

`droid daemon [--port|--unix <path>] [--listen websocket|ipc] [--droid-path] [--remote-control]` is a JSON-RPC
server for Factory's desktop/web clients. The method names in the binary include `daemon.initialize_session`,
`daemon.load_session`, `daemon.add_user_message`, `daemon.interrupt_session`, `daemon.list_opened_sessions` and
`daemon.create_terminal`/`terminal_data`. A daemon-owned session can therefore be pushed into, but the only surface
that shows it to a human is Factory's app over Remote Control, not a terminal TUI.

A 6 s start (`droid daemon --unix /tmp/ac/dd-probe.sock --listen websocket`, isolated home) printed "Daemon is
running", created the socket and wrote state only under `<home>/.factory/` (logs, sessions, cache, state,
telemetry id). It opened three outbound HTTPS connections, and SIGTERM stopped it. No push path into a
human-attachable TUI exists, so there is no `droid-daemon` adapter. `tmux-paste` stays Droid's only mechanism for
now.

### Cross-machine claims (recorded, not tested)

- OpenCode: `serve --hostname <any>` plus password; `opencode pair` "Print one-time links to connect a browser or
  app" ("Traffic is end-to-end encrypted, and access requires your server password", `commands/handlers/pair.ts`);
  service config `remote` starts a `RemoteTunnel` (`server-process.ts`).
- Droid: `droid daemon --remote-control` and `droid computer register|list|ssh|port-forward` ("Manage Remote Control
  registrations").
- pi-session-bridge `instructions.md`: "To control other interactive Pi sessions (different tmux windows,
  terminals, hosts)". Its transport is a local unix socket, and the registry only records `hostname`.

### Harness changes

- New adapters `opencode-server-steer|queue|synthetic`, `opencode-service-steer`, `pi-ext`, `pi-session-bridge` and
  `pi-claude-link`, with senders `opencode_http.py`, `pi_bridge.py` and `claude_link.py`. Agent sockets named by pid
  inside a `/tmp/ac/<run>-<kind>/` dir are guarded by `guard.owned_agent_socket`.
- Backends: OpenCode kinds have an isolation check. A backend can be an `http://127.0.0.1:<port>` endpoint (TCP
  readiness, not recorded as a socket), `opencode-service` starts with `service start` and is tracked by its
  registration pid, and an adapter may create the session (`prepare_backend`) before the TUI starts. Sockets named
  by the agent pid are recorded after readiness (`ready_sockets`). `cleanup` removes `/tmp/ac/<run>-*` dirs.
- OpenCode TUI argv drops `--standalone` when a backend exists. S6 resume reattaches with `--server`.
- Pi reader: the latest `agentcomms-turn` marker decides idle when no message follows it.
- `agentcomms probe-claude-link` (above).

Superseded (R11, moved to `runs/<id>/superseded-record.jsonl`): `20261027-115831-cf8f` (`opencode-server-steer` S1
on OpenCode's free default model, because the API-created session had no model) and `20261027-115943-3ef3` (the same
cell's `env_error` "Model unavailable", because the backend was not started through `sops-exec`).

### Task 5 review fixes (2026-10-27, F1–F9, R25)

- F1 `service start`: runs in its own process group with a 150 s limit (OpenCode's ensure loop waits up to 120 s).
  On a timeout, a non-zero exit, a wrong registered URL or an unreachable port, the harness kills that group and
  stops the registered `serve --service` before raising `BackendError` (only when the registered pid is alive and
  its cwd is inside the run's home). `cleanup` stops such a registered service too. A stub `opencode` (detached
  `sleep` plus registration) covers all three failure branches in the tests.
- F2 `pi-ext`: the extension always uses `sendUserMessage(text, {deliverAs: "followUp"})`. While idle this starts
  a turn, and while busy it queues behind the running one, so there is no idle-check race. It refuses with `error
  compacting` between `session_before_compact` and `session_compact`/`_failed`, and replies `queued followUp`
  instead of claiming delivery. Pi's `prompt()` throws "Cannot submit a prompt while compaction is in progress" and
  "Agent is already processing" only asynchronously (`agent-session.js:1648-1667`), so no reply could ever report
  them. Records still take delivery from the transcript. Re-runs:
  - S1 `20261027-125354-e868`: delivered, acked, 0.003 s.
  - S2 `20261027-125359-a576`: `queued`, intact, acked, 10.7 s. The pushed message waited for the gated turn to end,
    then became the next turn.
  - S10 `20261027-125859-404e`: `/new` delivered in the new session. `/compact` produced a real `compaction` record,
    then delivered in the same session. The turn markers bracket each turn.

  The first S10 (`20261027-125418-4bdb`) failed its precondition: Pi refused "Nothing to compact (session too
  small)". Pi keeps `compaction.keepRecentTokens` of recent context and compacts nothing below that. The isolated
  Pi settings now set it to 1, and that record is superseded. This is the first Pi S10.
- F3: `OPENCODE_PASSWORD` goes through a 0600 `runs/<run>/env-<session>.sh` / `env-backend.sh` sourced by
  `/bin/sh -c '. "$0" && exec "$@"'`. On `20261027-125341-fe15` it was absent from `ps -axww`, from tmux
  `#{pane_start_command}` and from the tmux session environment; the check compared in-process and printed only
  booleans. `server-password`, the seeded `service.json` and the env files are mode 600. An earlier manual check
  (`20261027-125325-1269`) put the password into the argv of a local `grep` for a moment; that was a mistake in the
  check, nothing was printed, and the run was cleaned up.
- F4: `free_port()` never returns 49374, and the `serve` isolation check refuses it.
- F5: `restart` fails unless the old backend runs as the run's own process (pid plus identity), is gone after the
  stop, and the start returns a process with a new identity. S12 records such a failure as `error`
  `backend-restart-failed: …`. The S12 re-runs all passed the check: queue `-130004-0b7f`, synthetic `-130057-045a`,
  service `-130125-c98e` (pid 57380 → 57498, down 0.4 s).
- F6: pid-named sockets are registered in `Engine.start`, so a resume records the new pid's socket. Tested with
  a fake tmux host.
- F7: `http.client.HTTPException` (for example `BadStatusLine`) is a rejected send in the adapter and in
  `opencode_http.py`. Session creation wraps transport errors in `OpenCodeSessionError`.
- F8: the missing cells are in the table above (queue S8/S12, synthetic S12).
- F9: new tests cover:
  - service start failures (stub);
  - TCP endpoint waits;
  - session-creation errors (409, connection refused);
  - rejected sends (401, a bad status line, a timeout);
  - port selection;
  - restart verification;
  - secret env;
  - 0600 launch files;
  - S8 `reply-only` on real OpenCode attach streams;
  - the Pi compaction setting.

  The extension is type-checked against Pi 1.4.0's `types.d.ts` with vendored `typescript@5.9.3`
  (`vendor/REVIEW.md`). A deliberate `deliverAs: "followup"` misspelling made that test fail with TS2820.
- R25: S8 now notes `rendered=yes|reply-only|no`. `reply-only` means the reply shows in the attached client but
  `ACK-REQUEST <token>` never does. Only `yes` scores. On the old attach logs, the Claude, Codex and OpenCode
  prompt routes all show the pushed prompt, and `/synthetic` shows none.
- R26 is recorded above: Claude `accept` delivers an unauthenticated frame from an unregistered local process.

Superseded (R11): `20261027-115657-a114` (`pi-ext` S1, pre-fix extension), `20261027-120528-1384` (`/synthetic` S8,
scored `rendered=yes` before R25) and `20261027-125418-4bdb` (`pi-ext` S10, Pi refused to compact a small session).

## Task 6: terminal variants and hosts (2026-10-27)

### Hostcheck

`agentcomms hostcheck` (run `20261027-151513-3cc8`; table in `results/hostcheck.md`, raw reads in
`runs/20261027-151513-3cc8/hostcheck-*.json`): a raw-mode PTY recorder with bracketed paste enabled logs every
`read()` inside each host; 7 payloads (plain, multi-line, quotes/`$VAR`/backticks, semicolons, tab, unicode+emoji,
10.2 KB) and a burst of 5 per adapter.

| host | adapter | fidelity | markers | submit | chunking (10 KB) | burst order |
|---|---|---|---|---|---|---|
| tmux | tmux-keys | 7/7 exact | absent | CR | 11 reads, max 1022 B | 5/5 in order |
| tmux | tmux-paste | 7/7 exact | wrapped | CR | 11 reads, max 1022 B | 5/5, 5 paste regions |
| tmux | tmux-paste-retry | 7/7 exact | wrapped | CR | 11 reads, max 1022 B | 5/5, 5 paste regions |
| tmux | tmux-buffer | 6/7: multi-line LF arrives as CR | wrapped | CR | 11 reads, max 1022 B | 5/5, 5 paste regions |
| zmx | zmx-send / zmx-paste | 7/7 exact | absent / wrapped | CR | 11 reads, max 1022 B | 5/5 in order |
| zellij | zellij-write / zellij-paste | 7/7 exact | absent / wrapped | CR | 10 / 12 reads, max 1022 B | 5/5 in order |
| iterm2 | iterm2-text / iterm2-paste | 7/7 exact | absent / wrapped | CR | 11 reads, max 1022 B | 5/5 in order |

- Every host delivers the bytes unchanged; the only translation is tmux `paste-buffer`, which turns each LF into CR
  (so `tmux-buffer` multi-line text reaches an agent as CR line breaks). Markers are never split across reads.
- Chunk sizes are the receiving pty's read sizes (about 1 KB), so they do not show how each host writes; they are the
  same on all hosts. Hosts differ in the agents, not in the bytes: see the spot cells.
- A first iTerm2 hostcheck run was contaminated by the user's own keystrokes (`ne`, `ed to` arrived in the recorder):
  a new iTerm2 window becomes key. That run is not in `results/hostcheck.md`; the host later stopped taking focus (below).

### Hosts

- zmx 0.8.1 and zellij 0.45.1 from release binaries in `vendor/bin` (`vendor/REVIEW.md`: URLs, sha256, no signature
  published). State is per run under `/tmp/ac/<run>-zmx` / `-zj`; the user's sessions are never touched. A detached
  zellij session is 50x50, so `start` attaches a 200x50 pty client briefly; zellij actions need `--pane-id
  terminal_0`, otherwise writes go to a plugin pane and vanish.
- Deviation: the first `--version`/`help` calls of both binaries (before the isolation env existed) created an empty
  `~/Library/Caches/org.Zellij-Contributors.Zellij/contract_version_1/session_info`, an empty
  `~/.local/state/zmx/logs/zmx.log` and `$TMPDIR/zmx-501`. Nothing else outside the repo was written.
  At 13:06 the main session removed the stray empty files: zmx `~/.local/state/zmx/logs/zmx.log` with its dirs, and
  zellij `~/Library/Caches/org.Zellij-Contributors.Zellij/contract_version_1/session_info` with its dirs.
- iTerm2: the Python API is enabled and the cookie request succeeded with no prompt (`IT2_APP_PATH` selects
  `/Applications/Development/iTerm.app`), so nothing is Blocked. Cells run in tabs of a single holder window
  (`user.agentcomms_holder=1`, kept alive by a placeholder `sleep` tab), opened with `select=False`. The holder
  persists across cells, runs and matrix processes: cell cleanup closes only the cell's tab, and only
  `agentcomms cleanup --iterm-holder` closes the holder (when it has no cell tabs). `Window.async_create` makes the new
  window key, so the holder is created only while iTerm2 is not the frontmost app (`lsappinfo front`, checked right
  before the create; `agentcomms iterm-holder` pre-creates it). If iTerm2 stays frontmost for 10 minutes (polled every
  2 s) the cell is `env_error` with `iterm-holder-blocked: iTerm2 frontmost`. The host refreshes the app state and
  settles 0.4 s before reading the frontmost app and iTerm2's current window before/after holder creation, tab
  creation and tab close, and re-activates the previous app when it changed (`focus_stolen=yes` in record notes,
  error records and hostcheck rows included; an iTerm2 window is never activated). Every start notes
  `iterm-focus <before> -> <after>`. `async_set_grid_size` works on an unselected tab (asked 200x50, iTerm2 clamps to
  150x50). The first persistent holder was created at 15:41 (window `pty-DFEC6F80-7528-463F-B6AA-8E4FEF1028C4`)
  with the previous app (`ASN:0x0-0x9c09c`) frontmost before and after: no steal.
- User interference: Codex iTerm2 cells `20261027-140925-3ba4` (S1) and `-141231-3058` (S4) were run while the user
  cleared their input (empty final pane), and `-141842-0914` errored on readiness with a mislabeled `host=tmux`
  (fixed in `plain_record`). All three moved to `runs/<id>/superseded-record.jsonl` ("user-interference: input
  cleared by human"; R11) and re-run as `-142606-3329` (S1), `-142914-c3c6` (S4) and `-143225-8065`
  (paste S1): same verdicts as the other hosts.
- Superseded for the persistent-holder host (R11, `runs/<id>/superseded-record.jsonl`): every iTerm2 record that ran on
  the window-per-cell code (focus could be stolen): `20261027-140216-d19c`, `-140526-b37d`, `-140835-ec23`,
  `-140849-d966`, `-140901-6fa3`, `-140912-1d51`, `-141536-7cc9`, `-142016-5328`, `-142028-1b9e`, with the note
  `superseded: pre-holder iTerm2 host (focus could be stolen)`; and the duplicate rep-1 records `20261027-132447-ab2e`
  (zmx-send Claude S1; kept `-132511-e554`) and `20261027-142432-ec0f` (iterm2-paste Claude S1, which carried
  `focus_stolen=yes`; kept `-142533-1a52`, together with `-140849-d966` once a triplicate). Re-runs on the persistent
  holder (rep 1): Claude iterm2-text S4 `-154930-11b6` lost, S7 `-155242-dbbe` delivered (merged); Claude iterm2-paste
  S4 `-155258-93d0` delivered, S7 `-155312-5602` delivered (merged); Codex iterm2-text S7 `-155327-6d6a` lost; Codex
  iterm2-paste S4 `-155638-1e06` delivered, S7 `-155651-d6da` delivered (merged). None noted `focus_stolen`. Verdicts
  match the superseded ones.
- Claude iterm2-text S1 (`lost, stuck-in-composer`) is not user input: re-run twice on the persistent holder
  (`-154158-fe6b` rep 1, `-154539-527f` rep 2), same result, with no focus change and nobody typing. The pane log
  (`runs/-154158-fe6b/pane-claude.log`) shows the composer holding exactly the envelope text from the first frame and
  never changing; the Enter does not submit (a user's keystrokes would add characters). The typed adapter writes the
  whole envelope with one `async_send_text` and then the Enter about 20 ms later (`send_s=0.02`); the bytes are
  identical to zmx/zellij typed (hostcheck: 11-byte read, then `0d`), where Claude submitted. The remaining
  difference is timing between text and Enter inside iTerm2's input path, which the byte recorder cannot see; the
  mechanism is not isolated, but this is an iTerm2 typed-send effect (like Codex typed on every host), not interference.
- Harness fixes found by the cells: ownership needs the root's process group, not its pid (`procs.owned_group`;
  zellij's server is not a group leader); recorders (`zmx tail`, `zellij subscribe`) are tracked pids; engine,
  scenarios and CLI now dispatch on `Target.host`.

### Spot cells on non-tmux hosts (stage pilot, rep 1; Claude 2.1.311, Codex 0.164.0)

| host | adapter | Claude S1 | Claude S4 | Claude S7 | Codex S1 | Codex S4 | Codex S7 |
|---|---|---|---|---|---|---|---|
| zmx | zmx-send | delivered | lost (10 collapsed pastes, Enter stuck) | merged | lost, stuck-in-composer | lost | lost, merged |
| zmx | zmx-paste | delivered | lost, then delivered on rep 2 (`-151652-ea30`, paste reference) | merged | delivered | lost | merged |
| zellij | zellij-write | delivered | lost, stuck-in-composer (paste placeholder) | merged | lost, stuck-in-composer | lost | lost, merged |
| zellij | zellij-paste | delivered | delivered (paste ref) | merged | delivered | delivered | merged |
| iterm2 | iterm2-text | lost, stuck-in-composer (2/2 reps, not user input; Claude S1 delivered on zmx/zellij typed) | lost | merged | lost, stuck-in-composer | lost | lost, merged |
| iterm2 | iterm2-paste | delivered | delivered (paste ref) | merged | delivered | delivered | merged |

Run ids are in `results/raw.jsonl` (`host` column). Typed input (`*-send`, `*-write`, `*-text`) behaves like
`tmux-keys`: Codex loses it (Enter swallowed, text stays in the composer) and Claude turns a 10 KB typed message into
ten pastes with the Enter stuck. Paste variants behave like `tmux-paste`: delivered, S7 merges the draft. The
zmx-paste Claude S4 loss (`-132854-e1c3`, empty composer, no transcript) did not reproduce on rep 2, and zmx-paste
Codex S4 (`-134159-d318`) was lost: the two zmx-paste 10 KB cells are the only paste-variant failures, so 10 KB
through zmx is unreliable but not shown broken (n=1 each; rep 2 is the only repeat). `stuck-in-composer (paste placeholder)` is a new note for collapsed pastes left in the box.

### tmux variants vs `tmux-paste` (pilot, rep 1)

S1, all five agents: `tmux-paste-retry` and `tmux-buffer` delivered, intact and acked everywhere (`-143256-60ca` ...
`-143355-9014`), 0 retries; same as `tmux-paste`.

| agent | scenario | tmux-paste | tmux-paste-retry | tmux-buffer |
|---|---|---|---|---|
| Claude | S3 | lost, harmful (`-143403-c851`) | lost, harmful (`-144047-5379`) | lost, harmful (`-144733-6d3b`) |
| Claude | S7 | merged (`-143726-b602`) | merged (`-144410-1706`) | merged (`-145056-6a16`) |
| Claude | S11 | lost (`-143733-3849`) | lost (`-144419-864c`) | lost (`-145104-193a`) |
| Codex | S3 | lost, harmful (`-145418-70cb`) | lost, harmful (`-150110-0e87`) | lost, harmful (`-150801-a02a`) |
| Codex | S7 | merged (`-145746-3b2b`) | merged (`-150436-089e`) | merged (`-151128-400c`) |
| Codex | S11 | lost (`-145754-b8f1`) | lost (`-150444-bb10`) | lost (`-151136-0925`) |

Neither variant fixes S3, S7 or S11. `retries` stayed 0 in all 22 cells: the retry adapter only fires when the receiver
was idle with an empty box before the send, and S3/S7/S11 start from a dialog, a draft or a modal, which is the case it
must not touch. Its trigger (message stuck in the composer after an idle send) is the `tmux-keys` Codex failure, which
`tmux-paste` does not have, so the retry path was never exercised live; it is covered by unit tests only. `tmux-buffer`
flips LF to CR in multi-line text.

## Task 7: bridges and S9 agent→agent (2026-10-27)

Claude 2.1.311 (`haiku`), Codex 0.164.0 (`gpt-6-luna` low), Pi 1.4.0 (`deepseek-v4.1-flash`), OpenCode 2.1.4, macOS
27.2, stage pilot, rep 1, `--sandbox raw`, one cell at a time. Install details and the code read for each bridge are in
`vendor/REVIEW.md`. `cleanup` left 0 harness processes after every cell; the global config hashes (now also
`~/.gc/cities.toml`, `~/.gc/supervisor.toml`, `~/.hcom/config.toml`) changed only in the user's `~/.claude.json`, which
has no `runs/` reference. Codex and OpenCode auth links stayed intact.

### Bridge status (S1 idle wake)

| bridge | version | Claude | Codex | Pi | OpenCode | Droid | how it is launched / sends |
|---|---|---|---|---|---|---|---|
| hcom | 0.7.31 | delivered 0.05 s (`-162734-ad11`) | delivered 0.35 s, ACK sent over hcom instead of text (`-162744-9b3a`) | delivered 0.04 s (`-163050-965c`) | delivered 0.96 s (`-163058-d1cc`) | – (not a listed hcom tool) | `hcom <tool> <agent args>` in the tmux pane; `hcom send @<name> -b` |
| agent-intercom | Pi 0fffed27, Claude 7de76e5d, Codex ea1c5b53 | `held` (default inbound, `-170104-cdf4`); `intercom-accept` delivered 0.21 s (`-170410-42ef`) | delivered 0.43 s (`coi`, `-171346-8677`) | delivered 0.48 s (`-165701-70e1`) | not usable (plugin targets OpenCode 1.x) | – (no adapter) | Pi `-e index.ts`; Claude `cci --tui --transport native`; Codex `coi`; harness sender `agentcomms/intercom/send.mts` (broker client) |
| claude-session-driver (`csd`) | 4.0.1 | delivered 0.32 s (`-171426-667a`) | not run (copies `auth.json`) | not run (overrides Pi home) | – | – (no driver) | `csd launch` with `CSD_CLAUDE_BIN` shim; `csd --worker <name> send` |
| Gas City `gc session nudge` | 1.4.0 | delivered 4.7 s after a 15.2 s startup turn (`-190321-fb49`) | delivered 5.2 s after an 18.3 s startup turn (`-190415-71af`) | – | – | delivered 4.4 s after a 25.4 s startup turn (`-191705-095d`) | repo-local city per slot with its own tmux server, `gc supervisor run`; `gc session nudge <alias>` (default `wait-idle`) |
| agent-deck | 1.16.34 | delivered 4.7 s (`-173636-e413`) | lost: queued, a fresh Codex never reports idle (`-190517-fca9`); `--codex-composer-fallback` the same (`-191053-0594`) | – | – | delivered 5.3 s (`-191525-e909`) | `agent-deck add -c <shim> --tmux-socket agentcomms` + `session start`; `session send --message-file -` |
| ntm, cli-agent-orchestrator | – | inventory only | | | | | tmux pane drivers with REST/WebSocket APIs |

Run ids are `20261027-…`. Bridges whose agent support we did not exercise: hcom also lists Gemini, Kimi, Copilot and
others; agent-intercom has no Droid adapter; csd has no OpenCode/Droid driver; gc and agent-deck can wrap any command
(Claude, Codex and Droid were run). Droid is reached only through gc and agent-deck, which run it as a wrapped command
in a tmux pane and type into it; Droid through a bridge is therefore terminal injection, not a Droid push API.

### S9 agent→agent (pilot, rep 1)

A is typed one instruction: send the message in `runs/<id>/s9/to-b.txt` to B through B's adapter (a shell command reading
the file, or a native tool with the text quoted in «»). The message asks B to reply `ACK <token>` through A's adapter
(`reply-<token>.txt`). Pass = a received entry in A's transcript (user/peer/custom/hook, or a tool result) holds
`ACK <token>` without `ACK-REQUEST`. `discovery=name` means A needed only B's bridge name, `address` that it needed a
socket, thread, URL or per-worker wrapper path. `attribution=mechanism` means B's entry names A outside the message
body; `message` means only our reply instruction names A; `none` means neither.

| pair | mechanism (fwd+back) | verdict | discovery | attribution | round trip | run |
|---|---|---|---|---|---|---|
| Claude>Codex | hcom | delivered, acked | name | mechanism | 9.0 s | `-163503-da9c` |
| Claude>Pi | hcom | delivered, acked | name | mechanism | 7.7 s | `-163551-f640` |
| Codex>OpenCode | hcom | delivered, acked | name | mechanism | 16.0 s | `-172238-f31c` |
| Claude>Codex | codex-queue+claude-uds-accept | delivered, acked | address | message | 11.9 s | `-164800-8ea3` |
| Claude>Pi | pi-claude-link+claude-uds-accept (SendMessage one way, reply via the link's relay) | delivered, acked | address | mechanism | 16.2 s | `-172211-0b02` |
| Codex>OpenCode | opencode-server-steer+codex-queue | delivered, acked | address | message | 13.9 s | `-164857-ae1e` |
| Pi>Droid | agent-deck+pi-ext (agent-deck types into Droid's pane; Droid replies through Pi's socket sender) | delivered, acked | address | none | 15.0 s | `-191810-9dfe` |
| Droid>Pi | pi-ext+agent-deck | delivered, acked | address | none | 15.7 s | `-192430-c7fd` |
| Claude>Codex | gc-nudge (one city, GC home and tmux server per slot) | delivered, acked | address | none | 16.0 s | `-191857-fc98` |
| Codex>Claude | gc-nudge | delivered, acked | address | none | 17.7 s | `-192028-d690` |
| Codex>Claude | claude-uds-accept+codex-queue | delivered, acked | address | message | 12.2 s | `-192304-8c59` |
| OpenCode>Codex | codex-queue+opencode-server-steer | delivered, acked | address | message | 13.4 s | `-192342-a265` |
| Pi>Claude | intercom-accept | delivered, acked | name | mechanism | 13.4 s | `-172328-161a` |
| Pi>Codex | intercom | delivered, acked | name | mechanism | 11.3 s | `-173102-323c` |
| Pi>Pi | intercom | delivered, acked | name | mechanism | 8.1 s | `-172309-a36a` |
| Claude>Claude | csd | delivered, acked | address | none | 12.5 s | `-172500-5c9f` |
| Claude>Claude | agent-deck | delivered, acked | address | message | 18.9 s | `-175646-531b` |
| Claude>Claude | claude-uds (SendMessage) | delivered, acked | address | mechanism | 17.2 s | `-171554-6acd` |
| Claude>Claude | claude-uds-accept (SendMessage) | delivered, acked | address | mechanism | 19.1 s | `-171628-5f83` |
| Claude>Claude | claude-uds-child | delivered, acked | address | none | 10.5 s | `-164303-1573` |
| Claude>Claude | claude-channel | delivered, acked | address | none | 9.4 s | `-164326-e9bf` |
| Codex>Codex | codex-queue | delivered, acked | address | message | 18.0 s | `-171705-a5c3` |
| Codex>Codex | codex-remote-start | delivered, acked | address | message | 13.5 s | `-171804-32a0` |
| Codex>Codex | codex-remote-steer | delivered, acked | address | message | 12.8 s | `-171848-02dd` |
| OpenCode>OpenCode | opencode-server-steer / -queue / -synthetic / opencode-service-steer | 4/4 delivered, acked | address | message | 10.5–12.2 s | `-164454-cb9d`, `-164534-4bd6`, `-164615-02a7`, `-164653-eebb` |
| Pi>Pi | pi-ext / pi-session-bridge / pi-claude-link | 3/3 delivered, acked | address | none / message / message | 6.5–7.3 s | `-164015-8765`, `-164722-af35`, `-164741-1a8c` |

Same-agent native pairs ran B in a second run (`b-run=` in the notes) because their sockets are named by run id.
Not run: intercom with Claude as A (native-mode `cci` can only reply to the peer that wrote,
so Claude↔Pi used Pi as A), and the terminal adapters (no agent-usable sender). The deepseek Pi model filled every tool
argument in these cells, so the R24 second Pi model was not needed.

Findings:

- Every adapter with an agent-usable sender completed the round trip once. The default `claude-uds` inbound did not
  hold here: both Claudes bypass permissions and `SendMessage` asserts `from-mode="bypass"`, so mode parity delivers.
- `discovery` describes the route type, not something A worked out: A is always handed B's exact name or command
  (the harness looks up hcom and intercom names before typing the instruction). `name` means the mechanism addresses
  B by a bridge name; `address` means it needs a socket, thread, URL or per-worker wrapper path.
- Discovery by name only works through the bridges with a registry: hcom (four-letter names hcom assigns; agents also
  learn `hcom list` from its primer) and agent-intercom (`intercom_send` to a broker name). csd, gc and agent-deck
  address workers by name in their own CLIs, but the agent needed a run-specific wrapper (the bridge's env and tmux
  socket), so they count as `address` here.
- Attribution in the frame: hcom (`<hcom>[new message #N] <sender> → <recipient>: …`), agent-intercom
  (`📨 From <name> (<cwd>)`, `Intercom message for … From: <name> (<id>)`, `[Intercom message from <name> (<id>)]`),
  Claude peer messages (`<cross-session-message from="uds:…" from-name="claude-…">`) and pi-claude-link
  (`From <name>`). The sender names are self-asserted in every case. csd, gc (`- [session] …`), agent-deck sent from
  outside its own sessions, OpenCode, Codex queue/remote and the unix-socket senders carry no sender identity.
- hcom and agent-intercom replies arrive without a reply instruction being followed: B composed its own
  `hcom send @<A> --intent inform …` or `intercom_send` from the bridge's primer.

### Mechanism notes per bridge

- hcom: wraps the tool in its own PTY proxy. An idle Claude or Codex is woken by typing `<hcom>` into the PTY, after
  which a `UserPromptSubmit` hook adds the message as hook context (Claude `attachment` `hook_additional_context`,
  Codex `developer` message with `hooks.additional_context`; both readers now report them as kind `hook`). Pi and
  OpenCode get it as a user message through hcom's per-run extension/plugin. Receivers reply over hcom rather than in
  text, so Codex S1 is `model_noncompliant` with intact delivery.
- agent-intercom: routing is `local-public`: any two local sessions may discover and message each other
  (`agent-intercom-core/src/policy.ts`); remote principals are tree-scoped. Pi gets a `custom_message`
  (`intercom_message`, `triggerTurn`). `cci --tui` native mode sends Claude peer frames without an auth line or a
  `from-mode`, so the default inbound policy holds them (`held`); `crossSessionInbound: accept` delivers (R26 again).
  `coi` runs its own `codex app-server` plus a `--remote` TUI and starts a turn per message. Intercom tools for
  Codex need the `codex-intercom` MCP server (README: `codex mcp add`, a global write); the harness passes it with
  `-c` flags, `default_tools_approval_mode = "approve"` (otherwise `approval_policy = never` refuses the MCP call) and
  an explicit `PI_CODING_AGENT_DIR`. macOS limitations: the orchestrator package needs Linux systemd cgroups; the
  Alt+I/Alt+M shortcuts need `node-pty` (optional, not built here); broker transport is a Unix socket (TCP only on
  Windows).
- csd: `send` is a bracketed paste plus Enter re-sent every 2 s until the worker's `UserPromptSubmit` hook event
  appears (≤10 s), so it confirms submission; it blocks the sender for that time (`send_s` 0.5 s here).
- gc: `gc session nudge` defaults to `wait-idle`: the nudge is queued and a poller injects
  `<system-reminder>\nYou have a deferred reminder … - [session] <text> … </system-reminder>` as a user message once
  the session is idle (4.4–5.2 s after the send once the startup turn has settled; the CLI returns after 1.9–2.5 s).
  Every gc session starts with a beacon typed by gc ("Run `gc prime` to initialize your context."), which starts a
  turn of 13–28 s; the earlier 11–23 s latencies measured that turn, not the nudge (review M4). Droid stores the frame
  HTML-escaped (`&lt;system-reminder&gt;`), which `unwrap` now accepts. `--delivery immediate` (tmux literal send-keys,
  debounce, Enter with busy confirmation) was not run.
- agent-deck: a custom command runs as a generic tool, so `session send` types into the pane and verifies the
  submit; Claude delivered in 4.7 s, Droid in 5.3 s. For Codex, agent-deck detects the tool from the pane and holds
  the send until its Codex `notify` hook (`agent-deck codex-notify`, run by Codex at the end of a turn) reports the
  session waiting. A fresh TUI has completed no turn, so the status stays `running` and the S1 message stays queued
  until cleanup, with or without `--codex-composer-fallback`. In probe `-190917-961d` (no record) one typed turn
  flipped the status to `waiting` and a following `agent-deck session send` was delivered and acked within seconds.
  The earlier records (`-174604-450c`, `-174942-9c88`) ran with a hook that could not reach `agent-deck` at all (not
  on the agent's `PATH`, review M3) and were superseded; the re-runs reach the same verdict for a fresh session.

### Skips and limits

- agent-intercom OpenCode: OpenCode 2.1.4 ignores the plugin (a file path is rejected with "configured plugin path must
  be a directory"; the package directory exposes no 2.x server entrypoint). The plugin uses the 1.x SDK's
  `session.promptAsync`, which 2.x does not have. Two `rejected` records were superseded; no matrix record.
- csd Codex and Pi: the Codex driver copies `$HOME/.codex/auth.json` into each worker home (a second copy of the
  ChatGPT credential whose refresh token would rotate apart from the user's file); the Pi driver replaces
  `PI_CODING_AGENT_DIR` and `--session-dir` and copies `auth.json`, `models.json`, `settings.json`. Both conflict with
  the isolation rules; Claude-only.
- gc S9: fixed by giving each slot its own city, GC home, supervisor port and tmux server
  (`tmux -S /tmp/ac/agentcomms-<run>-<slot>`); Claude>Codex and Codex>Claude completed (`-191857-fc98`,
  `-192028-d690`). Before that, two cities shared the `agentcomms` server and one supervisor reconciled the other's
  session.
- `codex-queue-embedded` S9: skipped. It is a probe variant (Task 4); its thread exists only after a typed turn, so a
  fresh TUI offers no forward route (`-192206-a083`, `error`, superseded).
- `agent-deck-composer-fallback` S9: skipped; B is a fresh Codex, which agent-deck never sees idle (S1 above).
- intercom with Claude as A: skipped; native-mode `cci` can only reply to the peer that wrote, so Pi is A.
- `intercom-accept` keeps Pi and Codex in its agent list because the Pi>Claude S9 pair uses it for both legs; only
  its Claude launch differs from `intercom`, so Task 8 should screen `intercom-accept` for Claude only.
- No bridge needed a global-config write that could not be redirected, and none insisted on the user's real homes for
  all agents, so the substitutes (agent-comms, agmsg) were not triggered.
- Pi model registry: two Pi launches at 17:19–17:20 came up with an empty `models-store.json` (Pi shows the model
  without `(openrouter)`); the harness classified that as `auth-required` and paused (`-171933-7768`, `env_error`).
  OpenRouter answered 200 for `/key` and `/models` minutes later and the next launches were normal.

### Security observations

- hcom: no daemon; each agent's hcom PTY proxy listens on loopback TCP ports for wake pings and `hcom term` injection
  (authentication of the inject port was not checked). State is a SQLite DB in `~/.hcom` (here `runs/<id>/hcom`);
  any same-user process can send as any name (`hcom send --from <name>`, `-b` = bigboss). For Codex it installs an
  execpolicy auto-approving `hcom send|relay|config|hooks|…`, so an agent can enable the cross-device relay without an
  approval prompt. Legacy-hook cleanup rewrites `~/.claude/settings.json` and `~/.codex/*` when old hcom hooks are
  present (fenced here by `HCOM_TEST_ROOT`).
- agent-intercom: a detached broker per agent dir (Unix socket in a 0700 dir, exits 5 s after the last session);
  same-user processes are trusted (`trustedLocal`), names are self-chosen, and routing lets any local session reach
  any other. Durable outbox/inbox JSON files in the intercom dir. A component that loses `PI_CODING_AGENT_DIR` falls
  back to `~/.pi/agent/intercom`, i.e. joins the user's real broker; this happened once (below). The native Claude
  bridge writes unauthenticated frames into Claude's peer socket and registers itself in Claude's session registry.
- csd: workers always run with `--dangerously-skip-permissions`; default state in `/tmp/csd-workers` (including copied
  Codex credentials under `homes/<name>`); delivery is tmux paste, so anything that can reach the tmux server can
  drive a worker.
- gc: `gc start`/`register`/`supervisor install` install and `launchctl load` a LaunchAgent even with `GC_HOME` set;
  the supervisor's HTTP API listens on 127.0.0.1:8372 by default and answered our duplicate's `/health` without
  credentials; any gc command run below `~` treats the home directory as a city because `~/.gc` exists and writes
  `~/.gc/scripts/gc-beads-bd.sh`. Injected text is framed as a `<system-reminder>` in the user channel (gc sanitises
  `</system-reminder>` in the body). The supervisor runs `pgrep`/`lsof`-style process scans.
- gc tells every agent it starts to run `gc` by name: the startup beacon ("Run `gc prime` …"), the prime text
  (`gc hook --claim --json`) and its Claude hooks (`SessionStart`, `UserPromptSubmit`, `PreCompact`, each prefixing
  `$HOME/go/bin:$HOME/.local/bin` to `PATH`). Whatever `gc` the agent's shell resolves runs with the agent's env; a
  fleet using gc must make that the intended binary and city (here: a run-pinned wrapper, review H1).
- Codex writes `shell_snapshots/*.sh` into `CODEX_HOME` holding the exported environment, injected secrets
  included (92 of the 129 harness snapshots held at least one), mode 0644 (`[features] shell_snapshot = false` turns it off in 0.164).
- agent-deck: by default shares the user's tmux server, writes `trust_level = "trusted"` for each project into
  `$HOME/.codex/config.toml` (or `$CODEX_HOME`), auto-installs updates and manages a launchd update timer; `session
  send` leaves a detached queue worker running until delivery or deadline (30 min).

### Cross-machine claims (recorded, not tested)

- hcom: "Connect agents across machines via MQTT relay" (`hcom relay new/connect <token>`, end-to-end encrypted with a
  shared PSK; the token grants launch/kill/drive on every enrolled device, SECURITY.md).
- agent-intercom: "Same-machine only by design" (Pi README), but the broker implements `remote-access-v1` registrations
  through `remote-gateway.sock` with remote-tree policy.
- csd: none (local tmux).
- Gas City: runtime providers include k8s and ACP; the supervisor API can bind beyond loopback (`[supervisor] bind`).
- agent-deck: `add --ssh user@host` runs sessions on remote hosts; `agent-deck web` serves the TUI over HTTP/WebSocket.

### Writes outside the repo

- `~/.pi/agent/intercom/`: at 17:25–17:27 the Codex intercom MCP server (started by `coi` through the harness's `-c`
  flags, before `PI_CODING_AGENT_DIR` was passed to it) spawned a broker there; `broker.owner`, `broker.pid`,
  `broker.sock` and `remote-gateway.sock` were created and removed again, and
  `outbox/82021a57524a4f611d7668a1b1a63b99d634a0fe812afab4393f163401966bd1.json` (`{"version":1,"entries":[]}`) remains.
  The user's `broker-access.json`/`broker-admin.json` are unchanged. Removing the file was not attempted again after the
  first attempt was refused.
- `~/.gc/scripts/gc-beads-bd.sh` (new, 17:24) from the `gc version` probe; `~/.gc/events.jsonl` and
  `~/.gc/supervisor.log` gained a `/health` request entry from the user's own supervisor at 17:31 when the harness
  supervisor probed port 8372. `~/.gc/cities.toml` is unchanged; `~/Library/LaunchAgents` is unchanged.
- Downloads in `/tmp/ac/dl/{hcom-0.7.31,gascity-1.4.0,agent-deck-1.16.34}` (as in Task 6). Run sockets and symlinks
  `/tmp/ac/<run>-{ic,icr,pih-*}` are removed by `cleanup`.
- Incident (review H1): gc-nudge receivers ran the user's real `gc`. gc types a beacon into every session it starts
  ("Run `gc prime` to initialize your context."), and the agent's shell had the user's `PATH` (mise shims,
  `~/.local/bin`) and real `HOME`. What ran, from the transcripts:
  - `-173344-f537` (Claude, already superseded for an unwrap gap): `gc prime` hit the mise shim and failed ("No
    version is set for shim: gc"); the agent then ran `mise ls`, `mise where github:gastownhall/gascity` and
    `ls ~/.local/share/mise/installs`, and at 17:34:01 executed
    `~/.local/share/mise/installs/github-gastownhall-gascity/1.4.0/gc prime` with cwd `runs/<id>/work/claude`.
  - `-173508-8211` (Claude): the same sequence; the real binary ran `gc prime` at 17:35:26, same cwd.
  - `-173548-9491` (Codex): ran `gc prime` at 17:35:59; the mise shim failed (no global version), nothing else.
  - Both real executions printed the generic Gas City agent prime ("warning: this city does not import required
    builtin pack(s) core … # Gas City Agent … Claim work: `gc hook --claim --json`"). The warning shows gc treated
    the gc-written `runs/<id>/work/claude/.gc` as a legacy city (the walk up from cwd stops at `$HOME` as a ceiling);
    neither agent claimed work. `gc prime` is read-only as far as the evidence shows: by mtime, nothing in `~/.gc`
    changed between 17:31:44 (the 8372 probe above) and 18:34, and `work/claude/.gc` holds only the `settings.json`
    gc wrote at session start (17:33:47 and 17:35:11, before the primes). Contents were not read.
  - Fix: see "Task 7 review fixes" below. The three records are superseded with "receiver reached user's real gc
    (H1)" (`-173344-f537` was already out of `raw.jsonl`; its earlier reason stays).
- Per-city tmux sockets: the first fix-round gc cells (`-190321-fb49` … `-192028-d690`) used `tmux -L
  agentcomms-<run>-<slot>`, which left 8 dead socket files in `/private/tmp/tmux-501/`; the suite's real-tmux test
  left 42 more (`agentcomms-test*`). All 50 were removed (each checked dead first). Per-run sockets now live in
  `/tmp/ac/` (`tmux -S`) and `cleanup` deletes them. Older `actest*` socket files there come from earlier test runs and
  were left.

Guards added after these: `cleanup` also kills vendored bridge processes whose cwd is in the run, gc runs only with an
explicit city and its own port, and the bridge-state guard (rewritten in the review fixes below) stops a run.

### Harness changes

- `LaunchMods.launcher`/`args_in_shim`/`path_prepend`: a bridge command runs the agent through a per-run PATH shim
  (`runs/<id>/bin/<slot>/<agent>`) that execs the pinned binary; `start_session` lets a bridge create the tmux
  session itself on `-L agentcomms` (csd, gc, agent-deck use a `tmux` shim that adds `-L agentcomms -f tmux.conf`);
  `prepare_launch`, `daemon_pids`/`ready_pids` (tracked as `bridge-daemon`) and `bridge_versions` (recorded in
  `versions`).
- `Engine.launch(label=…)` for same-agent pairs; Claude's session id is re-read from the registry after readiness;
  readiness re-resolves an agent pid whose process exited (hcom runs a transient `opencode` probe).
- Readers: Claude `hook_additional_context` and Codex hook-context developer items are kind `hook` and count as
  received; held entries after the send count as `held` even when the preview omits the token.
- `agentcomms s9 --a --b --fwd --back` (`agentcomms/scenarios/s9.py`); S9 scores good only with `roundtrip=yes`.
- `after_run` (shared by `run`, `matrix`, `s9`) with the bridge-state guard; the global hash list gained the gc and
  hcom files.

Superseded during Task 7 (27 records; R11, `runs/<id>/superseded-record.jsonl`, reason in the `superseded` field):
hcom S1 `-162234-46fa`,
`-162313-fba1`, `-162620-692d`, `-162630-d65d` (reader and unwrap gaps); S9 `-163611-4971` (transient pid),
`-163808-c9bd`, `-164048-c1fa`, `-164154-39a9`, `-164349-1d23`, `-164416-d320`, `-164435-5268`, `-164831-a9a8`
(ambiguous tool prompt, unresolved Codex thread, attribution identities, `b-replied` heuristic); intercom
`-164954-7e88`, `-165721-882a`, `-170503-e481`, `-170832-0420`, `-171311-a368`, `-172352-2e56`, `-172549-acff`,
`-172732-28f9`; csd `-171407-9ea0`; gc `-173142-11ee`, `-173344-f537`, `-175324-b7bb`, `-175424-5d9c`; agent-deck
`-173701-65d5`, `-174225-d376`.

### Task 7 review fixes (2026-10-27)

Fix round for the Task 7 review (H1, M1–M7, L1–L9, N1–N3); same versions as above, stage pilot, rep 1, `--sandbox raw`,
one cell at a time.

- H1, bridge-instructed tools: the rule is now that every CLI a bridge tells an agent to run (beacon, primer, hook,
  notify command) resolves, from the agent's shell, to a run-pinned wrapper of the vendored binary that comes first on
  the agent's `PATH`, and the user's install of the same tool is unreachable by name. gc cells: the agent runs as
  `sops-exec /usr/bin/env HOME=<run>/gc/<slot>/agent-home PATH=<run>/bin/tools-<slot>:<user PATH minus every dir
  holding gc or mise and every shims dir> GC_CITY=<city> GC_HOME=<gc home> GC_CEILING_DIRECTORIES=<run> GC_BEADS=file
  <agent>`; `tools-<slot>/gc` execs `vendor/gc/bin/gc --city <city>` under `env -i` with the run's `HOME`/`GC_HOME`;
  `agent-home/{go/bin,.local/bin}/gc` link to it, so gc's own Claude hooks (`export PATH="$HOME/go/bin:$HOME/.local/bin:
  $PATH" && gc …`) would resolve to it too (they still do not reach Claude: the provider shim drops gc's args). With
  `HOME` in the run, mise finds no user installs either. agent-deck cells put `tools-<slot>/agent-deck` (pinned to the
  run's `ad-home` and the agent's `CODEX_HOME`) first on the agent's `PATH` and forward `AGENTDECK_*` into the agent;
  hcom cells already had `vendor/hcom/bin` first with `HCOM_DIR` in the run. Re-runs: gc S1 Claude `-190321-fb49` and
  Codex `-190415-71af`; their `gc prime`, `gc hook --claim --json` and `gc hook --help` calls hit the run city
  (no "builtin pack" warning).
- M1, guard: the whole `~/.gc` tree plus `~/.pi/agent/intercom`, `~/.hcom`, `~/.agent-deck`, `~/.config/agent-deck`
  and `~/Library/LaunchAgents` are compared by size and mtime before and after every `run`, `matrix` cell, `s9`,
  `launch`, `send` and `cleanup`; any change stops with exit 5. `~/.gc/events.jsonl` and `~/.gc/supervisor.log` (the
  user's supervisor appends to them) only stop when they shrink or are replaced; growth is printed and written to
  `runs/<id>/bridge-guard.txt` with byte deltas, attributed to the user's own `gc supervisor run` when one is running
  outside `vendor/`. State of `~/.gc` (sizes and mtimes of 2449 entries, no contents): snapshot at 18:34 before the
  fix-round runs and at 19:27 after them were identical; the newest entries are still `supervisor.log` and
  `events.jsonl` (17:31:44) and `scripts/gc-beads-bd.sh` (17:24:09). No guard stop or append note fired in any
  fix-round cell.
- M2, S9 classifier: `roundtrip=yes` now needs B received the message, a reply in A's transcript as a pushed entry
  (`user`, `peer`, `custom`, `hook`; a `tool_result` is A polling), recorded after B's receipt, a reply send by B
  (a `tool_use` with the reply marker, after B's receipt and before A's entry), and no reply send by A before it (a
  `tool_use` quoting the full request is A's forward send and does not count). Otherwise the note
  `no-roundtrip=<not-delivered|no-reply|reply-polled|reply-before-receipt|b-did-not-reply|a-sent-reply>` says why.
  The 25 kept Task 7 S9 records were recomputed from their transcripts under the new classifier: all 25 keep
  `delivered`, `roundtrip=yes`, `b-replied=yes`; none was superseded.
- M3, agent-deck Codex: the notify hook now reaches the run-pinned `agent-deck` (hook files appear in the run's
  `ad-home`). Fresh-session S1 is still `lost` (`-190517-fca9`, composer fallback `-191053-0594`); see the mechanism
  note above. `-174604-450c` and `-174942-9c88` were superseded (hook could not reach agent-deck).
- M4, gc latency: an adapter can name a startup marker (`gc-nudge`: "Run `gc prime`"); after readiness the engine
  waits for it to appear (≤45 s) and for the session to be idle (≤150 s), and records `startup-turn=<s>` on S1 records
  and `a-/b-startup-turn` on S9 records. The send starts after that.
- M5, tests: `tests/test_task7_containment.py` checks the launch argv/env the adapters actually write (the agent shim,
  the tool wrappers, the send wrappers, the `run_cli` calls) and runs the CLI guard end to end. 37 single mutations,
  each applied to a scratch copy and checked to have landed, each fail at least one test.
- M6, Droid: `agent-deck` and `gc-nudge` now list Droid. S1 delivered through agent-deck (`-191525-e909`) and gc
  (`-191705-095d`; `-191548-63e6` was superseded because Droid stores gc's frame HTML-escaped and `unwrap` missed it).
  S9 Pi>Droid and Droid>Pi completed through agent-deck with Pi's `pi-ext` socket as the other leg. The hand-written
  n/a record `-175937-83a6` (no run dir, filed under `tmux-paste`) was superseded.
- M7, secrets: isolated Codex homes set `[features] shell_snapshot = false` (checked with `codex features list` on
  0.164.0: effective `false`), and `cleanup` deletes `<codex home>/shell_snapshots/*.sh` of the run's Codex targets.
  Existing files: 129 `runs/*/home/codex/shell_snapshots/*.sh` in 126 Codex homes were deleted (92 of them held at
  least one of the 11 injected secret values). A by-value scan of all of `runs/` (138,788 files, 14 GB) found secret
  values in no other file type: none in Pi, OpenCode or Droid homes, hcom or intercom state, or the `env-*.sh` files
  (those hold only the per-run OpenCode password, R23). The 17 fix-round runs hold no secret value and no snapshot.
- gc S9: each slot gets its own city, GC home, supervisor port and tmux server; Claude>Codex `-191857-fc98` and
  Codex>Claude `-192028-d690` completed. The reverse native pairs Codex>Claude (`-192304-8c59`) and OpenCode>Codex
  (`-192342-a265`) also completed.
- LOW/NIT: attribution matches whole identities only (L1); `discovery` documented as a route property (L2); S9 skips
  listed above (L3); `cleanup` stops tracked bridge daemons before it kills sessions and kills the run's per-city tmux
  servers (L5); gc no longer shares a tmux server (L6); the gc version is recorded only when the vendored binary's
  sha256 matches `vendor/REVIEW.md`, otherwise `unknown (sha256 …)` (L7); S9 evidence includes `pane` when the token is
  in a pane log or snapshot (N2); the count above is 27 (N1); gc refuses a launch whose `HOME`, `GC_HOME`, `GC_CITY` or
  `GC_CEILING_DIRECTORIES` is outside the run (N3 backstop; `--yes` stays, see below).
- Not changed: L4 (a token-less held preview after the send still counts as `held`; Claude's held preview omits the
  token, so requiring it would turn real holds into `lost`); L5's node-run broker respawn (the intercom broker is
  still tracked only through `broker.owner`; a respawn after its 5 s idle exit is left for Task 8 cleanup checks);
  L8 (`send.mts` stays a harness-only node/tsx sender until a decision before Task 10); L9 (the stray
  `~/.gc/scripts/gc-beads-bd.sh` and `~/.pi/agent/intercom/outbox/82021a…json` are left for the user;
  `runs/.version-gc` stays because that script points into it); N3 `--yes` (with stdin not a terminal gc proceeds
  without asking anyway, so dropping it adds no backstop).

Superseded in this round (7): `-173508-8211`, `-173548-9491` (H1); `-174604-450c`, `-174942-9c88` (M3);
`-175937-83a6` (M6); `-191548-63e6` (escaped gc frame); `-192206-a083` (`codex-queue-embedded` S9, no route).
Probes without a record: `-190917-961d` (agent-deck Codex after one typed turn), `-192851-a405` (gc `launch`/`send`/
`cleanup` with the `/tmp/ac` tmux socket).

## Task 8 screen stage (2026-10-27/28)

S1, S4, S7, S8 at 1 rep for all 71 mechanism x agent pairs (284 cells), `stage=screen`, `--max-concurrency 3`;
verdict table, survivors, n/a reasons, failure modes, harness fixes and decisions are in `results/screen.md`.
Claude auto-updated 2.1.311 -> 2.1.312 at 21:28 (the version guard stopped batch 1 with exit 3); every Claude screen
verdict is on 2.1.312. Wall clock 19:50 to 03:35, about 3 h of it with the laptop asleep on battery (idle sleep at
19:53, later Deep Idle with short DarkWakes); cells hit by sleep were recorded `env_error sleep-or-network` and re-run.

Harness fixes (tests named in `results/screen.md`): S8 attach for zmx/zellij; bridge `shared_state` locks in the
matrix scheduler; matrix plans only supported pairs; a `## Notes` section survives `progress.md` rewrites;
`--time-budget` default 360; Pi's transient provider-less footer no longer counts as an auth screen (5 s hold); the
OpenCode composer parser reads the indented input block; S8 polls the human-turn render with a 45 s wait; csd,
agent-deck and gc-nudge strip Claude's paste reference.

Superseded (R11, `runs/<id>/superseded-record.jsonl`, 21): OpenCode S7 precondition errors `20261027-215451-e11f`,
`-215541-9c65`, `-215806-509b`, `-215946-731e`, `-220246-ec80`, `-220418-df32`, `-220541-6c76`, `-220644-1fc2`,
`-220740-09a3`, `-221040-0b58`, `-221338-3edf`, `-221607-f100`, `-221929-8c60`; OpenCode zmx S8 render errors
`-220327-c3d8`, `-220437-5354`; Pi hcom S1 transient auth `-214818-54c6`; Claude bridge S4 body hash
`-223221-220d`, `-223501-828a`, `-224102-0860`; Claude 2.1.311 verdicts `-195044-d5f6`, `-195118-6a98`.

Probe without a record: `20261027-232551-3e1e` (OpenCode on zmx with an attached PTY client: the client receives the
screen in bursts about 30 s apart and `zmx history` takes several seconds per call while OpenCode redraws).

Stop: the bridge guard stopped the last re-run (`20261028-033403-e3a8`, exit 5) when `~/.gc/scripts/gc-beads-bd.sh`
and `~/.pi/agent/intercom/outbox/82021a57….json`, the two files left for the user's decision, were removed at
03:34:12 (both directories carry that mtime). Not traced to the harness; no cells ran after it.

## Task 8 extensive stage (2026-10-28)

### R34 — coordinator rulings for the extensive stage

1. Survivors are the screen survivors in `results/screen.md`: Claude 16, Codex 11, Pi 13, OpenCode 13, Droid 10.
2. Screen records count toward the extensive reps: S1, S4 and S8 are covered by their screen rep and S7 has 1 of its
   3 reps. Extensive adds, per survivor where the scenario applies: S2 x3, S3, S5 x3, S6, S7 x2, S10, S11, and S12
   for server- or daemon-backed mechanisms only. A scenario that does not apply is recorded `n/a` with its reason.
3. zmx-send, zmx-paste, zellij-write and zellij-paste deliver byte-identical input to their tmux equivalents
   (`results/hostcheck.md`) and their screen verdicts match, so they run only the host-sensitive scenarios S2 x3,
   S5 x3 and S6; the rest is `by-equivalence: <tmux adapter>` in `results/shortlist.md` and the matrix notes, with no
   records written for it. A host-sensitive result that differs from tmux gets the full set for that pair.
4. S9 fills the cross-agent gaps among survivors with an agent-usable sender: Claude<->Codex, Claude<->Pi,
   Codex<->OpenCode and Pi<->Droid, each mechanism once, both directions where routes exist, under R30. Same-agent
   pairs are already covered.
5. R33 is applied: Codex intercom S8 becomes `delivery=delivered, rendered=no` (classifier change with a regression
   test; the screen record superseded per R11 and re-run).
6. Runs use `--time-budget 360 --max-concurrency 3 --resume` under `caffeinate -i`; sleep-hit `env_error`s are
   re-run with `--retry-errors`.

### Harness fixes before and during the extensive stage (each with a regression test)

1. Screen-review M1 (safety): `blank_composer` read only the first line of OpenCode's composer block, a blank padding
   row, so `tmux-paste-retry` could take a box holding a human draft for empty and press Enter. OpenCode now reads every
   input line above the `Build …` mode line. Tests: `test_an_opencode_draft_below_the_padding_row_is_not_an_empty_box`,
   `test_an_idle_opencode_session_box_is_empty` (both mutation-checked). Checked against every saved draft pane under
   `runs/` (Claude 32, Codex 30, OpenCode 15, Pi 14, Droid 10: all read as not empty) and idle panes (all empty): no
   other agent's parser has the first-line problem (Claude, Codex and Droid start input on the prompt-glyph line; Pi
   reads the whole box). The five OpenCode `tmux-paste-retry` records (pilot S1, screen S1/S4/S7/S8) all have
   `retries=0` and S7 `merged`, not `submitted`, so none was superseded.
2. R33: a push that the human's thread never records but another transcript of the same work dir received (Codex
   intercom's `coi` bridge thread) is `delivered` with the note `hidden-thread`; S8 then records `rendered=no`. Reply
   waits now look for the token in every transcript of the target instead of caching the first one found, which also
   fixed warm-ups typed into Codex intercom (the user thread's rollout appears only after its first turn, so the cached
   lookup had picked the bridge thread). S2 records a hidden-thread delivery as `delivered` plus `parallel-thread`
   (neither queued nor interrupted; not good). Tests: `test_s8_push_answered_in_a_hidden_thread_is_delivered_but_not_
   rendered`, `test_wait_for_token_finds_the_reply_in_a_thread_created_after_the_first_lookup`,
   `test_s2_push_answered_in_a_hidden_parallel_thread_is_neither_queued_nor_interrupted`. The screen record
   `20261027-225828-8020` was superseded and re-run: `20261028-035747-100e` delivered, acked, `hidden-thread`,
   `rendered=no`.
3. S6 resumed every receiver with the bare agent command, dropping the adapter's launch setup (Claude `--mcp-config`
   and channel flags, `crossSessionInbound`, Pi `-e` extensions, bridge launchers), so S6 on any non-terminal adapter
   would have measured a session without its mechanism. The launch mods are kept on `Launched` and the resume reuses
   their args, runs launcher bridges through the launcher and rewrites an args-in-shim launcher's PATH shim. Tests:
   `test_resume_keeps_the_adapters_launch_args`, `test_resume_runs_a_launcher_bridge_through_its_launcher`,
   `test_resume_puts_the_resume_args_in_the_shim_for_an_args_in_shim_launcher`.
4. Scenario applicability was per agent and backend only. Adapters can now declare `scenario_na` reasons, and S12
   applies to bridges with a daemon (`bridge_daemon`): intercom restarts its broker (stop, then a client respawns it),
   gc-nudge restarts the city supervisor. Restarted daemons are tracked for cleanup. Tests:
   `test_bridge_scenarios_that_do_not_apply_are_named_per_adapter`,
   `test_bridge_daemon_restart_refuses_a_pid_the_run_does_not_track`.
5. `matrix --plan <file>` runs an explicit cell list in file order, so phase 1 (one rep of everything) and phase 2
   (extra reps) can cover a different survivor set per agent. Tests: `test_matrix_runs_a_plan_file_in_its_order_and_
   resumes_recorded_reps`, `test_a_plan_entry_for_an_unsupported_pair_is_refused`.
6. Screen-review LOW items: `run --time-budget` default pinned (`test_run_time_budget_defaults_to_six_hours`); S8
   `RENDER_WAIT_S` pinned (`test_s8_render_wait_covers_slow_relaying_hosts`); a Pi auth screen still up at the ready
   timeout now pauses with `auth-required` (`test_an_auth_screen_that_appears_just_before_the_ready_timeout_still_
   pauses`); a bridge adapter without a declared `shared_state` is locked by its own name
   (`test_a_bridge_adapter_without_a_declared_shared_state_is_locked_by_its_own_name`). NITs: `unwrap` moved below
   the class attributes in `csd.py`/`agent_deck.py`; the duplicated `--time-budget` in README fixed.
7. `results/matrix.md` names the by-equivalence pairs below the table
   (`test_matrix_names_the_by_equivalence_pairs_and_their_tmux_rows`).

### Version wave and decisions so far (2026-10-28)

- The user's installs updated at 04:22-04:25: Codex 0.164.0 -> 0.165.0 (`~/.codex/packages/standalone/current`),
  Droid 0.249.0 -> 0.251.0 (`~/.local/bin/droid` replaced in place, so it cannot be pinned), OpenCode `--version`
  2.1.4 -> 2.2.0 (binary mtime unchanged, Oct 27 09:39). The per-cell guard compares only one cell's launch with its
  end, so it missed the change between cells; `matrix` now stops (exit 3) when a record's versions differ from an
  earlier record in the batch (`test_matrix_stops_when_an_agent_version_changes_between_cells`). Following R32,
  170 old-version screen/extensive verdicts were superseded (Droid 43 + the 0.251.0 agent-deck S3 error, Codex and
  OpenCode 126); their screens are re-run on the new versions before their extensive cells. S9 records from Task 7
  stay on the old versions (noted, not re-run).
- Droid 0.251.0 starts in `Auto (Med)` when `autonomyLevel` is absent, so the prompting mode showed no dialog. Isolated
  prompting settings now set `autonomyLevel: off`; Droid tmux-paste S3 (`20261028-043025-8c11`) then showed the dialog
  and the paste approved it (harmful).
- n/a decisions (adapter `scenario_na`): S6 on csd, agent-deck, gc-nudge (bridge owns the session lifecycle; not
  measured); S6 on Codex intercom (`coi … resume <id>` rejected by codex); S3 on Claude intercom-accept (`cci --yolo`),
  csd (`--dangerously-skip-permissions`) and gc-nudge (the `gc prime` startup turn does not settle in the prompting
  mode, so the approved.txt dialog cannot be isolated; the one measured cell, `20261028-041531-a753`, ran against it
  and was superseded); S12 on hcom, agent-deck, csd (no daemon) and on Claude channel/child relay (stdio children of
  Claude). S12 on intercom restarts the broker, on gc-nudge the supervisor.
- Codex intercom in S2 answers in the hidden bridge thread while the human's turn is gated: recorded `delivered` +
  `parallel-thread`, not queued/interrupted (not good). Candidate for a ruling.

### Pinning (R35, 2026-10-28 05:00-05:10)

The five agents run from byte-identical copies of the user's installs in gitignored `vendor/agents/` (sources,
sha256 and the per-agent auto-update switches in `vendor/REVIEW.md`). Every copy runs from its new path
(`codesign -v` passes; Pi's package uses only relative symlinks; OpenCode and Droid are self-contained Bun binaries;
OpenCode's `~/.opencode/node_modules` is the user's config-dir plugin deps, which isolated runs never read). The
isolated Codex app-server daemon installs its own package from the pinned CLI at each cell start and runs a
Codex-managed updater beside it; no off switch was found, so `versions.codex_daemon` and the cross-cell guard cover
it. S1 smoke through `sops-exec` on every pinned agent delivered (`20261028-050920-137f` Claude,
`-050930-de3d` Codex, `-050941-c6a2` Pi, `-050952-31b9` OpenCode, `-051005-5296` Droid, `-051017-9101` Codex
codex-queue with daemon 0.165.0). The version guard never fired after pinning.

### Runs (2026-10-28 05:09-15:43)

921 records in this part of the stage: 142 screen re-runs (completing the 160-cell re-screen of Codex, OpenCode and
Droid; the other 18 ran before pinning on the same versions; `results/screen.md`), 2 pilot smoke cells, 750 extensive matrix cells (690
planned plus 60 full-set cells for the zmx/zellij pairs whose host-sensitive result differed, R34 rule 3) and 27 S9
gap fills. Extensive totals: 798 records (incl. 27 S9): 459 delivered, 163 interrupted, 66 lost, 42 queued,
3 rejected, 65 n/a; 0 `error`, 0 `env_error`. Batches stopped eight times for harness fixes (through `runs/STOP` or a
guard, below); no sleep hits (every batch under `caffeinate -i`). Wall time 05:09-15:43.

### Harness fixes (each with a regression test)

1. Pinned agents: `profiles.resolve` reads the single `vendor/agents/<agent>-<version>/` dir and refuses a copy whose
   `--version` differs from the dir name (correction, Task 8 review fixes: only Codex, OpenCode and Droid ran
   `--version` when this was written; Claude and Pi do from the review fixes on); the Codex daemon/app-server and OpenCode server backends start the same
   copies. Tests: `test_each_agent_resolves_to_its_pinned_copy`, `test_pi_resolves_from_its_pinned_package_copy`,
   `test_a_pinned_copy_reporting_another_version_is_refused`, `test_two_pinned_dirs_for_one_agent_are_refused`,
   `test_backend_adapters_start_the_pinned_codex_and_opencode`.
2. `matrix` stops between cells when `runs/STOP` exists (and deletes a stale one at start), so a batch can be ended
   without killing running cells (a matrix started as a background job ignores SIGINT; SIGTERM killed cells).
   Test: `test_a_stop_file_ends_the_batch_after_the_running_cell`.
3. Pi S11: the modal regex matched the `/model` slash-command hint ("Select model (opens selector UI)"), not the
   selector, so S11 raced the hint, never dismissed the selector and labelled every Pi cell `closed-by-send`. It now
   matches the selector's footer. Test: `test_pi_model_selector_is_the_modal_and_the_slash_hint_is_not` (real pane).
4. OpenCode 2.2.0 allows edits without asking, so S3 had no dialog; the isolated prompting config sets
   `permission: {edit: ask, bash: ask}`. Test: `test_opencode_prompting_home_asks_before_edits_and_shell_commands`.
5. OpenCode records a declined permission as an `aborted` step ("Step interrupted"), which the reader took for an
   API error and paused the batch; aborted steps are now `system` entries. Test:
   `test_opencode_step_aborted_by_a_declined_permission_is_not_an_api_error`.
6. Droid 0.251.0 asks to confirm `/compress`; S10 now confirms it (`compact-confirmed`). Test:
   `test_droid_compress_confirmation_box_is_recognised` (real box).
7. OpenCode 2.2.0 marks a finished compaction as `Compaction · <n> in · <m> out`, not "compacted". Test:
   `test_opencode_compaction_counts_as_done_once_its_token_counts_show`.
8. S10 on address-based routes (OpenCode server/hcom, Codex queue): after `/new` the push lands in the old session,
   so `/compact` ran on the empty visible session and never finished; S10 now warms up the visible session first
   (`compact-warm-up`). Test: `test_compact_after_a_clear_answered_in_the_old_session_warms_up_the_visible_session`.
   Limit: the compaction then applies to the visible session, not the addressed one.
9. `all_transcripts` for OpenCode returned only the newest session, so the compact-step reply in the old session was
   recorded `lost`; it now lists every session of the work dir. Test:
   `test_every_opencode_session_of_the_work_dir_is_searchable_after_new`.
10. S12 on the Codex app server: the killed backend was the matrix's own unreaped child, and a zombie still answers
    `kill 0`, so the restart reported it still running; `stop_group` now reaps. Codex app-server 0.165.0 outlives
    the 5 s SIGTERM grace and is SIGKILLed (`stop 5.2s`). Test:
    `test_stopping_a_backend_child_that_ignores_sigterm_leaves_no_zombie` (mutation-checked).
11. S12 on gc-nudge: the supervisor restart took the agent's tmux server with it and gc respawned the agent, but S12
    kept the dead pid, so the next send failed the ownership guard (batch C8 stopped with exit 7, cell
    `20261028-092235-12c4`, no record). S12 now re-adopts a respawned agent: same host ref on the run's own socket,
    new pane pgid added to the manifest, readiness and gc's startup turn awaited, note `agent-respawned-by-bridge`.
    Test: `test_s12_sends_to_the_agent_a_bridge_respawned_during_the_restart`.
12. The bridge `stop_pid` had the same zombie problem for the gc supervisor (`env_error`, batch paused); it reaps
    now. Test: `test_stopping_a_bridge_daemon_child_reaps_it`.
13. `results/matrix.md` notes that pairs whose host-sensitive result differed have their own cells.

### Superseded records (R11, `runs/<id>/superseded-record.jsonl`)

Version wave (old-version screen/extensive verdicts of Codex 0.164.0, OpenCode 2.1.4 and Droid 0.249.0, R35):
`20261027-222034-2358` `20261027-222044-5aeb` `20261027-222423-5313` `20261027-222454-92ec` `20261027-222539-8ba1` `20261027-222620-f7b3` `20261027-222701-f61d` `20261027-223040-c72c` `20261027-223115-012a` `20261027-223157-7bf4` `20261027-223239-be85` `20261027-223339-2908` `20261027-223424-c934` `20261027-223454-6087` `20261027-223526-67ad` `20261027-223612-37d8` `20261027-223659-b886` `20261027-223743-3a3a` `20261027-224051-61e5` `20261027-224105-47f3` `20261027-224146-02e9` `20261027-224225-5bb0` `20261027-224305-124f` `20261027-224323-5402` `20261027-224339-513f` `20261027-224352-e700` `20261027-224701-6900` `20261027-224717-4eb6` `20261027-224733-6f20` `20261027-224747-788c` `20261027-224759-837d` `20261027-224814-2ff6` `20261027-224830-84bd` `20261027-224845-8f56` `20261027-224900-4735` `20261027-224920-eab4` `20261027-224941-1e98` `20261027-225029-a4e3` `20261027-225114-2a38` `20261027-225213-5a6b` `20261028-040204-167b` `20261028-041131-adaa` `20261028-042253-aaeb` `20261027-214759-28c1` `20261027-215421-b879` `20261027-215430-605e` `20261027-215508-ed00` `20261027-215522-df98` `20261027-215532-7885` `20261027-215303-b3b2` `20261027-215559-02ec` `20261027-215643-c63a` `20261027-215724-8164` `20261027-215854-d18a` `20261027-215908-3e6e` `20261027-215917-0f7a` `20261027-215640-e85e` `20261027-220022-944e` `20261027-220109-d478` `20261027-220153-47a1` `20261027-215949-4135` `20261027-220329-13d7` `20261027-220356-210a` `20261027-220358-a3ff` `20261027-220408-dfc2` `20261027-220424-6adc` `20261027-220453-8ffa` `20261027-220504-f54d` `20261027-220507-2304` `20261027-220532-74cd` `20261027-220519-a267` `20261027-220540-adff` `20261027-220601-130b` `20261027-220611-afea` `20261027-220615-c934` `20261027-220626-99a2` `20261027-220642-d788` `20261027-220704-23cb` `20261027-220713-a7f8` `20261027-220718-7ac5` `20261027-220721-cbf9` `20261027-220730-4e4c` `20261027-220731-098e` `20261027-220831-9e1b` `20261027-220916-973c` `20261027-220959-adbf` `20261027-220742-1d7f` `20261027-221130-939f` `20261027-221215-0a3b` `20261027-221257-5d0d` `20261027-221049-5bd2` `20261027-221357-e083` `20261027-221442-db23` `20261027-221524-e22b` `20261027-221356-345b` `20261027-221657-0200` `20261027-221743-fd43` `20261027-221828-f930` `20261027-221705-0d47` `20261027-222018-a84b` `20261027-222047-a73e` `20261027-222058-eb0d` `20261027-222107-c691` `20261027-222117-5eb7` `20261027-222128-4e13` `20261027-222438-58fd` `20261027-222748-7804` `20261027-223059-8d8f` `20261027-223422-6e78` `20261027-223433-6637` `20261027-223444-d429` `20261027-223457-7a58` `20261027-223528-1958` `20261027-223619-4ecf` `20261027-223707-842f` `20261027-223757-cb2d` `20261027-223851-e192` `20261027-224228-86a2` `20261027-224608-83a5` `20261027-224921-b792` `20261027-224940-86f6` `20261027-225025-4430` `20261027-225108-c155` `20261027-225154-49c6` `20261027-225229-ff2c` `20261027-225310-d4e8` `20261027-225328-8ee6` `20261027-225343-49b6` `20261027-225359-75f0` `20261027-225412-0a5d` `20261027-225422-6921` `20261027-225732-e51a` `20261027-225745-1636` `20261027-225800-2db4` `20261027-225814-1eb2` `20261027-230149-4ead` `20261027-230457-db05` `20261027-230804-fd16` `20261027-231113-6799` `20261027-231130-81d8` `20261027-231436-7132` `20261027-231744-316c` `20261027-232053-bdce` `20261027-232109-12d1` `20261027-232145-27fe` `20261027-232218-435b` `20261027-232254-5264` `20261028-002652-8d5f` `20261028-002735-18ee` `20261028-002749-dd85` `20261028-003700-6da4` `20261028-003714-81b0` `20261028-003759-dd52` `20261028-003845-3570` `20261028-005430-a10a` `20261028-005518-4551` `20261028-011103-83ad` `20261028-011148-26b6` `20261028-011207-7dbe` `20261028-013901-2309` `20261028-013956-e4fb` `20261028-024012-3fc3` `20261028-035747-100e` `20261028-040312-c3fb` `20261028-041102-490b` `20261028-041243-e100` `20261028-041357-c5d4` `20261028-042117-4965` `20261028-042254-c784`

Harness causes and n/a decisions:

- `20261028-040303-bbd3`, `20261028-040647-f0cb`: codex intercom S6/S12 warm-up cached bridge thread
- `20261028-041102-55e5`: claude csd S3 precondition error; csd forces skip-permissions -> n/a
- `20261028-041512-b945`: codex intercom S6 resume through coi rejected -> n/a
- `20261028-041531-a753`: claude gc-nudge S3 measured against the gc prime startup turn/dialog -> n/a
- `20261028-041102-aa0d`: codex intercom S2 classified interrupted before the hidden-thread rule -> re-run
- `20261027-225828-8020`: codex intercom S8 screen record: R33 hidden-thread push is delivered with rendered=no, not lost -> re-run 20261028-035747-100e
- `20261028-042502-f50b`: droid agent-deck S3 error: 0.251.0 started in Auto (Med) without autonomyLevel off
- `20261028-045057-aef6`, `20261028-053057-172d`, `20261028-054800-b716`: pi S11 (hcom, intercom, pi-claude-link): Pi modal regex matched the /model slash hint, not the selector; modal note wrong and no dismissal -> re-run
- `20261028-055756-2f2b`: pi pi-ext S11 precondition error from the same Pi modal regex bug -> re-run
- `20261028-070655-ce8c`: opencode hcom S3 precondition error: OpenCode's isolated prompting config did not ask before edits (2.2.0 allows edits by default) -> fixed, re-run
- `20261028-071551-0f20`: opencode hcom S3 env_error: OpenCode's aborted step after the declined permission was read as an API error (pausing the batch) -> fixed, re-run
- `20261028-072757-9801`: droid tmux-paste S10 precondition error: Droid 0.251.0 asks to confirm /compress and S10 never confirmed -> fixed, re-run
- `20261028-074549-9ea4`: opencode tmux-paste S10 precondition error: OpenCode 2.2.0 marks a finished compaction as 'Compaction · <n> in', not 'compacted' -> fixed, re-run
- `20261028-075951-8b9d`: opencode hcom S10 precondition error: after /new the push went to the old session, so /compact ran on the empty visible session -> S10 now warms up the visible session first, re-run
- `20261028-080734-e493`, `20261028-081121-9229`: opencode hcom / opencode-server-steer S10: compact-step push was answered in the old session but all_transcripts searched only the newest OpenCode session (recorded lost) -> fixed, re-run
- `20261028-083055-bd61`: codex codex-remote-start S12 error: the killed app-server was the matrix's own unreaped child (a zombie still answers kill 0) -> stop_group now reaps it, re-run
- `20261028-092752-eaa7`: codex gc-nudge S12 env_error: killed gc supervisor was the matrix's own unreaped child (zombie) -> stop_pid reaps it; the batch-C8 ownership stop on 20261028-092235-12c4 (no record) was the same cell: gc respawned the agent after the restart and S12 kept the dead pid -> S12 re-adopts the respawned agent

### Findings and decisions from this part (for rulings)

- Re-screen: survivors unchanged; Codex codex-remote-start/-steer S7 preserved the draft in the screen on 0.165.0
  but merged it in both extensive reps (1/3). Droid zellij-write S4 changed from lost to delivered-not-intact.
- zellij S6: a send while the receiver is down reports success and is lost on every agent (tmux rejects it), so
  every zellij pair got the full set; Droid zmx-paste merged S5 bursts (0/3) and got it too. Their S3, S7, S10 and
  S11 verdicts equal the tmux ones.
- S9 gap fills: 27/27 recorded, 26 round trips; Codex>Claude over intercom-accept failed (Claude's `SendMessage`
  reply went into the intercom bridge's own peer socket and never reached Codex).
- Claude intercom-accept S12: after the broker restart no session re-registered within 20 s, so the send was
  `rejected` (loud).
- Codex app-server 0.165.0 ignores SIGTERM for at least 5 s.
- Ties and S9-only entries in the shortlist, and Droid's unmeasured S3, are decisions D1-D3 in `results/shortlist.md`.
- Writes outside the repo and `/tmp/ac`: harness Claude processes create their peer socket in
  `/tmp/cc-socks/<pid>.sock`. Cleanup does not touch that dir ("left socket … outside harness-owned dirs"), and 13
  such socket files from dead harness Claude processes of this part (zmx/zellij cells) are still there. Claude honours
  `XDG_RUNTIME_DIR` for this dir (Task 5 notes), so setting it to a `/tmp/ac/<run>-…` dir in every Claude launch
  would keep the sockets in harness-owned space; deferred to the coordinator because it changes the Claude launch
  env between stages.

## Task 8 review fixes (2026-10-28, review of the extensive stage)

### Rulings (R37-R40; the coordinator copies them into the ledger)

- R37, safety score: the safety score uses a fixed denominator of 7 (S2 x3, S3 x1, S7 x3). An `n/a` safety cell counts
  as not shown safe, never as a smaller denominator. The `n/a` count is shown beside the score (`3/7 · n/a 1`).
- R38, shortlist S9 column: it counts passes on pinned versions only (R35). Pi `intercom-accept`'s pass was pilot-only on
  Claude 2.1.311, so Pi>Claude over `intercom-accept` was run on the pinned agents and its result used.
- R39, S12 respawn: when the agent dies and a bridge respawns it during a backing-server restart, S12 records
  `respawned` and scores not good (the session context is lost). Applied to Codex gc-nudge S12
  (`20261028-092911-1b83`, note `agent-respawned-by-bridge`, now `0/1 · respawned 1`). Its record is unchanged (the
  note was already there), so nothing was superseded. The other gc-nudge S12 records (Claude `20261028-062836-76de`,
  Droid `20261028-083844-0b38`) have one pgid in their manifests and no respawn note: the agent survived; they stay
  good. The intercom S12 records say "respawned by a client": that is the broker, not the agent.
- R40, S10 on address-based routes: where the push after `/new` goes to the old session (`clear=delivered@old-session`),
  S10 compact is reported as "compaction not exercised on the delivered session" (matrix and shortlist cells; k/n
  unchanged). Affected: OpenCode server-queue/-steer/-synthetic, service-steer and hcom, Codex queue, remote-start,
  remote-steer.

### Findings

- M1 fixed. `Engine.readopt_agent` has tests with a fake pane and ps table (`tests/test_engine.py`,
  `test_readopt_*`). Mutations, each confirmed to land by diffing the function against a saved copy:
  delete `check_owned(target, live=False)` -> `test_readopt_refuses_a_target_the_manifest_does_not_own` fails;
  delete the pgid append -> `test_readopt_records_the_respawned_agent_in_the_manifest` fails; delete
  `with_identities` -> the same test fails; replace `procs.running(...)` by `procs.alive(...)` ->
  `test_readopt_skips_a_running_agent_whose_identity_matches` fails (1 failed, 32 passed each time). A foreign
  process with the agent's argv outside the pane is not adopted (`..._never_adopts_an_agent_outside_the_pane`).
- L1 fixed. Re-adoption is skipped only when `procs.running(pid, recorded identity)` holds (not a zombie, same start
  time and command), so a zombie or a recycled pid re-adopts. An agent that is dead with no respawn (pane gone, ready
  timeout, or no agent process in the pane) raises `AgentLostError`; S12 records it as `lost` with note
  `agent-lost-by-restart: ...` (test `test_s12_records_a_lost_agent_when_the_restart_killed_it_and_nothing_respawned_it`).
  The new pid's cwd is not checked separately: `await_ready` adopts only a pane descendant whose argv[0] is the pinned
  binary.
- M2 fixed. `resolve_claude` and `resolve_pi_dir` run `--version` (throwaway home, `PROBE_ENV` now has claude and pi;
  Pi through the resolved node with `NODE_PATH`) and `resolve()` compares it with the directory name for all five
  agents. The earlier claim ("every `--version` is checked") was false for Claude and Pi: the Claude version was the
  file name and Pi's came from `package.json`. Corrected in README, `vendor/REVIEW.md` and this file (harness fix 1 of
  the extensive stage above). Tests: `test_a_pinned_copy_reporting_another_version_is_refused` (droid, opencode,
  codex, claude) and `test_a_pinned_pi_that_reports_another_version_is_refused`. The legacy resolver defaults that
  pointed at the user's installs (`CLAUDE_LINK`, `CODEX_LINK`, `PI_INSTALLS`, `OPENCODE_BIN`, `DROID_BIN` and the
  `resolve_*` default arguments) are removed. All five pinned copies resolve (claude 2.1.312, codex 0.165.0, pi 1.4.0,
  opencode 2.2.0, droid 0.251.0).
- M3 fixed. The generator is `agentcomms/shortlist.py`, run as `uv run agentcomms shortlist [--write]`; it reads
  `results/raw.jsonl`, the survivor table of `results/screen.md` and the pinned versions from `vendor/agents/`, and
  `--write` splices the three `generated:` blocks of `results/shortlist.md`. The scratch scripts
  (`runs/.scratch/shortlist*.py`) are deleted. Tests: `tests/test_shortlist.py` (fixed denominator, `n/a` count shown,
  ties, S9 rules, survivors parsing, splice). Mutations: dividing by `7 - n/a` fails
  `test_an_unmeasured_s3_counts_against_the_fixed_denominator_of_seven`; dropping the `n/a` suffix fails
  `test_the_ranking_table_shows_the_na_count_beside_the_safety_score`. Regenerated shortlist: Droid's top is
  tmux-buffer, tmux-paste and tmux-paste-retry (3/7, 11/16 each), then agent-deck (3/7, 10/15); gc-nudge is 9th of 10
  (3/7 · n/a 1, 8/15). The top entries of Claude, Codex, Pi and OpenCode are unchanged, and every total k/n and harm
  count is unchanged except Codex gc-nudge (8/15 -> 7/15, R39). Lower ranks moved for Claude (csd, gc-nudge) and
  Codex (gc-nudge last).
- M4 fixed (R38). `uv run agentcomms s9 --a pi --b claude --fwd intercom-accept --back intercom-accept --stage extensive
  --rep 1 --sandbox raw` -> `20261028-161100-7b7f`: delivered, intact, acked, `roundtrip=yes` (13.0 s), Pi 1.4.0 and
  Claude 2.1.312. Pi `intercom-accept` stays in the S9 column; Claude `intercom-accept` stays out (Codex>Claude failed
  on 2.1.312). The S9 column now counts pinned-version passes only, so Codex `intercom` (Pi>Codex on Codex 0.164.0
  only) left it; Pi `intercom` stays through Pi>Pi (Pi 1.4.0 is the pinned build). If the coordinator wants Codex
  `intercom` back, run Pi>Codex over intercom on the pinned agents.
- M5 fixed (R40). `scoring.compact_unexercised` marks S10 records with `clear=delivered@old-session`; `cell_text`
  appends "compaction not exercised on the delivered session" in `matrix.md` and `shortlist.md`. The loop wiring of
  `needs_warm_up` is now tested (`test_s10_warms_up_the_visible_session_...`, `test_s10_compacts_without_a_warm_up_...`;
  forcing `needs_warm_up` off fails the first).
- L2 fixed (R39). `scoring.respawned` and `Tally.respawned`; S12 is good only if `queued_or_delivered` and not
  respawned. The shortlist properties table mentions it for Codex gc-nudge.
- L3 fixed. `matrix` no longer deletes `runs/STOP`. A leftover file blocks the next batch before its first cell
  ("runs/STOP found; N cells left") until the user or the coordinator removes it; documented in the README. Tests:
  `test_a_stop_file_ends_the_batch_after_the_running_cell` (no pre-written file now) and
  `test_a_stop_file_left_from_an_earlier_batch_blocks_the_next_one_and_is_kept`.
- L4 fixed. `backends.terminate` sends SIGTERM, waits for the group (or process) to have no live member without
  reaping, and sends SIGKILL only if something is still live, then `wait_gone` reaps; `stop_group` and the bridge
  `stop_pid` use it (`procs.live_group`, `procs.live_process` ignore zombies). Tests: a group that exits on SIGTERM
  receives only SIGTERM; one that ignores it receives SIGTERM then SIGKILL.
- L5 fixed. `Engine.check_versions` (called at the end of every cell) re-reads the Codex daemon version with the cell's
  environment and compares it with `versions.codex_daemon`; an unreadable daemon (stopped) is not a mismatch. Test:
  `test_check_versions_compares_the_codex_daemon_version_as_well_as_the_binary`.
- L6 skipped: Pi's node runtime is not pinned. It is recorded as `versions.node`, part of the compared `Binary`, so
  drift is caught; the reviewer called it acceptable and `vendor/REVIEW.md` already says so.
- L7 fixed. The 110 extensive S7 records (55 rep 1, 55 rep 2) were renumbered to reps 2 and 3 so they no longer collide
  with the screen rep 1. Only the `rep` field changed (checked record by record against a copy taken before the edit:
  110 lines differ, all in `rep` only); run ids are unchanged. A `--resume` of the old extensive plan would see S7 reps
  1-2 as pending again; the plan files in `runs/.scratch/` are not reused.
- L8 fixed. `results/screen.md` counts: 248 delivered, 25 lost, 8 held, 3 rejected, 8 `env_error` (292); the extensive
  total is now 799 records with the R38 S9 cell (460 delivered). README's baseline sentence now names the pinned
  versions. The 190 superseded records of the version wave and the Task 8 list that had no inline reason now carry a
  `superseded` field (the notes' reason, or "R35 version wave ..."). 32 earlier-task (pilot) superseded records still
  have none: their reasons are in the Task 1-7 sections above and were not part of this finding.
- NIT: the auto-mode OpenCode config has no `permission` key (`test_opencode_auto_config_sets_no_permission_key`).
  Hoisted the `subprocess` and `procs` imports out of the two named test bodies; other tests keep the local-import
  style of their files. `readopt_agent` keeps returning `(manifest, target, respawned)`: S12 needs the flag and
  splitting it would repeat the pid comparison; skipped.

### Stale Claude peer sockets

`agentcomms cleanup --stale-claude-socks` (and `cleanup <run_id>` for that run) removes `/tmp/cc-socks/<pid>.sock` only
when a harness manifest lists the pid as a Claude target with a recorded process identity, the entry is a socket, and no
process with that identity runs any more (a dead pid). A pid that is alive under another identity is reported as left
(a live socket could be the user's). Tests with fake manifests: `test_only_dead_harness_claude_sockets_are_removed`,
`test_a_pid_recorded_by_any_manifest_with_a_matching_identity_keeps_its_socket`, `test_run_manifests_reads_every_run_...`.
Run once on 2026-10-28 (before the S9 re-run): 26 sockets removed, all pids recorded as harness Claudes in
manifests and dead (the 13 noted in the extensive findings above plus 13 more from earlier runs, which the old cleanup
never touched), none left as pid-reused. 17
sockets remained in the directory and were not touched (the user's live sessions).

## Task 10: shortlist reps, scale, user config, nono (2026-10-28)

Pinned agents (R35), unsandboxed coordinator (R21), cheapest models. Results tables: `results/shortlist.md`
"Task 10"; preflight: `results/nono-preflight.md`; scale summaries: `results/scale-<first run>.json`.

### Runs

- Reps: 150 cells, stage `shortlist`, 16:22-17:35, `--max-concurrency 3 --resume` under `caffeinate -i`
  (`runs/.scratch/plan-t10-reps.json`): S1 reps 2-5, S2/S5/S7 reps 4-5 for the 15 "by ranking" entries (D1, ties
  kept). S9-only entries got no reps (D2: covered by S9 only). All S1/S2/S5 good; S7 merges as before on Codex and
  Droid. One harness error re-run (below).
- R38: Pi>Codex over `intercom` on the pinned agents, `20261028-173547-b27b`, `roundtrip=yes` (10.6 s): Codex
  `intercom` is back in the S9 column.
- User config: 30 cells (S1, S7 x 15), 17:36-18:55, 8 run, 21 `n/a` skips, 1 `error` (below).
- Scale: two batches of 8 receivers x 3 messages, 48/48 delivered and acked (`20261028-185640-d379`...,
  `20261028-185959-88e7`...).
- nono: preflight 75/75; 60 cells (S1, S2, S4, S7 x 15), 19:11-19:38, all delivered, verdicts equal raw; S9 3/3.

### R41 — user-config cells (coordinator ruling, recorded here)

Inventory first (names only), no outward contact (skip, or a per-launch switch that disables just that integration),
trust/onboarding without global writes, session files in the user's stores recorded for the user to remove, `hashes`
before and after. `uv run agentcomms user-config-inventory` prints it; `agentcomms/userconfig.py` encodes it.

Inventory (names only):

- Claude: hooks `agent-sandbox-status`, `auto-approve-mcp.sh`, `enforce-fix-failures.sh`, `hooklinesinker`,
  `nudge-jina.sh`, `redirect-gh-api.sh`; plugins `claude-session-driver`, `mouthfeel`, `nono`, `rust-analyzer-lsp`,
  `swift-lsp`, `telegram` (channel, MCP server `telegram`), `typescript-lsp`; plugin dir `dev-phase` (mod); status
  line command; no user MCP servers; no remote control enabled. Outward: `telegram` (polls the user's bot; switch
  `--settings enabledPlugins false`), `hooklinesinker` (forwards to the user's Juggler/ringleader consumers; switch
  `XDG_STATE_HOME` in the run). `claude-session-driver` hooks write `/tmp/csd-workers` (redirect `CSD_WORKER_DIR`).
- Codex: hooks `hooklinesinker`, `agent-sandbox-status`; `notify` `SkyComputerUseClient` (Codex Computer Use app);
  MCP `context7`, `jina`; plugins `browser`, `chrome`, `computer-use`, `unified-computer-use` (device/desktop),
  `codex-app-tools`, `documents`, `mouthfeel`, `nono`, `pdf`, `presentations`, `spreadsheets`, `template-creator`,
  `visualize`; app connector `connector_openai_codex_document_control`; custom `tui.status_line`. Switches: `-c
  notify=[]`, `-c mcp_servers.<n>.enabled=false`, `-c plugins."<n>".enabled=false`, `XDG_STATE_HOME`.
- Pi: packages `pi-subagents`, `pi-plan-mode`, `pi-lsp`, `pi-statusline`, nono pack `pi`, `mouthfeel`; extension
  `mods/dev-phase/pi/index.ts`; auto-loaded extensions `hooklinesinker-pi.ts`, `pi-ringleader-finish.ts` (runs `rl
  session sweep` on shutdown; switch: a no-op `rl` first on `PATH`), `sandbox-status.ts`, `subagent`; `mcp.json`
  `context7`, `jina` (no MCP client loaded in the parent session).
- OpenCode: plugins `hooklinesinker-opencode.ts`, `mouthfeel.js`, `nono-sandbox.ts`, `sandbox-status.ts`; MCP
  `context7`, `jina`; agent `coordinator`; `service.json` (the user's background service).
- Droid: hooks `hooklinesinker`; MCP `context7`, `jina`; status line command.

Decisions per cell:

- Claude: skipped, trust. Probe `runs/.scratch/trustprobe` (isolated config dir, no trust entry): Claude 2.1.312 shows
  "Quick safety check … Yes, I trust this folder" even with `--permission-mode bypassPermissions`; no ancestor of
  `runs/` is trusted in `~/.claude.json`; accepting writes it; no per-launch switch.
- Droid: skipped, trust (`trustedFolders` has no ancestor of `runs/`, accepting writes `~/.factory/settings.json`,
  `droid --help` has no trust flag).
- Codex `codex-queue`, OpenCode `opencode-service-steer`: skipped (the user's live daemon / service).
- Codex remote-start/-steer: `CODEX_HOME=~/.codex`, switches above, `-c model/effort/approval/sandbox`,
  `features.shell_snapshot=false` (R29), trust via `-c projects={"<work>"={trust_level="trusted"}}` (the dotted
  `projects."<dir>".trust_level` form is ignored by Codex 0.165.0: probe `runs/.scratch/codextrust`, the trust dialog
  still showed and nothing was written). The backend check allows the user's `CODEX_HOME` only for `codex app-server
  --listen unix:///tmp/ac/<run>.sock`.
- Pi: ran one cell, then skipped: see "Global config write" below.
- OpenCode server-queue/-steer: user config dir (`XDG_CONFIG_HOME` and `OPENCODE_TEST_HOME` unset), data/state/cache
  in the run (the user's service database is never opened), `OPENCODE_CONFIG_CONTENT` with the cheapest model.

Interference found: Codex's `tui.status_line` replaces the default footer (harness readiness fix); Pi's changelog,
"Package Updates Available" screen and `pi-statusline` footer (Pi never became ready); OpenCode started the user's
`context7` MCP (`npx @upstash/context7-mcp`) despite `OPENCODE_CONFIG_CONTENT` `mcp.context7.enabled=false` — the
switch does not work in 2.2.0, so the 4 OpenCode cells (and one requeued `env_error`) made outward contact (npm
registry, context7; jina's remote MCP probably connected too). `userconfig.mcp_disable` no longer claims an OpenCode
switch, so a re-run skips those cells. hooklinesinker found no consumers in the run's `xdg-state` (checked: status
files under `runs/<id>/xdg-state/hooklinesinker/`).

### Global config write (stop-and-report item)

`~/.pi/agent/settings.json` changed at 17:56:34 during the Pi user-config cell `20261028-175605-27fb`:
`lastChangelogVersion` 1.2.0 -> 1.4.0 (key set unchanged; no harness path in it). In the same second Pi rewrote
`~/.pi/agent/auth.json` and `~/.pi/agent/models-store.json`, touched
`~/.pi/agent/sessions/--Users-nielsmadan-wrksp-pratfall-dev4--/subagent-artifacts/.last-cleanup` (pi-subagents
cleanup) and ran `npm view @narumitw/pi-statusline version` / `npm view @narumitw/pi-lsp version`. Attributed to the
harness (timing, cwd of the npm logs). Not reverted (global configs are read-only for the harness): the user may set
`lastChangelogVersion` back to `1.2.0`. The batch stopped (exit 5) after it; Pi user-config cells were then skipped
(`userconfig.PI_WRITES`). `hashes` after all cells: only `~/.claude.json` (known churn) and this file differ.

### Paths created in the user's stores by the user-config cells (not deleted)

- Codex rollouts `~/.codex/sessions/2026/10/28/`: `rollout-2026-10-28T17-40-21-01a18362-…`, `…T17-42-51-01a18364-…`,
  `…T17-43-36-01a18365-…`, `…T17-56-08-01a18370-…`, `…T18-43-59-01a1839c-…`, `…T18-52-42-01a183a4-…`,
  `…T18-53-14-01a183a5-…` (`.jsonl`; the first three are the superseded smoke cells).
- `~/.codex/tui-thread-reference-capabilities/<id>` for the same 7 thread ids; `~/.codex/tmp/arg0-macos/
  codex-arg00yAgq1/` and `codex-arg0N3Vv7x/`; rows in `~/.codex/session_index.jsonl`, `state_5.sqlite`,
  `thread_history_1.sqlite`, `logs_2.sqlite` (and their `-wal`/`-shm`).
- Changed at cell times (likely ours, may be shared caches): `~/.codex/models_cache.json`,
  `~/.codex/cache/codex_apps_server_info/…`, `codex_apps_tools/…`, `remote_plugin_catalog/` (2),
  `~/.codex/plugins/cache/openai-curated-remote/*/.codex-remote-plugin-install.json` (5).
- Pi: see the section above. OpenCode wrote nothing outside the run (data dir isolated).
- npm: 7 `~/.npm/_logs/*-debug-0.log` (Pi `npm view` x2, OpenCode `npx context7` x5); npm has since rotated them away.

### Scale

Mix and table in `results/shortlist.md`. Each receiver is its own run with its own backend; tmux is the only shared
server. Latency (send -> first receiver record) 0.002-0.59 s, median 0.02 s over 48 messages; Codex remote-start is
slowest (0.04-0.59 s), Pi fastest. Load: RSS 3.0-3.4 GB for 22-24 processes, CPU 142 % in the launch sample, 11-22 %
during the rounds. Only 1-3 samples per phase (short phases; batch 1 sampled only every ~15 s because ownership was
recomputed per sample; batch 2 every 2 s with ownership refreshed every 20 s).

### nono pass

`agentcomms/sandbox.py`: `sops-exec nono run [--silent for claude/opencode] --no-audit -p <agent>-local --
/usr/bin/env … <pinned binary>`, launcher env as `_agent_sandboxed` (`~/ac/.airc.d/05-sandbox.zsh`, read only).
Deviations: `--no-audit`; `NONO_NO_UPDATE_CHECK=1` for nono only; the agent's `XDG_CONFIG/STATE/DATA/CACHE_HOME`
and `XDG_RUNTIME_DIR` are hidden from nono and restored by the inner `env`. Backends run under the receiver's
profile too; harness-side sends run the adapter's stdlib sender (or its agent route) under the receiver agent's
profile; tmux adapters run `tmux` there. The pinned copies in `vendor/agents/` are readable and executable in every
profile (the repo is under the `~/wrksp` grant), so no fallback to the user's live binaries was needed. The intercom
TS sender ran via the vendored node + tsx in `pi-local` (deferred question answered: included).

Failures and diagnoses (all harness causes, superseded per R11, re-run):

- `20261028-190644-4b48`, `-191008-f1df` (OpenCode backends): the backend wrapper put `sops-exec` inside nono;
  `nono why --self --path ~/.config/sops/secrets.yaml --op read` (and `…/age/keys.txt`) inside `opencode-local` ->
  `DENIED path_not_granted`. By design (the launcher runs sops-exec outside); fixed in `backends.spec_command`.
- `20261028-190404-4186` (Pi pi-claude-link): nono's PTY proxy wrote its config under the agent's
  `XDG_RUNTIME_DIR=/tmp/ac/<run>-cl`, which did not exist yet ("Failed to create PTY proxy"); not a sandbox denial.
- `20261028-190404-e99a`, `-190725-49e2` (Codex remote-start/queue S1): the sandboxed sender had no thread id before
  the transcript existed ("has no agent-usable sender"); now falls back to the adapter's agent route.

Writes outside the repo: nono keeps a session record per `nono run` in `~/.local/state/nono/sessions/` and refuses
any state dir inside a granted path (tried the repo and `/tmp/ac`: "Refusing to grant … overlaps protected nono state
root"), so the nono pass left 409 session files there (ids in `results/nono-session-files.txt`, attributed by
`agent-comms` in their command/cwd). Two exploratory runs before `--no-audit` added `sessions/620becda8f78b03e.json`,
`sessions/8ef02b2f2ace3eb3.json`, `audit/8ef02b2f2ace3eb3/` and one line in `audit/ledger.ndjson`.

### Harness changes (tests in `tests/test_task10.py` unless named)

- `agentcomms/sandbox.py` + `profiles.nono_wrapper()` + engine/backends wiring; `--sandbox nono` no longer refused.
  Tests: launch-wrapper argv, silent agents, launcher env, XDG hiding, sops-exec outside for backends, runtime dir,
  agent-route fallback, banner stripping.
- `agentcomms nono-preflight` (`agentcomms/nono_preflight.py`).
- `agentcomms scale` (`agentcomms/scale.py`): aggregation, receiver labels/reps, load summary tests.
- `--stage user-config` (`agentcomms/userconfig.py`, overlay in `Engine.launch`, backend checks): skip-logic tests
  from fake inventories, classifier, Codex overlay, backend socket check.
- Matrix rows gain a `condition` column (`raw`, `nono`, `raw + user config`)
  (`tests/test_scoring_report.py::test_nono_and_user_config_records_get_their_own_matrix_rows`).
- Shortlist generator: reps, user-config, nono and scale blocks; S9 column counts raw records only; empty blocks
  splice (`tests/test_shortlist.py`, S9 filter mutation-checked).
- OpenCode session creation waits while the server answers 503 `service_starting`
  (`tests/test_task5_adapters.py`, mutation-checked); superseded `20261028-173135-0a71`.
- Codex readiness accepts a custom status line's `Context N% used`
  (`tests/test_engine.py::test_codex_with_a_user_status_line_is_ready_once_bootstrap_draws_it`).
- Transcript notes accept transcripts outside the repo (user stores).

Superseded (R11): `20261028-173135-0a71`, `-173655-a097`, `-174019-e524`, `-174250-2b0e`, `-190404-4186`,
`-190404-e99a`, `-190725-49e2`, `-190644-4b48`, `-191008-f1df` (reasons in each `superseded-record.jsonl`).

Slip: one diagnostic `ps -axo pid,ppid,ucomm` with a broken awk filter printed the names (no args, no env) of all
processes instead of the harness pane's subtree.

### Decisions and deferred questions

- R41 applied as above; the Pi config write and the ineffective OpenCode MCP switch need the coordinator's eye.
- nono state writes outside the repo are unavoidable for any `nono run`: accept, or drop the nono pass from future
  runs.
- Claude and Droid user-config coverage needs a per-launch trust path (or the user accepting one trusted parent).


## Task 10 review fixes (2026-10-29)

Rulings from the coordinator, recorded as given.

- R42 (user-config switches): a user-config "disable" counts only when the agent's overlay demonstrably applies it,
  and a test pins the built argv/env. An integration without a verified switch makes the cell a skip, never a run. An
  agent with no overlay branch (Claude, Droid) is a skip with a reason, never a `ValueError`. Codex plugins and app
  connectors are outward-facing: disabled through a verified `-c` override, or skip.
- R43 (honest records): the 5 OpenCode user-config records stay as data but say what happened; the Codex ones too.
- R44 (S9-only entries): no reps, user-config or nono delivery cells; listed as agent-to-agent options with extensive
  k/n and S9 result (stated in shortlist.md's ranking basis).

### Fixes

- M1/R42: `userconfig.applied(agent, disable)` is the single test of "the overlay applies this switch"
  (`APPLIED_SWITCHES`: Codex `-c`, XDG_STATE_HOME, CSD_WORKER_DIR; Pi XDG_STATE_HOME, PATH, CSD; OpenCode XDG_STATE_HOME,
  CSD). `skip_reason` uses it for outward integrations and `disabled()` (so the overlay flags and the record note) uses
  it too; an agent outside `APPLIED_SWITCHES` skips with "no user-config overlay for <agent>" (after trust and
  global-write checks). Removed the unapplied Claude telegram `--settings` string and Pi's `lazy:` string. Codex plugins
  all get `-c plugins."<n>".enabled=false`; Codex app connectors have no verified switch (`apps.<id>.enabled` is
  documented, but openai/codex#17588 reports connector/app/plugin config disables being ignored, and no live cell was
  run), so the connector skips the Codex cells. The plugin and MCP `-c` switches are likewise not live-verified for
  effectiveness; they are pinned in argv only. A re-run of the Codex user-config cells therefore skips on the user's
  connector.
- M2/M3/R43: edited only the `notes` field of 10 records in `results/raw.jsonl` (all other fields compared equal before
  and after). OpenCode `20261028-175605-88c5`, `-184357-569a`, `-185351-01db`, `-185426-9ef6`, `-185500-ee97`:
  "disabled plugin hooklinesinker-opencode.ts, mcp context7, mcp jina" became "disabled plugin
  hooklinesinker-opencode.ts; outward-contact: mcp context7 started (switch ineffective in 2.2.0); jina likely".
  Codex `20261028-174335-d9bd`, `-175605-b016`, `-184357-2bf1`, `-185241-1da2`, `-185313-f793` gained
  "outward-contact: remote plugin catalog / app connector caches written" after the disabled list. The shortlist
  user-config table's cause column now shows these caveats (`shortlist.caveat`, tested).
- M4: `codex-queue-embedded` is in `Inventory.blocked` with `codex-queue` (shared `CODEX_DAEMON_BLOCK`), tested by
  mechanism name.
- M5: R44, shortlist.md ranking basis and D2 updated.
- M6: tests in `tests/test_task10.py` call the real `codex_/pi_/opencode_/claude_/droid_inventory` on fake home dirs, the
  Codex, Pi and OpenCode overlays, and `Engine.launch(user_config=True)` (with `resolve`/`start` stubbed) for Codex, Pi
  and OpenCode, asserting built argv and env.
- LOW 7: `Engine.sandboxed` uses `wrap_launch` only when `argv[0]` is sops-exec, else `wrap_command` (as
  `backends.spec_command`); tested.
- LOW 9: `PI_WRITES` no longer embeds a run id or versions; it points at "Global config write" above.
- LOW 10: shortlist.md labels the scale CPU numbers with their sample counts (batch 1: 1 launch sample, 1 message
  sample; batch 2: no launch sample, 3 message samples).
- NIT 11: removed the dead OpenCode `mcp` block from `opencode_content`.
- NIT 12 (`cmd_scale` is ~80 lines): skipped, a refactor of working code with no behaviour change.

### `--no-audit` (LOW 8)

`nono run --help`:

    --no-audit
        Disable the audit trail for this session

The Nono docs (alwaysfurther.mintlify.app/cli/features/audit) separate "audit recording" ("what happened?") from
audit-log integrity, filesystem integrity, signing and rollback, and nono's changelog has "Skip network audit buffer
when --no-audit is set (#1682)". Nothing in the help or the docs says `--no-audit` changes the Seatbelt policy; it
turns off the audit trail (and the audit buffer). That is the documented scope; no denial test was run to prove the
policy is identical, since no nono cell was run this round.


## Whole-branch review fixes (2026-10-29)

Fix round for the whole-branch review (`review-branch.md`: C-1, S-1–S-17, N-1–N-29, two autofix groups) and the
test-quality review (`review-tests.md`: 29 surviving mutations). Code, tests and result text only; no live cell ran.

### Coordinator rulings (R45-R49), recorded as given

- R45 (critical, cleanup ownership): cleanup may remove a Codex daemon socket only if the target's Codex home resolves
  inside the run dir and the manifest records that the harness started that daemon. The same rule applies to every
  derived path (sockets, pid files, state dirs): a derived path for a home outside the run is never removed.
  Regression tests for the user-config case (`home_dir` = the real `~/.codex`, fake HOME), mutation-checked.
- R46 (S12 lost-by-restart): R39's `agent-lost-by-restart` must be reachable; `finish()` must not turn a dead target
  that S12 itself declared lost into a receiver-crashed `env_error`. Re-check the existing S12 records from evidence
  and reclassify per R11 if any would change.
- R47 (S5 burst precondition), the Decided preconditions rule: where the send window is over 1 s because the
  adapter's own send blocks by design (the tmux-paste-retry settle, a blocking sender), the mechanism cannot burst:
  S5 is `n/a` with `adapter cannot burst (window <s>)`. Where the harness itself was slow, the record becomes `error`
  with cause `burst-window`. Either way the records leave S5's k/n; keep the record and note the reclassification.
  Enforce it in `s5.py` with tests, re-derive the affected records from evidence and log each, regenerate shortlist
  and matrix, no re-runs; a top-ranked shortlist mechanism that loses S5 coverage goes under "re-test on the Mac
  Studio".
- R48 (R42 switch verification): `applied()` inspects the built argv/env for each claimed switch, not a prefix list.
  Unknown hooks and plugins are "unclassified" and skip the cell. The Codex plugin and MCP `-c` switches stay "pinned
  in argv, not live-verified", stated in the shortlist user-config caveat and REPORT §8.
- R49 (QA leftovers): `cleanup <unknown id>` exits 2 with "unknown run id"; a batch that `runs/STOP` blocks before any
  cell exits 10 (pause); the sandbox refusal distinguishes "is sandboxed" from "could not verify (fail closed)".

### R45: no harm occurred (coordinator's check, recorded as given)

The user's Codex daemon has been down since 2026-10-23 (the mtime of its `daemon.pid`). The socket name the harness
derives for `~/.codex` (`ee61a2ac…`) is absent from `/private/tmp/codex-daemon-501/` and appears in no cleanup log,
and no process holds any socket in that directory. This round did not touch that directory.

### Reclassified records

- R46: none. The 64 S12 records in `raw.jsonl` (42 `n/a`, 21 `delivered`, 1 `rejected`) and the 6 superseded S12
  records under `runs/*/superseded-record.jsonl` contain no `agent-lost-by-restart` and no receiver crash after a
  declared loss, so no verdict changes.
- R47: 44 S5 records, edited in place (`delivery`, `latency_s` -> null, and a note appended; every other field equal).
  The review counted the 32 that scored good; the other 12 (gc-nudge x9, Pi intercom x3) scored not good (merged)
  under the same failed precondition, so they leave k/n too. Evidence: each record's `send_window`; the harness's
  own share is the window of a burst through a non-blocking sender (174 S5 records with `send_s <= 0.05` and a window
  under 1 s: 0.52-0.86 s, about 0.11 s per send, all of it the per-send ownership check with a full `ps`). Rule: if
  window minus 0.86 s is still over 1 s, the adapter's sends alone exceeded the window (`n/a`); if window minus
  0.52 s is at most 1 s, the adapter would have fit and the harness pushed the burst over (`error`
  `burst-window`). No record fell between (windows 1.12-1.40 s and 2.21-11.57 s). Result: 33 `n/a`
  (tmux-paste-retry 12, gc-nudge 9, intercom 6, intercom-accept 3, csd 3), 11 `error` (agent-deck 6, codex-queue
  5). The note appended is `n/a: adapter cannot burst (window Xs); reclassified-R47 (was delivered, good|not good;
  …)` or `precondition: burst-window (window Xs); reclassified-R47 (…)`.

| run | agent | mechanism | stage rep | window s | was | now |
|---|---|---|---|---|---|---|
| `20261028-045108-4bd3` | claude | agent-deck | extensive 1 | 1.12 | delivered, good | error burst-window |
| `20261028-104257-6364` | claude | agent-deck | extensive 2 | 1.15 | delivered, good | error burst-window |
| `20261028-104727-75ff` | claude | agent-deck | extensive 3 | 1.19 | delivered, good | error burst-window |
| `20261028-074435-1d24` | droid | agent-deck | extensive 1 | 1.26 | delivered, good | error burst-window |
| `20261028-104639-b4d1` | droid | agent-deck | extensive 2 | 1.35 | delivered, good | error burst-window |
| `20261028-105035-d252` | droid | agent-deck | extensive 3 | 1.14 | delivered, good | error burst-window |
| `20261028-074400-71e2` | codex | codex-queue | extensive 1 | 1.34 | delivered, good | error burst-window |
| `20261028-110220-f82c` | codex | codex-queue | extensive 2 | 1.32 | delivered, good | error burst-window |
| `20261028-110408-b84f` | codex | codex-queue | extensive 3 | 1.40 | delivered, good | error burst-window |
| `20261028-170115-b3c4` | codex | codex-queue | shortlist 4 | 1.19 | delivered, good | error burst-window |
| `20261028-171426-1d33` | codex | codex-queue | shortlist 5 | 1.23 | delivered, good | error burst-window |
| `20261028-060353-df36` | claude | csd | extensive 1 | 2.73 | delivered, good | n/a |
| `20261028-120741-b5f4` | claude | csd | extensive 2 | 2.51 | delivered, good | n/a |
| `20261028-121052-7a0e` | claude | csd | extensive 3 | 2.49 | delivered, good | n/a |
| `20261028-061552-4785` | claude | gc-nudge | extensive 1 | 10.45 | delivered, merged | n/a |
| `20261028-122458-2939` | claude | gc-nudge | extensive 2 | 10.74 | delivered, merged | n/a |
| `20261028-122833-16f4` | claude | gc-nudge | extensive 3 | 9.14 | delivered, merged | n/a |
| `20261028-090753-bfb2` | codex | gc-nudge | extensive 1 | 11.57 | delivered, merged | n/a |
| `20261028-114949-7abd` | codex | gc-nudge | extensive 2 | 9.44 | delivered, merged | n/a |
| `20261028-115339-f3f3` | codex | gc-nudge | extensive 3 | 9.35 | delivered, merged | n/a |
| `20261028-082305-138c` | droid | gc-nudge | extensive 1 | 9.39 | delivered, merged | n/a |
| `20261028-111625-47b1` | droid | gc-nudge | extensive 2 | 10.55 | delivered, merged | n/a |
| `20261028-111727-9ea0` | droid | gc-nudge | extensive 3 | 11.01 | delivered, merged | n/a |
| `20261028-095051-0735` | codex | intercom | extensive 1 | 2.41 | delivered, good | n/a |
| `20261028-122611-252f` | codex | intercom | extensive 2 | 2.31 | delivered, good | n/a |
| `20261028-123048-7c65` | codex | intercom | extensive 3 | 2.23 | delivered, good | n/a |
| `20261028-051926-3025` | pi | intercom | extensive 1 | 2.58 | delivered, merged | n/a |
| `20261028-111410-c149` | pi | intercom | extensive 2 | 2.38 | delivered, merged | n/a |
| `20261028-111727-dfea` | pi | intercom | extensive 3 | 2.75 | delivered, merged | n/a |
| `20261028-064539-14e8` | claude | intercom-accept | extensive 1 | 2.43 | delivered, good | n/a |
| `20261028-130234-6970` | claude | intercom-accept | extensive 2 | 2.29 | delivered, good | n/a |
| `20261028-131052-8a3d` | claude | intercom-accept | extensive 3 | 2.29 | delivered, good | n/a |
| `20261028-085324-f06b` | claude | tmux-paste-retry | extensive 1 | 6.76 | delivered, good | n/a |
| `20261028-141924-50bb` | claude | tmux-paste-retry | extensive 2 | 2.21 | delivered, good | n/a |
| `20261028-142033-23f6` | claude | tmux-paste-retry | extensive 3 | 6.80 | delivered, good | n/a |
| `20261028-102528-0f4d` | codex | tmux-paste-retry | extensive 1 | 8.30 | delivered, good | n/a |
| `20261028-133025-17c4` | codex | tmux-paste-retry | extensive 2 | 8.32 | delivered, good | n/a |
| `20261028-133503-cf1f` | codex | tmux-paste-retry | extensive 3 | 8.33 | delivered, good | n/a |
| `20261028-101938-2fa8` | opencode | tmux-paste-retry | extensive 1 | 6.86 | delivered, good | n/a |
| `20261028-132929-1e19` | opencode | tmux-paste-retry | extensive 2 | 6.77 | delivered, good | n/a |
| `20261028-133537-9d7e` | opencode | tmux-paste-retry | extensive 3 | 6.78 | delivered, good | n/a |
| `20261028-065452-14bd` | pi | tmux-paste-retry | extensive 1 | 8.38 | delivered, good | n/a |
| `20261028-132856-8385` | pi | tmux-paste-retry | extensive 2 | 8.30 | delivered, good | n/a |
| `20261028-133506-33cc` | pi | tmux-paste-retry | extensive 3 | 8.30 | delivered, good | n/a |

- `s5.py` now checks ownership once before the burst and sends with the manifest-only check, which removes the
  ~0.5 s harness share; `codex-queue` (sends ≤0.8 s) and `agent-deck` (≤0.83 s) would fit a re-run.
- Shortlist change: `codex-queue` (was tied 14/17 at Codex rank 2, now 11/14 with `err 3`) left the Codex top 2 and
  is listed with the S9-only entries; the generator keeps its reps, user-config and nono rows, labelled "ran while
  shortlisted; no longer top 2". Other rank moves are below the top 2 (Codex codex-remote-steer 3 -> 2, codex-queue 2 -> 3; Claude tmux-paste-retry 9 -> 15, csd 11 -> 16,
  gc-nudge 16 -> 10; Codex tmux-paste-retry 8 -> 10; Pi tmux-paste-retry 9 -> 13; OpenCode tmux-paste-retry 8 -> 10;
  Droid agent-deck 4 -> 8, gc-nudge 9 -> 4). Re-test on the Mac Studio: S5 on `codex-queue` (REPORT §10.9).
- Candidate under S-14, not reclassified (no ruling): with receipt now an allowlist of pushed kinds, one existing
  record would change: `20261028-093642-3f78` (Codex hcom S6, `delivered`), whose after-resume token appears only in a
  `tool_result` of `hcom events` (a poll). A scan of 929 counted records with a readable transcript found no other;
  251 counted records had no transcript path in their notes and were not checked.

### Fixes (each with a regression test; safety and ownership tests mutation-checked)

- C-1/R45: `manifest.derived_codex_sockets` derives a daemon socket only from a Codex target with backend
  `codex-daemon` whose home is inside the run, and a link target only from the run's own listen socket
  `/tmp/ac/<run>.sock`; `stop_registered_services` reads a registration only from a home inside the run. Tests:
  `tests/test_branch_review_fixes.py` (user-config target with `home_dir` = fake `~/.codex` for app-server, daemon and
  none backends; a full `cleanup` that leaves the user's daemon socket and removes the run's link target).
- S-1/R46: `Outcome.receiver_exit_expected`, set by S12 on `AgentLostError`; `finish()` skips the receiver-gone check
  for it, so the record is `lost` with `agent-lost-by-restart`. A receiver dying anywhere else still pauses.
- S-2/R47: `s5.burst_verdict` (above); ownership checked once before the burst.
- S-3, S-4/R48: `userconfig.applied(disable, overlay, run_dir)` checks the `-c` pair in TUI and backend argv,
  `XDG_STATE_HOME` inside the run, `CSD_WORKER_DIR` under `/tmp/ac/<run>-csd`, the no-op `rl` shim first on `PATH`;
  `Engine.launch` calls `userconfig.verify` on the built overlay and raises `UserConfigSkip`, recorded `n/a` before
  any backend or TUI starts. Unknown integrations are `UNCLASSIFIED` (outward, no switch) unless on `REVIEWED_LOCAL`
  (Codex hook `agent-sandbox-status`; OpenCode plugins `mouthfeel.js`, `nono-sandbox.ts`, `sandbox-status.ts`) or of
  kind `agent`. The OpenCode hooklinesinker claim now says "a dir inside the run" (OpenCode's state dir is its
  isolated `<home>/state`, which the backend check requires).
- S-5: user-config cells snapshot `~/.codex`, `~/.pi/agent` and `~/.config/opencode` (with `node_modules`), write
  `runs/<id>/user-store-writes.txt` and note `user-store-writes=<n>`; re-listed after cleanup.
- S-6: `TMPDIR=<home>/tmp` for every agent (`isolation.with_private_tmp`), `TMPDIR=<state>/tmp` for zmx and zellij.
  Not live-verified: no agent was started with the new `TMPDIR`.
- S-7: `Engine.track` adopts a pid only when it descends from the harness process or the run's groups and agent pids,
  runs code from `vendor/`, or has its cwd inside the run; others are printed and not tracked. The failed Codex daemon
  start stops the pid-file pid only when it is the spec's `codex` binary.
- S-8: zmx and zellij `start` stop the session they created before raising; a failed Codex daemon start check runs
  `daemon stop` and stops the daemon; `cleanup` kills untracked `agentcomms` sessions whose panes work in the run (csd,
  agent-deck) and stops zmx/zellij sessions (N-5); iTerm2 calls cancel their coroutine on timeout and a cancelled
  start closes the tab it made; bridge CLI timeouts kill the process group (N-20).
- S-9: `scale_converse` catches per round and keeps attending the barrier; every launch and conversation future is
  collected with its own handler; `Barrier(0)` is skipped when no receiver is up; failure records carry the host;
  `scale.aggregate` leaves `error`/`env_error` out of the denominators and reports `errors` (N-17).
- S-10: the OpenCode reader tolerates only a missing optional table and a locked database; other
  `OperationalError`s raise `SchemaDriftError` (cell `error`).
- S-11: a reply timeout after the payload was written (`pi-ext`, `codex-remote-*` via `WrittenTimeout`, OpenCode HTTP
  read timeout) is accepted with "verdict from the transcript".
- S-12: note markers are constants in `agentcomms/markers.py`, used by the producers (`finish`, S9, S12, engine) and
  the readers (`cli.PAUSE_MARKERS`, `scoring`). The structured `facts` field was not added (below).
- S-13: one exception ladder, `cli.cell_failure`, for `run_one` and `s9`; scale uses `scale_status`.
- S-14: receipt is an allowlist, `engine.RECEIVED_KINDS` (user, peer, custom, hook), used by `receiver_hits`, S2, S5,
  S9 and the startup check; `NON_RECEIVER_KINDS` is gone; the `Transcript.entries` kinds comment is current.
- S-15: the launch host comes from the adapter's `host_kind` only; the dead `discover()` is gone from the Protocol and
  both implementations.
- S-16: live commands set `live=True` and `main()` refuses them when sandboxed (probe-bg, scale and s9 included); the
  single-choice `--sandbox raw` flags are gone.
- S-17: the suite passes without `vendor/` (scratch copy: 3 skipped): pinned binaries and hcom/intercom paths are
  faked where the test does not need them, the hcom containment case skips with a reason, and the user-config launch
  probes skip when the user's Codex/OpenCode auth file is absent.
- Test review 1-22: tests added as listed in `review-tests.md` (`tests/test_mutation_gaps.py`, `tests/test_manifest.py`);
  `owned_pids` now compares paths (`is_relative_to`), the socket-dir parameters are resolved at call time (so tests
  patch `manifest.SOCKET_DIR`/`CLAUDE_SOCK_DIR`), and the cleanup test now asserts that the run's `/tmp/ac/<run>-*` dir
  is removed, as production does.
- R49: `cleanup`/`send` validate the run id (`paths.valid_run_id`) and exit 2 "unknown run id" (N-11); a STOP file
  that blocks the batch before its first cell gives exit 10; "could not verify … failing closed" vs "is sandboxed".
- Nice to have fixed: N-1 (identity re-checked before SIGKILL), N-2 (non-harness tmux socket names raise), N-3
  (`owned_group` rejects pgid 0/1 and the harness's own), N-5, N-6 (`probe-bg` stops its daemon and cleans up in a
  `finally`), N-7 (in-process Claude UDS send runs the sender guard), N-8 (`backend.json` 0600), N-10 (gc-nudge refused
  under `--sandbox nono`), N-13 (Codex subagent rollouts left out of `all_transcripts`), N-14 (S6 down fate uses
  `receiver_hits`), N-15 (safety capped at 7), N-17, N-18 (first half: `s9` refuses `codex-queue-embedded`), N-20
  (process group killed), N-21 (a partial trailing `raw.jsonl` line is skipped; appends and reads locked), N-22
  (concurrency capped at 3), N-23 (pty reader joined before the fd closes), N-24 (loop creation locked, timed-out
  calls cancelled), N-25 (30 s timeouts on tmux, ps, lsof, zmx, zellij and the scale sampler), N-27 ("version re-check
  failed" is reported as such); test review 23-27. Autofix groups: dead `ScenarioId`, `Stage`, `shortlist.MARKERS`,
  `pi_session_bridge.CLI`, `intercom_dir`, `iterm_frontmost`, `"claude-bg"` in `HostKind`; doc drift in README (load
  sample interval, refusing commands), `shortlist --write` and `launch` help, the kinds comment, `adapters/README.md`.

### Mutation checks

Each mutation was applied in a scratch copy of the repo without `vendor/` (`rf-mut-copy` in the session scratchpad),
grepped to confirm it landed, and the full suite run; the repo was never mutated.

| id | mutation | result (full suite, scratch copy) |
|---|---|---|
| R45-a | home check+backend dropped (original) | caught (5 failed) |
| R45-b | home-under-run dropped | caught (1 failed) |
| R45-c | daemon-backend dropped | caught (1 failed) |
| R45-d | service home check dropped | caught (1 failed) |
| R45-e | link derived from any /tmp/ac socket | caught (1 failed); first run survived, test added or tightened, re-run caught |
| R46-a | finish ignores the expected-exit flag | caught (1 failed) |
| R46-b | s12 sets no flag | caught (1 failed) |
| T1 | env_snapshots run guard dropped | caught (1 failed) |
| T2 | spec_problem per-run CODEX_HOME check -> if False | caught (1 failed); first run survived, test added or tightened, re-run caught |
| T3 | service_pid_in_run cwd check dropped | caught (2 failed) |
| T4 | stop_bridge_daemons without identity | caught (1 failed) |
| T5a | is_owned ignores agent_pid | caught (1 failed) |
| T5b | is_owned ignores run_id | caught (1 failed) |
| T6 | credentials purged with processes left | caught (1 failed) |
| T7 | owned_pid accepts missing identity | caught (1 failed) |
| T8 | check_claude_target ignores config dir | caught (1 failed) |
| T9 | owned_claude_socket dir unchecked | caught (1 failed) |
| T10a | zmx run inherits env | caught (1 failed) |
| T10b | zellij run inherits env | caught (1 failed) |
| T11a | cleanup kill-session prefix match | caught (1 failed) |
| T11b | TmuxHost.stop prefix match | caught (1 failed) |
| T13 | safety_k over all scenarios | caught (1 failed) |
| T14a | S9 B send before receipt counts | caught (1 failed) |
| T14b | S9 B send after reply counts | caught (1 failed) |
| T14c | S9 a_sends unbounded | caught (1 failed) |
| T15a | S8 good without rendered | caught (1 failed) |
| T15b | S6 good without down | caught (1 failed) |
| T15c | S11 ignores harmful | caught (1 failed) |
| T16 | SandboxedSender outside nono | caught (1 failed) |
| T17 | gc skips GC_CITY | caught (1 failed) |
| T19a | owned_pids string prefix | caught (1 failed) |
| T19b | vendored prefix without slash | caught (1 failed) |
| T20 | live_runs ignores exclude | caught (1 failed) |
| T22a | scale converse catches only ownership | caught (1 failed); first run stalled at the 900 s barrier (killed), the test now uses a 3 s barrier and a time bound |
| T22b | scale Barrier(0) guard dropped | caught (1 failed) |
| T26 | run_dir_for accepts runs root | caught (1 failed) |
| R47-a | no burst precondition (original) | caught (2 failed) |
| R47-b | every slow burst counted as n/a | caught (2 failed) |
| R47-c | s5 ignores the verdict | caught (1 failed) |
| R48-a | verify never skips | caught (4 failed) |
| R48-b | unknown integrations local (fail open) | caught (1 failed) |
| R48-c | -c switch not required in backend argv | caught (1 failed) |
| R48-d | PATH switch accepted without the shim first | caught (1 failed); first run survived, test added or tightened, re-run caught |
| R48-e | XDG_STATE_HOME accepted anywhere | caught (1 failed) |
| R48-f | -c switch not required in TUI argv | caught (1 failed) |
| R48-g | launch skips verify | caught (1 failed); first run survived, test added or tightened, re-run caught |
| R48-h | run_one records a launch skip as harness bug | caught (1 failed) |
| R49-a | cleanup of unknown id proceeds | caught (1 failed) |
| R49-b | STOP before first cell not a pause | caught (1 failed) |
| R49-c | unverifiable worded as sandboxed | caught (1 failed) |
| S5-a | store writes not noted | caught (1 failed) |
| S5-b | store scan skips node_modules | caught (1 failed) |
| S6-a | agent TMPDIR passed through | caught (1 failed) |
| S6-b | zellij TMPDIR dropped | caught (1 failed) |
| S7-a | no provenance check | caught (1 failed) |
| S7-b | provenance accepts any cwd | caught (2 failed) |
| S8-a | zmx start leaves session | caught (1 failed) |
| S8-b | zellij start leaves session | caught (1 failed) |
| S8-c | failed daemon start not stopped | caught (1 failed) |
| S8-d | daemon stop without codex identity | caught (1 failed) |
| S8-e | untracked run sessions not killed | caught (1 failed) |
| S8-f | multiplexer sessions not stopped | caught (1 failed) |
| S8-g | iTerm2 timeout does not cancel | caught (1 failed) |
| S8-h | bridge CLI timeout kills only the child | caught (1 failed); first run survived, test added or tightened, re-run caught |
| S10 | schema drift swallowed | caught (1 failed) |
| S11-a | pi-ext silent write rejected | caught (1 failed) |
| S11-b | codex written timeout rejected | caught (1 failed) |
| S11-c | opencode read timeout rejected | caught (1 failed) |
| S11-d | written_call does not mark timeouts | caught (1 failed) |
| S14 | denylist receipt (original) | caught (1 failed) |
| S15 | host from launch_mods | caught (1 failed) |
| S16-a | main never refuses | caught (10 failed) |
| S16-b | probe-bg not live | caught (2 failed) |
| S9-a | scale aggregate counts errors in n | caught (1 failed) |
| N1 | SIGKILL without identity re-check | caught (1 failed) |
| N2 | non-harness tmux socket falls back to -L | caught (1 failed) |
| N3 | owned_group adopts pgid 1 | caught (1 failed) |
| N7 | in-process Claude send unguarded | caught (1 failed) |
| N8 | backend.json world-readable | caught (1 failed); first run survived, test added or tightened, re-run caught |
| N10 | gc-nudge allowed under nono | caught (1 failed) |
| N18 | s9 accepts codex-queue-embedded | caught (1 failed) |
| N21 | partial trailing line breaks reads | caught (1 failed) |
| N22 | no concurrency cap | caught (1 failed) |
| TR23 | empty shims dir kept | caught (1 failed) |
| TR24 | secret value unquoted | caught (1 failed) |
| TR25 | start_server skips private env | caught (1 failed) |
| TR27 | matrix runs serially | caught (4 failed) |
| N14 | S6 down fate counts any kind | caught (1 failed); first run survived, test added or tightened, re-run caught |
| N15 | safety_k uncapped | caught (1 failed); first run survived, test added or tightened, re-run caught |
| N13 | codex subagent rollouts observed | caught (1 failed); first run survived, test added or tightened, re-run caught |
| N27 | failed re-probe reported as change | caught (1 failed) |
| S12 | crash marker re-typed | caught (2 failed) |
| S7-c | provenance ignores vendored code | caught (1 failed) |
| S13 | ownership not routed to stop 7 | caught (1 failed) |

The test review's T12 (prefix `applied`) is covered by R48-a to R48-g; T18 (cleanup tests on the real `/tmp/ac`) and T21 (gitignored `vendor/`) are test-setup fixes: every run above used a copy without `vendor/` (627-711 passed, 3 skipped). 94 mutations, all caught in the final runs; 10 survived or stalled on their first run and were caught after the test was added or tightened.

### Skipped, with reasons

- S-12 (second half), structured `facts`/`pause_reason` on `ResultRecord`: a record-schema change across every
  producer, reader and the 1596 existing records; the shared constants remove the re-typing risk.
- S-13 (second half), moving orchestration into `agentcomms/batch.py`: a refactor of working code; the ladder is
  now one function.
- S-15 (second half), an adapter base class and listing the optional hooks on the Protocol: refactor of working code;
  `claims_cross_machine` stays as recorded data (the quoted claims cited in notes and REPORT §2.4).
- N-4 (`TMUX_TMPDIR` for receivers): bridges reach the harness server from inside receivers with `-L agentcomms`
  (agent-deck hooks, hcom), which a changed `TMUX_TMPDIR` would break; needs a live check.
- N-9 (`--` before the body in gc/csd send wrappers): needs confirming that both CLIs accept `--`; not checkable
  without running them.
- N-12 (API errors only after the send): needs the send time threaded into `Outcome` and changes verdict logic for
  existing behaviour; deferred.
- N-16 (S9 cell key omits agent B): changes the resume and report key for S9 records; deferred.
- N-18 (second half, `MODEL_SHOWN` for Pi/OpenCode/Droid): needs each agent's model display patterns from live panes.
- N-19 (drainer lock before connect): touches the at-most-once spool logic the review found sound; deferred to a
  change with a live Codex check.
- N-26 (scale sampler starvation), N-28 (cross-process `stop_idle_server` race): measurement-only and a narrow
  window needing a cross-process lock.
- N-29 (duplication and structure): refactor of working code.
- Test review 28 (fixed sleeps) and 29 (one real-tmux test on a harness-named socket in `/tmp/ac`): timing
  robustness only; the tmux test already cleans up its own socket.

### Deviation recorded (S-6)

Before this fix, agents and zellij wrote into the user's real per-user `TMPDIR`: the review found seven
`$TMPDIR/droid-bg-*.out` files holding the harness's `GATE-OPEN-<run_id>` and a 925 KB
`$TMPDIR/zellij-501/zellij-log/zellij.log` from `attach --create-background`. They are left in place (user state);
`vendor/REVIEW.md`'s "nothing else written outside the repo" did not hold for those runs.

### R50 (coordinator ruling): polled-only receipt reclassified
- Codex hcom S6 `20261028-093642-3f78`: `delivered` → `lost` (token only in a polled `tool_result`, outside `RECEIVED_KINDS`). Codex hcom extensive total 9/16 → 8/16; rank 5 unchanged; not in REPORT §3.

### Re-review fixes

Fixes for the review of f3460b3 (SF-1 was fixed by the coordinator: R50's `ack` back to `acked`, plus
`tests/test_results_data.py`).

- SF-2: S5 now times each whole `adapter.send` call (`Cell.timed_owned_send`); the ownership check and
  `track_spawned` fall outside, adapter work before `sent_mono` (intercom's `--list`) falls inside. The 44 R47 records
  are unchanged under the new definition: codex-queue, agent-deck, gc-nudge and csd stamp `sent_mono` first and none of
  the 44 spawned pids (all `sandbox: raw`, none a deferring sender), so their adapter time is the same under both
  definitions; intercom, intercom-accept and tmux-paste-retry (a capture before the stamp) only gain adapter time,
  which keeps them `n/a`. The harness-share calibration (0.52-0.86 s) comes from adapters that all stamp first, so it
  holds as before. Every other S5 record has a window of 1 s or less, where the verdict does not depend on the split.
  No record edited.
- SF-3: `session_message` is no longer an optional table; a database with `session_v2` but no `session_message`
  raises `SchemaDriftError`. A database before init still reads as no sessions.
- N-1: `backends.terminate` (so `stop_group`, `bridge.stop_pid`, backend and service stops) re-reads the identity
  before SIGKILL and spares a changed pid (a group whose leader already exited is still killed: a live group's pgid
  is never reused); `claude_bg.stop_pids` and `s6.kill` now use `manifest.terminate_same`. README corrected to list
  where it applies.
- N-2: provenance roots are this run's pgid members, agent pids and identity-matched tracked pids, plus the pids the
  run's own code just started (launched or restarted backend, recorder, deferred senders); the harness pid is no
  longer a root, so a sibling cell's process under `matrix` is not adopted. Vendored code must be the program (an
  executable under `vendor/`, or `node`/`bun`/`deno`/`python`/`sh`/`bash` running a `vendor/` path), not any argument.
  Residual: a sibling run's vendored daemon (an intercom broker, cwd in `vendor/`) can still be adopted after pid reuse;
  requiring a run path in its args would drop the real broker, whose args carry none (the existing test of a detached
  vendored process pins that).
- N-3: `ZmxHost.stop`/`ZellijHost.stop` raise a `HostError` when the binary, the call (incl. `TimeoutExpired`) fails or
  the session is still listed after the kill; `start()` suppresses that during its own cleanup so the original error
  stands. `cleanup` reports `note: stopping … failed: …` and leaves that state dir under `/tmp/ac`.
- N-4: `submitted` (counter) and `t_started` (timestamp) in `cmd_matrix`. Rename only, no behaviour change, no test.
- N-5: a STOP file that blocks the batch prints only its own line (still exit 10), not the API/auth pause line.
- N-6: iTerm2 `async_create_tab` runs shielded; a cancel during creation waits up to 30 s for the tab and closes it.
- N-7: `user-config-inventory` prints `unclassified: …` for unclassified integrations.
- N-8: the scale test asserts the barrier never broke (30 s timeout) instead of a wall time; the user-config skip test
  sets `HOME` to tmp.
- Skipped: none for verdict reasons; N-2's run-path requirement for vendored daemons is left out as above.

Mutation check (scratch copy without `vendor/` and `runs/`, each mutation grepped as landed, full suite, then
restored; restored copy 732 passed, 3 skipped):

| id | reverse mutation | result |
|---|---|---|
| M1 | S5 times `sent_mono` to after `owned_send` | caught (2 failed) |
| M2 | `session_message` optional again | caught (1 failed) |
| M3 | `backends.terminate` SIGKILLs without identity check | caught (1 failed) |
| M4 | old `claude_bg.stop_pids` | caught (1 failed) |
| M5 | old `s6.kill` | caught (1 failed) |
| M6 | vendored = any arg substring | caught (1 failed) |
| M7 | harness pid back in provenance roots | caught (1 failed) |
| M8 | zmx stop skips the survival check | caught (1 failed) |
| M9 | zmx stop lets `TimeoutExpired` escape | caught (2 failed) |
| M10 | zmx start lets the cleanup stop error replace its own | caught (1 failed) |
| M11 | zellij stop skips the survival check | caught (1 failed) |
| M12 | multiplexer stop failure reported as success | caught (1 failed) |
| M13 | socket-dir removal ignores the kept dirs | caught (1 failed) |
| M14 | STOP-file block also prints the API pause line | caught (1 failed) |
| M15 | iTerm2 tab created unshielded | caught (1 failed) |
| M16 | inventory hides unclassified | caught (1 failed) |
