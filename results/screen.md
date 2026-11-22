# Screen stage

Task 8 screen: S1 (idle wake), S4 (10 KB payload), S7 (human draft in the input box), S8 (attached human client) at
1 rep for every mechanism x supported agent, `stage=screen`, `--sandbox raw`, unsandboxed coordinator, 2026-10-27
19:50 to 2026-10-28 02:41; Codex, OpenCode and Droid re-screened on 2026-10-28 on Codex 0.165.0, OpenCode 2.2.0 and
Droid 0.251.0 (Re-screen, below). The version list that follows is the first screen's. Claude 2.1.312 (`haiku`; the user's install auto-updated from 2.1.311 at 21:28, see
Decisions), Codex 0.164.0 (`gpt-6-luna` low, daemon 0.164.0), Pi 1.4.0 on node 24.22.0 (`deepseek-v4.1-flash`),
OpenCode 2.1.4 (`opencode-go/gpt-6-luna`), Droid 0.249.0 (`gpt-6-luna` low), macOS 27.2; bridges hcom 0.7.31,
agent-intercom (Pi 0fffed27, Claude 7de76e5d, Codex ea1c5b53), csd 4.0.1, agent-deck 1.16.34, gc 1.4.0.

Survivor = a good S1 outcome (delivered and intact, `agentcomms/scoring.py`) and no harmful outcome. No screen
scenario can be harmful (harm is judged only in S3/S11), so survivorship here is S1. Good outcomes are in **bold**.
Verdicts are the latest non-`env_error` record per cell in `results/raw.jsonl` (run ids there; `host`, `backend`
columns). S4 `not intact` = delivered with a body mismatch (diff in `runs/<id>/body-diff-<agent>.txt`); S7 shows
`draft_fate` (`preserved` is the good outcome); S8 shows `rendered=` (`yes` is good, R25).

## Counts

- 71 mechanism x agent pairs screened, 284 cells, every one with a verdict; 0 `error` records left.
- 292 screen records in `raw.jsonl`: 248 delivered, 25 lost, 8 held, 3 rejected, 8 `env_error`. The 8 `env_error`
  records are machine-sleep hits (`sleep-or-network`, wall clock ran ahead of the monotonic clock); each of those
  cells was re-run and has a verdict.
- 21 records superseded (R11, `runs/<id>/superseded-record.jsonl`): 15 harness-bug `error` records, 1 harness-bug
  `env_error`, 3 Claude bridge S4 records with a wrong body hash (verdict unchanged), 2 Claude 2.1.311 verdicts
  (version split). See Harness fixes and Decisions.
- n/a, not run: 12 pairs (48 cells), below.

## Results

| agent | mechanism | host | backend | S1 | S4 | S7 | S8 | survivor |
|---|---|---|---|---|---|---|---|---|
| claude | agent-deck | tmux | none | **delivered** | not intact | lost, draft preserved | **rendered=yes** | yes |
| claude | claude-channel | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| claude | claude-uds | tmux | none | held | held | held, draft lost | held (stuck) | no |
| claude | claude-uds-accept | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| claude | claude-uds-child | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| claude | csd | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | gc-nudge | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | hcom | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| claude | intercom | tmux | none | held | held | held, draft lost | held (stuck) | no |
| claude | intercom-accept | tmux | none | **delivered** | **intact** | **preserved** | rendered=no | yes |
| claude | tmux-buffer | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | tmux-keys | tmux | none | **delivered** | lost (stuck) | merged | **rendered=yes** | yes |
| claude | tmux-paste | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | tmux-paste-retry | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | zellij-paste | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | zellij-write | zellij | none | **delivered** | lost (stuck) | merged | **rendered=yes** | yes |
| claude | zmx-paste | zmx | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| claude | zmx-send | zmx | none | **delivered** | lost (stuck) | merged | **rendered=yes** | yes |
| codex | agent-deck | tmux | none | lost | lost | lost, draft preserved | **rendered=yes** | no |
| codex | agent-deck-composer-fallback | tmux | none | lost | lost | lost, draft preserved | **rendered=yes** | no |
| codex | codex-queue | tmux | codex-daemon | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | codex-queue-embedded | tmux | codex-daemon | rejected | rejected | rejected, draft preserved | **rendered=yes** | no |
| codex | codex-remote-start | tmux | codex-app-server | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| codex | codex-remote-steer | tmux | codex-app-server | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| codex | gc-nudge | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | hcom | tmux | none | **delivered** | not intact | lost, draft preserved | **rendered=yes** | yes |
| codex | intercom | tmux | codex-app-server | **delivered** | **intact** | **preserved** | rendered=no | yes |
| codex | tmux-buffer | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | tmux-keys | tmux | none | lost (stuck) | lost | lost, draft merged | lost (stuck) | no |
| codex | tmux-paste | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | tmux-paste-retry | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | zellij-paste | zellij | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | zellij-write | zellij | none | lost (stuck) | lost | lost, draft merged | lost (stuck) | no |
| codex | zmx-paste | zmx | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| codex | zmx-send | zmx | none | lost (stuck) | lost | lost, draft merged | lost (stuck) | no |
| pi | hcom | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| pi | intercom | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| pi | pi-claude-link | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| pi | pi-ext | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| pi | pi-session-bridge | tmux | none | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| pi | tmux-buffer | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | tmux-keys | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | tmux-paste | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | tmux-paste-retry | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | zellij-paste | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | zellij-write | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | zmx-paste | zmx | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| pi | zmx-send | zmx | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | hcom | tmux | none | **delivered** | **intact** | submitted | **rendered=yes** | yes |
| opencode | opencode-server-queue | tmux | opencode-server | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| opencode | opencode-server-steer | tmux | opencode-server | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| opencode | opencode-server-synthetic | tmux | opencode-server | **delivered** | **intact** | **preserved** | rendered=reply-only | yes |
| opencode | opencode-service-steer | tmux | opencode-service | **delivered** | **intact** | **preserved** | **rendered=yes** | yes |
| opencode | tmux-buffer | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | tmux-keys | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | tmux-paste | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | tmux-paste-retry | tmux | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | zellij-paste | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | zellij-write | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | zmx-paste | zmx | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| opencode | zmx-send | zmx | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| droid | agent-deck | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | gc-nudge | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | tmux-buffer | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | tmux-keys | tmux | none | **delivered** | lost | merged | **rendered=yes** | yes |
| droid | tmux-paste | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | tmux-paste-retry | tmux | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | zellij-paste | zellij | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | zellij-write | zellij | none | **delivered** | not intact | merged | **rendered=yes** | yes |
| droid | zmx-paste | zmx | none | **delivered** | **intact** | merged | **rendered=yes** | yes |
| droid | zmx-send | zmx | none | **delivered** | lost | merged | **rendered=yes** | yes |

## Re-screen on pinned versions (R35, 2026-10-28)

The user's Codex (0.164.0 -> 0.165.0), Droid (0.249.0 -> 0.251.0) and OpenCode (2.1.4 -> 2.2.0) installs updated at
04:22-04:25, during the extensive stage. Their old-version screen verdicts were superseded (R11, R35; list in
`results/notes.md`) and all 40 of their pairs re-screened, 160 cells, 04:30 to 07:11, from 05:10 on with the pinned
copies in `vendor/agents/` (byte-identical to the installs that updated; `vendor/REVIEW.md`). The table above shows the
re-screen verdicts for these three agents: 136 delivered, 21 lost, 3 rejected, 0 `error`. Claude 2.1.312 and Pi 1.4.0
did not change, so their screen records stand.

Survivors are unchanged (Codex 11, OpenCode 13, Droid 10). Verdict changes against the old versions:
- Codex codex-remote-start and codex-remote-steer S7: `merged` on 0.164.0, the human's draft `preserved` on 0.165.0
  (the pushed turn ran and the draft stayed in the composer; `runs/20261028-054849-2fe5/pane-codex-final.txt`).
- Codex intercom S8: `lost` -> `delivered`, `rendered=no` (R33 label; the push still runs in `coi`'s hidden thread).
- Droid zellij-write S4: `lost` -> delivered but not intact.
- Everything else matched the old verdict. Droid 0.251.0 starts in `Auto (Med)` unless `autonomyLevel` is set, which
  changes S3 (prompting mode), not the screen scenarios; isolated prompting settings now set `autonomyLevel: off`.

## Survivors per agent

- Claude (16 of 18): agent-deck, claude-channel, claude-uds-accept, claude-uds-child, csd, gc-nudge, hcom,
  intercom-accept, tmux-buffer, tmux-keys, tmux-paste, tmux-paste-retry, zellij-paste, zellij-write, zmx-paste,
  zmx-send. Not: claude-uds, intercom (held for approval).
- Codex (11 of 17): codex-queue, codex-remote-start, codex-remote-steer, gc-nudge, hcom, intercom, tmux-buffer,
  tmux-paste, tmux-paste-retry, zellij-paste, zmx-paste. Not: tmux-keys, zmx-send, zellij-write (typed input stuck in
  the composer), agent-deck, agent-deck-composer-fallback (fresh Codex never idle, R31), codex-queue-embedded (no
  thread before a typed turn).
- Pi (13 of 13): hcom, intercom, pi-claude-link, pi-ext, pi-session-bridge, tmux-buffer, tmux-keys, tmux-paste,
  tmux-paste-retry, zellij-paste, zellij-write, zmx-paste, zmx-send.
- OpenCode (13 of 13): hcom, opencode-server-queue, opencode-server-steer, opencode-server-synthetic,
  opencode-service-steer, tmux-buffer, tmux-keys, tmux-paste, tmux-paste-retry, zellij-paste, zellij-write,
  zmx-paste, zmx-send.
- Droid (10 of 10): agent-deck, gc-nudge, tmux-buffer, tmux-keys, tmux-paste, tmux-paste-retry, zellij-paste,
  zellij-write, zmx-paste, zmx-send.

Mechanisms that were good in all four screen scenarios: Claude claude-channel, claude-uds-accept, claude-uds-child,
hcom; Codex codex-remote-start, codex-remote-steer (since 0.165.0, below); Pi hcom, intercom, pi-claude-link, pi-ext,
pi-session-bridge; OpenCode opencode-server-queue, opencode-server-steer, opencode-service-steer. No Droid mechanism
preserves an S7 draft; on Codex only codex-remote-start/-steer and intercom (whose S8 push is hidden, below) do.

## n/a (not run)

- iTerm2, all agents (`iterm2-text`, `iterm2-paste` x 5 agents = 10 pairs, 40 cells): the Decided scope bullet makes
  iTerm2 a lower-priority host covered by hostcheck and the Task 6 spot cells; the user types in iTerm2 and its
  persistent holder window was left alone. Its hostcheck rows and spot cells are in `results/hostcheck.md` and
  `results/notes.md` (Task 6).
- `intercom-accept` on Pi and Codex (2 pairs, 8 cells): n/a by equivalence. Only the Claude launch differs from
  `intercom` (it adds `crossSessionInbound: accept` to the Claude settings); the Pi and Codex launches and the sender
  are identical to `intercom`, which was screened on both (Task 7 notes).

Typed adapters on zmx and zellij (`zmx-send`, `zellij-write`) were screened, not marked n/a by equivalence with
`tmux-keys`: the hostcheck bytes match, but zellij-write's 10 KB read pattern differs (10 vs 11 reads), the spot cells
covered only Claude and Codex, and `tmux-keys` had no S4/S7/S8 records to compare with. The screen shows them behaving
like `tmux-keys` on every agent. The paste adapters on zmx and zellij were screened as well.

## Notable failure modes

- Typed input (tmux-keys, zmx-send, zellij-write) on Codex: the Enter that follows a fast keystroke burst does not
  submit; the text stays in the composer (`stuck-in-composer`) in S1, S4, S7 and S8. Same as the pilot.
- Typed 10 KB (S4): Claude turns it into ten collapsed pastes with the Enter stuck (lost); Droid loses it
  (tmux-keys, zmx-send; zellij-write delivers it with a body mismatch on 0.251.0); Pi and
  OpenCode deliver it with every tab removed (OpenCode binds Tab, Pi converts each tab to four spaces).
- Pasted 10 KB (S4): Claude and Pi turn each tab into four spaces; OpenCode appends one trailing space after the last
  line; Codex and Droid keep it byte-identical. Through agent-deck, csd and gc-nudge Claude shows the same tab
  conversion; Codex hcom receives the message truncated ("Warning: truncated output
  (original token count: 2616)").
- Draft present (S7): every terminal adapter on every agent merges the push into the human's draft (`merged`), as do
  Codex codex-queue (and codex-remote-* on 0.164.0), gc-nudge and agent-deck on Droid. Native/injected routes keep the
  draft: Claude channel and peer messages, Claude hcom and intercom-accept, every Pi native and bridge route, OpenCode
  server and service routes, Codex intercom and (on 0.165.0) codex-remote-start/-steer. OpenCode hcom submits the draft as its own message (`submitted`). agent-deck
  (Claude, Codex) and Codex hcom leave the draft alone and never deliver the push within 180 s.
- Held messages: Claude `claude-uds` (default inbound) and `intercom` park every push for a human Deny/Deliver; in S7
  the Deny/Deliver picker replaces the input box, so the draft is no longer visible (`lost`).
- S8 not rendered while delivered: OpenCode `/synthetic` shows the reply but never the pushed prompt (`reply-only`,
  R25); Claude `intercom-accept` shows the push only as a collapsed `[Intercom message from agentcomms …] (ctrl+o to
  expand)` line and Claude answers with `SendMessage` back over intercom instead of text (`rendered=no`); Codex
  `intercom` runs pushes in `coi`'s separate bridge thread (`thread_source: cli`), not the TUI thread the human typed
  in (`thread_source: user`), and the attached TUI shows only an OSC 9 desktop notification ("Intercom turn from
  agentcomms completed: ACK …"). The record says `lost` because the reader follows the human's thread; the bridge
  thread did receive and answer (see Decisions).
- agent-deck on Codex: S1/S4/S7 lost on a fresh TUI (R31: no completed turn, so agent-deck never sees it idle); S8,
  which starts with a human turn, delivered and rendered.
- `codex-queue-embedded`: `rejected` (sender found no thread on the daemon) until a typed turn exists; S8 delivered.
- zmx relays OpenCode's screen to an attached client in bursts about 30 s apart, and `zmx history` calls take several
  seconds while OpenCode is redrawing (probe `20261027-232551-3e1e`: attach stream 55 KB -> 88 KB -> 122 KB at about
  t=6 s and t=40 s). Claude and Pi on zmx render promptly. With S8's 45 s render wait, OpenCode zmx S8 rendered.

## Harness fixes (each with a regression test)

1. S8 attached only tmux clients, so S8 on zmx/zellij would have crashed. Hosts `zmx` and `zellij` gained
   `attach_client`/`detach_client`; S8 uses the target's host. Tests: `test_zmx_and_zellij_attach_a_client_to_the_
   existing_session_in_the_host_env`, `test_s8_attaches_through_the_targets_own_host`.
2. The matrix scheduler serialized only per agent; cells of one bridge (shared broker, tmux server or state) could
   overlap across agents. Adapters now declare `shared_state` (hcom, intercom/-accept, csd, agent-deck/-composer-
   fallback, gc) and the scheduler locks it. Tests: `test_concurrent_matrix_never_runs_two_cells_of_one_bridge_state_
   at_once`, `test_cell_locks_name_the_agent_and_any_shared_bridge_state`.
3. `matrix` crossed every agent with every adapter and recorded `n/a` for unsupported pairs; it now plans only
   supported pairs. Test: `test_matrix_plans_only_agent_adapter_pairs_the_adapter_supports`.
4. `progress.md` was fully regenerated, so a progress note could not survive; a hand-written `## Notes` section is now
   kept. Test: `test_progress_rewrite_keeps_the_hand_written_notes_section`.
5. `--time-budget` defaulted to 110 min, not the 360 min of R20. Test: `test_matrix_time_budget_defaults_to_six_hours`.
6. Pi draws its footer without `(openrouter)` for a moment on every start, which the auth check took for the no-key
   screen (Pi hcom S1 paused the batch). An auth screen now has to persist 5 s. Tests:
   `test_a_startup_frame_without_the_provider_is_not_an_auth_screen`,
   `test_an_auth_screen_that_stays_up_pauses_with_auth_required`.
7. The OpenCode composer parser matched only an unindented `┃` and started at the last `┃` line (the `Build auto`
   footer), so S7 never saw the draft (13 `error` records) and OpenCode `stuck-in-composer` notes could never fire.
   It now takes the whole indented input block. Test: `test_opencode_composer_is_the_whole_indented_input_block`
   (real home-screen and session panes).
8. S8 checked the attached client for the human turn once; zmx relays OpenCode late (above), giving 2 `error`
   records. The human-turn render is now polled like the pushed reply, and the render wait is 45 s (was 10 s; fast
   hosts return at once). Test: `test_s8_waits_for_a_human_turn_that_a_slow_host_relays_late`.
9. csd and agent-deck kept Claude's `<pasted_content id=…>` reference around a 10 KB message (their `unwrap` was the
   identity) and gc-nudge stripped only its reminder frame, so the Claude S4 body hashes and diffs were wrong (the
   verdict, not intact because of the tab conversion, was unchanged). All three now strip the paste reference
   (outermost first for gc). Test: `test_bridges_that_paste_into_claude_unwrap_its_paste_reference`. The three
   records were superseded and re-run (`20261028-033333-4517`, `-033344-4c32`, `-033403-e3a8`): only the tab lines
   differ now.

## Decisions (for rulings)

- D1: Claude auto-updated 2.1.311 -> 2.1.312 at 21:28 mid-batch; the version guard stopped the batch (exit 3) as
  designed. The two Claude verdicts recorded on 2.1.311 (`tmux-keys` S1, `zmx-paste` S8) were superseded and re-run on
  2.1.312 so the Claude screen is one version (both again delivered); the two 2.1.311 sleep `env_error` records stay.
- D2: Typed adapters on zmx/zellij were screened rather than marked n/a by equivalence (evidence above).
- D3: `intercom-accept` screened for Claude only; Pi and Codex n/a by equivalence (Task 7 note).
- D4: `codex-queue-embedded` (a Task 4 probe variant) was screened because it declares Codex; it is not a survivor.
- D5: Codex `intercom` S8 keeps `lost` for the human's thread; the push was received and answered in `coi`'s hidden
  bridge thread. Scoring is unaffected (S8 is not good either way); the label is a question for a ruling.
- D6: Machine sleep: the laptop idle-slept on battery at 19:53 and later slept again; the harness's sleep detector
  turned affected cells into `env_error` and they were re-run. Later batches ran under `caffeinate -i` (an idle-sleep
  assertion for the matrix process only; no setting changed); one `caffeinate -u -t 2` user-activity assertion was
  tried to get a full wake and did not.
- D7: Bridge-guard stop (exit 5) during the last re-run, the gc-nudge S4 cell `20261028-033403-e3a8` (03:34:03 to
  03:35). The guard saw `~/.gc/scripts/gc-beads-bd.sh` (with `~/.gc/scripts`) and
  `~/.pi/agent/intercom/outbox/82021a57….json` removed; both directories have the mtime 03:34:12. These are the two
  stray Task 7 files left for the user's decision. Nothing in the harness references either path, a gc cell has no
  route into the Pi intercom dir, and both disappeared in the same second, which was the coordinator
  removing both at 03:34:12 after the user approved it ("Sure, delete them"). The record (delivered, not intact by tabs only) was kept. Per the brief,
  no further cells were run after this stop. `~/.gc/cities.toml`, `supervisor.log`, `events.jsonl` and the user's
  supervisor (pid 1844, up since 2026-10-27 00:46) are unchanged; `runs/.version-gc` is still in place.
