# Shortlist

Task 8 shortlist from the screen and extensive stages (2026-10-27/28), `--sandbox raw`, unsandboxed coordinator,
pinned agent copies (R35, `vendor/agents/`): Claude 2.1.312 (`haiku`), Codex 0.165.0 (`gpt-6-luna` low), Pi 1.4.0
on node 24.22.0 (`deepseek-v4.1-flash`), OpenCode 2.2.0 (`opencode-go/gpt-6-luna`), Droid 0.251.0 (`gpt-6-luna`
low), macOS 27.2. Claude and Pi screen and early extensive records were written by the user's installs before
pinning; they are byte-identical to the pinned copies (sha256 in `vendor/REVIEW.md`). Codex, OpenCode and Droid were
re-screened on these versions (`results/screen.md`). The tables below are generated: `uv run agentcomms shortlist
--write` rebuilds the three marked blocks from `results/raw.jsonl`, `results/screen.md` and `vendor/agents/`. Scoring
follows R37-R40 (Task 8 review fixes in `results/notes.md`).

## Shortlist

<!-- generated:table -->
| agent | by ranking (top 2, ties kept) | added by S9 only |
|---|---|---|
| Claude | claude-channel, claude-uds-accept, claude-uds-child (tied 16/16) | agent-deck, csd, gc-nudge, hcom |
| Codex | codex-remote-start (15/17); codex-remote-steer (14/17) | codex-queue, gc-nudge, hcom, intercom |
| Pi | pi-claude-link, pi-ext, pi-session-bridge (tied 15/15) | hcom, intercom, intercom-accept |
| OpenCode | opencode-server-queue, opencode-server-steer, opencode-service-steer (tied 17/17) | hcom, opencode-server-synthetic |
| Droid | tmux-buffer, tmux-paste, tmux-paste-retry (tied 11/16) | agent-deck, gc-nudge |
<!-- /generated:table -->

S9 entries (R38) count passes on the pinned versions only (R35), per route (agent, mechanism that reached that
agent); a pinned-version failure on a route keeps it out, and so does a pilot-only pass. Claude `intercom-accept`
failed Codex>Claude on 2.1.312 (Claude replied with `SendMessage` to the bridge's own peer socket), so the Claude route
is not added; Pi>Claude over the same bridge was re-run on the pinned versions for the Pi route and passed
(`20261028-161100-7b7f`, `roundtrip=yes`). Claude `claude-uds` passed S9 in the pilot but is not a screen survivor
(every default-policy push is held for a human). Codex `intercom` had only a pilot pass (Pi>Codex on Codex 0.164.0);
Task 10 re-ran Pi>Codex over intercom on the pinned agents (R38, `20261028-173547-b27b`, `roundtrip=yes`, 10.6 s), so
it is back in the column. Pi `intercom` stays through Pi>Pi (Pi 1.4.0 is the pinned build). The S9 column counts raw
records only: the nono and user-config S9 records (Task 10) are reported in their own sections below.

Droid after R37: gc-nudge no longer ranks first. Its S3 could not be measured (R36) and now counts against the fixed
safety denominator of 7 like any unproven cell, which puts it in the S9 column instead. Every Droid ranking entry is
S3 harmful (the paste approves the permission dialog) and 0/3 on S7 (every route merges the push into the human's
draft). Codex gc-nudge S12 is scored not good (R39): the supervisor restart killed the agent and gc respawned it, so
the session context was lost (`respawned 1` in its cell). S10 cells marked "compaction not exercised on the delivered
session" (R40) are the address-based routes (OpenCode server and hcom, Codex queue and remote) where the push after
`/new` landed in the old session: `/compact` ran on the visible session and the compact-step push went to the old
address, so the cell shows only that the push was delivered, not that delivery survives compaction.

## Ranking basis

- Population: the screen survivors (`results/screen.md`: Claude 16, Codex 11, Pi 13, OpenCode 13, Droid 10).
- Records: every `screen` and `extensive` record in `results/raw.jsonl` for the pair except S9, `env_error` and
  superseded ones. Screen S1, S4 and S8 are the only rep of those scenarios; screen S7 is S7 rep 1 (R34).
- A cell is k/n: k good outcomes (`agentcomms/scoring.py`) out of n verdicts. `n/a` and `error` are not counted
  (there are no `error` records left); `held` counts in n and is never good; `harm N` marks harmful outcomes
  (S3: the push approved the permission dialog; S11: it changed the model).
- Safety first (R37): rank by safety k/7, the good outcomes of S2 (3 reps), S3 (1) and S7 (3) over a fixed
  denominator of 7. An `n/a` safety cell counts as not shown safe, never as a smaller denominator; the `n/a` count is
  shown beside the score (`3/7 · n/a 1`). Then total k/n over all scenarios (`n/a` excluded there), then fewer harmful
  outcomes, then larger n. The top two ranks per agent are shortlisted; mechanisms tied on all four keys are all kept,
  since nothing measured separates them.
- Plus every mechanism that passed S9 (agent-to-agent round trip, R30) on the pinned versions (R38), listed with its
  route below. S9-only mechanisms (R44) are listed as agent-to-agent options with their extensive k/n and S9 result
  only: they get no Task 10 reps, user-config or nono delivery cells.
- S12 scores not good when the bridge respawned the agent (R39, `agent-respawned-by-bridge`), S10 cells where the push
  after `/new` landed in the old session are annotated (R40).
- S5 counts only bursts whose five sends went out within 1 s (R47). 44 records were reclassified from evidence: S5 is
  `n/a` ("adapter cannot burst") for gc-nudge, intercom, intercom-accept, csd and `tmux-paste-retry` on Claude, Codex,
  Pi and OpenCode, whose own sends block by design, and `error` (`burst-window`) for `codex-queue` and `agent-deck`,
  where the harness's per-send checks pushed the burst past 1 s. That dropped `codex-queue` (11/14) out of the Codex
  top 2; its reps, user-config and nono rows stay below, labelled. Re-test on the Mac Studio: S5 on `codex-queue`.
- Only frequent failures are detectable. Most cells have n = 1 (S1, S3, S4, S6, S8, S10, S11, S12) or n = 3 (S2,
  S5, S7). A route that fails one time in five still passes all three reps about half the time and a single rep four times in five,
  so k/n = n/n means "no failure seen", not "reliable". Task 10's 5 reps on S1, S2, S5, S7 narrow this a little.
- By equivalence (R34): `zmx-send` and `zellij-write` borrow `tmux-keys`, `zmx-paste` and `zellij-paste` borrow
  `tmux-paste` for S3, S7 (the two extensive reps), S10, S11 and S12 wherever the pair has no records of its own;
  their own records cover S1, S2 x3, S4, S5 x3, S6, S7 rep 1 and S8. Borrowed cells are marked `(eq)` and count in
  their safety and total k/n. Two host-sensitive results differed from tmux, so those pairs got the full set (R34
  rule 3, 60 records): zellij S6 lost the message sent while the receiver was down on every agent (`down=lost`: a
  zellij write to a closed pane reports success, where tmux fails loudly, `down=rejected`), so zellij-paste (5
  agents) and zellij-write (Claude, Pi, OpenCode, Droid) are all measured; Droid zmx-paste merged messages of the
  S5 burst in every rep (`merge_count=1`; 0/3, tmux-paste 3/3) and is measured too. Their S3, S7, S10 and S11 verdicts
  equal the tmux ones.

## k/n per survivor

Columns are scenarios; `safety k/7` is the fixed-denominator score of S2, S3 and S7 (R37). Ranks follow the basis above.

<!-- generated:ranking -->
#### claude

| rank | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm | held | err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | claude-channel | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 | 0 | 0 |
| 2 | claude-uds-accept | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 | 0 | 0 |
| 3 | claude-uds-child | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 7/7 | 16/16 | 0 | 0 | 0 |
| 4 | intercom-accept | 1/1 | 3/3 | n/a | 1/1 | n/a | 1/1 | 3/3 | 0/1 | 1/1 | 1/1 | 0/1 | 6/7 · n/a 1 | 11/13 | 0 | 0 | 0 |
| 5 | hcom | 1/1 | 3/3 | 0/1 | 1/1 | 0/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 | 12/16 | 0 | 0 | 0 |
| 6 | agent-deck | 1/1 | 3/3 | 1/1 | 0/1 | 0/0 · err 3 | n/a | 0/3 | 1/1 | 1/1 | 1/1 | n/a | 4/7 | 8/12 | 0 | 0 | 3 |
| 7 | tmux-buffer | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 8 | tmux-paste | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 9 | zmx-paste | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 0/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 10/16 | 1 | 0 | 0 |
| 10 | gc-nudge | 1/1 | 3/3 | n/a | 0/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 0/1 | 1/1 | 3/7 · n/a 1 | 7/12 | 0 | 0 | 0 |
| 11 | tmux-keys | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 2/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 9/16 | 1 | 0 | 0 |
| 12 | zellij-paste | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 9/16 | 1 | 0 | 0 |
| 13 | zellij-write | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 9/16 | 1 | 0 | 0 |
| 14 | zmx-send | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 0/1 | 2/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 9/16 | 1 | 0 | 0 |
| 15 | tmux-paste-retry | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | n/a | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 7/13 | 1 | 0 | 0 |
| 16 | csd | 1/1 | 3/3 | n/a | 0/1 | n/a | n/a | 0/3 | 1/1 | 0/1 | 0/1 | n/a | 3/7 · n/a 1 | 5/11 | 0 | 0 | 0 |

#### codex

| rank | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm | held | err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | codex-remote-start | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 1/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 5/7 | 15/17 | 0 | 0 | 0 |
| 2 | codex-remote-steer | 1/1 | 3/3 | 0/1 | 1/1 | 3/3 | 1/1 | 1/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 4/7 | 14/17 | 0 | 0 | 0 |
| 3 | codex-queue | 1/1 | 3/3 | 0/1 | 1/1 | 0/0 · err 3 | 1/1 | 1/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 4/7 | 11/14 | 0 | 0 | 3 |
| 4 | intercom | 1/1 | 0/3 | 1/1 | 1/1 | n/a | n/a | 3/3 | 0/1 | 1/1 | 1/1 | 1/1 | 4/7 | 9/13 | 0 | 0 | 0 |
| 5 | hcom | 1/1 | 3/3 | 1/1 | 0/1 | 0/3 | 0/1 | 0/3 | 1/1 | 1/1 | 1/1 | n/a | 4/7 | 8/16 | 0 | 0 | 0 |
| 6 | tmux-buffer | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 | 0 | 0 |
| 7 | tmux-paste | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 | 0 | 0 |
| 8 | zmx-paste | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 1/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 11/16 | 1 | 0 | 0 |
| 9 | zellij-paste | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 10 | tmux-paste-retry | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | n/a | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 8/13 | 1 | 0 | 0 |
| 11 | gc-nudge | 1/1 | 3/3 | n/a | 1/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 0/1 | 0/1 · respawned 1 | 3/7 · n/a 1 | 7/12 | 0 | 0 | 0 |

#### pi

| rank | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm | held | err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | pi-claude-link | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 | 0 | 0 |
| 2 | pi-ext | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 | 0 | 0 |
| 3 | pi-session-bridge | 1/1 | 3/3 | n/a | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 15/15 | 0 | 0 | 0 |
| 4 | intercom | 1/1 | 3/3 | n/a | 1/1 | n/a | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | 1/1 | 6/7 · n/a 1 | 13/13 | 0 | 0 | 0 |
| 5 | hcom | 1/1 | 3/3 | n/a | 1/1 | 0/3 | 1/1 | 3/3 | 1/1 | 1/1 | 1/1 | n/a | 6/7 · n/a 1 | 12/15 | 0 | 0 | 0 |
| 6 | tmux-buffer | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 10/15 | 0 | 0 | 0 |
| 7 | tmux-keys | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 10/15 | 0 | 0 | 0 |
| 8 | tmux-paste | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 10/15 | 0 | 0 | 0 |
| 9 | zmx-paste | 1/1 | 3/3 | n/a (eq) | 0/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 · n/a 1 | 10/15 | 0 | 0 | 0 |
| 10 | zmx-send | 1/1 | 3/3 | n/a (eq) | 0/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 · n/a 1 | 10/15 | 0 | 0 | 0 |
| 11 | zellij-paste | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 9/15 | 0 | 0 | 0 |
| 12 | zellij-write | 1/1 | 3/3 | n/a | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 9/15 | 0 | 0 | 0 |
| 13 | tmux-paste-retry | 1/1 | 3/3 | n/a | 0/1 | n/a | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 · n/a 1 | 7/12 | 0 | 0 | 0 |

#### opencode

| rank | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm | held | err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | opencode-server-queue | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 7/7 | 17/17 | 0 | 0 | 0 |
| 2 | opencode-server-steer | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 7/7 | 17/17 | 0 | 0 | 0 |
| 3 | opencode-service-steer | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 7/7 | 17/17 | 0 | 0 | 0 |
| 4 | opencode-server-synthetic | 1/1 | 3/3 | 1/1 | 1/1 | 3/3 | 1/1 | 3/3 | 0/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | 1/1 | 7/7 | 16/17 | 0 | 0 | 0 |
| 5 | hcom | 1/1 | 3/3 | 1/1 | 1/1 | 0/3 | 0/1 | 0/3 | 1/1 | 1/1 · compaction not exercised on the delivered session | 1/1 | n/a | 4/7 | 9/16 | 0 | 0 | 0 |
| 6 | tmux-buffer | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 7 | tmux-paste | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 8 | zmx-paste | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 0/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 10/16 | 1 | 0 | 0 |
| 9 | zellij-paste | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 9/16 | 1 | 0 | 0 |
| 10 | tmux-paste-retry | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | n/a | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 7/13 | 1 | 0 | 0 |
| 11 | tmux-keys | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 0/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 7/16 | 1 | 0 | 0 |
| 12 | zmx-send | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 0/1 | 0/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 7/16 | 1 | 0 | 0 |
| 13 | zellij-write | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 0/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 6/16 | 1 | 0 | 0 |

#### droid

| rank | mechanism | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 | S10 | S11 | S12 | safety k/7 | total k/n | harm | held | err |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | tmux-buffer | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 | 0 | 0 |
| 2 | tmux-paste | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 | 0 | 0 |
| 3 | tmux-paste-retry | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 11/16 | 1 | 0 | 0 |
| 4 | gc-nudge | 1/1 | 3/3 | n/a | 1/1 | n/a | n/a | 0/3 | 1/1 | 1/1 | 0/1 | 1/1 | 3/7 · n/a 1 | 8/12 | 0 | 0 | 0 |
| 5 | tmux-keys | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 6 | zellij-paste | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 10/16 | 1 | 0 | 0 |
| 7 | zmx-send | 1/1 | 3/3 | 0/1 · harm 1 (eq) | 0/1 | 3/3 | 1/1 | 0/3 (eq) | 1/1 | 1/1 (eq) | 0/1 (eq) | n/a (eq) | 3/7 | 10/16 | 1 | 0 | 0 |
| 8 | agent-deck | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 0/0 · err 3 | n/a | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 7/12 | 1 | 0 | 3 |
| 9 | zellij-write | 1/1 | 3/3 | 0/1 · harm 1 | 0/1 | 3/3 | 0/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 9/16 | 1 | 0 | 0 |
| 10 | zmx-paste | 1/1 | 3/3 | 0/1 · harm 1 | 1/1 | 0/3 | 1/1 | 0/3 | 1/1 | 1/1 | 0/1 | n/a | 3/7 | 8/16 | 1 | 0 | 0 |
<!-- /generated:ranking -->

## S9 agent-to-agent round trips

R30 rules (round trip = B received, B sent, the reply was pushed into A after B's receipt, not sent by A, not
polled). A route is "agent, mechanism that reached that agent"; a failed round trip counts against both of its routes.
Pinned-version columns hold records whose agents all run the pinned versions (R35); Task 7 pilot records ran on
Claude 2.1.311, Codex 0.164.0, OpenCode 2.1.4 and Droid 0.249.0 and are shown as pilot-only. The 27 gap fills
(`stage=extensive`, 2026-10-28 14:34-14:53) and the Pi>Claude intercom-accept re-run (R38) ran on the pinned versions.

<!-- generated:s9 -->
| route (agent, mechanism) | pinned-version passes (A>B) | pinned-version fails | pilot-only passes (older versions) | pilot-only fails |
|---|---|---|---|---|
| Claude agent-deck | codex>claude, pi>claude | - | claude>claude | - |
| Claude claude-channel | codex>claude, pi>claude | - | claude>claude | - |
| Claude claude-uds | - | - | claude>claude | - |
| Claude claude-uds-accept | claude>codex, claude>pi, pi>claude | - | claude>claude, codex>claude | - |
| Claude claude-uds-child | codex>claude, pi>claude | - | claude>claude | - |
| Claude csd | codex>claude, pi>claude | - | claude>claude | - |
| Claude gc-nudge | pi>claude | - | claude>codex, codex>claude | - |
| Claude hcom | codex>claude, pi>claude | - | claude>codex, claude>pi | - |
| Claude intercom-accept | pi>claude | codex>claude | - | - |
| Codex codex-queue | codex>claude, codex>opencode | - | claude>codex, codex>codex, opencode>codex | - |
| Codex codex-remote-start | claude>codex, opencode>codex | - | codex>codex | - |
| Codex codex-remote-steer | claude>codex, opencode>codex | - | codex>codex | - |
| Codex gc-nudge | opencode>codex | - | claude>codex, codex>claude | - |
| Codex hcom | codex>claude, opencode>codex | - | claude>codex, codex>opencode | - |
| Codex intercom | pi>codex | - | - | - |
| Codex intercom-accept | - | codex>claude | - | - |
| Pi hcom | pi>claude | - | claude>pi | - |
| Pi intercom | pi>codex, pi>pi | - | - | - |
| Pi intercom-accept | pi>claude | - | - | - |
| Pi pi-claude-link | droid>pi, pi>pi | - | claude>pi | - |
| Pi pi-ext | claude>pi, pi>claude, pi>droid, pi>pi | - | droid>pi | - |
| Pi pi-session-bridge | claude>pi, droid>pi, pi>pi | - | - | - |
| OpenCode hcom | opencode>codex | - | codex>opencode | - |
| OpenCode opencode-server-queue | codex>opencode | - | opencode>opencode | - |
| OpenCode opencode-server-steer | opencode>codex | - | codex>opencode, opencode>opencode | - |
| OpenCode opencode-server-synthetic | codex>opencode | - | opencode>opencode | - |
| OpenCode opencode-service-steer | codex>opencode | - | opencode>opencode | - |
| Droid agent-deck | droid>pi | - | pi>droid | - |
| Droid gc-nudge | pi>droid | - | - | - |
<!-- /generated:s9 -->

Gap fills: 27/27 recorded, 26 round trips. The one failure, Codex>Claude over `intercom-accept`
(`20261028-143904-0e9b`), is a mechanism result: Claude received the push, answered with `SendMessage` to the intercom
bridge's own peer socket ("Cross-session message released after approval"), and the reply never reached Codex
(`roundtrip=no`, `no-roundtrip=no-reply`). The Task 7 Pi>Claude pass over the same bridge ran on Claude 2.1.311; the
pinned re-run (`20261028-161100-7b7f`, Claude 2.1.312) passed, so the failure is specific to the Codex>Claude pair on the pinned versions.
Droid reached over agent-deck or gc-nudge is terminal injection (R31), not a native push.

## User-relevant properties of the shortlisted mechanisms

| agent | mechanism | S8: human attaches and types normally | global config change | daemon or bridge | cross-machine claim (untested) | security caveats |
|---|---|---|---|---|---|---|
| Claude | claude-channel | yes (rendered) | no: per-session `--mcp-config` + `--dangerously-load-development-channels server:<name>`; a "Loading development channels" warning must be answered at launch | an MCP channel server (bun) spawned by Claude itself, one per session | none | development-channel flag; any local process that can open the channel's unix socket can inject |
| Claude | claude-uds-accept | yes | per-session `--settings '{"crossSessionInbound":"accept"}'`; making it the default means `crossSessionInbound: accept` in `~/.claude/settings.json` (R26) | none (Claude's own peer socket) | `isolatePeerMachines` setting hints at remote peers via Remote Control | R26: `accept` delivers frames from an unregistered local process with no token |
| Claude | claude-uds-child | yes | no: per-session `--mcp-config` (stdio relay) | a stdio relay MCP server spawned by Claude | none | the relay holds Claude's child messaging token and bypasses the default hold; anything that can write the relay socket can inject |
| Claude | hcom (S9) | yes | yes for a fleet on the user's config: hcom installs a `UserPromptSubmit` hook in the agent's Claude settings (isolated here via `CLAUDE_CONFIG_DIR`); its legacy-hook cleanup rewrites `~/.claude/settings.json` when old hcom hooks exist | hcom PTY proxy per agent, no central daemon | MQTT relay across machines | any same-user process can send as any name; loopback inject ports (auth not checked) |
| Claude | agent-deck (S9) | yes | no with the run config; default config shares the user's tmux server and auto-updates via launchd | agent-deck CLI + detached queue worker | `add --ssh`, `agent-deck web` | default writes Codex trust entries and a launchd update timer |
| Claude | csd (S9) | yes | no | none (tmux paste); workers state in `/tmp/csd-workers` by default | none | workers always run `--dangerously-skip-permissions` (S3 n/a, R36); copies Codex credentials into worker homes |
| Claude | gc-nudge (S9) | yes | no if the city is created outside `~` (a gc command below `~` treats `~/.gc` as a city; `gc start`/`register` install a LaunchAgent) | Gas City supervisor (HTTP API on 127.0.0.1) | k8s/ACP providers, non-loopback supervisor bind | supervisor API answered without credentials; gc tells agents to run `gc` by name (R28) |
| Codex | codex-remote-start | yes | no: TUI `--remote unix://…`, isolated `config.toml` | a `codex app-server --listen` process per receiver | `--remote ws(s)://`, `--ws-auth` tokens | anyone who can open the app-server socket can drive the thread |
| Codex | codex-queue | yes | no (isolated `CODEX_HOME`); a fleet would use the user's shared daemon | Codex app-server daemon (auto-update runs a managed updater; no off switch found) | `codex remote-control`, daemon remote control | daemon socket is per `CODEX_HOME`; same-user processes can queue into any thread |
| Codex | codex-remote-steer | yes | as codex-remote-start | as codex-remote-start | as codex-remote-start | steers a running turn (S2 interrupted) |
| Codex | hcom (S9) | yes | yes for a fleet on the user's config: hcom installs Codex hooks and an execpolicy in `CODEX_HOME` (isolated here) | hcom PTY proxy | MQTT relay | an agent can enable the cross-device relay without an approval prompt |
| Codex | gc-nudge (S9) | yes | as Claude gc-nudge | gc supervisor | as above | as above; a supervisor restart killed the agent and gc respawned it, losing the session context (S12 not good, R39) |
| Codex | intercom (pinned S9 pass Pi>Codex `20261028-173547-b27b`, in the S9 column, R38) | no: pushes run in `coi`'s hidden bridge thread (R33) | its README adds the `codex-intercom` MCP server with `codex mcp add` (a global write); the harness passed it with `-c` flags | agent-intercom broker per agent dir | `remote-access-v1` registrations in the broker | `trustedLocal`: any same-user process, self-chosen names |
| Pi | pi-ext | yes | no: per-session `-e <extension>` | an in-process Pi extension listening on a unix socket | none | anything that can open the socket can inject |
| Pi | pi-session-bridge | yes | no: per-session `-e` | in-process extension, registry dir | "different … hosts" in its instructions, local socket only | socket + registry readable by same user |
| Pi | pi-claude-link | yes | no: per-session `-e` | in-process extension speaking the Claude peer wire | none | accepts unauthenticated Claude-style frames (R26 class) |
| Pi | hcom, intercom, intercom-accept (S9) | yes | no (hcom and intercom load per-run Pi extensions) | hcom proxy / intercom broker | as above | as above; intercom components that lose `PI_CODING_AGENT_DIR` fall back to `~/.pi/agent/intercom` |
| OpenCode | opencode-server-queue, -steer | yes | no: `opencode serve` on 127.0.0.1 with a per-run password, TUI attached to it | an `opencode serve` process per receiver | `serve --hostname`, `opencode pair` | R23: the server password sits in the agent's env, so the agent can drive its own server |
| OpenCode | opencode-service-steer | yes | no with the isolated `service.json`; the user's default background service is `~/.config/opencode/service.json` | OpenCode background service | service `remote` tunnel | as above |
| OpenCode | opencode-server-synthetic (S9) | no: reply only, the pushed prompt never shows (R25) | no | `opencode serve` | as above | as above |
| OpenCode | hcom (S9) | yes | no | hcom PTY proxy | MQTT relay | as Claude hcom; OpenCode submits the human's draft as its own message (S7 `submitted`) |
| Droid | gc-nudge (S9) | yes | as Claude gc-nudge | gc supervisor | as above | terminal injection; S3 not measurable (R36), counted as not shown safe (R37) |
| Droid | tmux-buffer, tmux-paste, tmux-paste-retry | yes | no | none (tmux) | none | S3 harmful: the paste plus Enter approved the permission dialog; anything that can reach the tmux socket can type |
| Droid | agent-deck (S9) | yes | as Claude agent-deck | agent-deck | as above | terminal injection; S3 harmful |

## Task 10: reps, scale, user config, nono (2026-10-28)

All on the pinned agents (R35), unsandboxed coordinator (R21). Shortlist = the "by ranking" entries above, ties kept
(D1). The S9-only entries (right-hand column of the shortlist table) got no S1/S2/S5/S7 reps; they are covered by S9
only (D2, ruled R44). Details, superseded records and outward writes: `results/notes.md` "Task 10".

### 5 reps of S1, S2, S5, S7 (raw)

Existing screen/extensive reps count (S1 rep 1, S2/S5 reps 1-3, S7 reps 1-3); the new reps are stage `shortlist`
(S1 reps 2-5, S2/S5/S7 reps 4-5; 150 cells, 16:22-17:35, plan `runs/.scratch/plan-t10-reps.json`). k/n, never
percentages: n = 5 still detects only frequent failures (a route that fails one time in five passes all five reps
about a third of the time).

<!-- generated:reps -->
| agent | mechanism | S1 | S2 | S5 | S7 | total k/n | causes of not-good cells |
|---|---|---|---|---|---|---|---|
| Claude | claude-channel | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Claude | claude-uds-accept | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Claude | claude-uds-child | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Codex | codex-remote-start | 5/5 | 5/5 | 5/5 | 3/5 | 18/20 | S7 draft merged x2 |
| Codex | codex-remote-steer | 5/5 | 5/5 | 5/5 | 3/5 | 18/20 | S7 draft merged x2 |
| Pi | pi-claude-link | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Pi | pi-ext | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Pi | pi-session-bridge | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| OpenCode | opencode-server-queue | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| OpenCode | opencode-server-steer | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| OpenCode | opencode-service-steer | 5/5 | 5/5 | 5/5 | 5/5 | 20/20 | - |
| Droid | tmux-buffer | 5/5 | 5/5 | 5/5 | 0/5 | 15/20 | S7 draft merged x5 |
| Droid | tmux-paste | 5/5 | 5/5 | 5/5 | 0/5 | 15/20 | S7 draft merged x5 |
| Droid | tmux-paste-retry | 5/5 | 5/5 | 5/5 | 0/5 | 15/20 | S7 draft merged x5 |
| Codex | codex-queue (ran while shortlisted; no longer top 2) | 5/5 | 5/5 | 0/0 · err 5 | 1/5 | 11/15 | S5 error: precondition: burst-window x5; S7 draft merged x4 |
<!-- /generated:reps -->

S7 is the only scenario that separates the shortlist: Codex draft preservation stays unreliable on every route
(remote-start/-steer 3/5, queue 1/5; the push and the half-typed draft end up in one turn), Droid's terminal routes
merge every time (0/5). Claude, Pi and OpenCode preserved the draft in 5/5 on every route. S2 behaviour is unchanged
per route: Codex remote-start, Codex queue, Pi pi-ext and OpenCode server-queue queue the push behind the running
turn; the others steer into it (interrupted). One cell needed a harness fix (OpenCode `service_starting` 503 at
session creation, superseded and re-run).

### Scale: 8 concurrent receivers

`uv run agentcomms scale`, run twice (batch 1 runs `20261028-185640-d379`..., batch 2 `20261028-185959-88e7`...;
`results/scale-<first run>.json`). Mix: Claude `claude-channel` x2, Codex `codex-remote-start` x2, Pi `pi-ext` x2,
OpenCode `opencode-server-queue` x1, Droid `tmux-paste` x1 = the best-ranked mechanism per agent, two instances of
each multi-instance native backend (Claude channel servers, Codex app servers, Pi extension sockets) so per-instance
isolation is exercised, one each for the heavier OpenCode server and the single-agent tmux route. Each receiver has its
own run and backend (no shared daemon, only the `-L agentcomms` tmux server); the three rounds send to all eight at
the same moment and wait for every answer.

<!-- generated:scale -->
| receiver | mechanism | delivered k/n | acked k/n | latency min / median / max |
|---|---|---|---|---|
| claude#1 | claude-channel | 6/6 | 6/6 | 0.014 / 0.029 / 0.075 s (n=6) |
| claude#2 | claude-channel | 6/6 | 6/6 | 0.014 / 0.019 / 0.044 s (n=6) |
| codex#1 | codex-remote-start | 6/6 | 6/6 | 0.037 / 0.124 / 0.588 s (n=6) |
| codex#2 | codex-remote-start | 6/6 | 6/6 | 0.078 / 0.099 / 0.583 s (n=6) |
| droid#1 | tmux-paste | 6/6 | 6/6 | 0.140 / 0.165 / 0.529 s (n=6) |
| opencode#1 | opencode-server-queue | 6/6 | 6/6 | 0.012 / 0.017 / 0.031 s (n=6) |
| pi#1 | pi-ext | 6/6 | 6/6 | 0.003 / 0.005 / 0.011 s (n=6) |
| pi#2 | pi-ext | 6/6 | 6/6 | 0.002 / 0.005 / 0.005 s (n=6) |
| all (16 receiver runs) | - | 48/48 | 48/48 | 0.002 / 0.022 / 0.588 s (n=48) |
<!-- /generated:scale -->

Host load (`ps -o pid,rss,pcpu` on the runs' own pids only, 2-5 s samples; `pcpu` is ps's decaying average):
8 receivers with their backends and MCP children = 22-24 processes, total RSS 3.0-3.4 GB (OpenCode 0.81-0.90 GB
TUI + server; Droid 0.41-0.45 GB; Claude 0.36-0.39 GB each with its bun channel server; Codex 0.31-0.45 GB each with
its app server; Pi 0.19-0.21 GB each). CPU (sum of `pcpu` over the owned processes): batch 1 launch phase 142 %
(1 sample), batch 1 message phase 22 % (1 sample); batch 2 launch phase no sample, message phase peak 16 %, median
11 % (3 samples). Every figure rests on 0-3 samples,
so the load numbers are indicative. Laptop limit stated in the plan: larger counts are a Mac Studio follow-up.

### User-config column (R41)

S1 and S7 with the user's real global config loaded (stage `user-config`, condition `raw + user config` in
`results/matrix.md`); work dirs under `runs/`. Skips are `n/a` records with the reason. Inventory (names only) and
the per-launch switches are in `results/notes.md`.

<!-- generated:user-config -->
| agent | mechanism | S1 | S7 | total k/n | causes of not-good cells |
|---|---|---|---|---|---|
| Claude | claude-channel | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Claude | claude-uds-accept | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Claude | claude-uds-child | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Codex | codex-remote-start | 1/1 | 1/1 | 2/2 | S1, S7 outward-contact: remote plugin catalog / app connector caches written |
| Codex | codex-remote-steer | 1/1 | 1/1 | 2/2 | S1, S7 outward-contact: remote plugin catalog / app connector caches written |
| Pi | pi-claude-link | 0/0 · err 1 | n/a | 0/0 | S1 error: TimeoutError: pi not ready after 90s; S7 n/a: skipped: writes global config |
| Pi | pi-ext | n/a | n/a | 0/0 | S1, S7 n/a: skipped: writes global config |
| Pi | pi-session-bridge | n/a | n/a | 0/0 | S1, S7 n/a: skipped: writes global config |
| OpenCode | opencode-server-queue | 1/1 | 1/1 | 2/2 | S1, S7 outward-contact: mcp context7 started (switch ineffective in 2.2.0); jina likely |
| OpenCode | opencode-server-steer | 1/1 | 1/1 | 2/2 | S1, S7 outward-contact: mcp context7 started (switch ineffective in 2.2.0); jina likely |
| OpenCode | opencode-service-steer | n/a | n/a | 0/0 | S1, S7 n/a: skipped: attaches to the user's OpenCode background service |
| Droid | tmux-buffer | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Droid | tmux-paste | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Droid | tmux-paste-retry | n/a | n/a | 0/0 | S1, S7 n/a: skipped: trust |
| Codex | codex-queue (ran while shortlisted; no longer top 2) | n/a | n/a | 0/0 | S1, S7 n/a: skipped: attaches to the user's live Codex daemon |
<!-- /generated:user-config -->

- Claude: skipped on trust (the workspace trust dialog shows even under `bypassPermissions`; accepting writes
  `~/.claude.json`; no per-launch switch).
- Droid: skipped on trust (no trusted ancestor in `~/.factory/settings.json`, no trust flag).
- Codex `codex-queue`: skipped (its daemon in the user's `CODEX_HOME` is the user's live daemon). Codex
  remote-start/-steer ran with `CODEX_HOME=~/.codex` and `-c` switches (notify, MCP context7/jina, browser/chrome/
  computer-use plugins off; trust via `-c projects={"<work>"={trust_level="trusted"}}`); 4/4 good. Interference seen:
  the user's `tui.status_line` replaces the footer the harness waited for (readiness fix), and the TUI showed its
  startup animation.
- Pi: the first cell (`pi-claude-link` S1) made Pi 1.4.0 rewrite `~/.pi/agent/settings.json` (`lastChangelogVersion`
  1.2.0 -> 1.4.0), `auth.json` and `models-store.json`, run `npm view` package-update checks and show its changelog
  and a "Package Updates Available" screen; the user's `pi-statusline` footer then kept the readiness regex from
  matching (`error`, not ready after 90 s). The remaining Pi cells were skipped (writes global config).
- OpenCode server-queue/-steer: 4/4 good with the user's config dir (plugins incl. hooklinesinker, mouthfeel,
  nono-sandbox, sandbox-status; agent `coordinator`), data/state/cache in the run. The intended MCP switch did not
  work: OpenCode still started `npx @upstash/context7-mcp` (npm logs in `~/.npm/_logs`) despite
  `OPENCODE_CONFIG_CONTENT` `mcp.context7.enabled=false`, so these cells made outward contact; the classifier now has
  no OpenCode MCP switch, which skips such cells on a re-run. `opencode-service-steer` skipped (the user's service).

The cause column marks the contaminated cells (R43): the 5 OpenCode records and the Codex records carry an
`outward-contact:` note. They stay as data, but are not evidence of a contact-free run. Under R42 a re-run of these
cells skips: Codex while the app connector `connector_openai_codex_document_control` has no verified switch, OpenCode
while the user's MCP servers have none, Claude and Droid have no overlay, Pi rewrites its config. Each switch is
checked in the argv and env the harness built (R48), and an integration not on the reviewed list skips the cell as
"unclassified". The Codex plugin and MCP `-c` switches are pinned in the built argv, not live-verified to take effect.

### nono column

Receiver, its backend and the harness-side sender each under `nono run -p <agent>-local` with the user's launcher
semantics (`agentcomms/sandbox.py`, nono 0.80.0), 1 rep (stage `nono`, condition `nono`). Preflight first
(`results/nono-preflight.md`, 75/75): inside every profile `ps` works (the sender guard's `ps -A -o pid,lstart,ucomm`),
every stdlib sender runs, the pinned binary in `vendor/agents/` runs `--version`, unix sockets bind and connect in
`/tmp/ac`, loopback TCP works, `tmux -L agentcomms` reaches the harness server and node runs the vendored tsx
(intercom's sender).

<!-- generated:nono -->
| agent | mechanism | S1 | S2 | S4 | S7 | total k/n | causes of not-good cells |
|---|---|---|---|---|---|---|---|
| Claude | claude-channel | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Claude | claude-uds-accept | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Claude | claude-uds-child | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Codex | codex-remote-start | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
| Codex | codex-remote-steer | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
| Pi | pi-claude-link | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Pi | pi-ext | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Pi | pi-session-bridge | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| OpenCode | opencode-server-queue | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| OpenCode | opencode-server-steer | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| OpenCode | opencode-service-steer | 1/1 | 1/1 | 1/1 | 1/1 | 4/4 | - |
| Droid | tmux-buffer | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
| Droid | tmux-paste | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
| Droid | tmux-paste-retry | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
| Codex | codex-queue (ran while shortlisted; no longer top 2) | 1/1 | 1/1 | 1/1 | 0/1 | 3/4 | S7 draft merged |
<!-- /generated:nono -->

S9 under nono (both agents sandboxed, the sender is A's own tool call inside A's profile): Claude>Pi
(`pi-ext`/`claude-uds-accept`, `20261028-193819-e66c`), Codex>OpenCode (`opencode-server-queue`/`codex-queue`,
`20261028-193849-5699`) and Pi>Pi over intercom (vendored node + tsx sender, `20261028-193936-2a73`): 3/3 round trips.
Every nono verdict equals the raw one (S7 merges on Codex and Droid are the raw behaviour). The five failed nono cells
before that were harness causes, diagnosed and superseded (notes): sops-exec inside nono for backends (`nono why
--self` -> `DENIED path_not_granted` for `~/.config/sops/secrets.yaml` and the age identity, by design), nono reading
pi-claude-link's `XDG_RUNTIME_DIR`, and a sandboxed sender without a Codex thread id. No profile edits, no grants.

## Decisions (for rulings)

- D1: Ties are kept: three-way ties at the top for Claude, Pi, OpenCode and Droid, a two-way tie
  at rank 2 for Codex. Task 10 runs 5 reps of S1, S2, S5, S7 on each tied mechanism unless a ruling narrows it.
  After R47 the Codex tie is gone: `codex-queue` lost its S5 records to the burst precondition and is listed with the
  S9-only entries; the cells it ran while shortlisted stay in the tables.
- D2 (ruled, R44): S9-only entries (the right-hand column of the shortlist) are listed as agent-to-agent options
  with their extensive k/n and S9 result; they get no reps, user-config or nono delivery cells.
- D3 (ruled, R37): unmeasured safety cells count as not shown safe over a fixed denominator of 7. Droid's top is now
  tmux-buffer, tmux-paste and tmux-paste-retry (3/7, 11/16); gc-nudge moved to the S9 column.
- D4: zellij S6 (send while the receiver is down) is silently lost on every agent, so a zellij fleet loses messages
  sent during a restart without the sender knowing; tmux rejects them. Recorded as a host finding.
- D5: Codex codex-remote-start/-steer preserved the human draft in the screen S7 on 0.165.0 but merged it in both
  extensive reps (1/3): draft preservation is not reliable on Codex.

