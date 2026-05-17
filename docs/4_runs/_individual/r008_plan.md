# r008 — CFR prototype cross-paradigm validation

> **⚠️ SUPERSEDED / FAILED (2026-04-23).** r008 已跑完并失败 — Deep CFR 200 iter
> 的 final ckpt 40% vs random,0/10 vs 一切 baseline。详见 memory `project_r008_postmortem`。
> 本计划 doc 保留作历史参考。
>
> **后续 paradigm 转向**: [adr-0008 paradigm pivot](../../2_decisions/adr-0008-rl_paradigm_pivot.md)。

## Purpose

First production-scale **Deep CFR** training run. All prior `rNNN`
runs were AlphaZero. r008 asks: can a Deep CFR policy trained under
the same game setup compete with r007's AZ champion?

If yes, CFR paradigm is viable on TCG-scale games and we invest in
per-player net scaling / Linear-CFR tuning. If no (expected,
per the review's cautionary note that TCG infostate scale has no
precedent for Deep CFR success), we document the failure mode and
close the CFR exploration.

## Launch conditions

- r007 completed. Its `final_champion.pt` under
  `artifacts/202604211058_r007_slow_1500g/` is the AZ opponent.
- 14-core CPU free (r007 saturated all during training; CFR wants
  `n_workers=4` at least, room for the main process + fit threads).
- `eval_service` running, socket at `/tmp/gicg_eval.sock`.

## Scope — what r008 trains

Fixed 2v2 matchup pinned to one cell of r007's char pool. Why
fixed (not sampled from r007's pool):

- CFR convergence is sample-hungry; restricting to one matchup cuts
  infostate space dramatically, giving paradigm-validity signal
  within a single-day budget.
- Gauntlet comparison vs r007 on the SAME fixed teams is directly
  meaningful — both nets learn that matchup from scratch.

Launch:

```bash
# From repo root, post-r007:
.venv/bin/python -m tools.run_cfr \
    --preset r008_cfr_prototype \
    --n-workers 4 \
    --seed 42
```

Output dir: `artifacts/YYYYMMDDHHMM_cfr_r008_cfr_prototype/`.
(`tools.run_cfr` builds `cfr_<label>` by default — acceptable; if
strict `rNNN_<slug>` conformance is needed, pass
`--artifacts-dir artifacts/${ts}_r008_cfr_prototype`.)

Config (hard-coded in `PRESETS["r008_cfr_prototype"]`):

| field | value |
|---|---|
| team_0 | `[赤蝶, 墨客]` |
| team_1 | `[猫咪, 刻师傅]` |
| iterations | 200 |
| traversals_per_iter | 32 |
| d_model | 64 |
| n_cross_layers | 2 |
| advantage_fit_steps | 32 |
| strategy_fit_steps | 64 |
| strategy_fit_every | 5 iter |
| fit_batch_size | 64 |
| buffer_capacity | 50,000 |
| checkpoint_every | 20 iter |
| epsilon | 0.10 |
| W_max | 100 (TraversalConfig default) |
| n_workers | 4 |

Produces `cfr_strategy_iter{0020..0199}.pt` ckpts every 20 iters.

## Expected timeline

Smoke (8 iter × 8 traversal, d=32, single-process, under r007
contention) took 14.3 min (`artifacts/202604211303_cfr_smoke/`).

r008 math:
- iterations × traversals_per_iter / n_workers = 200 × 32 / 4
  = 1600 traversals per worker
- d_model=64 vs smoke d=32: per-traversal forward cost ~2× (quadratic
  in d for attention scale; roughly linear for us since heads scale
  with d but dot-product dim matters)
- strategy_fit_every=5 → 40 strategy-fit passes (vs smoke's 4) =
  longer per-iter on fit iterations
- Without r007 CPU contention: per-traversal closer to micro-bench
  (0.2-0.5 s) than smoke's 5 s

Estimate: **6-12 hours** on a freed 14-core CPU. Safety budget: one
overnight run.

## Post-training gauntlet

4 matchup requests to `eval_service`, varying n_simulations on both
sides. CFR ckpt = `<r008>/cfr_strategy_iter000199.pt`. AZ ckpt =
`artifacts/202604211058_r007_slow_1500g/final_champion.pt`.

### Matchup A: CFR vs r007 AZ at 4 budgets

```python
# Pseudo-python (or use tools.send_gauntlet after extending it to
# support --challenger-type cfr):
import json, socket
for budget in [0, 50, 100, 200]:
    req = {
        "kind": "gauntlet",
        "id": f"r008_cfr_vs_r007_b{budget}",
        "game_marker": 800 + budget,
        "seed": 90000 + budget,
        "players": [
            {"type": "cfr", "ckpt": "<r008>/cfr_strategy_iter000199.pt",
             "n_simulations": budget},
            {"type": "az",  "ckpt": "<r007>/final_champion.pt",
             "n_simulations": budget},
        ],
        "mode": "fixed",
        "team_0": ["赤蝶", "墨客"],
        "team_1": ["猫咪", "刻师傅"],
        "card_pool": None,
        "data_dir": "data",
        "games_per_cell": 50,   # 100 games per budget (with side-swap)
        "max_game_steps": 400,
        "result_path": "artifacts/<r008>/gauntlet_r008_vs_r007.jsonl",
    }
    # POST to /tmp/gicg_eval.sock
    ...
```

### Matchup B: CFR vs pure MCTS sweep

Same structure, `{"type": "mcts_pure", "n_simulations": budget}` as
opponent. Budgets: [50, 100, 200] (skip 0 — mcts_pure requires >0).

```python
for budget in [50, 100, 200]:
    req = { ..., "players": [
        {"type": "cfr", "ckpt": "<r008>/...", "n_simulations": 0},  # argmax challenger
        {"type": "mcts_pure", "n_simulations": budget},
    ], ... }
```

## Success criteria (pre-registered)

Based on the Phase-3 launch discussion (`cfr-plan-iteration`):

| CFR win rate | mcts_0 | mcts_200 | Interpretation |
|---|---|---|---|
| vs r007 ≈ 0.50 | ≈ 0.50 | ≈ 0.50 | Paradigm viable, CFR competes at parity. Invest in scaling. |
| vs r007 ≈ 0.50 | << 0.50 | ≈ 0.50 | CFR strong with search but weak without. Policy head under-trained (expected). |
| vs r007 < 0.30 | < 0.50 | < 0.50 | CFR paradigm weaker on this game. Document + close. |
| vs r007 > 0.60 | > 0.50 | > 0.50 | CFR beats AZ unexpectedly. Verify (repro + different seed). |

Honest prior: most likely bucket is **vs r007 < 0.30**. That's
still a valuable negative result — quantifies the paradigm gap.

## Monitor (during training)

`metrics.jsonl` in the artifacts dir emits per-iter JSON. Key
signals:

- `advantage_loss`: bouncy under outcome-sampling W (variance
  high); should stay bounded (not diverge). Per-player nets now —
  look for skew between p0 and p1.
- `strategy_loss`: CE over regret-matching policy targets. Should
  trend DOWN across iterations as strategy_net learns the average
  strategy. Iter 0 is None (skipped). Compare iter 5, 10, ...
- `value_loss`: MSE against episode outcomes ±1. Should decrease
  slowly; value head learning position evaluation.
- `buffer_sizes`: advantage_p0 + advantage_p1 grows ~linearly in
  iterations × traversals/iter × traverser_decisions_per_game
  (~100 with this team). Strategy grows at half that (only
  traverser decisions per traversal). Hits capacity (50k) around
  iter 100.

Red flags:
- `advantage_loss` monotonically climbing past 10× initial → reach
  weight explosion; consider lowering ε or tightening W_max.
- `strategy_loss` flat or rising → policy head not learning;
  possibly the regret signal is too noisy. Enable
  `advantage_reset_each_iter=True` next run.
- `value_loss` > 1.0 permanently → value head stuck; OK for CFR
  prototype (search augments at inference time) but notes a
  limit for mcts-wrap performance.

## Failure modes → next run

- If **CFR < 0.30 vs r007** at all budgets: close CFR, document
  in `../../5_history/postmortems/`, resume AZ-centric work.
- If **CFR mcts_0 > 0.4 but mcts_200 < 0.3**: value head is the
  bottleneck. r009 tries value distillation from r007's value
  head as warmstart.
- If **training diverges** (loss NaN / sudden jump): check
  grad_clip actually firing (trainer logs) + lower W_max to 50.

## References

- Code: `training/cfr/{network,traversal,train,collector,worker,parallel_trainer}.py`
- Launcher: `tools/run_cfr.py`(2026-04-24 加自动 post-training gauntlet,
  commit `66907b2`)
- CLI CFR vs MCTS: `tools.send_matchup --kind gauntlet`(schema-driven)
- Algo review history: `../../2_decisions/`(D14 ExpandUnionK 废弃补记;
  CFR 本身无专用 decision 文档,见 commit 0601da2、65c9fef 原始 review)

---

## 中期 gauntlet 观察(iter ~120 时做)

2026-04-23 r008 跑到 iter 120 左右做了早期 ckpt 对 random 的快速
gauntlet,发现**策略 oscillation**:

| iter | win vs random | note |
|---|---|---|
| 20 | 1.00 (10/10) | 早期低质策略,random 弱,假象高 |
| 40 | 0.80 | 渐降,正常 |
| 60 | 0.70 | 渐降 |
| 80 | 0.60 | 渐降 |
| 100 | **0.00 (0/10)** | 谷底,Switch 沉迷(见 `tools/diag_cfr_argmax.py` 1 局 trace) |
| 120 | 0.30 | 反弹 |

iter 100 vs mcts_200 同样 0/10(wall 924s/10 局,全程游戏非 Switch spam
早结束)。

iter 100 CFR argmax 诊断:50% 动作选 Switch(远高于 legal_actions 中
Switch 的基线 ~5%),来回切换浪费整个 AP 预算;value 头终局前 +0.2
严重乐观。

**排除的失败模式:**
- Pipeline bug — iter 20 能赢,eval 路径 OK
- CFR 数学 — iteration 加权、regret_to_policy、buffer 标签均正确
- 初始化偏置 — iter 20 是合理策略

**候选未验证原因(等 r008 完整数据再决定):**
- Strategy buffer Vitter-R 自强化:好样本被挤出,iter 加权放大最新样本 →
  自强化退化
- Advantage net 发散(adv_loss 100k-280k 震荡)

配套 memory:`project_r008_oscillation`。
