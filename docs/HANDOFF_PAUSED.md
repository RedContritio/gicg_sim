# 暂停交接

2026-09-14、2026-09-15 的三次暂停记录见
[暂停期会话记录](5_history/pause_sessions_20260914_0915.md)。
2026-09-16 设备恢复后已完成策略保留六臂正式对照和文档收尾；当前没有已知运行中的训练。
当前目标仍是「随机规则变体下稳定胜过 D2」，**仍未达成**。分支 `dev`，恢复时以
`git status` 核对工作区，不 reset/clean。

工作区包含未提交的 `remote-host-decoupling` 实现与策略保留文档；本地提交也尚未 push。
提交状态、运行产物和完整结论分别以 `git status`、[实时状态](0_status/README.md)与
[策略保留报告](5_history/policy_retention_20260916.md)为准。

## 恢复顺序

1. 读本页、`CLAUDE.md`、`docs/0_status/README.md`；`git status` 核对工作区，并检查本机与 56
   是否仍有运行任务。没有自动续训任务。
2. **「清理」已完成，不再是前置决策**：行数清理全部收尾，`gicg_env/libgicg.dylib` 已按新 Go 源码
   重建（指纹 `ff423c96…`）。兼容性前置已满足，但启动训练仍需用户明确要求。若之后再改
   `fingerprint()` 覆盖范围内的源码，
   须重新走「改完 → 重建 dylib」。`fingerprint()` 不含 `tools/` 与 `configs/`，改这两处无需重建。
3. `remote-host-decoupling` 已实施并通过本机端到端链路验证，`configs/hosts/hosts.toml` 已建立；
   本机测试、pre-commit、源码指纹中性验证与文档记录核对均通过。唯一未完成的验收是真实 56 的
   **远端首次同步与训练派发全链路验收**。该验收已获授权；当前等待 56 可用，change 尚未 archive。
   设备上线后先只读探测：
   `.venv/bin/python -m tools.runs.exec --timeout 30 configs/dmc/native_starter.toml -- hostname`
   再确认没有活动训练：
   `.venv/bin/python -m tools.runs.status configs/dmc/native_starter.toml`
   `.venv/bin/python -m tools.runs.kill configs/dmc/native_starter.toml --dry-run --all`
   确认无活动训练后，串行执行：
   `.venv/bin/python -m tools.runs.train configs/dmc/native_starter.toml`
   远端根统一为 `D:/gicg_dev`。
   **不要**全树同步覆盖 56 的指纹目录；只同步 `tools/` 与 `configs/`（`fingerprint()` 不含它们），
   远端操作只走项目封装，不手写 `ssh` / `scp`；训练按单个任务串行执行。
4. 策略保留六臂对照已完成。下一轮等预算 RL 从
   `artifacts/202609160202_000021_retention_full/full_policy.pt` 开始；`warmup` 用于对照，
   不要重跑六臂。`full` 与 `anchored` 的直接差值为 `anchored-full=+1.36pp
   [-6.82,+9.55]`，没有证据支持 `anchored` 更好，因此选择机制更简单的 `full`。
5. 评测纪律：开发面板与确认面板必须分开；**96400 与 96600 均已用于选模，不能再当独立证据**。
   下一轮正式对比必须用新 seed，差值报配对场景聚类 95%CI，并做臂对臂比较。
6. 最终三种子训练 seed 971000/981000/991000、测试 seed 971900/981900/991900 仍保留未用。
7. 文档审计未完成全仓人工审阅（以 `coverage.tsv` 为准）；网页回放已通过桌面与 390px 移动端
   浏览器验收。
