# 显式后果残差匹配 RL

2026-09-17 已完成并否决加预算：配对差 candidate−control = 0.0pp [0,0]（440 局
配对面板逐局相同），残差 RL 未改变策略；规则学习复现且 paired 差值目标优于
纯绝对值目标，但初始骨干只有 19.55%（变体 vs D2），瓶颈在骨干强度。
结果见[历史报告](../../5_history/consequence_residual_20260917.md)。

## 原始记录（2026-09-17 启动时）

路线图方法选择表「预测已响应，策略仍按旧偏好」行的首选方案：
把模型预测后果显式输入动作评分，零初始化残差，保留完整对局胜负奖励，并与同预算
同初始化对照比较（09-14 报告预定的下一候选；Week 2 行记录的「已试但未证明」
对应 56 上 000032–000040 无文档运行，按协议不继承，本轮为新指纹下的正式执行）。

## 问题

规则预测已能响应数值变化（09-17 复现中 `full` 臂规则学习通过），但策略偏好不按
后果改变；配对监督本身会改写共享 Q 表征（09-16 机制结论），09-17 复现中使策略
相对 warmup 明确退化 -10pp。本实验检验：在冻结的（可能受损的）配对骨干上，
只训练零初始化残差、并把规则头预测后果作为残差输入（候选臂），能否相对
「同样残差但后果输入置零」的对照臂获得完整对局收益。

这不是 D2 强度验收；它回答「显式后果输入是否带来独立收益」，为后续是否沿此
方向加预算提供依据。

## 设计

工具链：`consequence_bootstrap`（warmup→paired→export）→ `consequence_rl`
（双臂匹配 RL→留出选模→独立复核）。本轮**跳过 bootstrap 的 warmup 阶段**，
直接复用 run `000042` 的 warmup（同为指纹 `afa1cdcd…`、seed 95500、256 局/2000 步、
同一 catalog；bootstrap 默认参数与该运行一致，重跑只产生近重复产物），
只执行 paired → export → residual RL。跳过理由与产物哈希记录在本卡与历史报告。

- paired_training：seed 95820，1500 步，contexts 6，两臂内部对照
  （paired β=1 / absolute β=0，后者即「回归目标分解」参考）；导出 `paired.pt`。
- export：seed 95830，生成 matched initials：`candidate.pt`
  （use_consequences=True）与 `control.pt`（False），骨干与规则头冻结、
  残差零初始化、初始权重逐张量相同。
- consequence_rl：seed 95840（dev 95930、选模 95940、复核 96040），
  4 轮 × 512 局/臂，F1-D2 对手与开发，temperature 0.5，value baseline，
  lr 1e-5，anchor KL 0.02，clip 0.2；`native_variants.toml` 混合。
  RL 只训练残差 MLP（骨干与规则头 requires_grad=False）。
  每臂按 dev 选最早最优轮；独立复核 = 110 场景 × 双方 × 2 布局、
  变体规则 vs F1-D2（440 局/模型），报场景聚类 95% CI 与配对差。

## 固定协议

- 只在 56（`D:/gicg_dev`）执行；前置同步 `_remote_sync --auto` 完成。
- 源码指纹 `afa1cdcd…`（453fde0 后）；`tools/` 与 `configs/` 不在指纹覆盖内，
  本轮未改它们。
- 种子：paired 95820、export 95830、RL 95840/95930/95940/96040。
  95500（warmup，复用不消耗）、95000（协议固定复现）沿用既有记录。
- 产物根：`artifacts/consequence_residual_20260917/`（56）。
- 判读：候选臂配对差（candidate−control，复核面板）区间下界 > 0 才算
  「显式后果输入有收益」；点估计为正但区间跨 0 记为未证明；为负则否决该方向。
  两臂绝对得分只作参考，不与 warmup/旧 RL 直接比（初始化不同源）。
