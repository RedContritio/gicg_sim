# 教师具体动作模仿（executed 目标）：首个显著收益（2026-09-17 深夜）

协议卡 [executed_objective](../3_plans/cards/executed_objective.md)。
背景：三假设（后果残差 / 2× 数据 / d128 容量）证伪后，拟合审计
（`artifacts/imitation_gap_20260917/fit_warmup{1,2}.json`）显示 warmup 对教师数据
top-1 一致率 75.6%/80.3%（随机 ~28%）——不是欠拟合，而既有 `uniform`/`set`
目标按构造丢弃教师的具体选择（`executed_action` 字段一直落盘但未被使用）。

## 改动

`imitation_loss.py` 新增 `executed` 目标（教师动作交叉熵）；
`train.py` CLI `--tie-objective`（103 项测试全过）。`tools/` 不在源码指纹覆盖内，
无需重建 dylib。

## 结果（run 000051，256 局/2000 步，seed 96150，面板 96160）

| 模型 | vs F1-D2 原生（110 场景） | 拟合审计（96140 水库） |
|---|---|---|
| warmup1（uniform, run 000042） | 33.18% [27.3, 39.6] | 一致 75.6%，tied mass 0.62 |
| **warmup3（executed, run 000051）** | **41.36% [35.0, 47.7]** | 一致 75.2%，tied mass 0.60 |

**配对差 +8.18pp [+0.45, +15.45]，CI 下界 > 0**——2026-09-17 全战役首个显著收益。

## 结论

- 机制证实：教师（贪婪 F1-D2）的具体动作选择（含 tied 集内偏好与偶尔选到
  tied 集外）携带引擎恒等不表达的长程价值；uniform 目标把它均匀化抹掉后，
  推断时的 argmax 在集内近乎随机。
- 拟合度相同（75% vs 75%）而强度 +8pp：**目标而非容量/数据是模仿路线的关键变量**。
- 41.36% 仍未达 50%，但方向首次正确。下一步：① 目标修正后重测数据缩放
  （512 局/4000 步）；② RL 从 warmup3 出发；③ 变体面板复核零样本保留。

## 数据缩放复测（warmup4，run 000052，512 局/4000 步 executed，seed 96170；面板 96180）

| 模型 | vs F1-D2 原生（96180） |
|---|---|
| warmup1（uniform 256/2000） | 27.27% [21.4, 33.2] |
| warmup3（executed 256/2000） | 35.91% [30.0, 41.8] |
| warmup4（executed 512/4000） | 31.36% [25.5, 37.7] |

配对：warmup3 − warmup1 = **+8.64pp**（同 seed 复算 executed 收益，与 96160 的
+8.18pp 互为印证）；warmup4 − warmup3 = -4.55pp [-13.2, +4.5]——
**目标修正后数据缩放仍无收益**（第二次证伪）。面板间 seed 方差约 ±6pp
（warmup1 在 96160/96180 为 33.18/27.27），executed 收益量级记为 +4~9pp。

结论：最优初始化 = warmup3（256 局/2000 步 executed）。进入 RL 阶段
（[协议卡](../3_plans/cards/rl_from_executed_warmup.md)）。

## 产物

- 面板/配对：`artifacts/executed_objective_20260917/`（56）
- 拟合审计：`fit_warmup3.json`（同 `imitation_gap_20260917/fit_warmup{1,2}.json`）
- ckpt：`artifacts/202609172228_000051_semantic_warmup/ckpts/latest.pt`

## 种子

消耗：96150（训练）、96140（审计水库）、96160（面板）；96170/96180（warmup4
缩放）、96190（变体保留面板）。
