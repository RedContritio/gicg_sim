# 教师具体动作模仿（executed 目标）

2026-09-17 完成，**首个显著收益**：配对 +8.18pp [+0.45,+15.45]（41.36% vs 33.18%
vs F1-D2，seed 96160），证实教师具体动作选择的价值被 uniform 目标丢弃。
结果见[历史报告](../../5_history/executed_objective_20260917.md)。

## 原始记录（2026-09-17 启动时）

- warmup1/warmup2 对教师数据的 top-1 一致率 75.6%/80.3%（随机基线 ~28%），
  tied 集概率质量 0.62/0.65——**不是欠拟合**；且拟合更好的 warmup2 对局强度
  并无提升（+0.91pp 跨 0）。
- 既有目标 `uniform`/`set` 只对「引擎 tied 集」拟合，**按构造丢弃教师的具体
  选择**；而教师（贪婪 F1-D2）有时会选 tied 集之外的动作，其集内选择可能携带
  引擎恒等不表达的长程价值。

## 假设与改动

把教师具体执行动作（`executed_action`，数据行已有）作为交叉熵目标
（`tie_objective='executed'`，`imitation_loss.py` 新增，train CLI
`--tie-objective`），其余与 run 000042 完全一致。预期：若教师偏好有信息，
warmup3 的 D2 面板应相对 warmup1 有配对增益；若仍为 0，则模仿路线到头，
应转纯 RL/搜索支线。

## 固定协议

- 同 cfg（`configs/dmc/native_starter.toml`）、同预算（256 局/2000 步、workers 16、
  50% 变体）、同指纹 `afa1cdcd…`；`tools/` 不在指纹覆盖内，本轮改了
  `imitation_loss.py`/`train.py`（含测试，103 项全过）。
- 种子：训练 96150；拟合审计复用 96140；面板 96160（warmup3 与 warmup1
  同场景配对）。
- 判读：配对差（warmup3 − warmup1，110 场景 vs F1-D2）区间下界 > 0 才算收益；
  跨 0 则模仿路线（数据/容量/目标）全部证伪。
- 产物根：`artifacts/executed_objective_20260917/`（56）。
