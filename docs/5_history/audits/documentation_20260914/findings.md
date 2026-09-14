# 文档与注释审计交接

审计日期：2026-09-14。工作树基线与用户已有改动均保留；本审计未提交 Git、未访问远端 56、未启动训练，也未修改模型结构、规则或运行逻辑。

## 覆盖口径

- `coverage.tsv` 是本次结束时重新生成的全文件清单，来源为 `git ls-files` 加 `git ls-files --others --exclude-standard`。共 4,382 个文件：4,359 tracked、23 untracked。脚本逐文件读取字节并尝试 UTF-8 解码。
- `manual_review.tsv` 只记录本次 continuation 中逐文件阅读全文、并把注释/文档与相邻实现核对的文件。共 203 个 `manual-full-context`，另有 3 个空文件或无注释文件标记不适用。
- 前一阶段曾报告另有 30 个完整人工审阅文件，但精确文件名未保留下来，因此没有并入 `manual_review.tsv` 或 203 的可审计计数。
- 全量清单中的其余范围：1,600 个 UTF-8 源码/文档仅完成字节与编码扫描，214 个结构化配置/数据仅完成字节与编码扫描，2,297 个 `data/` 规则文件按任务约定只做清单与字节扫描、未逐条审核卡牌规则，38 个二进制文件不适用，28 个空文件不适用，1 个生成的依赖锁文件不适用。
- “机器字节扫描”不等于语义审阅；未在 `manual_review.tsv` 中列出的文本文件不能视为完成人工逐文件语义检查。

本轮人工优先覆盖了：`training/core/eval`、`matchup`、`inference`、`config`、`cfg`、`network`、`actor`、buffer/opponent/perf、核心训练生命周期、全部 `tools/runs` 生产 Python、五范式 loader/config/paradigm/network/loss/policy、IR 编译核心五文件，以及当前规则学习路线和指定实验入口。当前 consequence/RL/transfer/gradient 实验源码及结果报告按维护边界只读审阅。

## 已修正的主要文字问题

- 评估与基线：BC gauntlet 支持状态、DMC/PPO 非零 `n_simulations` 的实际异常行为、greedy tune 评分依据、D1-D4 minimax 描述与 loader 注册范围。
- 配置与形状：legacy 配置实际适用 DMC/CFR；schema 校验阶段边界；五个范式都使用 `build_shape_from_toml`；配置字段是 `agent: ObsShape`；`AgentConfig`/`ObsShape` 有 8 个形状字段。
- 观测与网络：typed-damage padding 是类别 `-2` 加零标量，并由可学习 padding embedding 处理；未来 checkpoint schema 版本没有被当前实现拒绝；移除私有记忆引用和过期迁移叙述。
- actor 与 IPC：Go pipeline 参数已经收进 `PipelineTuningCfg`；transition wire v3 refs/pay 是按 `n_legal` 传输；Python multiprocessing queue 仍受支持；socket 回调仍进入请求队列；`LocalNetworkProvider` 的 SHM 分支当前不会轮询权重。
- 规则与协议：TableCtor 实际发出 `OpLoadImm(0)`；`OpCall` 对应 builtin/dynamic method；平局 winner 是 `2`；`EpisodeRunner` 不直接向 `EpisodePolicy.act` 转发 deterministic/epsilon。
- 生命周期与运行工具：移除已删除入口和过期阶段说明；修正 metadata writer 在已持锁场景下的用法，避免文档建议嵌套 flock；补齐 sync 会传输 config snapshots；明确 status/pull/tail/source sync 的 PowerShell 远端边界；修复 IPv6 zone-id 注释自相矛盾。
- 范式：AZ MCTS 配置是运行配置的子集而非逐字段镜像；AZ policy 的当前路径是 `training.paradigms.az.mcts`/`selfplay`；DMC/PPO wrapper 说明与共享 `AgentModuleWrapper` 一致；DMC loss 的 pipeline 参数是 `DMCNetwork`。
- 路线文档：当前 paired joint RL 已完成，预测改善但动作响应和 D2 强度未改善；梯度复核没有发现规则编码器整体断开；下一候选改为显式后果残差策略。

历史实验名、历史结果、旧版本事实均保留为历史，没有机械重命名。

## 未修改的运行契约疑点

1. `tools/eval/eval_service_schema.json:48` 把 greedy depth 限为 1/2/3，而 `training/core/matchup/greedy_player.py` 接受 D1-D4。触发条件是 eval-service gauntlet 请求 depth=4；影响是服务 schema 会拒绝核心 player 支持的 D4。
2. `training/paradigms/ppo/_player_loader.py:44-49` 的 `_game_started` 一旦置真不会在复用 player 时复位。触发条件是同一个 loader 生成的 player 对象跨多个环境/游戏复用；影响是后续游戏可能跳过 `PPOAgent.game_start`，沿用旧静态观测缓存。
3. `training/core/actor/network_provider.py:152-179` 的 `LocalNetworkProvider.update_weights()` 在附加 `_shm` 且未传 `state_dict` 时直接返回，权重和版本不会更新。触发条件是通用 `build_network_provider(local, weights_shm=...)` 后依靠 `update_weights()` 轮询；影响是该 provider 可能继续使用旧权重。当前 semantic RL 每轮保存 `latest`，新建 `ProcessPoolExecutor`，worker 由 `evaluate.initialize` 经 `load_player(semantic_rl)` 重载；它不经过 `LocalNetworkProvider`/`WeightsSHM`，所以此问题不影响本轮 semantic RL 训练。
4. `training/core/actor/inference_server_socket_listener.py:96,124` 将连接设为无超时阻塞读取。触发条件是 peer 保持空闲连接且 listener 收到 stop event；影响是 daemon handler 不能在 peer 关闭前观察 stop event，可能晚于 listener 退出。
5. `RemoteCfg` 接受 linux/darwin，但 `tools/runs/status.py`、`pull.py`、`tail.py` 与 `_remote_sync.py` 的多条远端路径直接构造 PowerShell 命令。触发条件是这些工具使用非 Windows remote cfg；影响是命令可能在远端缺少 PowerShell时失败。文档已明确现有能力边界，运行行为未改。
6. `tools/runs/build_engine.py` 对 linux 与 darwin 共用 `.so` 输出名。触发条件是 `remote.os = "darwin"`；影响是产物名与仓库本机约定的 `libgicg.dylib` 不一致。未改构建逻辑。

## 验证

- 结束时重新读取 Git 清单，仍为 4,382 个文件；`coverage.tsv` 无缺项、无陈旧项。
- `manual_review.tsv` 有 203 个 `manual-full-context`、1 个无注释文件和 2 个空文件；其中 196 个 Python 文件全部通过 `ast.parse`。
- `git diff --check` 通过；五个已审阅 IR Go 文件通过 `gofmt -d`。
- 全仓 Markdown/TXT 共检查 1,372 个相对链接引用。唯一机器告警是规范目录树里的字面占位符 `./<file>.md`，不是实际链接目标；未发现真实断链。
- 本轮仅修改文字，未运行完整训练或大型 smoke。
