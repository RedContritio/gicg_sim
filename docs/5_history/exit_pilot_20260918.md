# ExIt 固定对手 pilot（2026-09-18）

语义 Q 范式穷尽后（[d2_campaign_20260917](../d2_campaign_20260917.md)，14 项证伪 + executed
目标唯一成立，最好 RL16 原生 42.3–44.6% vs F1-D2）启动的结构不同路线：AZ 固定对手自对弈 +
迭代蒸馏（ExIt），对应用户 06-11 定义（「能找到 combo 获胜路线、验收允许带搜索的 agent」）。协议卡 [exit_az](../../3_plans/cards/exit_az.md)。

## 本阶段基础设施（全部已合入并测试）

- AZ 非镜像自对弈（`fixed_opponent` 配置 + FixedOpponentPool：greedy F1-D2 权重 + 历史 ckpt ring 冷启动回退）；镜像默认路径 A/B 逐字节不变。
- `need_target`（砂糖强制切换/鹤归之时触发）三层修复：自对弈顶层 + MCTS 树内（出牌与选目标成为两个 ply）；真实触发覆盖测试。
- ckpt 格式兼容：保存侧 duck-gate 认 `_agent`（`cfg`+`net_state_dict` 增量键）；一次性回填工具 `tools/ckpt/az_compat.py`。
- provenance env-gate（`GICG_SKIP_PROVENANCE=1`，只跳指纹相等，跨进程生效）；`evaluate.py` 的 `game_start` hasattr 守卫——「训练→ckpt→matchup→evaluate」全链打通。
- 并行推理接线（serial + parallel_rollouts>1 → InferenceServer 批量）：**单对局场景实测零增益**（v4 = v3 = 120s/局；该路径属多多 actor 设计），pilot 用 in-proc（parallel_rollouts=1）。

## 吞吐矩阵（实测）

| 配置 | 局速 |
|---|---|
| 64 rollouts × depth 400（v2） | 100s → 15min/局（随 agent 变强递增） |
| 16 × 100（v3） | ~120s/局 |
| 16 × 100 × parallel 8（v4） | ~120s/局（零增益，归因见卡） |
| **16 × depth 50 × 128 局（v5，判读线）** | **~90s/局** |

工具链教训：TaskStop 只断本地 ssh 需 `tools.runs.kill --pid`；崩溃评估留孤儿 worker 占 GPU
需 nvidia-smi 巡检 + tskill；evaluate.py 一律用 `python -c`（base64）方式调用——脚本文件缺
`__main__` 守卫时 spawn 子进程重放顶层代码导致 BrokenProcessPool；旧 ckpt 推理加载用 `GICG_SKIP_PROVENANCE=1`；
56 多 CUDA 上下文不稳定（崩/hang 全在多上下文窗口）——async 已改为每 actor 本地 CPU 推理、GPU 上下文恒 1，根因待最小双上下文复现定性。

**并行化结论（09-18 实测）**：引擎 c-api 线程安全（8 线程交错快照/克隆轨迹逐字节一致），但单进程并行加速
1.0×、多库实例 0.72×——GIL+FFI 绑定，真并行必须跨进程且 actor 本地推理（中央 server 管道税抵消并行）。
本机 ExIt pilot（run 000034，4 actors CPU）：~0.3-0.5 局/分，256 局 ≈ 5h；56 版（8 actors）预期 8-12 局/分。

## 首个数据点：33 局 ckpt（run 000064）双层评估 0/220

argmax 与 MCTS16 两层均 0 胜 [0,0]，双边全负、平均第 6 回合被清台。判读为
**学习前基线**（33 局 ≈ 1600 样本，网络近随机；D2 对随机策略碾压至 ~0% 为
合理区间；obs 经 `_get_obs()` acting 玩家视角，座位处理正确）。决定性验证
看 v5 后续 ckpt 的胜局曲线。

## pilot v5（run 000069）判读

（已被 run 000034 async pilot 取代；v5 serial 于 32 局按用户指令停掉，
见下节。）

## run 000034 async pilot：学习曲线第一个阳性点

- run `artifacts/202609181826_000034_exit_async_mv`（本机 4 actors CPU，
  fixed_opponent = greedy F1-D2 + 历史 ring），速率 ~0.4 局/分。
- **g17（17 局 ckpt，latest.pt）argmax 层：10/220 胜（4.5%），0 和局**
  （7 限时胜 + 3 击杀胜），seed 96510。对照：run 000064 与 v5 的 33 局
  ckpt 双层均 0/220。若真实胜率 ≈4.5%，220 场 0 胜概率 ≈ e⁻¹⁰ ≈ 5e-5，
  学习信号在 17 局即显著 > 基线，且出现在 argmax（裸策略）层 = policy 头
  确实从固定对手自对弈中学到东西。输出 `artifacts/exit_eval_20260918/
  panel_argmax_g17`。
- **g17 mcts16 层：0/220**（10 场限时、0 胜），反而劣于 argmax 的 10/220。
  判读：**搜索零增益 = 当前瓶颈在 value head 而非 policy**——MCTS 被弱 value
  （09-17 战役 R²≈0.14）引导反而比裸 argmax 差。z 对照臂
  （value_target_source 对比）必要性由此确立。
- 评估调用方式：/tmp/_exit_eval_ckpt.py + base64 exec（evaluate.py spawn
  守卫问题），workers=2 避免抢 pilot CPU。
- 待续：100 局里程碑双层评估；判读阳性 → 启动 z 对照臂
  （configs/az/exit_async_local_z.toml）。

## 09-19：56 主臂接管与本机 pilot 退役

- 用户放行 56。主臂按 exit_async.toml（GPU master + 8 CPU actors）两次
  失败：run 000075 首个训练 forward `CUDA unknown error`（embedding 处
  异步上报）；run 000076 训练 forward hang 5 分钟（faulthandler 栈停在
  actor_critic.encode）。远端裸 `torch.randn matmul` 正常 → 非驱动全死，
  是 56 训练主循环 CUDA 不稳定（与 09-18 记录的"多上下文不稳定"同族，
  单上下文亦中招，根因仍待定性）。
- 决策：master 改 CPU（`configs/az/exit_async_cpu56.toml`，唯一差异
  `device="cpu"`），绕开 CUDA。run 000077 健康：5 分钟 11 局、train_steps
  正常推进，速率 ~2 局/分，256 局 ≈ 2h。
- 本机 pilot（run 000034，~31 局）按"56 接管即退役"停掉，释放用户机器；
  其 g17 ckpt 评估结论（上节）继续有效，学习曲线第二数据点改由 56 主臂
  提供（到 100 局时 scp ckpt 回 Mac 用 CPU 评估，56 评估与训练不并发）。
- **教训（09-19 凌晨）**：pilot 的"停掉"只杀了包装进程，`tools.runs.train
  configs/az/exit_async_local.toml` 主进程 orphan 化（ppid=1）后继续跑了
  ~2.5h，白烧 ~6.5 核并拖慢 g40 评估才发现后补刀。教训：停本地训练必须
  按进程树清（pkill -f 匹配 cfg 路径或杀整个 pgid），并 ps 复核 CPU 归零。
- 补充：56 实时利用率（wall 2300s 采样）CPU 32 核均值 86–93%（近饱和），
  GPU 4%/1GB/42W（闲置）。master 走 CPU 后 GPU 全闲是设计态；提速唯一大头
  是 actor 推理 GPU 化，但属两次 CUDA 故障的未定性区，待用户拍板是否开
  诊断线。
- **用户拍板（09-19 05:0x）**：① GPU 实为 **5070 Ti**（16GB）；② 当前
  主臂训练 + 验收评估完成后，允许 actor 推理切 GPU。
  切换方案（代码链路已核实）：az async 双模式——默认
  `paradigm.az.local_inference=true`（每 actor 进程内 CPU 网，WeightsSHM
  广播，现用）；置 `false` 走中央 `InferenceServer`，其 device 来自
  `[pipeline.inference] device`（继承链 pipeline.inference.device →
  meta.device，schema 校验 cuda/cuda:N 合法）。即新 cfg =
  exit_async_cpu56.toml + `local_inference=false` +
  `[pipeline.inference] placement="local" / device="cuda"`，master 仍 CPU。
  上线顺序：先 total_games≈8、num_actors=2 的短 smoke 验证 InferenceServer
  CUDA 路径不复现 000075/076 的 unknown error/hang（故障面与 master
  forward 不同，可能直接可用），过了再上全量臂。smoke cfg =
  configs/az/exit_async_gpu56_smoke.toml（已 schema 校验通过）。

## g256 终局评估（09-19 09:25）：mv 臂判阴性

- run 000077 全量 256/256 完成（~4.5h，orphan 续跑成功，进程树自然退出
  干净，56 无残留）。final ckpt ckpt_11240（08:56）scp 回 Mac 双层评估：
  **argmax 0/220，mcts16 0/220**（panel_{argmax,mcts16}_g256_56）。
- 同 run 两点：g40（ep29）0/220 → g256（ep256）0/220；train/loss 20.4→15.8
  只在拟合自对弈分布，未转化为对 F1-D2 的胜率。**g17 的 10/220 定性为
  不可复现波动**（跨 run、低胜率正向噪声）。
- 结论：value_target_source="mcts_value" 臂在 256 局/32k train_steps 规模下
  无可测学习。进入升级路线：① GPU 推理 smoke（用户已拍板，先行——
  15 分钟）；② z 对照臂（cfg 已备，save_every=50）；③ 补 loss 分项日志
  （tb 目前只有 train/loss 总值，无法区分 value/policy 谁在劣化）。

## z 臂中途判读（09-19 11:30–12:00）：阳性 + 性能剖析

- **g095_z（ckpt_14351, ep~95）argmax 10/220（4.5%）、mcts16 26/220
  （11.8%）**——z 目标复现了 g17 的 argmax 阳性，且 mcts16 反超 argmax
  （mv 臂是 mcts16 更差）：value head 拟合（value_loss 0.81→0.20）转化
  成了搜索增益，机制闭环成立。
- 用户 11:47 指令：等下一 ckpt 即停训练让出 56。ckpt_14401（ep~140）
  于 11:50 落盘即取回（/tmp/g140_000079.pt），训练杀掉、56 清零交还。
- **性能剖析（Mac，/tmp/_prof_selfplay.py + _bench_serial.py）**：
  - 每局 wall 的 **41–64% 是 MCTS 内网络求值**（eval_s；每 eval ~4.8ms），
    对手 F1-D2 占 19–45%，引擎步进/快照/确定性合计 ~10%；
  - cProfile 定位：4.8ms 的 97% 在 net forward 内，且 139 次 nn.Module
    调用/eval 的 Python 调度开销是大头（matmul 本身仅 0.18ms）——
    **不是引擎问题**（Go random_rollout vs Python 1.0×，引擎本来就在
    Go 库里）；GPU 推理帮不上是因为 forward 小、瓶颈在调度不在算力；
  - parallel_rollouts=16 + InferenceServer 批量端到端仅 1.02×（IPC 吃掉
    收益）——standalone server 路径偶发死锁（server 阻塞 send、main 不
    recv，两次复现一次成功），待查，不阻塞；
  - **eval cache（per-search，键=行棋方+dyn+refs 字节）已实现**（serial +
    parallel 两路，46 单测过）但同种子 A/B 显示 search 内重复 eval ≈ 0
    （n_eval 不变）——对当前树形收益为零，保留待用（跨局缓存才有肉）；
  - **有效杠杆：n_rollouts 16→8**（同种子 wall 5.7/4.8s→4.3/3.0s ≈1.5x，
    eval_s 精确减半）。已改 exit_async_z_gpu56.toml（n_rollouts=8,
    parallel_rollouts=16），注意这是配方变更（搜索强度降一档），恢复
    z 臂续跑时用新配方，余 116 局预计 ~1.2–1.5h。
- **standalone server"死锁"已翻案（09-19 13:00）**：macOS `sample` 抓栈显示
  主进程其实早已跑完 B 阶段，挂在 `_Py_Finalize → os_waitpid` 等 spawn
  的 server 子进程退出——根因是 bench 脚本收尾缺失（InferenceClient 无
  close 方法，AttributeError 使 server.stop() 没被执行）。**server 协议
  本身无死锁**，生产路径（AZAsyncCollector.close）收尾完整不受此影响。
  parallel_rollouts+server 批量端到端 1.02× 的结论维持（IPC 开销吃掉
  批量收益）。
- 仍待办：torch.jit.trace 包装 net 消除 139 次模块调度/eval（az 的
  InferenceServer handlers 未接 trace 基建，是下一阶段最大提速头）。

## z 臂第二次停止与 56 冻结（09-19 15:01，用户指令）

- 用户 14:58 指令：下一 ckpt 即停、**之后未经明确允许不再使用 56**。
  ckpt_14951（ep~225，14:49 落盘）已是最新可用点，随即 scp 回 Mac
  （/tmp/g225_000079.pt），训练杀掉、56 复核 CLEAN、守望撤除。
  z 臂最终状态：ep~225/256（续跑段 140→225，n_rollouts=8 配方），
  未跑满 256——三点判读改为 g095 / g140 / g225。
- **56 冻结生效**：在用户明确允许前，不启动任何 56 任务、不做任何
  远程执行（只读探查也暂停）。待解冻后的队列：① g225 的 Mac 双层
  评估（不碰 56，随时可做）；② RL16 热启动臂（/tmp/_launch_ws_rl16.sh，
  全就绪）；③ 对手决策缓存 + torch trace 两个提速实现。

## 提速攻坚（09-19 15:00–16:10，Mac，56 冻结中）：Go backend 胜出

三个候选逐一实证，最终 **backend="go" 配置级切换 ~1.7x** 落地：

- **对手决策缓存：证伪，不建**。① soundness 实验（gicg_env
  set_player_dice/set_player_hand 扰动）：8 个对手决策中 2 个因我方
  隐藏骰子/手牌改变而改变着法——掩码 obs 做键不安全；② 且随机卡组使
  跨局轨迹复用率≈0（与 eval cache 同因），建了什么也命中不了。
- **torch.jit.trace：可行但搁置**。requires_grad_(False) + strict=False
  后 trace 成功，输出逐位一致，forward 1.90→1.16ms（1.64x）；但端到端
  仅 ~1.2x，且在 server+批量配方下收益更小（批量已摊薄调度），需要
  per-game 常量改 args + 权重推送重 trace 的管线改造。记入待办。
- **Go MCTS backend（mcts_search_go，既有代码）：采用**。同种子 A/B
  （n_rollouts=8，本地 Agent）：python 树 3.0–3.9s/局 vs go 树
  2.0–2.2s/局 ≈ **1.6–1.8x**；经真实 pipeline 端到端 smoke
  （configs/az/_go_smoke.toml，2 局 1 actor）通过。注意 go 路径的 eval
  回调是逐叶同步的，配 GPU InferenceServer 会把 IPC 串行化——故
  **go 必须与 local_inference=true 搭配**（parallel_rollouts 回到 1，
  该参数只作用于 python+InferenceClient 异步路径）。
- **exit_ws_rl16.toml 已切新配方**：backend="go" + local_inference=true
  + n_rollouts=8 + pipeline.inference device="cpu"（GPU 闲置是此配方
  的设计态，负载本就不在推理）。预估 256 局 ≈ 2–2.5h（若对手搜索
  占比如剖析的 20–45%，剩余大头是 F1-D2 的 Python depth-2 搜索本身）。

## g225_z 评估与 z 臂总结局（09-19 15:43）：机制验证收官，主线交棒

- **g225（ckpt_14951, ep~225，续跑段为 n_rollouts=8 配方）：argmax
  8/220（3.6%），mcts16 10/220（4.5%）**。z 臂完整曲线：

  | 点 | argmax | mcts16 |
  |---|---|---|
  | g095 | 10（4.5%） | 26（11.8%） |
  | g140 | 10（4.5%） | 14（6.4%） |
  | g225 | 8（3.6%） | 10（4.5%） |

- 判读：argmax 层 95→225 局**完全饱和在 ~4%**（8–10 胜互在噪声内）；
  mcts16 从 26 单调衰减到与 argmax 持平——搜索增益随训练消失
  （value_loss 仍在降但 eval 端搜索不再受益，疑似自对弈分布漂移
  使 value 泛化劣化）。结合 mcts64 零缩放（g140），z 臂（从零、
  d32、225 局）的天花板就是 ~4–6%。
- **z 臂结论：机制验证成功、配方天花板有限**——z 目标 vs mv 目标
  的对比是阳性的（mv 两次 0/220，z 全程非零且 mcts16 曾 2.6 倍于
  argmax），但从零 ExIt 在 225 局规模到不了 15%+。此线关闭，结论
  全部喂给主线：**RL16 热启动臂（38.6% 起步 + ExIt 搜索训练 +
  Go 快配方）是唯一在跑的方向**，等 56 解冻启动。
- **评估通路修复（09-19 15:54）**：此前每次评估开局固定 ~15 分钟预热，
  根因是 base64+`-c` 调用下 spawn 子进程重放顶层代码。改为
  `-m tools.experiments.semantic_training.evaluate` 直跑（CLI 补了
  `--player-spec` JSON 参数）后预热消失——同参数复测 g140 argmax
  **10/220 逐位一致**，整块 220 局面板 **8 分钟跑完（原 ~30+ 分钟）**。
  base64 调用法作废，以后评估一律 -m 直跑。
- **RL16 热启动 ckpt 泛化基线（09-19 16:06）**：heldout 规则变体面板
  （configs/rule_validation/native_variants.toml，55 场景 ×2 布局 ×双方，
  argmax，seed 96540）：**79/220 = 35.9%** vs 原生 38.6%（-2.7pp）——
  零样本泛化保持，与 D2 时代 RL16 的"变体≈原生"形态一致。此数为
  热启动臂训练后的泛化对照基准：训练后 heldout 掉幅应维持个位数 pp，
  若掉幅 >10pp 说明 ExIt 过拟合原生分布，需回放正则。

## g140_z 评估（09-19 12:51）：argmax 持平，mcts16 回落，待终点裁决

- **g140（ckpt_14401, ep~140）：argmax 10/220（与 g095 持平），mcts16
  14/220（g095 为 26/220）**。二项检验 z=2.81（pooled p=9.1%）——形式上
  显著，但属多点比较之一且两点独立噪声大，判"边界回落，疑似中段波动 +
  评估方差"，不作回归定论。
- 同期训练曲线（至 ep140，545 train steps）：value_loss 季度均值
  0.49→0.17 持续拟合；policy_loss 1.83→1.70、entropy 1.85→1.71 缓慢
   specialize；argmax 持平说明 policy 头无退化。
- 裁决点：z 臂续跑（n_rollouts=8 新配方）到 256 局的终局评估——mcts16
  回到 ≥20/220 = 回落即噪声；仍 ≤15 且 argmax 同步跌 = 真回归信号，
  届时查 value 过拟合（train value_loss ↓ 但 eval 胜率 ↓ 的组合）。
- **eval cache 最终结论（09-19 13:00，已整体回退）**：per-search 与
  game-scoped（weight-version 键，跨决策复用）两种实现都测了——同种子
  A/B 中 n_eval **分毫不变**（713/815）。原因：该游戏骰子/手牌使状态
  高熵，MCTS 每局访问的 ~700 个状态在 search 内和跨决策间**零重复**
  （无转置复用）。此路不通，代码已回退。
- **事故与教训**：回退时误用 `git checkout --` 清掉了 selfplay.py 等 5
  个文件的**既有未提交改动**（含 play_vs_opponent_game 本体！）。因 56
  端 09:33 自动同步保存了完整副本才得以无损恢复（35+14 测试复验通过）。
  教训：①本仓库大量功能处于未提交状态，git checkout 是禁手；②_remote_sync
  客观上充当了未提交代码的异地备份。恢复后基准性能与最初基线一致
  （5.7/4.7s，n_eval 713/815）。
- **搜索缩放否定结果（09-19 13:22，g140 ckpt）**：argmax 10/220 →
  mcts16 14/220 → **mcts64 12/220**——4 倍模拟数零收益，三层全在噪声带。
  结论：当前 d32 net 的 policy/value 质量即天花板，**评估端堆搜索不能
  通往"稳定战胜"**；这同时解释了 g140 mcts16 回落为何意义有限——搜索层
  信号本就噪声主导，裁决更应看 argmax 层（g095 10 → g140 10，持平）。
- **战略校准（09-19 13:30，重读 d2_campaign_20260917）**：上文"下一杠杆
  是容量 d128+"**错误，已修正**——D2 战役已证伪容量（d128×2L 在两目标
  下配对 -5.91pp，"容量问题彻底关闭"），且 BC/数据/DAgger/RL 预算等
  训练侧假设全部穷尽（这正是转 ExIt/AZ 的动机）。D2 最强模型 **RL16
  （run 000055，executed-warmup3 + 16 轮 RL）对 F1-D2 已达 42–44%
  （原生）/ 40–43%（heldout 变体），零样本泛化保持**，距稳定战胜
  （CI 下界 >50%）差 ~14pp。当前 ExIt z 臂 140 局仅 5–6%，远落后于
  该基线——**下一步优先级：① z 臂续跑到 256 完成机制验证（新配方
  ~1.2h）；② 用 RL16 ckpt 热启动 ExIt（warm-start 自对弈搜索训练）——
  D2 已穷尽训练侧、ExIt 补搜索侧，组合是最有希望打通 50% 的路径**。
  run 000055 确认仍在 56（202609172344_000055_semantic_rl）。

## g40 中途评估（09-19 05:22）：阴性，升级为黄旗

- run 000077 @ ~38 局 ckpt（scp 回 Mac，sha256 与 result.json 记录一致）：
  **argmax 0/220，mcts16 0/220**（输出 panel_{argmax,mcts16}_g40_56）。
- 与 g17（run 000034 @17 局，argmax 10/220）方向相反。注意这是**跨 run
  比较**（4 actor 本机 pilot vs 8 actor 56，同 seed 同超参但轨迹不同）：
  g17 的 10 胜可能本身就是低真实胜率的正向波动，不能排除。
- 训练侧数值健康：tb 标量只有 train/loss 一个 tag（无 value/policy 分项，
  诊断粒度受限），205 步从 20.4 降到 15.8（-23%）——net 在拟合自对弈分布，
  但 38 局时未转化为对 F1-D2 的 argmax 胜。
- 判读决定点仍在 **g100 同 run 内对比**（g40→g100 argmax）：显著 >0 = 学习
  曲线成立只是慢；仍 0/220 = 该臂 100 局内无可测学习，升级诊断（补 loss
  分项日志、提前上 z 臂、查 WeightsSHM/优先级回放正确性）。
- 执行修正（09-19 06:10）：ep100 达成，但 save_every=500 env step ≈
  25–30 局/ckpt，ep100 时 latest.pt 仍 = ckpt_11001（≈ep29，即已评过的
  g40，sha 相同）。最近可用判读点是 ckpt_11501（≈ep128，约 40 分钟后），
  守望任务 bash-lyod6fra 盯其出现后 scp 评估，tag `g128_56`。另注意本地
  train 任务 4h timeout ≈ 08:27 到点，256 局跑不完（预计 ~ep210 被断），
  用最后一个 ckpt 作第三点即可。
- 再修正（06:30，step 速率实测后）：**step 速率从开局 ~5.6 step/s 衰减到
  ~64 s/step**（对手池混入历史 AZ 后对局变长），save_every=500 ≈ 8.9h
  一个 ckpt，远超 run 全时长——中途不会再有新 ckpt，11501 守望已撤。
  判读改为两点式：g40（ckpt_11001, ep29, 已评 0/220）vs g256（自然结束
  ~09:35 的 final ckpt）。本地 wrapper 08:27 timeout 只会断 ssh，远端训练
  按 pilot 先例会变 orphan 继续跑（master pid 23524，已记录待收尾清理）。
  终局守望 bash-oipqymxm（ep≥250 或 pid 23524 消失）。教训：**慢对局制度
  下 save_every 必须按实测速率校准**——z 臂/GPU 臂 cfg 已改 save_every=50、
  keep_last_n=8。

## 种子

96410/96430（d128×executed 容量臂，已结）；96450（ckpt_33 评估）；
96140（fit 审计复用）。v5 用 cfg 固定 seed 42；评估 seed 用 96470 起段。

## F1-D2 快赢尝试与最终结论（09-19 17:20）：证伪，已回退

- 按 profile 线索实现 reroll 检测改走 kinds 预取（消除每节点一次
  get_action_refs 编组），greedy_player/greedy_dice 两文件改动，89
  测试过 + 新旧实现 187 决策逐位对拍 0 失配——**但同状态重测速
  203.6→202.1ms，仅 0.7%**。cProfile 的 tottime 把 ctypes 调用里的
  引擎耗时记进了 Python 侧，"编组占 42%"的判断失真。
- 结论：**F1-D2 的 203ms/决策 ~95% 是引擎内部工作**（每节点 step
  160µs×700+ 次 + 每叶 view 导出），任何只动 Python 侧的优化（缓存/
  Cython/编组去重）天花板 <5%。**唯一有效的优化是 Go 下沉**（引擎内
  既有 SelectAction，capi 暴露后整段搜索零 Python/边界开销），预计
  对手组件 ×10–20、端到端再 ×1.3–1.5。两文件已回退（改动前与 HEAD
  一致，checkout 安全，复测 89 测试过）。

## "编译固定规则集"调查与 GC 发现（09-19 18:20）

- 用户问"规则（Lua 风格 DSL）固定，能否编译掉"。查明：DSL 是自定义
  Go AST 解释器（gicg_engine/interp/，非 Lua VM）；**每局 NewGame 确实
  重新 ExecFile 全部规则脚本**，但 pprof 显示装载占总时长 ~0.6%，
  不是热点。
- Go 基准（tests/interp_share_bench_test.go，训练同款队伍/卡池，
  random play）：每步 64.1µs；**interp 解释器累计仅 ~2-4%**（random
  play 触发效果少，卡牌重对局会更高，但量级有限）→ "AST→Go 预编译"
  上限有限且工程大，**不做**。
- **真热点是 Go runtime GC**：pprof 里 madvise 26% + GC 并发标记/扫描
  ~25%（runtime 合计 ~50%+）。调优实测：GOGC=400 → **55.1µs/步
  （1.16×）**，GOGC=off → 58.9µs（1.09×且内存风险）。零代码零语义
  风险。**行动：56 训练/评估进程的启动环境加 GOGC=400**（libgicg
  内嵌 Go runtime 启动时读该环境变量）。卡牌密集的真实 MCTS 对局
  分配更多，预期收益更大。

## F1-D2 Go 下沉落地（09-19 18:40）：对手决策 4×，强度等价通过

- **实现**：Go 版贪心搜索早已完整存在于 gicg_actor/dmc/greedy_player.go
  （F1-F5×D1-D4 + dice fold + SnapshotPooled 零分配）。本次只是暴露：
  capi 新增 `GameSelectGreedyAction`（一次 cgo 跑完整局 minimax），
  Python 绑定 gicg_env._engine_actions.select_greedy_action（旧 lib 无
  符号自动回退），GreedyPlayer.select_action 在 dice_greedy=True 时
  自动走快路径（GICG_NO_GO_GREEDY=1 可关；select_with_info 保持纯
  Python 供 BC 工具）。macOS libgicg.dylib 已重建安装。
- **速度**：对手决策复杂态 203.6→55.9ms（3.6×），均值口径 4.0×。
  全游戏（go树+go对手）Mac 短局 2.0→1.9s（~5-10%，对手占比小）；
  56 长局对手占比 19-45%，预期端到端 15-30%。评估面板同样受益。
- **等价验证**：① 逐状态对拍一致率 54-60%——F1 评分粗粒度导致平局
  集均值 3.59（最大 31），独立随机破平局的理论一致率 ~65%，测量值
  在噪声内（行为分布等价）；② **强度面板：g140 argmax vs Go-F1D2 =
  16/220（7.3%），vs Py-F1D2 = 10/220（4.5%），z=1.71 不显著**——
  强度等价通过（与 Go port 当年的 winrate-gate 结论一致）。
- **注意**：跨面板可比性在噪声内成立但非逐局同轨迹；GOGC=400 与
  56 端引擎重建已加入 /tmp/_launch_ws_rl16.sh（--resume 前执行
  build_engine + 设用户级 GOGC）。

## 远端同步内容寻址化（09-19 19:00，用户点单的 A+D 方案）

- `tools/runs/_remote_sync.py`：远端新增 `.sync_manifest.json`（路径 →
  sha256，记录同步放置的全部文件内容）。auto 模式每次对候选集算哈希，
  **只推内容变了的文件**，推完重写 manifest 并**读回校验**（D，不一致
  返回 3 fail-loud）。附带：删除也按 manifest 跳过远端已缺席的路径
  （幂等，省重复 ssh 往返）。`.last_synced_sha` 语义不动（clean 才前进）。
- 效果（长战役主要痛点）：未提交文件一字未改则不再过网线——此前每次
  启动重推 ~1447 文件/3.4MB，此后增量应为 KB 级。旧远端无 manifest =
  首次全量，向后兼容。
- 测试：`tools/runs/tests/test_sync_manifest.py` 新增 3 例（二次零推送/
  单文件触发/删除幂等），全套 842+3 绿。`--single/--git-changed` 不更新
  manifest（下次 auto 按哈希差补推，无害）。e2e 留待 56 解冻首跑验证。

## Web 端能力更新（09-19 20:05）：可对战的当前冠军模型

- 此前 `artifacts/exit_az/release/semantic_rl/` 槽位为空 → web 只有随机
  练习模式。本次部署 **RL16 热启动 AZ ckpt**（当前最强模型）到新槽位
  `artifacts/exit_az/release/az_exit/`（model.pt + evaluation.json，36.8% vs
  F1-D2，220 局，seed 96600）。
- `web/backend/semantic_live.py`：live 服务类型从硬编码 semantic_rl
  扩展到 `semantic_rl | az`（报告 sha/指纹/场景校验链不变；az 跳过
  semantic 专属的 load_semantic_agent，builder 加载在 build_session
  经 matchup loaders 完成并缓存）；`game_start` 改为可选协议调用
  （az argmax player 无此方法，与 evaluate.py 同款约定）；
  profile().checkpoint_format 按类型报告。
- `configs/web/semantic_live.toml` → type az 指向新槽位；
  `Live.tsx` 头部新增评估胜率显示（对 F1-D2 x% · N 场景）。
- 验证：profile() available=True、build_session + 对手着法冒烟 OK、
  31 个后端测试全过、前端构建通过。启动方式见 web/README.md。
- 注意（设计使然）：未来任何源码改动使指纹漂移 → web 模型显示
  "不可用"，需重跑一块评估面板刷新 evaluation.json（~8 分钟）。

## run 000080 第二次暂停（09-19 21:33，用户要用 56）

- 停止于 **ep105 / 404 train_steps / wall 105min**，进程树清除、56
  CLEAN。断点 ckpt 已取回 Mac（/tmp/g070_ws_pause.pt；远端 run 目录
  的 latest.pt 同内容，恢复时直接 --resume 原路径即可续）。
- 首个判读点 ws_g063（ep~63）：argmax 33.6%（基线 38.6%，z≈1.1 噪声
  内持平略降），mcts16 26.4% < argmax——value 头从零起步的预期形态，
  非退化证据。裁决点：恢复后续跑到 ep150，argmax 守 ~38% 且 mcts16
  收敛/反超 = 健康；argmax 跌破 30% 且 mcts16 无起色 = 干预（降 lr /
  缩回放）。
- **56 再次冻结至用户下次说明可用**。恢复后的队列：① resume run
  000080 续跑（余 ~150 局，GOGC=400 与引擎库已在位）；② ep150 双层
  评估裁决；③ 训练若健康，web 槽位换最新 ckpt + 刷评估报告（指纹会
  随源码漂移，这是特性）。

## Web 对战体验修复（09-20 凌晨，用户实测反馈）

- **支付推荐**：LegalActionList 小组内支付组合按万能骰用量升序排序，
  默认推荐落在零/最少万能的组合（此前默认取引擎枚举序首位，烧万能）。
  下拉仍可手动换组合。
- **重掷阶段**：之前前端完全没有 reroll 交互（引擎其实一直按「每颜色
  选数量 + 确认」拆帧暴露 ActionReroll 合法动作，标签引擎自带中文）。
  后端 build_legal_actions 增加 refs 字段（[kind, count, color]），
  前端新增 RerollPanel：全 Reroll 帧时渲染专用面板（显示己方骰子池、
  该颜色 0..N 枚选择、颜色 8 确认帧单按钮），并在面板下提示万能骰
  使用策略。后端 31 测试过、前端构建过、API 冒烟（reroll 帧带 refs
  到达前端）。web 服务已重启（:8080）。

## ep150 中期裁决（09-20 04:10，偏负）与锚定 v2 预备

- ws_g150：argmax 74/220（33.6%，与 g063 相同，低于基线 85，z≈1.7
  单侧 p≈0.045）；mcts16 59/220（26.8%），较 g063 零进展，仍低 argmax 7pp。
- 训练诊断（680 steps 四季）：value_loss 0.37→0.22（在学），**policy_loss
  1.16→1.31、entropy 1.19→1.32 逐季上升**——policy 漂离 RL16 收敛解且更
  随机 = D2 战役"无锚漂移"同款形态（anchor_beta=0 曾中段崩至 32.7%）。
- **处置**：不打断，跑到 ep256 补终局曲线（约 1.2h）；同时预备**锚定
  ExIt v2**：① AZLoss 新增锚定蒸馏（train.anchor_beta/anchor_ckpt，对冻结
  参考策略 CE，惰性构建缓存；0×-inf nan 坑已修，数学收敛已单测）；
  ② configs/az/exit_ws_anchor.toml（lr 3e-4、anchor_beta 0.3、anchor 指向
  已部署的 artifacts/exit_az/inputs/warmstart_rl16.pt）。41 项相关测试过。
- 待用户拍板：ep256 终局曲线确认劣化后启动 v2。

## run 000080 终局裁决（09-20 05:50）：无锚 ExIt 热启动判负，v2 申请提交

- ws_g256：**argmax 51/220（23.2%）、mcts16 33/220（15.0%）**。完整曲线：

  | 点（累计局数） | argmax | mcts16 |
  |---|---|---|
  | 基线 ep0 | 85（38.6%） | — |
  | g063（~168） | 74（33.6%） | 58（26.4%） |
  | g150（~255） | 74（33.6%） | 59（26.8%） |
  | g256（~361） | **51（23.2%）** | **33（15.0%）** |

- 终局 vs 基线 z≈4.9σ，无歧义；且 51→33 显示后段加速恶化。训练侧同向：
  policy_loss 1.17→1.40、entropy 1.19→1.41 逐季升，value_loss 0.33→0.23
  （value 在学但救不了 policy）。
- **结论：无锚 ExIt 从强初始化训练是净负**——z 目标能训 value（z 臂已
  证），但从 RL16 起步的自由漂移摧毁 policy。D2 战役"锚点是保护性的"
  教训在 ExIt 上复现。
- **下一步（待用户拍板）**：锚定 ExIt v2（lr 3e-4 + anchor_beta 0.3 蒸馏
  锚到 RL16 + z 目标），全部就绪（loss 改动单测过、cfg 已建、anchor ckpt
  已在 56），56 空闲即可一键发。
- 09-20 06:00 预备动作：warmstart ckpt 已按当前源码指纹重建并重新部署
  56（artifacts/exit_az/inputs/warmstart_rl16.pt）——v2 resume 不会因指纹再卡。等用户
  拍板即一键发锚定臂。

## 锚定 ExIt v2 启动（09-20 11:50，用户已授权）

发射 saga（四次点火，三个雷全部排掉）：

1. **代码没同步**：56 端 loss.py/config.py 还是无锚版 → TrainStepCfg
   不认识 anchor_beta。`_remote_sync` 内容寻址同步补上（教训：手动
   Start-Process 发射绕过了 train.py 的内置自动同步，要走同步或
    canonical 入口）。
2. **指纹雷 ×2**：anchor 改动改指纹 → resume ckpt（000080/latest.pt）
   和 anchor ckpt（warmstart_rl16.pt）双双失配。骨架重建注入（skeleton
   → 注入 RL16 转换权重 → 清 optimizer/零计数器 → scp 双点位），并在
   56 端 python 直接预检 `fingerprint() == provenance` 后才点火。
3. **`Agent` 无 `.eval()`**：`_anchor_ref` 误对 wrapper 调 eval/
   parameters（ tests 用的是 mock，没抓到）。改 `ref.net.eval()` /
   `ref.net.parameters()`。

发射后实测修正：

- **save_every=150000 永不触发**：cfg 注释假设 step≈搜索步 ~1000/s，
  实测 resume 后稳态 **每 150s 才进一步**（每步含 4×train batch，anchor
  使 batch 15.6s→37s，CPU 争 10 进程）。150000 步≈稳态 26 天。改
  save_every=10（约每 25-60 局一档）。
- **吞吐 ≈ 1 局/min**，与 000080 昨日同配方同速率（非 v2 退化）；
  判读节点 ep60 预计 ~1h。
- 发射方式 = ssh 前台保活（Mac 后台任务托底），**kill 本地 ssh 不会
  杀远端训练**——重启前必须显式 Stop-Process 远端 python。

判读标准（不变）：argmax 守住 ~38% = 锚起效；mcts16 反超 argmax =
搜索增益兑现。若 argmax 仍跌 → anchor_beta 0.5-1.0 或再降 lr。

### v2 吞吐实测（09-20 12:00）

- v2 稳态 **0.32 局/min**（000080 无锚时 1.0 局/min）：anchor 每 batch
  多一次冻结参考前向，单 batch 15.6s→37s，训练门槛 3 倍化，actor 被
  权重发布门控 → 吞吐同比降 3 倍。判读节点 ep60 相应 ~3h（约 15:00）。
- 本地合成 batch 测量定位：单步成本几乎全在 hook 编码器
  （B×900×128≈29M token/前向，内存带宽 bound），anchor 是 +1 次同价
  前向——**配方固有成本，非实现病理**。不做修补；若 v2 判读阳性再谈
  降频锚（每 K batch 锚一次）之类的折中。
- 判读工具链备忘（09-20 12:00）：`semantic_training.evaluate` CLI 默认
  `--opponent-depth 1`（**必须显式传 2 才是 F1-D2**，本战役 297 次面板
  都是 depth 2）；`--scenarios` 默认 64 非 55 倍数会炸，历史面板实为
  55×2 布局×双边=220 局（`_exit_eval_ckpt.py`，56 上已部署）。输出路径
  参数是目录。Mac 本地跑评估会 64 局后 0% CPU wedge（multiprocessing
  挂起），**评估一律在 56 跑**。
- **checkpoint 自剪枝 bug（09-20 12:20 定位）**：`save()` 的 keep_last_n
  按**文件名 step 数字**排序删最旧；resume 注入的 ckpt 计数器清零后，
  新 ckpt（step 2485）比昨日遗留（922601）"小"→ 每次保存即自删。
  编号历史全灭、latest.pt 独活（评估可用它，无阻塞）。昨日 000080
  "19:28 后无新存盘"同因。处置：cfg keep_last_n=0（下次重启生效）；
  代码级修复（按 mtime 剪枝）待源码稳定期再做。
- **评估并发不可靠（09-20 13:00 实证）**：训练同机跑评估 BrokenProcessPool/
  忙循环（seed 96510  Lineup 下 worker 死循环占核）。 ep0（未动过的
  RL16 ckpt）同条件也挂 → 排除"v2 政策退化"解释；dylib 未变（9/19
  19:05）→ 排除引擎回归。**处置：评估一律空闲窗**。注意 Stop-Process
  -Force 不跑 finally，停训会丢最近一次周期存盘后的进度（分钟级）。
