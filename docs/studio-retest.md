# Mac Studio re-test plan

What to re-measure on the Mac Studio (M5 Max, 128 GB) before the fleet relies on the delivery layer recommended in
`REPORT.md` (tmux, one native route per agent, `agent-send` with a name registry). Based on REPORT §10.9, adjusted
for the fleet decisions in `~/wrksp/notes/work/factory/spec.md`:

- No nono. Agents run raw as one non-admin macOS user; the human's own interactive sessions run as the same user.
- Core agents are Claude, Codex and Pi. OpenCode is optional; Droid is dropped.
- Pushes are doorbells ("new mail in X"); bodies live in a durable inbox/forum store.
- Most wake-ups start a fresh TUI in tmux with an initial prompt; permanent agents are identity plus memory.
- The real per-agent config is a loadout profile, not the harness's isolated homes.
- About 30 sessions, real auth shared across them, some sessions long-lived.

Dropped from §10.9: the nono pass, Droid (guard, `tmux-paste` round trips), iTerm2/zmx/zellij hosts, bridges.

## Setup

1. Clone the repo, `uv sync`, `uv run pytest -q && uv run ruff check`.
2. Pin the agent versions the fleet will run: copy the loadout-installed binaries into `vendor/agents/` as in README
   "Setup" and record source and sha256 in `vendor/REVIEW.md`. Turn auto-update off for the run (R35: three agents
   changed behaviour across one update).
3. The harness launches every agent through `~/ac/bin/sops-exec` with `AGENT_REQUIRE_SECRETS=1`. Either install the
   same launcher on the Studio or point `agentcomms/profiles.py` at the fleet's credential launcher. Never put
   credentials in argv.
4. Run the coordinator unsandboxed (R21) from a terminal that is not one of the fleet's sessions. AC power;
   `caffeinate -i` around long batches.
5. Prerequisites as in REPORT §10.7: python3, tmux, bun (Claude channel server), node 24 (Pi).

## Harness changes to build first

Each is a small, separately testable change; none exists yet.

| id | change | why | done when |
|---|---|---|---|
| H1 | `--config real`: launch against the loadout profile (real `~/.claude`, `~/.codex`, `~/.pi`) in a dedicated test work dir, instead of isolated homes. Keep the manifest ownership checks, the per-run tmux server and cleanup; drop the R41 "skip outward integrations" rule only where the fleet will run them anyway. | The fleet runs on real config; the isolated-home results may not transfer (hooks, MCP servers, plugins, trust). | One S1 cell per core agent passes on real config; `cleanup` leaves the real stores' session lists as the run's notes say. |
| H2 | `scale --n N --mix claude,codex,pi`: parameterise `scale.MIX` (fixed at 8 today). | Target is ~30 sessions. | `scale --n 30` runs and writes the SCALE records and JSON. |
| H3 | S13 launch-with-initial-prompt: start a fresh TUI with an initial prompt (Claude `claude "<prompt>"`, Codex `codex --remote <sock> "<prompt>"`, Pi `pi "<prompt>"`), then ring a doorbell at fixed offsets: before ready, at ready, during the initial turn, after it. | Sends during startup were never measured (REPORT §10.7, R14). | Per agent and offset: delivered / lost / duplicated, and whether the initial prompt itself ran. |
| H4 | S14 Claude `SendMessage` across permission classes: sender mode × receiver mode over {bypass, auto, default/prompting} with `crossSessionInbound` unset; plus a `--dangerously-load-development-channels` session sending to and receiving from a plain peer. | Only bypass↔bypass was measured (S9 pilot `20261027-171554-6acd`). | A table of delivered / held per pair, from the receiver's transcript. |
| H5 | S15 doorbell: push "new mail in <inbox>"; the receiver must read the body from the store. Good only when the transcript shows the store read and the body's token. | This is the fleet's delivery pattern; R50's "polled is not a receipt" is inverted here by design. | Verdicts for each core route; a merged burst of doorbells counts as good if every body was read. |
| H6 | Soak: N sessions kept for 8–24 h with doorbells every few minutes, `/compact` and `/new` mid-run, Codex token refresh, a whole-fleet restart. | Long-lived sessions, shared auth and restarts were not measured at fleet size. | Delivery rate over time, auth failures, RSS growth, and S6/S12 verdicts after the fleet restart. |

## Run order

1. **Baseline on the Studio** (isolated homes, as measured here): shortlist routes only, so results compare
   directly with REPORT §3.
   ```sh
   uv run agentcomms matrix --stage shortlist --agents claude,codex,pi \
     --adapters claude-channel,claude-uds-child,codex-remote-start,pi-ext --reps 5
   ```
   Add `opencode-server-queue` with `--agents ...,opencode` if OpenCode stays in.
2. **Real config (H1):** the same cells with `--config real`. Any verdict that differs from step 1 is a config effect;
   find the hook, MCP server or setting responsible before going on.
3. **Permission mode:** S3 in the fleet's real mode (`agentcomms run --mode`, REPORT §10.7; the harness's `auto` is
   Claude `bypassPermissions`, not Claude's auto mode, so add the real mode first). In auto/bypass, confirm
   no dialog appears at all; in prompting, S3 applies as measured.
4. **Cross-class `SendMessage` (H4)** and **doorbells (H5)** on real config.
5. **Launch-with-initial-prompt (H3).** Codex: confirm `--remote` with an initial prompt creates the thread, and that
   the registry can read the thread id afterwards (REPORT §10.7 "Codex thread id").
6. **Scale (H2):** `scale --n 30`, then the largest N the box holds; record RSS (8 receivers were 3.0–3.4 GB here),
   latency and per-provider rate-limit errors with real shared auth.
7. **Soak (H6)** overnight.
8. **`agent-send` itself** once built: its readiness check, registry, Codex spool and drainer (REPORT §10.8), run
   through the same scenarios as an adapter.
9. Optional: S5 on `codex-queue` (lost its S5 coverage to R47), only if it is still a candidate.

## Safety checks for raw, one-user operation

Run once on the real config before the soak; record the result in `results/notes.md`.

- Codex shell snapshots are off in the real `~/.codex/config.toml` (`[features] shell_snapshot = false`, R29);
  otherwise every Codex session writes its exported environment, secrets included, to 0644 files.
- Claude peer keys (`<config>/sessions/*.key`) and every harness socket are readable by every agent: with one user,
  any agent can message any session, including the human's. Decide `crossSessionInbound` per session class with
  that in mind (R26: `accept` takes frames with no token).
- The human's sessions: confirm what a doorbell from each route looks like there (held picker, channel frame, or a
  plain user message) and that S7 still keeps a half-typed draft.

## What would change the recommendation

- Any core route below 5/5 on S1/S2 or losing S7 drafts on real config.
- Doorbells lost or duplicated during startup (H3) on the route a wake-up uses.
- Cross-class `SendMessage` held in a direction the fleet needs (H4).
- Rate-limit or token-refresh failures at 30 sessions with shared auth.
- RSS or latency growth over the soak.
