---
name: run
description: Orchestrate gicg-mono training runs. `/run launch <type> <NNN_slug> <config>` registers and launches a new run with eval_service precheck + container start + wakeup schedule. `/run verdict <label>` (or `--multi-seed <l1> <l2> <l3>`) collects full gauntlet ladder + dual judge + registry update + FAIL postmortem draft. Manual-only.
disable-model-invocation: true
---

# /run

Orchestrates the gicg-mono training run lifecycle. Two subcommands. Authoritative process docs live in `CLAUDE.md` (Container workflow / Artifacts naming) and the `tools.runs.*` CLI (`tools/runs/`,post `core-network-generic-promotion` 2026-05-17 取代手维护 `docs/4_runs/registry.md`)。This skill encodes the *sequence* and *guardrails*; details live in those files and in `MEMORY.md` references.

## Common preflight

Before either subcommand, verify cwd is repo root (`/Users/redcontritio/Documents/gicg_mono` — `CLAUDE.md` cwd convention) and the venv exists at `.venv/bin/python`. Bail otherwise.

---

## `/run launch <type> <NNN_slug> <config>`

Start a new training run. Three positional args, no flags.

| arg | example | requirement |
|---|---|---|
| `<type>` | `r` or `s` | `r` = production training run; `s` = smoke / bench |
| `<NNN_slug>` | `r010_az_bcwarmstart_stage3` | `<NNN>` must be **next free integer** for that type; user picks deliberately |
| `<config>` | `configs/r010_az_bcwarmstart_stage3.toml` | TOML must exist; its `run_label` field must equal `<NNN_slug>` |

### Steps

1. **Registry NNN check** — run `python -m tools.runs.list --type <type>`. Find the largest NNN currently in the output for that type. Expect arg's NNN == max+1. Mismatch (collision or skip) → **STOP**, report to user — do not auto-pick. (Note: pre-redesign 2026-05-17 之前的历史 r001-r012 + s001-s068 在 `docs/5_history/runs_pre_redesign_2026_05_17.md` archive,不进 live count,新 NNN 从最大 historical 之后开始。)

2. **Config sanity** — open `<config>`. Confirm `run_label = "<NNN_slug>"` field exact match. If absent or mismatched → **STOP**.

3. **Registry write (pending record)** — call:
   ```
   .venv/bin/python -m tools.runs.register \
     --run-id <NNN_slug> \
     --cfg <config> \
     --type <type>
   ```
   (writes `artifacts/runs/<NNN_slug>.toml` with status=pending,git_commit/host/cfg_checksum 自动注入;gitignored)
   Tool returns the allocated id; capture for the report.

4. **eval_service precheck** (memory `feedback_eval_service_precheck` — gauntlet/arena silently skip if down):
   - `tools/dc.sh ps eval` — if state ≠ running OR health ≠ healthy:
     - `tools/dc.sh up -d eval`
     - poll `tools/dc.sh ps eval` until healthy (timeout 60s; bail with logs on fail)

5. **Algorithm dispatch** — single entry `tools.run`, paradigm picked from `cfg.meta.paradigm` (per `openspec/specs/tools-layout/spec.md` TL2.1):

   | `meta.paradigm` value | Adapter |
   |---|---|
   | `az`  | `training.paradigms.az` |
   | `ppo` | `training.paradigms.ppo` |
   | `cfr` | `training.paradigms.cfr` |
   | `dmc` | `training.paradigms.dmc` |
   | `bc`  | `training.paradigms.bc` |

   Ambiguous (none / multiple match) → **STOP**, ask user.

6. **Container launch** (default; memory `feedback_benchmark_with_training` — never bypass real training to save time):
   ```
   DOCKER_CONFIG=/tmp/docker-config-anon docker compose run --rm train \
     python -u -m <module> <config> > /tmp/<NNN_slug>.log 2>&1
   ```
   Use Bash with `run_in_background: true`. Capture the bash id.

7. **Startup verification** — wait 30–60s, tail `/tmp/<NNN_slug>.log`. Look for one of: `[bc_train]`, `[selfplay]`, `[ppo]`, `[cfr]`, `[dmc]`, or `[run]` startup banner.
   - Banner present → continue.
   - Python traceback or container died → **STOP**, surface log.

8. **Wakeup schedule** (memory `feedback_wakeup_cadence`):
   - Estimated total runtime > 1h → `ScheduleWakeup(delaySeconds=3300, prompt='<<autonomous-loop-dynamic>>')` with `reason='检查 <NNN_slug> 训练进度'`
   - ≤ 1h → 900s
   - Estimate from TOML (`n_games`, `n_epochs`, etc.) — when in doubt, use 3300s.

9. **Report** — one-line summary to user: launched module, log path, projected wall, wakeup ETA.

### Boundaries (do NOT)

- Pick NNN automatically — user must claim it explicitly.
- Modify the TOML for any reason.
- Skip eval_service precheck even for "smoke that won't gauntlet" — it's cheap.
- Write the verdict row (that's `/run verdict`'s job).
- Auto-commit anything (per `CLAUDE.md`: every commit needs explicit user approval).

---

## `/run verdict <label>` or `/run verdict --multi-seed <l1> <l2> <l3> [...]`

Collect gauntlet metrics + update registry. Two modes.

### Steps

1. **Locate artifacts** — for each label, find `artifacts/<ts>_<label>/` (artifacts naming: `YYYYMMDDHHMM_<label>`, memory `feedback_artifacts_naming`). Read `summary.json`, tail `metrics.jsonl`. Missing → suspect crash; **STOP** with diagnostic.

2. **eval_service precheck** — same as launch step 4.

3. **Gauntlet ladder** (memory `feedback_post_run_gauntlet` — every run must produce gauntlet):
   - Run vs each baseline, n_eval_games ≥ 64 (memory `feedback_ppo_multiseed_required`):
     - `random`
     - `mcts_pure_50`, `mcts_pure_100`, `mcts_pure_200`
     - `F1-D1`, `F1-D2` (dice_greedy=true), `F1-D3`
   - F1-D2 dice_greedy is the canonical strong baseline (memory `project_greedy_baseline`).
   - Use `python -m tools.send_matchup` per baseline; collect win rates.

4. **Multi-seed aggregation** (only if `--multi-seed`, n ≥ 3):
   - Compute mean ± std per baseline.
   - **Dual judge** (memory `project_az_stage0_3_baselines`):
     - vs random ≥ 0.65 → **curriculum PASS**
     - vs F1-D2 ≥ 0.40 → **stricter PASS**
     - both fail → **FAIL**
   - Single-seed mode → emit per-baseline win rates **with explicit warning**: "single-seed indicative; verdict requires multi-seed n≥3 (memory `feedback_ppo_multiseed_required`)".

5. **Registry update** — call:
   ```
   .venv/bin/python -m tools.runs.complete \
     --run-id <NNN_slug> \
     --status done    # or 'failed' (FAIL = stricter judge fails)
     --wall <h>       # e.g. '16.3h'
     --gauntlet-json artifacts/<run>/gauntlet.json   # optional
     --notes 'wall=<h>; <one-line gauntlet summary>; <verdict tag>'
   ```
   (mutates `artifacts/runs/<NNN_slug>.toml` — gitignored;不需 docs/ edit)

6. **Postmortem draft** (only if FAIL):
   - Write `docs/5_history/<label>_postmortem.md` (or `<label_base>_postmortem.md` for multi-seed). Include: config summary, training trajectory snippets, gauntlet table, failure hypothesis, suggested next step.
   - **Do NOT commit** — leave for user review.

7. **Report** — verdict table (per-baseline mean±std for multi-seed; raw rates for single), judge labels, registry diff preview, postmortem draft path if any.

### Boundaries (do NOT)

- Auto-commit (CLAUDE.md: explicit approval per commit).
- Decide PASS/FAIL beyond the dual numeric judge — judge is a label, user does interpretation.
- Treat single-seed as a verdict — always tag as indicative.
- Skip gauntlet ladder for "obviously bad" runs — record the floor.

---

## Memory references (sync if memory names drift)

| Memory | Used in |
|---|---|
| `feedback_eval_service_precheck` | launch step 4, verdict step 2 |
| `feedback_post_run_gauntlet` | verdict step 3 |
| `feedback_ppo_multiseed_required` | verdict step 3 (n≥64), step 4 (n≥3 seeds) |
| `feedback_wakeup_cadence` | launch step 8 |
| `feedback_artifacts_naming` | verdict step 1 |
| `feedback_benchmark_with_training` | launch step 6 |
| `project_greedy_baseline` | verdict step 3 (F1-D2 strongest) |
| `project_az_stage0_3_baselines` | verdict step 4 (dual judge thresholds) |

If a memory is renamed or its content changes materially, update this table. The skill body is intentionally thin — guardrails live in memory; this file just sequences them.
