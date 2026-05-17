# 实施计划

> 状态（2026-04-19）：**阶段 B 完成,架构通过 3 scenario 验证**。
> r001 (team_size=2 random, 400g) **g400 vs mcts_200 = 0.55**,
> 同时超越 C1v7 400g 与 C3 200g。Go backend 切到 production,
> 11% 加速无质量回归。#152 mirror-match double-fire 修复,DSL 层
> 显式 actor filter。DSL parse cache + preload 防止 mid-run edit
> 崩溃。当前 r002 (fast_lambda_400g) 进行中。历史 C1v1-v4 见
> `../../history/az/c1_postmortem.md`,C1v6 见
> `../../history/az/c1v6_plan.md`。

本文档记录了从当前 PPO 代码库迁移至可运行的 AlphaZero + IS-MCTS
训练栈所需的有序工作，遵循 `decisions.md` 中的设计决策。

### 计划外的关键架构新增

以下组件未在原始计划中，但在实施过程中被证明必要并已完成：

- **B+C 推理服务器**（`training/framework/inference/server.py` +
  `training/az/inference_pool.py`）：跨 worker 合并 MCTS leaf eval
  为动态 batch，解决 worker-per-agent 架构中 batch=1 推理互抢 CPU
  的瓶颈。详见 `parallel_inference.md`。
- **虚损失 MCTS**（virtual loss）：单 worker 内并行多条 rollout，
  用虚损失避免重复走同一路径。单 worker 从 41.4s → 21.3s（1.94×）。
- **AlphaGo-mode 叶节点评估**（rollout mixing）：网络价值估计与
  纯 rollout 回报的 λ 混合。C1v1 发现网络价值有害后引入，
  `value = λ·V_net + (1-λ)·V_rollout`。

## 阶段概览

| 阶段 | 目标 | 状态 |
|---|---|---|
| B | 核心训练栈 | ✅ 全部完成 |
| C | MVP 场景验证 | ✅ C1v7 通过 (argmax vs mcts_200=0.45) / C3 进行中 |
| D | PPO 栈清理（C 通过后执行） | D3 已完成，D1/D2/D4 已在 C1v7 前完成 |
| E | 扩展特性（骰子、角色、构组） | 骰子已落地；角色 CharEncoder 未 shipped；构组未来 |

## 阶段 B — 核心训练栈

### B0：引擎隐藏状态注入 API ✅

**目标**：IS-MCTS 确定化需要在搜索时覆写对手的手牌和牌堆内容。

**工作内容**：
- Go：`gicg_engine/game.go` 中新增 `Game.SetPlayerHand(player int, refs []int)`
- Go：`Game.SetPlayerDeck(player int, refs []int)`
- capi：`gicg_engine/capi/capi.go` 中导出 `GameSetPlayerHand` 和 `GameSetPlayerDeck`
- Python：`gicg_env/engine.py` 中新增 `GicgEngine.set_player_hand(player, refs)` 和
  `set_player_deck(player, refs)`
- Python：`GicgEnv` 上的环境层包装函数
- Go 测试：设置手牌 → 合法行动反映新手牌；设置牌堆 →
  下次摸牌取到新顶牌；往返保存/设置/验证
- Python 测试：确定化不影响其他状态（计数器、弃牌区等）

**预计耗时**：1 天

**阻塞**：B1、B2

### B1：确定化采样器 ✅

**目标**：在每次 rollout 时，根据智能体的观察采样合理的隐藏状态。

**工作内容**：
- `training/az/determinize.py`
- 类：`CardPoolSpec` 协议，`SharedFixedPool` 具体实现（MVP）
- 函数：`sample_hidden_state(env, viewing_player, spec, rng)`
- 测试：合法性（手牌大小匹配，无卡牌超出最大副本数），
  确定性（固定种子 = 相同输出），边界情况（空牌堆、满弃牌区）

**预计耗时**：0.5 天

**阻塞**：B2

**依赖**：B0

### B2：IS-UCT MCTS 实现 ✅

**目标**：实现 `mcts_design.md` 中的核心搜索算法。

**工作内容**：
- `training/az/mcts/`
- `MCTSNode` 数据类，每个子节点含 `N`、`W`、`N_avail`、`prior`、
  `leaf_value`、`terminal`、`winner`
- `mcts_search(env, network, config, rng)` 主入口
- 带 `N_avail` 探索奖励的 PUCT 选择
- 懒扩展 + 网络价值叶节点评估
- 根节点狄利克雷噪声注入
- 自对弈中基于温度的行动采样
- 在 rollout [50, 100, 200, 400] 处记录检查点
- 发现事件检测（D13 模式 A）
- 后续新增：虚损失并行 rollout、AlphaGo-mode rollout mixing 叶节点评估
- 测试：已知正确答案的小型确定性博弈（例如"1 步必胜"局面）；
  验证访问分布是否正确集中

**预计耗时**：1.5 天

**阻塞**：B5、B6

**依赖**：B0、B1、B3

### B3：网络头重定向 ✅

**目标**：去除 PPO 专用损失，添加 AZ 专用损失，
重构主干以支持共享多头使用。

**工作内容**：
- `training/az/network/` + `training/framework/network/`（多文件拆分重构）
- 删除：`RewardNormalizer` 集成、每环境缓存、`sample_action` PG 方法
- 添加：`forward(obs) -> (logits, value)` 作为主入口
- 添加：`dice_combo_proj` MLP（8 → d_model），通过残差加法接入行动特征计算
- 添加：带特征的 `CardEncoder` 扩展（特征 MLP 残差）
- 添加：基于特征表示的新版 `CharEncoder`
- 添加：多头分发（`forward(obs, phase="tactical")`），
  但今天只实现 tactical 头
- 损失：`value_loss = MSE(v, z)`，`policy_loss = CE(visits, logits)`，
  加 L2 权重衰减
- 价值头输出 `tanh` 限界至 [-1, 1]
- 测试：前向传播形状正确性、损失计算、梯度流、各层初始化

**预计耗时**：1 天

**阻塞**：B2、B5

### B4：环境奖励简化 ✅

**目标**：按 D5 决策去除奖励塑形。

**实际结果**：在 AZ 迁移前已完成最小奖励重构（damage + win 仅 3 系数），
AZ 训练侧完全忽略局内 reward，只用终局 z。

**预计耗时**：0.5 天

**与 B3 并行执行**。

### B5：回放缓冲区 + 训练循环 ✅

**目标**：实现 `training_loop.md` 中的训练侧工作线程。

**工作内容**：
- `training/az/buffer.py` — `ReplayBuffer` 环形缓冲区
- `training/az/train_step.py` — `train_step(network, batch)` +
  `TrainingWorker` 类
- `training/az/train_az.py` — AZ 主训练循环入口
- 损失计算和优化器更新
- 定期检查点保存
- 指标日志（`metrics.jsonl`）
- 测试：缓冲区循环正确、优先级采样无偏、
  `train_step` 在合成任务上产生下降的损失

**预计耗时**：1.5 天

**依赖**：B3

### B6：自对弈工作线程 + 对局配置解析器 ✅

**目标**：实现 `training_loop.md` 中的自对弈侧工作线程。

**工作内容**：
- `training/az/selfplay.py` — `play_game(network, config, rng)`
- 温度调度、狄利克雷噪声、轨迹构建
- `training/az/config.py` — 配置解析
- 测试：完整对局端到端运行，验证轨迹包含合法的 (obs, pi, z) 元组

**预计耗时**：1 天

**依赖**：B2

### B7：配置 + 入口点 + 擂台评估 ✅

**目标**：将所有内容整合为可运行的训练命令。

**工作内容**：
- `training/az/train_az.py` — AZ 训练主入口
- `training/az/arena.py` + `training/framework/gauntlet.py` — 擂台评估
- `training/az/inference_pool.py` — 推理服务器 + 多 worker 自对弈编排
- 信号处理：SIGINT 保存检查点并干净退出
- 测试：运行端到端 smoke test，验证无崩溃

**预计耗时**：0.5 天

**依赖**：B5、B6

## 阶段 C — 验证

### C1：1v1 L1 训练运行 🔄

**目标**：完整性检查，确认完整循环可运行、损失下降、
网络能够学到有效策略。

**退出标准**：总损失下降，1k 局后网络 vs 随机基线胜率 > 80%

**实际进展**：

- **C1v1（网络价值）**：❌ 失败。纯网络价值估计对搜索质量有害——
  网络在训练早期输出的 value 噪声大且带偏差，MCTS 用这个值做
  backup 反而比均匀 prior + rollout 更差。诊断工具：
  `tools/diag_net_plus_mcts.py`。
- **C1v2（纯 rollout）**：✅ 验证通过。去掉网络价值，叶节点用纯
  rollout（随机 playout 至终局）做评估，MCTS 搜索质量显著好于随机，
  确认 IS-MCTS + rollout 基线可工作。诊断工具：
  `tools/diag_is_mcts_baseline.py`、`tools/diag_is_mcts_with_rollout.py`。
- **C1v3-v4（lambda 退火 + 单角色 mirror）**：AlphaGo-mode 叶节点评估，
  `value = λ·V_net + (1-λ)·V_rollout`。C1v3 lambda=0.3 固定；C1v4 lambda 0→0.8
  退火。**都在单角色 mirror match 退化场景下跑，不具备泛化意义**。详见
  `../../history/az/c1_postmortem.md`。
- **C1v5-v6（hook gradient bug 修复 + aux loss）**：F run 发现 hook_encoder
  梯度断流 bug，C1v6 是修复后首跑，但 cross-attn pool 零空间使 aux loss
  无效。g200 arena wr=0 崩盘。详见 `../../history/az/c1v6_plan.md` +
  `memory/project_cross_attn_saturation.md`。
- **C1v7（struct_readout 架构）**：✅ 通过。结构性 sid pinning + struct_head
  绕过 pool 零空间。400g 无崩，arena g100/g200/g300/g400 健康，final
  argmax vs mcts_200 = 0.45。首次公平泛化验证通过。详见 memory
  `project_c1v7_success.md`。

**依赖**：B7

### C2：1v1 L1+L2 训练运行

**目标**：验证引入 L2 卡牌不会导致训练不稳定。

**工作内容**：
- 从 C1 检查点继续，或使用 1v1 L1+L2 配置重新开始
- 运行 2-6 小时
- 退出标准：损失收敛，组合发现率 > 0

**预计耗时**：1 天

**依赖**：C1

### C3：2v2 L1+L2 训练运行

**目标**：**关键测试**。这是 PPO 曾在 phase1b 遭遇平台的场景。
若 AZ 在此取得成功，则迁移得到验证。

**工作内容**：
- 使用 2v2 配置继续训练
- 运行 4-12 小时
- 退出标准：AZ 训练所得检查点在擂台中击败原始 MCTS 基线
  和之前保存的 phase1a PPO 检查点

**预计耗时**：1-2 天

**依赖**：C2

### C4：多进程自对弈扩展 ✅

**目标**：验证并行自对弈能带来等比例加速。

**实际结果**：通过 B+C 推理服务器架构实现。详见 `parallel_inference.md`。

实测加速（d_model=64, 400 rollouts, 4 games）：
- nw=1 serial → nw=4：41.4s → 17.5s（2.37×）
- nw=1 par=4 → nw=4 par=4：21.3s → 11.8s（1.81×）
- 虚损失 par=4 在单 worker 内提供 1.94× 额外加速

MPS GPU 在 d_model=64 下 3-4× 慢于 CPU（kernel launch overhead），
暂不使用。

**依赖**：C1（任何训练运行均可）

## 阶段 D — PPO 清理

**仅在阶段 C 退出标准达到后执行。** 验证期间必须保留现有 PPO
栈，以便可以回退。

### D1：删除 PPO 训练代码

- 删除 `training/ppo.py`、`training/rollout.py`、
  `training/selfplay.py`、`training/stage_loop.py`、
  `training/opponent_pool.py`、`training/reward_norm.py`
- 删除 `training/tests/test_opponent_pool.py` 及其他 PPO 专用测试
- 更新 `training/__init__.py` 导入

### D2：删除 PPO 配置 ✓

- `configs/curriculum/`、`configs/stages/phase*.toml` 已删除(2026-04-19)
- `configs/az/` 子目录也同期取消,所有 TOML 直接放在 `configs/`

### D3：弃用旧文档 ✓

- PPO 时代训练与网络文档(原 `docs/training/`、`docs/network/`、
  `docs/decisions/training_design.md`)已整体归档至
  `../../5_history/eras/ppo_pre_az/`(2026-04-15 归档,2026-04-26 docs 大改后路径变为 `5_history/eras/`)。详情见
  `../../5_history/eras/ppo_pre_az/README.md`。

### D4：更新 CLAUDE.md

- 更新命令 / 路径 / 架构章节以反映 AZ 栈
- 删除对 PPO 时代概念的引用（阶段、池 ELO、奖励塑形）

**阶段 D1-D4 总预计耗时：2-3 天。**

## 阶段 E — 扩展特性（未来）

以下条目仅作完整性记录，**不在当前迁移范围内**。
每项均是在 AZ 栈之上的实质性功能添加。

### E1：骰子机制

见 `dice_spec.md`。约 5-7 天的引擎 + 网络工作。

### E2：角色池扩展

通过基于特征的 CharEncoder（B3 中已预留）扩展至 100-300 个角色。
实际添加 100+ 个角色 DSL 文件是独立的游戏内容任务。

### E3：构组阶段

见 `decisions.md` D11。新增引擎阶段、新策略头、自对弈循环扩展。约 3-5 天。

### E4：卡牌池扩展至 1000+

扩展基于特征的 CardEncoder（B3 中已预留）。游戏内容是独立任务。

### E5：贝叶斯确定化

将 `determinization.py` 从 `SharedFixedPool` 升级至
`UniformFromPool`，再到 `BayesianFromPlayHistory`。每步约 2-3 天。

## 测试策略

每个模块有各自的单元测试：
- `training/tests/test_mcts.py` — 确定性博弈可解性
- `training/tests/test_buffer.py` — 环形缓冲区正确性、优先级采样
- `training/tests/test_determinize.py` — 采样器合法性
- `training/tests/test_network_az_{trunk,agent,losses}.py` — 前向形状、损失计算、梯度流
- `training/tests/test_selfplay.py` — 端到端对局生成
- `training/tests/test_inference_server.py` — 推理服务器协议
- `training/tests/test_parallel_inference.py` — 多 worker 编排
- `training/tests/test_arena.py` — 擂台评估
- `training/tests/test_eval_service_*.py` — Gauntlet 评估服务

端到端测试：`training/tests/test_train_az.py`。

运行命令：`.venv/bin/python -m pytest training/tests/ -q`

## 代码布局（实际）

> 2026-04-22 refactor (commit 6917f74) 将 `training/` 拆为三层:
> `framework/` (跨算法公共设施)、`az/` (AlphaZero 专用)、`cfr/` (CFR/Deep-CFR 专用)。

```
training/
├── framework/                 ← 跨算法公共设施
│   ├── config.py              ← 基础 TrainingConfig
│   ├── obs_constants.py / step_encoding.py / structural.py
│   ├── env_factory.py / system_monitor.py / health_check.py
│   ├── gauntlet.py            ← Gauntlet 评估
│   ├── log_tee.py             ← 日志工具
│   ├── buffer/                ← 通用 buffer 基类
│   ├── network/               ← 共享主干/loss/agent 基类
│   │   ├── trunk.py / loss.py / agent_base.py
│   ├── inference/             ← 推理服务器 + 客户端
│   │   ├── client.py / server.py / server_loop/
│   └── matchup/
│       ├── matchup.py / loaders.py / players.py
├── az/                        ← AlphaZero 专用
│   ├── mcts/                  ← IS-UCT 核心 + 虚损失并行 + rollout mixing（包）
│   │   ├── __init__.py
│   │   ├── action_id.py / node.py / config.py
│   │   ├── rollout.py / parallel.py / search.py / search_parallel.py
│   │   ├── run_rollout.py / utils.py
│   ├── network/               ← AZ 专用 actor-critic + agent
│   │   ├── actor_critic.py / agent.py
│   ├── buffer.py              ← AZ 回放缓冲区
│   ├── train_step.py          ← 训练步 + 训练工作线程（含 TrainStepConfig）
│   ├── train_az.py            ← AZ 训练主入口
│   ├── train_loop/            ← async_loop / helpers / run_result / stats_ingest
│   ├── selfplay.py            ← 自对弈工作线程
│   ├── determinize.py         ← 隐藏状态采样器
│   ├── pool_spec.py           ← resolve_pool_refs / make_pool_spec
│   ├── config.py              ← AZConfig (+ ScenarioConfig)
│   ├── config_loader.py       ← TOML → AZConfig 加载
│   ├── inference_pool.py      ← 多 worker 编排
│   ├── inference_worker.py
│   ├── mcts_go.py / mcts_go_bindings.py  ← Go MCTS backend cgo 桥
│   └── arena.py               ← 擂台评估
├── cfr/                       ← CFR / Deep-CFR 专用
│   ├── agent.py / collector.py / config.py
│   ├── fit_steps.py / parallel_trainer.py / train.py / worker.py
│   ├── network/               ← strategy_net / advantage_net
│   ├── reservoir/             ← base / advantage / strategy / value
│   └── traversal/             ← encoding / config / traverser / os_sampling / es_sampling
└── tests/                     ← 所有测试仍在 training/tests/（非 refactor 对象）
    ├── test_mcts.py / test_mcts_go.py
    ├── test_buffer.py
    ├── test_determinize.py / test_dice_posterior.py
    ├── test_network_az_*.py (trunk / agent / losses)
    ├── test_selfplay.py
    ├── test_train.py / test_train_az.py
    ├── test_inference_server.py / test_parallel_inference.py / test_parallel_pool_deadlock.py
    ├── test_matchup.py
    ├── test_cfr_*.py (convergence_os/es、traversal_os/es、reservoir、network、train、...)
    ├── test_health_check.py / test_watch_run.py
    └── test_eval_service_*.py / test_scenario_sampling.py / ...

tools/
├── run.py                     ← 通用 TOML-driven 启动器 (paradigm dispatch)
├── eval_service.py            ← 全局 gauntlet 服务
├── send_gauntlet.py           ← 发 gauntlet 请求
├── sanity_sid_pin.py          ← 结构性 sid 校验
├── diag_hook_path.py          ← hook 通路诊断
├── probe_numeric_sensitivity.py ← 数值扰动敏感度
├── mcts_player.py             ← 最小 MCTS 玩家 + vs-random 验证
├── bench_snapshot.py          ← snapshot/restore 吞吐基准
└── watch_run.py               ← 运行监控

configs/                       ← TOML 运行配置 (P5-H 后子目录化)
├── active/                    ← 当前活跃实验 (s070 / dmc_stage3 等)
├── smoke/                     ← smoke 测试 (smoke.toml / smoke_2v2 / dmc_*_smoke 等)
├── shipped/                   ← 生产 baseline (shipped_{1v1,2v2} / fixed_1v1 / random_1v1)
└── _archived/<paradigm>_<month>/  ← 历史已结案 (az_apr / ppo_apr / bc_apr)

gicg_engine/
├── game.go / game_counter.go / game_shuffle.go ← 核心 + 计数器 + 洗牌（SetPlayerHand/SetPlayerDeck 在 B0 加入）
├── action.go / action_step.go / action_execute.go
├── observation.go / obs_labels.go
├── tokenizer.go / tokenizer_tokens.go
├── interp/
│   ├── builtins*.go (7 files) / proxies*.go (5 files)
│   ├── parser.go / parser_expr.go
└── capi/
    ├── capi.go / capi_actions.go / capi_state.go / capi_labels.go

gicg_env/
└── engine.py / _constants.py / _engine_api.py / _engine_lifecycle.py / _engine_actions.py / _engine_queries.py
    （Mixin 拆分；GicgEngine(_LifecycleMixin, _ApiMixin, _ActionsMixin, _QueriesMixin)）
```

## 依赖关系图（阶段 B 任务）— 全部已完成

```
B0 ✅ ─┬─> B1 ✅ ─> B2 ✅ ─┬─> B5 ✅ ─┐
       │                   │         ├─> B7 ✅
       │                   B6 ✅ ────┘
       │                   ↑
       B3 ✅ ─────────────┘
       B4 ✅ (parallel)
```

## 执行规则

1. ~~在用户明确授权前不编写任何代码~~ — 阶段 B 已全部完成。
2. ~~阶段 B 任务逐个提交~~ — 已完成。
3. **阶段 C 任务只监控，不提交** — 验证运行产生制品，除非发现 bug，否则不修改代码。C1 验证中发现的问题（网络价值有害）通过新增 rollout mixing 机制解决。
4. **阶段 D 推迟至阶段 C 退出标准达到后执行**。D3（文档归档）已提前完成。
5. **阶段 D 之前不删除 PPO 代码**。回退方案必须保持可访问。
