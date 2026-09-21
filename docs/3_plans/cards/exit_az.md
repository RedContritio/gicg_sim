# ExIt / AZ 固定对手支线（下一主路线，协议草案）

状态：协议草案，未启动。动机：D2 战役全部训练侧/推理侧处方穷尽
（[falsification map](../5_history/d2_campaign_20260917.md)，最好 RL16
原生 42.3–44.6% / 变体 40.5–43.2%，距 CI 下界 >50% 约 14pp）。语义 Q +
BC/RL 范式的天花板已确证；用户 06-11 定义的正解是「能找到 combo 获胜路线、
**验收允许带搜索**的 agent」——即 ExIt（搜索 + 迭代蒸馏）结构。

## 历史（docs/5_history/handoff_20260914_part2.md）

- AZ 纯自博弈 2026-04-28 关闭：mirror Nash 锁死，plateau 0.06–0.15；
- AZ+BC warm-start 关闭：r010-012 把 BC 的 0.75 摧毁到 0.167（mirror 对手
  分布漂移 + 探索噪声冲洗 sharp policy）；
- 06-12 已定补救：固定对手 OpponentPool + `value_target_source=mcts_value`。

## 代码现状（已核查，比 06-12 估计乐观）

- 缺口核心在 `training/paradigms/az/paradigm.py:97-109`：`make_collector`
  明确 `del opp_pool`（A5.2 mirror 锁）——固定对手模式要在这里接住
  `opp_pool` 并把 `az/selfplay.py` 的 mirror 对局改为 agent-vs-pool；
- `training/paradigms/dmc/_opponent.py` 的 `OpponentPool/OpponentPoolConfig`
  可直接复用（F1-D2 权重 + checkpoint ring）；
- **`value_target_source` 已端到端存在**（`az/config.py:75` →
  `az/train_step.py:96-120`，支持 'z'|'mcts_value'|'mixed'），从未启用——
  pilot 必备对照臂只需改配置；
- **`az` 玩家类型已注册**（`az/_player_loader.py:42`，spec
  `{type:'az', ckpt, n_simulations, max_rollout_depth}`），可直接进
  evaluate.py 的 `player_spec`——搜索增强评估链路现成；
- MCTS 本体在 Go 侧（gicg_mcts + `az/mcts_go.py`），Python actor backend
  可用（'go' actor backend 是另一个待办 I29，不阻塞）。

## 待实现（启动时细化为任务清单）

1. `az/selfplay.py`：非 mirror 对局变体（对手 = pool 玩家的
   select_action；agent 侧仍走 MCTS）；胜率/价值从 agent 视角记录。
2. `az/paradigm.py:make_collector`：按配置分支 mirror / fixed-pool。
3. 新 cfg：`configs/az/exit_starter.toml`——pool 权重（F1-D2 为主 +
   历史 ckpt ring）、mcts sims 预算、buffer/lr、两臂 value_target_source
   （'mcts_value' vs 'z' 对照）。
4. 起点：AZ 网络格式独立于 semantic-q，**不能加载 RL16**；pilot 从随机
   初始化 + ExIt 循环开始（BC warm-start 的覆辙不重演：固定对手已消除
   当时的根因，但 pilot 仍设 z-only 对照臂）。
5. 评估：evaluate.py + player_spec={'type':'az', n_simulations:N}，
   原生/变体两面板 vs F1-D2，与 RL16 配对。

## 预算与关口

- pilot：单臂 ~4×256 局自对弈收集（16 workers）+ 更新，估计 2-6 小时；
  两臂（mcts_value vs z）+ 评估约一天。先小规模冒烟（2 局/2 更新）。
- 晋级线：pilot 任一臂 dev（vs F1-D2）> RL16 的 42% 平台；达不到则回到
  路线图 Week 2-3 的覆盖扩展（技能禁用/持续回合变体），不再在语义 Q
  范式内加预算。

## 风险

- AZ 上次死于 mirror 分布漂移；固定对手后新风险是「过拟合 F1-D2 家族」
  （pool 需含变体与历史 ckpt 保多样性）；
- MCTS 每决策成本：n_sims=32 时 Python actor 端吞吐需实测（Go actor
  backend I29 是后备）。

## 吞吐实测记录（2026-09-18，避免重蹈）

| 配置 | 局速 | 备注 |
|---|---|---|
| 64 rollouts × depth 400 | ~100s→15min/局（随 agent 变强增长） | 局速随存活轮数上升 |
| 16 × 100（v3） | ~120s/局 | depth 是真杠杆（playout 引擎步） |
| 16 × 100 × parallel_rollouts=8（v4） | ~120s/局（**零增益**） | `mcts_search_parallel` 是单 client 流水线批量，只省 NN forward；单对局场景 IPC 开销抵消收益。**该路径为多多 actor 进程设计，单对局用 in-proc（parallel_rollouts=1）** |
| 16 × 50 × 128 局（v5，判读线） | **实测 ~90s/局** | value head 在 depth 截断处接管；128 局 ≈ 3.2h |
| 8 actors × 16 × 100，中央 InferenceServer（async v1） | ~18 分钟/局（比 serial 慢 10×） | 每树节点评估 = 管道往返 + 3ms 攒批等待；且 10 个 CUDA 上下文——与两次 CUBLAS 崩 + 一次 hang 同窗口 |
| **8 actors × 16 × 100，每 actor 本地 CPU 推理（async v2，`local_inference=True` 默认）** | **本机基准 12s/8 局聚合**（56 上预期 8-12 局/分） | 无管道税；GPU 上下文=1（仅 master 训练）；权重经 WeightsSHM 推送、actor 每局间加载；修了首局随机权重 bug |

**并行化结论（09-18 实测三人组）**：引擎 c-api 线程安全（8 线程交错快照/
克隆轨迹逐字节一致），但单进程并行加速 1.0×（GIL+FFI 绑定——每步
Python/ctypes 开销才是瓶颈，非引擎）；多份库实例同进程 0.72×（更差）。
**真并行必须跨进程，且 actor 必须本地推理**（中央 server 管道税抵消并行）。

已知教训：① `tools.runs` 后台 TaskStop 只断本地 ssh，远端进程成孤儿占 GPU——
停训练用 `tools.runs.kill --pid`；② 评估/训练崩溃的 ProcessPool worker 会
留下 100% GPU util 的孤儿，需定期 `nvidia-smi` 检查 + `tskill` 清理；
③ 指纹覆盖 training/paradigms/ 与 training/core/，工具迭代会使旧 ckpt
provenance 失效——推理侧用 `GICG_SKIP_PROVENANCE=1`（只跳指纹相等）。
下一步吞吐杠杆（判读阳性后）：async 多进程 + fixed_opponent 池跨进程注入。
**设计草案**（实现前细化）：不在父进程序列化整个 FixedOpponentPool
（ring 里的快照网络太重），而是把 `FixedOpponentCfg` 传入每个 actor 进程、
actor 自建池（greedy/random 本就可本地构造）；historical ring 的快照经由
pipeline 既有的权重广播通道推给 actor（与 InferenceServer 权重同步同通道），
actor 侧按 weights_version 重建快照玩家。`del opp_pool` 处改为按
`fixed_opponent` 配置构造并注入。预估改动面：paradigm.make_collector async
分支 + _async 的 actor 初始化 + 池重建钩子，~300-400 LOC + 多进程确定性测试。
