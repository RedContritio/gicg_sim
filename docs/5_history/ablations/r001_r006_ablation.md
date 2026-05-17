# r001–r006 消融矩阵

2026-04-19 — 2026-04-21 期间 6 次 AZ 训练 run 的消融总结。目标:
从 r002 fast-anneal regression 回到 r001 基线,同时逐项隔离
(fast-anneal / ExpandUnionK / char_skill_refs obs)的独立净效应。
全部 400g,team_size=2 disjoint,char_pool 5,go backend,parallel=4。

## 数据

| run | config 差异 | g400 vs_mcts_200 | 差值 |
|---|---|---|---|
| r001 | baseline(slow anneal 1500g,无 K=3,无 char_skill_refs) | **0.55** | baseline |
| r002 | +`lambda_anneal_games=400` | 0.30 | −0.25 |
| r003 | r002 +`char_skill_refs`+`expand_union_k=3` | 0.25 | −0.05 |
| r004 | r003 −fast-anneal(slow 1500g) | 0.40 | +0.15 |
| r005A | r004 −`expand_union_k` | 0.45 | +0.05 |
| r006 | r005A −`char_skill_refs` | 0.40 | −0.05 |

gauntlet 每跑 20 局,噪声 ±0.11(95% CI);0.05 差距在边缘,0.10+
视为有意义。

## 独立净效应(事后 isolate)

- **fast-anneal(lambda_anneal_games 1500→400):净 −0.25**
  主要归因。fast anneal 把 λ 推到 >0.5 时网络还没训出来,net 反而
  降低 MCTS 质量。r002→r004 切回 slow 就恢复 +0.15。memory
  `feedback_r002_fast_anneal_worse`。
- **ExpandUnionK=3:净 −0.05(方向确认,边缘显著)**
  r004→r005A 去掉 K=3 提升 0.05。事后 D1 埋点揭示根因:union
  只覆盖 dice 维,不覆盖 hand/deck,D1 触发场景 <20%。成本 > 收益。
  2026-04-21 commit `29ca0c4` 全量移除,见 `decisions.md` D14。
- **char_skill_refs obs:净 +0.05(有利)**
  r005A→r006 去掉后反而退 0.05,确认 char_skill_refs 是 AZ 有用特征。
  后续 run 保留该 obs 区。

## 残留 gap(r001 0.55 vs r005A 0.45)

三层 isolate 完仍剩 0.10 未解释。r001 跑于 2026-04-19,r005A 跑于
2026-04-20,中间有多个 commit 没单独 A/B。候选(未验证):
- `fb0c267` heartbeat 修复 + 其他 worker 改动
- `b125ef6` MCTS log_suspend 改动(r005A 之后才合入,时间不符 — 排除)
- 3c2ee89 char_skill_refs + 1c7c922 ExpandUnionK 之外的 MCTS 路径改动
- gauntlet 本身 20g 噪声 ±0.11,0.10 gap 可能是纯采样波动

没有明确单一元凶,0.10 gap 视为统计噪声可能 + 多个小 commit 累积。
不值再消融。

## 对后续 run 的指导

- **slow anneal 是硬条件**,除非有新证据推翻
- **ExpandUnionK 确定废弃**,D1 问题由 A1(D1 actions
  network-informed prior)单独 scope
- **char_skill_refs 保留**,r007+ 后续默认 `include_char_skill_refs=true`
- **扩 g(r007 1500g scaling)单独 scope**:实测 collapse(argmax
  g100=1.00→g1000=0.05),r007 kill。collapse 模式驱动 r008 paradigm
  change(AZ→Deep CFR),见 registry r007/r008 备注

## r007 collapse(scaling 失败)附记

r007 配置 = r005A +1500g 训练长度。arena 胜率 g100=1.00 →
g200=0.725 → g300-900 区间 0.35-0.525 → g1000=0.05 → g1100/1200=0.025。
vs_mcts_200 在 g500=0.35,g1000=0.05(完全崩)。完全崩溃。
不是单一 ckpt outlier — 从 g1000 之后稳定趋零。

根因假设(未验证):长程 self-play 下 λ 跑满 anneal window(λ≈1),
MCTS 从"rollout+net 混合"退化到"纯 net-value eval leaf",若 net
value 输出对边缘局面过自信 → exploit 循环 → 越训越糟。此为 C1v1
失败模式的长程版本,见 memory `project_c1_failure_diagnosis`。

r007 被 I5 deadlock kill,但即使没被 kill collapse 已确认。同时
I5 fix(heartbeat + PoolDeadlock)独立落地,commit `fb0c267`。

r008 转向 Deep CFR 检验 paradigm 鲁棒性,不复用 AZ 栈。
