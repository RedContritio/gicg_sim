# 新 session 接手清单

**训练保持暂停，不自动续训。** 恢复前先核对本机与 56 是否仍有运行任务，
再读 [暂停交接](HANDOFF_PAUSED.md)。

当前状态以 [docs/0_status/README.md](0_status/README.md) 为唯一实时入口；本页只列接手步骤与约定。
周/月级目标、各步验收和待选方案见[执行路线图](3_plans/rule_learning_roadmap.md)：先核对当前关口
证据，再安排下一实验，不按日历推定已完成。

1. 读实时入口、[CLAUDE.md](../CLAUDE.md)、[项目目的](../openspec/project.md)、
   [暂停交接](HANDOFF_PAUSED.md)。当前目标是随机规则变体下稳定胜过 D2，**尚未完成**。
   不要沿历史 v15/旧卡池实验误续训。
2. `git branch --show-current` + `git status --short` 核对工作区：当前在 `dev`，工作区仍有
   `remote-host-decoupling` 实现和策略保留文档等未提交改动，且本地提交**尚未 push**；
   未 push 不阻塞本地验收，远端指针见实时入口。不要假定工作区干净。三项推理一致性修复已通过
   [集成验收](3_plans/inference_consistency_repairs.md)并合入 `main`。
3. `remote-host-decoupling` 已实施；本机测试、pre-commit、源码指纹中性验证、文档记录核对和
   本机端到端链路验证均通过，`configs/hosts/hosts.toml` 已建立。唯一未完成的验收是真实 56 的
   **远端首次同步与训练派发全链路验收**。该验收已获授权；当前等待 56 可用。设备上线后先只读探测：
   `.venv/bin/python -m tools.runs.exec --timeout 30 configs/dmc/native_starter.toml -- hostname`
   再确认没有活动训练：
   `.venv/bin/python -m tools.runs.status configs/dmc/native_starter.toml`
   `.venv/bin/python -m tools.runs.kill configs/dmc/native_starter.toml --dry-run --all`
   确认无活动训练后，串行执行一次：
   `.venv/bin/python -m tools.runs.train configs/dmc/native_starter.toml`
   该验收通过前不得 archive，远端运行前确认注册表存在，并继续只使用 56 的 `D:/gicg_dev`。
4. **源码指纹已变，旧权重不可用**：`fingerprint()` 现值与历史值见实时入口；旧 warmup/paired 权重
   加载会抛 `ArtifactCompatibilityError`。**本轮训练必须从头重训初始化**，不得给旧权重重标指纹。
5. 策略保留六臂正式对照已完成，选择
   `artifacts/202609160202_000021_retention_full/full_policy.pt` 进入下一轮等预算 RL。
   `warmup` 和 `full_lowlr`/`replay` 保留为本轮对照；不要重跑已消耗的六臂确认面板。
   `96600` 已用于选臂，后续晋级必须使用新的独立训练和确认 seed。
6. 评测纪律：**已被用于选模的面板不能再当独立证据**；开发面板与确认面板分开，正式对比用新 seed。
   差值报配对场景聚类 95%CI，并做臂对臂比较。不能把挑选后的开发胜率或 3 步 smoke 的机制数字当结论。
7. 未完成的全仓项：文档审计没有全仓人工审阅（以 `coverage.tsv` 为准）。网页回放已通过桌面与
   390px 移动端浏览器验收；不要把局部检查当全仓通过。

## 重要约定

- 训练阵容为原生凯亚/迪卢克/芭芭拉/砂糖/菲谢尔；3v3、每队 30 张随机合法牌；D2 是强标准，不需要 D3。
- 不保留受污染权重用于当前训练，不改指纹骗过兼容性检查。BC、DAgger 和引擎辅助监督不能称纯 RL；
  纯 RL 是长期独立方向。
- 大规模运算在 56。**每台设备只允许一个项目根**：现只有 `D:/gicg_dev`。实验之间的隔离靠 cfg 参数
  与 per-run 目录，**不靠另开根目录**——每个根各持一套 `artifacts/` 索引与 NNN 计数器，多根会让
  `show <NNN>` 不再唯一。**不要整树同步覆盖 56 的指纹目录**，只同步 `tools/` 与 `configs/`
  （`fingerprint()` 不覆盖它们）。
- 远端操作只走 `tools.runs._host` / `tools.runs.exec` / `tools.runs.train` 等封装，不手写
  `ssh` / `scp`。训练是重量级操作，必须逐个串行启动，禁止并发。
- 按需用 ≤200B 的 progress 查看进度；有完成脚本，不高频读取大日志。跨会话不能依赖聊天内的
  自动通知仍有效。
- 停止聊天、停止训练、提交工作区是三个不同操作；启动训练必须由用户明确要求。

## 最小接手提示词

> 阅读 CLAUDE.md、docs/0_status/README.md、docs/HANDOFF.md 和 docs/HANDOFF_PAUSED.md，
> 在当前 dev 工作区接手。部分改动尚未提交且未 push，未 push 不阻塞本地验收，先 git status 核对。
> 注意源码指纹已变，旧权重一律不可用。`remote-host-decoupling` 已实施并通过本机端到端链路
> 验证，真实 56 的远端首次同步与训练派发全链路验收已获授权，当前等待设备可用；策略保留六臂对照已完成并选择
> `full_policy.pt`。训练保持暂停，不自动续训。
> 继续目标：解决学习不到规则的问题，在随机变体下稳定胜过 D2。以原始评估与反事实证据判断完成，
> 不依据历史状态或单次开发胜率。

## 历史资料（不代表当前状态）

- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
