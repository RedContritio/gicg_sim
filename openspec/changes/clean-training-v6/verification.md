# 验证记录

- 训练主测试（含产物来源与五范式基础路径）：1113 passed，6 skipped。
- 工具/eval/runs 与 DMC 扩展测试最终全量：828 passed，1 skipped。
- DMC Go 子进程与组装器单独回归：35 passed；BC 数据来源子进程测试：1 passed。
- 针对旧来源、旧布局、原语扩行、评估随机策略/区间、种子初始化和清理白名单新增回归通过。
- 真实实验：3 个种子 × 基础 3000 帧、独立微调 250/1000 帧、同预算从零 1000 帧。
  每次按完整 episode 结束，所以实际帧数可略超预算。各 run 的 complete.json 保存实际计数。
- 正式评估共 1920 场，包含重复基线；全部终局，无 step-limit 截断。
- 同 seed 独立进程小训练重复：模型所有张量及逻辑状态逐项相等，仅墙钟时间不同。
- 配置/效果审计重新运行：6 配置，692 个槽位绑定，0 issues。
- 用户再次确认的回合顺序与当前实现相符：召唤物先结束方优先；普通印记跨方按产生顺序。
  相关致死顺序用例重新运行；无需修改规则或废弃本轮数据。
- 远端第一批 1580 文件、9,662,919,290 字节；补充明确清单 159 文件、12,958,026 字节。
  最终远端 artifacts 仅剩 .gitignore 与 .run_id_lock。详见 docs/0_status/remote-training-reset-2026-09-11.json。
- Ruff、新增/修改文件差异空白检查、OpenSpec 索引检查通过。

早期工具扩展测试暴露旧的 4096 长度组装器夹具和无来源 BC 合成数据，已改为当前布局及正式保存入口。
沙箱限制导致的 socket/shared-memory 测试失败已在获准的本机测试运行中复验。
旧初步评估覆盖了 random 的 epsilon，并错误组合得分与区间口径；这些初步评估文件已删除，
本目录 learning-results.json 来自独立校正后的正式重算。

## 复现入口

- `python -m tools.experiments.clean_learning --output <new-dir> --seed 41 --frames 3000 --scenarios 16`。
  对种子 42、43 分别执行；内部所有子进程显式固定随机源。
- 同预算新环境从零对照：用对应 adapt_<seed>_1000.toml，执行
  `python -m tools.experiments.train_seeded <cfg> <new-scratch-dir>`，不传 --initial。
- `python -m tools.experiments.finalize_learning artifacts/clean_v6_seed41 --seed 41` 生成正式逐场结果。
- `python -m tools.experiments.cost_learning --output <new-cost-dir>`。
- `python -m tools.experiments.primitive_expansion <cost-dir> <new-primitive-dir>`，包含原表示同训练量对照。
- `python -m tools.experiments.summarize_learning` 读取本次固定路径并生成版本化汇总。

所有命令从仓库根目录以 `.venv/bin/python -m` 执行。输出目录使用新目录，不覆盖既有实验。
本轮没有宣称长程收敛，也没有完成真正新增引擎机制后的学习验证。
