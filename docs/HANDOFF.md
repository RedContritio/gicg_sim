# 新 session 接手清单

**用户已要求暂停（第三次，本次会话结束时）。恢复请先读 [暂停交接](HANDOFF_PAUSED.md)，
不要自动启动训练。**

当前状态以 [docs/0_status/README.md](0_status/README.md) 为唯一实时入口；本页只列接手步骤与约定。
周/月级目标、各步验收和待选方案见[执行路线图](3_plans/rule_learning_roadmap.md)：先核对当前关口
证据，再安排下一实验，不按日历推定已完成。

1. 读实时入口、[CLAUDE.md](../CLAUDE.md)、[项目目的](../openspec/project.md)、
   [暂停交接](HANDOFF_PAUSED.md)。当前目标是随机规则变体下稳定胜过 D2，**尚未完成**。
   不要沿历史 v15/旧卡池实验误续训。
2. `git branch --show-current` + `git status --short` 核对工作区：三次暂停的改动均已按逻辑单元
   提交本地 `dev`、**尚未 push**；远端指针见实时入口。不要假定工作区干净。三项推理一致性修复
   已通过[集成验收](3_plans/inference_consistency_repairs.md)并合入 `main`。
3. **先满足 change `remote-host-decoupling` 的 Phase 0 再碰远端**（`openspec/changes/remote-host-decoupling/`，
   已提交、未执行）：先 ssh 实测 56 的 `socket.gethostname()`，再建 gitignored 的
   `configs/hosts/hosts.toml`——配错会让 56 侧 `is_local_host` 判假、ssh 到自己成环
   （design.md §R1）。**T4.5 远端 e2e 通过前不得 archive**，而它需要设备开机。
4. **源码指纹已变，旧权重不可用**：`fingerprint()` 现值与历史值见实时入口；旧 warmup/paired 权重
   加载会抛 `ArtifactCompatibilityError`。**本轮训练必须从头重训初始化**，不得给旧权重重标指纹。
5. 策略保留实验代码已就绪（本机 6 臂 smoke 全通），但**正式对照尚未在 56 跑过**：按暂停交接的
   恢复顺序先 warmup，再用产出的 `ckpts/latest.pt` + `teacher/` 跑 `configs/dmc/policy_retention.toml`。
   **不要**跑 `consequence_bootstrap`——它的 paired 阶段正是要被隔离的坏配置。
6. 评测纪律：**已被用于选模的面板不能再当独立证据**；开发面板与确认面板分开，正式对比用新 seed。
   差值报配对场景聚类 95%CI，并做臂对臂比较。不能把挑选后的开发胜率或 3 步 smoke 的机制数字当结论。
7. 未完成的全仓项：文档审计没有全仓人工审阅（以 `coverage.tsv` 为准）；网页 UI 已实现但仍缺浏览器
   视觉验收。不要把局部检查当全仓通过。

## 重要约定

- 训练阵容为原生凯亚/迪卢克/芭芭拉/砂糖/菲谢尔；3v3、每队 30 张随机合法牌；D2 是强标准，不需要 D3。
- 不保留受污染权重用于当前训练，不改指纹骗过兼容性检查。BC、DAgger 和引擎辅助监督不能称纯 RL；
  纯 RL 是长期独立方向。
- 大规模运算在 56。**每台设备只允许一个项目根**：现只有 `D:/gicg_dev`。实验之间的隔离靠 cfg 参数
  与 per-run 目录，**不靠另开根目录**——每个根各持一套 `artifacts/` 索引与 NNN 计数器，多根会让
  `show <NNN>` 不再唯一。**不要整树同步覆盖 56 的指纹目录**，只同步 `tools/` 与 `configs/`
  （`fingerprint()` 不覆盖它们）。
- 按需用 ≤200B 的 progress 查看进度；有完成脚本，不高频读取大日志。跨会话不能依赖聊天内的
  自动通知仍有效。
- 停止聊天、停止训练、提交工作区是三个不同操作；用户未要求本次停止远端训练。

## 最小接手提示词

> 阅读 CLAUDE.md、docs/0_status/README.md、docs/HANDOFF.md 和 docs/HANDOFF_PAUSED.md，
> 在当前 dev 工作区接手。改动已提交到 dev 但未 push，先 git status 核对。
> 注意源码指纹已变，旧权重一律不可用。本轮主要产物是策略保留实验（6 臂，本机 smoke
> 已通但未上 56）；另有一个已定稿未执行的 change `remote-host-decoupling`（远端主机标识外置 +
> HEAD 脱敏），其 Phase 0 是任何远端运行的前置。
> 继续目标：解决学习不到规则的问题，在随机变体下稳定胜过 D2。以原始评估与反事实证据判断完成，
> 不依据历史状态或单次开发胜率。

## 历史资料（不代表当前状态）

- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
