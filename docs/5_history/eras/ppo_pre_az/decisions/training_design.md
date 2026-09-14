# 设计决策 — Stage A：训练管线设计（已废弃）

> **⚠️ 已于 2026-04-14 废弃。** 本文记录
> **PPO 时代**的训练管线设计决策（D14-D20：dropout、
> 晋级、reward shaping、card pool、产物、ssh 续跑），这些决策随
> PPO 栈本身一起被废弃。
>
> 替代决策与迁移概述现归档于 [`docs/paradigms/az/`](../../../../paradigms/az/README.md)。
>
> 仅保留供历史参考。

---

> 本文是 `docs/decisions/README.md` 的延续。前置阅读 `docs/decisions/README.md`、
> `docs/decisions/capi_obs.md`、`docs/decisions/engine_bugs.md`。本文记录
> 修完引擎 bug 后的训练管线设计决策 (D14-D20)：dropout、promotion、
> reward shaping、card pool 配置、artifacts 布局、ssh 续跑。

### D14：Dropout 与训练/评估模式策略

**问题：** 修复 D11 后的 phase0_v3 训练（约 960 个 episode）中，交叉注意力第 1 层几乎完全均匀。第 0 层有清晰的 hook 专属结构，但第 1 层退化为类恒等行为。标准 Transformer "注意力收敛"模式：残差 + LayerNorm 对计数器嵌入做均值，使各层间趋于同质，导致第 1 层没有可区分的有效信息。

**决策：** 为 `CrossAttentionBlock`、`ActorCritic` 的策略/价值头添加 dropout。默认 0.1，可通过 `[model] dropout = X` 按阶段配置。

```python
class CrossAttentionBlock(nn.Module):
    def __init__(self, d_model=64, n_heads=4, dropout=0.1):
        self.counter_to_hook = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, ...)
        self.attn_drop_c2h = nn.Dropout(dropout)
        self.counter_ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model), nn.Dropout(dropout),
        )
        # hook_to_counter 和 hook_ffn 同理
```

**训练与评估模式策略：**
- **Rollout**（collect_episode）：训练模式，dropout 激活。这意味着存储的 `old_log_prob` 带有 dropout 噪声。
- **PPO 更新**：训练模式，dropout 激活。关键在于 rollout 和更新使用**相同的** dropout 分布——否则重要性比 `π_new / π_old` 在首次梯度步之前就存在偏差。
- **评估**（`evaluate`）：评估模式，dropout 关闭。评估是对确定性策略的测量，而非训练步骤。`train_stage` 在调用 `evaluate` 前切换到 `eval()`，之后立即切回 `train()`。

这是保守选择。部分实现使用 eval 模式 rollout + train 模式 dropout 更新，但这会在每个 epoch 引入比率偏差。

**关于向后兼容性的说明：** 在 `nn.Sequential` 中插入 `nn.Dropout` 会改变 state_dict 的键索引（如 `counter_ffn.2.weight` → `counter_ffn.3.weight`）。旧检查点（phase0_v3 时代）无法加载到新模型中。用户接受了这一点；从头重新训练。

### D15：晋级策略 A（连续评估门控）+ G（部分通过兜底）

**问题：** 使用 `pass_winrate = 0.6` 和 `n_games = 20` 时，单次评估通过的误报率约为 32%（即使真实能力只有 55%）。各阶段"幸运通过"，缺乏统计证据支撑进步。更糟的是，vs-prior 评估存在结构性困难：刚分叉出的智能体对自己的 prior 约有 50% 胜率，要达到 60% 需要真实的新颖进步，可能需要数百次迭代。

**方案考量：**
- A：增加 `n_games`，增加 `min_iterations`，降低门限至 0.55，要求**连续两次**评估点 ≥ 门限方可通过。
- B：仅通过 `min_iterations = 30+` 强制更长的训练。
- C：ELO 评级系统加相对门限。
- D：平均窗口通过条件（要求最近 N 次评估的均值 ≥ 门限）。
- E：vs-random 对手的新卡预热子阶段。
- F：多 prior 对手池。
- G：max_iter 部分通过兜底（阶段耗尽迭代次数仍未正常通过时，不丢失进度）。

**决策：A + G + E**，延后 C 和 F。理由：
- A 是最小统计修复；结合 `n_games = 40`，连续两次误报约 7%
- E（预热）是独立必要的，因为每个 phase 都引入新卡——参见 D16
- G 防止阶段失败"杀死"整个训练过程，同时不妥协通过标准
- C（ELO）更强大，但实现成本约为 5 倍；若 A+G 不足再采用
- F（对手池）在本场景中增加了评估复杂度，收益不大

**后续更新（2026-04，提交 `6ffef04` + `14f1ed8`）：** C（ELO）
和 F（对手池）在 review #7 + #9 之后一起落地。它们通过
`[eval] opponent = "pool"` + `[progression] pass_elo_delta` 按阶段选用；
两者同时设置时，阶段改用 ELO delta 而非胜率作为晋级门限。
A + G 仍是 phase0 及未显式选用的阶段的默认行为。
完整流程参见 `docs/training/promotion.md`。

**G 方案实现草图：**
```python
# In train_stage, after the for loop:
if best_wr >= 0.52 and statistics.mean(last_5_wrs) >= 0.50:
    save_ckpt(stage_name + ".partial.pt")     # marker for inspection
    save_ckpt(stage_name + ".pt")               # so prior chain continues
    ctx.last_passed_ckpt = stage_name + ".pt"
    completed_stages.add(key)
    return "passed"
else:
    save_ckpt(stage_name + ".failed.pt")
    return "failed"
```

### D16：新卡引入的 Reward Shaping（E 方案）

**问题：** 当某个 phase 引入新卡（phase1 添加 L2，phase2 添加 L3，……）时，prior 智能体从未见过这些卡，会忽略它们。新智能体继承 prior 权重，也不会自然地使用新卡。没有明确驱动，新智能体 ≈ prior，新卡从未被探索。vs-prior 胜率始终在 50% 附近徘徊。

**方案考量：**
- 使用 vs-random 训练的按阶段预热（让智能体自由探索）
- 对新卡使用的反直觉辅助损失
- 新卡使用的密集 reward shaping

**决策：预热子阶段 + 新卡密集 reward shaping。**

预热阶段（`phase{N≥1}_warmup.toml`）在每个 phase 的子阶段之前运行：
- 训练对手 = random（自由探索）
- 评估对手 = random（无 prior 依赖）
- pass_winrate = 0.65（vs random 可达上限更高）
- 1v1 随机非镜像队伍（最简队伍规则，收敛快）
- `[reward_shaping]` 列出新引入的卡牌

**奖励公式**（每局、每 card_ref 去重一次）：
```
held_rounds = current_round − card.DrawnAtRound
bonus = max(novel_bonus − novel_bonus_decay × held_rounds, novel_bonus_floor)
```

默认值：`novel_bonus = 2.0`，`decay = 0.5`，`floor = 0.5`。
- 同轮打出（held=0）→ +2.0
- 持有 1 轮 → +1.5
- 持有 2 轮 → +1.0
- 持有 ≥3 轮 → +0.5（地板值）

**per-ref 去重**：每个 `card_ref` 每局最多触发一次奖励。同一 ref 的首次打出后，后续打出不再给予奖励。避免刷同一张卡的利用行为。

奖励自然缩放：有 N 张新卡时，每局最大奖励为 `N × novel_bonus = 8`（典型 phase 引入 4 张新 L 级卡）。这与约 2 次角色击杀的奖励量级相当。

**引擎支持**：`CardInst.DrawnAtRound`、`Game.LastCardRef`、`Game.LastCardDrawnAt`，capi 的 `GameGetLastCard{Ref,DrawnAt}` / `GameGetCurrentRound` / `GameGetCardNames`。Python 端 `GicgEnv.step()` 在每步后查询 `last_card_ref`，并应用奖励公式。

**为何只在引入阶段而非永久应用：** 在后续所有阶段持续奖励卡牌会与 vs-prior 压力竞争，使智能体陷入旧策略。引入时的一次性奖励只是学习驱动，之后策略应通过 vs-prior 压力自然保留该技能。若灾难性遗忘成为可量化的问题，可在后续阶段的 `novel_cards` 中重新列出该卡。

**特殊情况——phase0a：** 在 `novel_cards` 中列出 `["复刻"]`，即使 phase0 没有预热阶段。这激励智能体在 phase0 就学习刻师傅的 刻印→复刻 连招（否则在 phase0 的仅填充卡池下，该连招永远得不到有效学习信号）。复刻**不在任何牌组中**——它是角色通过 `add_card` 生成的卡，因此独立于 `cards.cards` 列于 `novel_cards`。

### D17：明确的 card_pool + extends_path（不感知 L_max 目录结构）

**问题：** A13 之前的 `selfplay.train()` 有一个 `cardLevel int` 参数，对应 `data/cards/L{1..N}/` 目录。A13 重构为 `card_pool: list[str]`，但**所有阶段都被设置为 `card_pool = "all"`**，在每个阶段加载所有卡牌。这悄无声息地丢弃了 L_max 课程渐进式进展。

**早期用户策略：** Go/Python/Lua 不应感知 L1-L6 目录结构。层级是人工组织工具；运行时按卡牌名称对待所有卡牌。

**决策：** 保留不感知层级的规则，但通过 `extends_path` 机制使卡池**按阶段明确**，支持继承：

```toml
# phase1_warmup.toml
[cards]
mode = "explicit"
extends = "../stages/phase0d.toml"
cards = ["美味烧鸡", "佛跳墙", "占星", "诅咒"]
```

`CardSelection` 新增可选的 `extends_path` 字段。`CardSelection.to_card_pool(base_dir)` 递归读取父阶段的卡牌并与自身的卡牌求并集。填充卡 `碌碌无为` 是隐式的（BuildDeck 总会用它填充牌组）。

一个 phase 内的 a/b/c/d 子阶段使用 `extends = "../stages/phase{N}_warmup.toml"`，自动继承预热阶段的完整卡池（无需重新列举）。

这恢复了 L1→L6 的渐进进展，同时*不*将 L 级目录结构硬编码到运行时中。

### D18：按 session_id 自动组织 Session 产物

**决策：** 一个 session 的所有训练产物都存放在单一根目录 `artifacts/<session_id>/` 下（session_id 默认为 `time.strftime("%Y%m%d_%H%M")`）。某 session 产生的所有内容——日志、状态、检查点、指标、图表、replay、pool——都嵌套在该根目录下，续跑只需 `--session-id`：

| 路径 | 产生者 |
|------|--------|
| `artifacts/<session_id>/session.log` | `log_tee.install_log_tee`（追加） |
| `artifacts/<session_id>/state.json` | 每次通过时 `SessionContext.save_state` |
| `artifacts/<session_id>/<curriculum_parts>/<stage>/checkpoint.pt` | 通过时 `stage_loop.train_stage` |
| `artifacts/<session_id>/<curriculum_parts>/<stage>/checkpoint.partial.pt` | G 方案兜底副本 |
| `artifacts/<session_id>/<curriculum_parts>/<stage>/metrics.jsonl` | 每次 iter 的 PPO + advantage 诊断 |
| `artifacts/<session_id>/<curriculum_parts>/<stage>/plots/` | 注意力/权重可视化 |
| `artifacts/<session_id>/pool/` | `OpponentPool.save`（ELO 门控 session） |

续跑：使用相同的 `--session-id`，`load_state` 读取 completed_stages，`train_stage` 跳过已通过的阶段。`--fresh` 忽略已有状态。早期按类型分拆（`checkpoints/`、`logs/`、`plots/`）已废弃——单一 session 根目录更便于移动/删除/归档。

### D19：用 nohup 保证 ssh 断线安全的后台训练

Bash 工具的 `run_in_background` 在子 shell 中运行进程，ssh 断线时会收到 SIGHUP。长时 session 需用 `nohup` 包装：
```bash
nohup .venv/bin/python -m training.session configs/curriculum/full.toml --seed 42 > /dev/null 2>&1 &
```
stdout/stderr 定向到 `/dev/null`——`session.main()` 已通过 tee 写入 `artifacts/<session_id>/session.log`。曾尝试 `setsid` 作为额外保护，但有 `nohup` 后已无必要。

### D20：阶段配置 schema 与评估

规范 schema 在 `training/config.py`——完整字段列表请查阅该文件。Review 后更新：`RewardShaping.coefs: RewardCoefs` 由数据驱动（review #10）；`TrainingParams` 有 `n_envs` / `strict_truncation` / `opponent in {self,random,prior,mix,hybrid_prior0,pool}`；`ProgressionRule.pass_elo_delta: Optional[float]` 在与 `eval.opponent == "pool"` 同时设置时切换为 ELO 门控（review #9）。

晋级检查顺序（在 train_stage 中）：
1. 每次 iter 执行一次 PPO 更新
2. 若 `iter >= min_iter` 且 `iter % eval.interval == 0`：运行 `evaluate`
3. 将胜率追加到最近 2 次的双端队列；若为 ELO 门控，也将 ELO delta 追加到独立队列
4. **胜率路径**（pass_elo_delta 未设置 OR 评估对手 != "pool"）：
   当双端队列中两个值均 ≥ `pass_winrate` 时通过
5. **ELO 路径**（pass_elo_delta 已设置 AND 评估对手 == "pool"）：
   当两次 ELO delta 均 ≥ 阶段开始快照的 `pass_elo_delta` 时通过
6. 通过时：保存检查点，更新 `last_passed_ckpt`，`ctx.pool.add(ckpt)`
   （无论门控模式如何，都为下游阶段播种 pool）
7. 循环结束后（仅胜率路径）：若 `best_wr ≥ 0.52` 且
   `mean(最近 5 次胜率) ≥ 0.50`：G 方案部分通过兜底。ELO 门控
   阶段在达到 max_iterations 时直接失败。
8. 否则：失败（仅有兜底检查点，不更新 prior 链）
