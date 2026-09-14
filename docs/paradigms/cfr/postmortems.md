---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# CFR postmortems

> CFR paradigm 失败诊断的 canonical 来源:memory `project_r008_postmortem`。
> 5_history 暂无 dedicated CFR postmortem doc(单 run,数据点全在 memory + registry r008 行)。

## 主要 postmortem 来源

| Topic | Canonical 来源 |
|---|---|
| r008 iter 199 collapse 完整诊断 | memory `project_r008_postmortem` |
| Run 数据点 | [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md) r008 行 |
| Closure 扩展(NFSP / Deep CFR redo)| memory `project_rl_routes_closure_2026_05_12` |
| `training/cfr/` 三层 layout 决策 | [`openspec/changes/archive/0006-training-layout/`](../../../openspec/changes/archive/0006-training-layout/) |

> **Follow-up**: 若未来 CFR 路线 reopen,SHOULD 把 memory `project_r008_postmortem`
> 落 `docs/5_history/postmortems/r008_cfr_postmortem.md` 以便 grep。本 task 暂不
> 落盘,保持 frozen history 与已有 5_history 风格一致(memory 是 source of truth)。

## Paradigm-level 失败 root cause(总结自 memory)

### 1. Switch fixation(iter 100)

iter 100 诊断发现 ~50% 动作选 Switch — agent 大量浪费 turn 在切换 character
而非攻击。Deep CFR advantage 估计在 GICG action distribution(highly imbalanced:
攻击 vs 切换 vs Tune)下可能 bias toward 低 visit-count actions(Switch),
形成自激励 visit pattern。

### 2. Value head 乐观

终局前 v=+0.2 但实际 0/10 输。可能成因:

- Shared trunk gradient leak — policy / advantage 训练 gradient 影响 value head
- Strat replay reservoir 老 traj 比例高,value target 基于已塌陷策略
- 2v2 fixed team 下 value head 学到 "team 配置好" 而非 "当前局面好"

### 3. Loss 与 policy quality 脱钩

strat_loss 1.3 → 1.045 视觉收敛,但 iter 100 wr = 0.00 vs random。Deep CFR 的
**loss 监控不可靠 as quality proxy** — 不像 supervised loss,advantage MSE 可以
在差策略上稳定下降。

### 4. d_model = 64 capacity 假设

未验证。GICG ActorCritic 通常 d_model ≥ 128;CFR prototype 用 64 是省 wall。
未试更大 d_model 之前不能断定 capacity 是根因。

## Closure 决策路径

- **2026-04-23**:r007 1500g killed → paradigm change 提出 Deep CFR
- **2026-04-23 ~ 04-24**:r008 run 启动,32.7h wall
- **2026-04-24**:iter 199 gauntlet 0.40 vs random / 0/10 vs everything →
  接受 r008 prototype FAIL,但未立即 closure(unit test 层 OK,
  config 可调,d_model 未尝试更大)
- **2026-04-25**:PPO 路线 BC warm-start 突破(s017),paradigm 主线回归 PPO
- **2026-04-26**:PPO Stage 3 ceiling 0.344 + AZ Stage 0-2 PASS,paradigm 转 AZ
- **2026-05-12**:user 评估扩展 closure 集合 — NFSP / Deep CFR redo 与
  r008 一并 closed(per memory `project_rl_routes_closure_2026_05_12`)
- **2026-05-12 之后**:DMC([`../dmc/`](../dmc/))作新主线

## 不 actionable 的 follow-up(知识保留)

完整列表见 [`runs.md`](./runs.md);要点:`advantage_reset_each_iter` / d_model
≥ 256 / per-iter gauntlet / value head 独立 opt。若未来证据强烈支持 Deep CFR
在 GICG-class imperfect-info game 可训(eg. some published large-pool result),
可基于 `training/cfr/` 现有 framework 直接复用。
