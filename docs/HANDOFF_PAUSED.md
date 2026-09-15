# 暂停交接

用户分三次要求停止任务：**2026-09-14**、**2026-09-14 晚**、**2026-09-15**（本次）。
当前目标仍是「随机规则变体下稳定胜过 D2」，**仍未达成**。分支 `dev`。恢复时以 `git status`
核对工作区，不 reset/clean。三次会话的完整叙事见
[暂停期会话记录](5_history/pause_sessions_20260914_0915.md)。

**没有任何一次会话启动过 56 训练**；所有产出都是本机代码 + 本机 smoke + 行数清理。三次会话的
改动均已提交到 `dev`，**尚未 push**（远端仍是 `dev`=`1e12d97` / `main`=`22c7345` /
tag `v0.3.0`）；提交条数以 `git log` 为准，本页不复述。

## 恢复顺序

1. 读本页、`CLAUDE.md`、`docs/0_status/README.md`；`git status` 核对工作区。没有自动续训任务。
2. **「清理」已完成，不再是前置决策**：行数清理全部收尾，`gicg_env/libgicg.dylib` 已按新 Go 源码
   重建（指纹 `ff423c96…`）。可直接进入训练。若之后再改 `fingerprint()` 覆盖范围内的源码，
   须重新走「改完 → 重建 dylib」。`fingerprint()` 不含 `tools/` 与 `configs/`，改这两处无需重建。
3. 策略保留实验的正式对照**需要在 56 上跑**（用户当前占用设备）。**前置是 change
   `remote-host-decoupling` 的 Phase 0**：先 ssh 实测 56 的 `socket.gethostname()` 再据此建
   `configs/hosts/hosts.toml`（配错会让 56 侧 `is_local_host` 判假、ssh 到自己成环）；此后
   所有 cfg 的远端根统一为 `D:/gicg_dev`。流程：
   a. 在该根上先跑 warmup（不要跑 `consequence_bootstrap`——它的 paired 阶段正是要研究的坏配置）：
      `python -m tools.experiments.semantic_training.train <cfg> <out> --episodes 256 --steps 2000
      --workers 16 --seed 95500 --device cuda --variants configs/rule_validation/native_variants.toml`
   b. 用产出的 `ckpts/latest.pt` + `teacher/` 跑：
      `python -m tools.experiments.semantic_training.policy_retention <cfg> <warmup.pt> <out>
      --teacher <teacher_dir> --steps 1500 --contexts 6 --device cuda --panel-scenarios 110 --probe`
   c. **不要**全树同步覆盖 56 的指纹目录；只同步 `tools/` 与 `configs/`（`fingerprint()` 不含它们）。
4. 评测纪律：开发面板与确认面板必须分开；**96400 已被用于选模，不能再当独立证据**，正式对比用
   新 seed（smoke 默认 `--panel-seed 96500`）。差值一律报配对场景聚类 95%CI，臂对臂比，
   不要只比"各臂 vs warmup"。
5. 剩一件早先收尾工作没做：为 `policy_retention` 补计划卡片（`docs/3_plans/cards/policy_retention.md`）
   并把本轮结论写入 `docs/5_history/`。
6. 最终三种子训练 seed 971000/981000/991000、测试 seed 971900/981900/991900 仍保留未用。
7. 文档审计未完成全仓人工审阅（以 `coverage.tsv` 为准）；网页 UI 仍缺浏览器视觉验收。
