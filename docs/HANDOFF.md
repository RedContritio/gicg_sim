# 新 session 接手清单

**用户已要求暂停（第三次，本次会话结束时）。恢复请先读 [暂停交接](HANDOFF_PAUSED.md)，
不要自动启动训练。**

当前状态以 [docs/0_status/README.md](0_status/README.md) 为唯一实时入口；本页只描述接手步骤。

周/月级目标、各步验收和待选方案见[执行路线图](3_plans/rule_learning_roadmap.md)。先核对当前关口
证据，再安排下一实验，不按日历推定已完成。

1. 读实时入口、[CLAUDE.md](../CLAUDE.md)、[项目目的](../openspec/project.md)、
   [暂停交接](HANDOFF_PAUSED.md)。当前目标是随机规则变体下稳定胜过 D2，**尚未完成**。
   不要沿历史 v15/旧卡池实验误续训。
2. `git branch --show-current` + `git status --short` 核对工作区。前两轮累积的改动已在
   2026-09-15 会话按逻辑单元分 9 个 commit 提交到 `dev`，**尚未 push**；远端 `gicg_sim` 仍是
   `dev`=`1e12d97` / `main`=`22c7345` / tag `v0.3.0`。三项推理一致性修复已通过
   [集成验收](3_plans/inference_consistency_repairs.md) 并合入 `main`。
3. **源码指纹已变，旧权重不可用。** 实测 `fingerprint()` =
   `ff423c96eaf01807ad11eb17543b726571039cc20ba7f80f37c74e5c7664db15` —— 拆 `interp/ir/` 下的
   Go 文件后再次变更（前值 `d8a09342…`，更早 `c2af135c…` / `b3e84a0a…`）。旧 warmup/paired 权重
   加载会抛 `ArtifactCompatibilityError`；`artifacts/pause_20260914/checkpoints/` 已按用户要求清空。
   **本轮训练必须从头重训初始化**，不得给旧权重重标指纹。
4. 策略保留实验（本轮主要产物）代码已就绪、本机 6 臂 smoke 全通，但**正式对照尚未在 56 跑过**。
   代码位置与 smoke 数据见暂停交接；恢复时先确认 `configs/dmc/policy_retention.toml` 的
   `[remote].root`（现填 `D:/gicg_retention_20260915`，**未经用户确认**），再按暂停交接的
   恢复顺序第 3 条跑 warmup + `policy_retention`。**不要**跑 `consequence_bootstrap`——它的
   paired 阶段正是要被隔离的坏配置。
5. 评测纪律：96400 面板**已被用于选模**，不能再当独立证据；开发面板与确认面板分开，正式对比用
   新 seed（默认 96500）。差值报配对场景聚类 95%CI，并做臂对臂比较。不能把挑选后的开发胜率
   当最终结论，也不能把 3 步 smoke 的机制数字当效果结论。
6. **行数清理已完成**（2026-09-15）：20 个存量违规全部处理，`check_line_limits` 零违反；
   `gicg_env/libgicg.dylib` 已按新源码重建；`CLAUDE.md` 阈值表新增 Go 测试 500 档。剩余未处理的
   只有 `docs/3_plans/cards/effect_mechanism_inventory.md`（被 gitignore、从未入库），用户明确
   决定暂不处理。详见暂停交接。
7. 文档审计未完成全仓人工审阅（以 `coverage.tsv` 为准）；网页 UI 已实现但仍缺浏览器视觉验收。
   不要把局部检查当全仓通过。

## 重要约定

- 训练阵容为原生凯亚/迪卢克/芭芭拉/砂糖/菲谢尔；3v3、每队 30 张随机合法牌；D2 是强标准，
  不需要 D3。
- 不保留受污染权重用于当前训练，不改指纹骗过兼容性检查。BC、DAgger 和引擎辅助监督不能称纯 RL；
  纯 RL 是长期独立方向。
- 大规模运算在 56；其旧 `D:/gicg_dev` 和 `D:/gicg_goal` 是历史目录，不随便清理。**不要整树同步
  覆盖 56 的指纹目录**，只同步 `tools/` 与 `configs/`（`fingerprint()` 不覆盖它们）。
- 按需用 ≤200B 的 progress 查看进度；有完成脚本，不高频读取大日志。跨会话不能依赖聊天内的
  自动通知仍有效。
- 停止聊天、停止训练、提交工作区是三个不同操作；用户未要求本次停止远端训练。

## 最小接手提示词

> 阅读 CLAUDE.md、docs/0_status/README.md、docs/HANDOFF.md 和 docs/HANDOFF_PAUSED.md，
> 在当前 dev 工作区接手。前两轮改动已分 9 个 commit 提交到 dev 但未 push，先 git status 核对。
> 注意源码指纹已变为 ff423c96…，旧权重一律不可用。本轮主要产物是策略保留实验（6 臂，本机 smoke
> 已通但未上 56），以及已收尾的行数清理（全仓零违规）。
> 继续目标：解决学习不到规则的问题，在随机变体下稳定胜过 D2。以原始评估与反事实证据判断完成，
> 不依据历史状态或单次开发胜率。

## 历史资料（不代表当前状态）

- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
