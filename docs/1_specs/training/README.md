# 1_specs/training/ — 训练栈 (shipped)

| 文件 | 用途 |
|---|---|
| [`az_loop.md`](az_loop.md) | AZ self-play → buffer → train → arena → gauntlet 端到端 |
| [`implementation.md`](implementation.md) | 代码布局、测试策略、阶段任务清单 (含 r001 g400 status) |

栈分层:
- `training/framework/` — 算法无关基础 (obs / step / matchup / inference)
- `training/az/` — AlphaZero 专属
- `training/cfr/` — Deep CFR (r008 后冻结)
- `training/ppo/` — Curriculum era PPO (Stage 0-3)

详见 ADR `training_layout` (在 `../../2_decisions/`)。
