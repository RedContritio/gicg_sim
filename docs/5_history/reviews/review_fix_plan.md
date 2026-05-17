# CFR + MCTS review fix plan

两份 subagent 评审(CFR 25 条,MCTS 14+ 条可见项)的完整设计修正方案。
每条给出: 问题速记 → 修复路径 → 成本估算 → 风险。分档:A=r008 阻塞、
B=算法正确性、C=实现/资源、D=架构、E=测试、F=文档。

---

## A. 阻塞级(r008 启动前必须)

### A1. launcher KeyError (CFR #1)
- **问题**:`tools/run_cfr.py:229` 打印 `buffer_sizes['advantage']`,trainer 已改为 per-player keys (`advantage_p0` / `advantage_p1`)
- **修**:改 f-string 为 `adv{p0+p1}` 合计或 `p0=.../p1=...`。~5 行
- **成本**:15 分钟
- **风险**:无

### A2. r008 gauntlet 无可执行脚本 (CFR #22)
- **问题**:`send_gauntlet.py` 只支持 az challenger;plan 写"or POST socket"但无工具
- **修**:方案二选一
  - a) 扩展 `send_gauntlet.py` 加 `--challenger-type {az,cfr}` + `--challenger-ckpt`(默认行为保持兼容 r007 path)
  - b) 新工具 `tools/send_matchup.py` 通用化 eval_service 调用
- **推荐 b**:新工具更符合 matchup API 的 generic 设计,send_gauntlet 可保持遗留。~150 行
- **成本**:2 小时
- **风险**:低

---

## B. 算法正确性(r008 可信度)

### B1. W 公式可能错 (CFR #2 + #3 + #15 打包)
- **问题**:`traversal.py:567` 用 `W_I = reach_opp_pre / reach_q_full`。reviewer 认为 `reach_q_full` (整条路径 q 积) 是错的,应该是 `q_tail_after_I` 或配合不同分子。convergence test 用 depth=1 简化 (`W=1/q_sampled`),没有 exercise production path,算法错误不可见
- **状态(2026-04-21 验证)**:
  - RPS (depth=1) convergence test 通过 ✓
  - Kuhn Poker **external-sampling** MCCFR 收敛到 Nash 家族成员(α≈0.12):`TestKuhnPokerExternalSampling` passed。这验证了:基础 CFR 算法 + `regret_to_policy` + 反事实 regret 更新 r(a)+=reach_opp·(v(a)−v(σ)) + reach-weighted strategy avg **全部正确**
  - Kuhn Poker **outcome-sampling** MCCFR 未收敛(我实现了 OpenSpiel 参考风格的递归 OS-MCCFR,reach_i/reach_opp/sample_prob 显式追踪,P1(K) bet 卡在 0.36-0.56)。标为 `xfail` (`TestKuhnPokerOutcomeSampling`)
  - **结论**:bug 定位在 OS-MCCFR 的 importance-weight bookkeeping,而非共享的 CFR algebra。production 的 `traversal.py:567` 公式是 OS 变种,可能与此 toy test 同 bug,但需要更精细的 pin-down
- **修**(分步):
  1. 完成的验证 ✓(external sampling 通过 + outcome sampling xfail,bug 局部化)
  2. **精准定位 OS bug**:对比当前实现 与 OpenSpiel `OutcomeSamplingMCCFRSolver` 源码(`open_spiel/python/algorithms/outcome_sampled_cfr.py`)line-by-line。重点看它如何从 terminal 往 root 传 util(是否带 1/q_tail IS 调整)+ regret 更新分子分母
  3. 修复 Kuhn Poker xfail test(先让 toy converge),再同步修 production `traversal.py`
  4. 修复后用 200 iter × 32 traversal smoke run 二次验证:advantage_loss 应更平滑、strategy_loss 单调下降
- **成本**:0.5-1 天(算法验证部分完成,剩下 pin 具体 bug + 修)
- **风险**:**中**(从"高"降)。基础算法被验证正确,W 公式 fix 改动范围限于 `_regret_estimate` + 可能的 util-return 签名;已训的 smoke ckpt 语义会变但无 production ckpt 受影响
- **依赖**:r008 启动前必须完成 — 否则 r008 跑出来无论胜负都不能解释(paradigm vs implementation bug 不可分)

### B2. per-player net 伪独立 (CFR #8)
- **问题**:`_encode_static` 用 `advantage_nets[0].hook_encoder`,然后 `_current_policy` 把这个 hook_emb 喂给 `nets[acting]`。p1 的 policy 依赖 p0 的 hook_encoder 权重
- **修**:`_encode_static` 产出两份 hook_emb(每 net 一份),`static.hook_emb_per_player: list[tensor]`。`_current_policy` 按 acting_player 取对应。静态分支其他字段(counter_sids 等)共享
- **成本**:4 小时(含 parallel trainer / worker 的 static 传递链)
- **风险**:中。需要更新 _StaticBundle 结构 + 所有 consumer(CFRTraverser / ingest / reservoir 没有直接消费 hook_emb,只传 tokens,所以 reservoir 侧不受影响)

### B3. Linear-CFR weighting 概念混淆 (CFR #4)
- **问题**:当前 `weight = iteration / iteration.max()`,既不是 uniform reservoir 也不是 Linear-CFR 的 `Σ t·ℓ / Σ t`。AdvantageNet fit 完全没加权
- **修**:
  - Strategy fit: `(ce_per_row * weights).sum() / weights.sum()` 其中 `weights = iteration.float()`(不归一,或归一到 mean 1 但用 weighted mean 公式)
  - Advantage fit: 同样加入 iteration weighting 或明确放弃 Linear 变体(回到 uniform)
  - docstring 显式注明实现的变体(原 Deep CFR uniform / Linear / third hybrid)
- **成本**:1 小时
- **风险**:低,但 **收敛速度可能变化**,r008 时长估算需同步更新

### B4. gauntlet 用 argmax 低估 CFR (CFR #24)
- **问题**:`_loader_cfr` 在 `n_simulations=0` 走 `_AZGreedyPlayer` (argmax)。CFR 的 Nash 在 argmax 下塌缩为 pure strategy,失去混合精髓
- **修**:新增 `_CFRSamplePlayer`,n_simulations=0 时从 strategy head 的 softmax 里 sample(τ=1 或可配置温度)。调用点按 opponent spec 里的新字段 `mode: "argmax" | "sample"` 选
- **成本**:2 小时
- **风险**:低。r008 plan 的 Matchup A / B 改成 sample-based,结论更有意义

### B5. Python parallel MCTS send_eval 不 copy obs (MCTS #18')
- **问题**:`get_action_refs` / `get_legal_action_payments` 从 `_engine._*` 返回的 ctypes buffer 可能在下次 env.step / restore 后被 mutate。Go 路径 (`mcts_go.py:138`) 明确注释 copy;Python parallel 路径没有
- **修**:在 `inference_client.send_eval` 里对传入的 refs/payments/dyn 做 `np.ascontiguousarray(..., copy=True)` 或显式 `.copy()`。或在 env 层 `get_action_refs` 本身返回新 buffer
- **成本**:1 小时 + 验证(需要实测 buffer 真被 mutate — engine 代码读一遍)
- **风险**:如果 engine 确实返回 fresh buffer(大概率是),fix 是 no-op 的 defensive copy,无害但值得;如果 buffer 确被复用,这是**真 bug**

### B6. InferenceClient 无 request_id FIFO 假定 (MCTS #19)
- **问题**:server 乱序返回会整树错位,无 defensive assertion
- **修**:
  - a) 确认 server 是 FIFO 的:读 `training/inference_server.py` 验证 batcher 输出顺序 = 输入顺序
  - b) 如果是,在 `InferenceClient.send_eval` 加一个 sequence check(本地计数 + assert),便宜
  - c) 如果不是,加 request_id 字段,发 + 收都带 id,server 不动
- **成本**:a) 30min,b) 30min,c) 4 小时
- **风险**:低(多数情况 a 已满足)

### B7. _random_rollout_value 深度超限返回 0(当平局)(MCTS #24)
- **问题**:Go 层 rollout.py:154 `winner<0 → 0.0`,但 sync tree 同 config 超限是 raise。同 config 不同路径语义不一致。value_mix_lambda<1 时有向 draw 的系统偏
- **修**:Go rollout 超深度应返回 `winner=-2` 哨兵,Python 侧识别 → skip 这个 rollout(不 backup)而非当 0 回填。或让 sync tree 也改成 "draw 回填"(不推荐,原 raise 更严)
- **推荐**:sync + async 都改成 raise,上层 catch 决定(当前的 raise 在 production 会让整搜索崩,需加 catch + 跳过该 rollout)
- **成本**:2 小时
- **风险**:中(改变 rollout 超限行为,要看现有 data 分析)

### B8. `_apply_leaf_mixing` prior blend 不 sum to 1 (MCTS #25)
- **问题**:只遍历 `legal_ids`,children dict 中上轮 determinization 留的 aid 不被修改。传给 Go 侧如果依赖 normalization 会错
- **修**:expansion 时 `node.children` 只包含当前 legal 的 aid(已经是这样?需验)。若 children 真含 stale aid,在 leaf mixing 之前 prune
- **成本**:1 小时验证 + 半天修
- **风险**:中

---

## C. 实现 / 资源

### C1. NaN raise 粒度过粗 (CFR #11)
- **修**:`_current_policy` 在 regret forward 外 wrap try/except ValueError。若 NaN,回退到 uniform over legal,log warning。继续 traversal
- **成本**:30min
- **风险**:低

### C2. MT seed relation for per-player reset (CFR #7)
- **修**:`torch.manual_seed(hash((seed, iteration, p)))` 或 `seed + iteration*7919 + p*10007`
- **成本**:5 min
- **风险**:无

### C3. CFRAgent 继承浪费 (CFR #13)
- **修**:改组合,不继承 Agent。CFRAgent 内部:
  - 复制 `_parse_dynamic_single` / `_pad_action_refs` / `_pad_action_payments` 的实现(~40 行)
  - 不再构造 ActorCritic + AdamW
  - encode_static 和 eval_state 自己实现
- **成本**:3 小时
- **风险**:中(代码重复,改 Agent 不会自动同步 CFRAgent)

### C4. 每 iter pickle 2x state_dict × N workers (CFR #12)
- **修**:shared file handoff。trainer 每 iter `torch.save([w0, w1], /tmp/cfr_weights_iter{i}.pt)`,worker 在 WorkItem 里只收 path,`torch.load(path)`。用 atomic write(tmp + rename)避免 partial read
- **成本**:3 小时
- **风险**:低(tmp 路径管理,但已有模式)

### C5. static dedup across gid (CFR #5)
- **问题**:同 static bytes 在 central reservoir 被多次 register_game,各自独立内存
- **修**:用 hash(static tensor 的 bytes) 做 gid 复用。添加 `_static_hash_to_gid: dict[bytes, int]` 索引,`register_game` 先查 cache
- **成本**:2 小时
- **风险**:低(refcount 已经有,只是改去重维度)

### C6. prune_empty_registrations O(N) (CFR #6)
- **修**:维护 `_zero_refcount_gids: set[int]`,register 时加入 set,第一次 add_sample 时从 set 移除,refcount==0 时加回。prune 变成遍历小 set
- **成本**:1 小时
- **风险**:低

### C7. 2x advantage buffer memory (CFR #14)
- **修**:docstring 更新 r008_plan 加入真实内存估算。不改实现(per-player buffer 是 #1.5 的必需)
- **成本**:15 min(纯文档)

### C8. sequential vs parallel rng (CFR #20)
- **修**:文档化 "parallel 模式下 rng 消费顺序与 sequential 不同;同 seed 不跨模式复现"。实现角度用 `torch.Generator(device).manual_seed()` 局部化太大改动,defer
- **成本**:10 min

### C9. KeyboardInterrupt iter 0 (CFR #21)
- **修**:`except KeyboardInterrupt` 里 `if metrics_log and metrics_log[-1].iteration >= 1: save_checkpoint(...)`;否则 print "interrupted at iter 0, no trained ckpt saved"
- **成本**:10 min

### C10. Dead defensive cleanup (CFR #9 + #10)
- **修**:删除 `regret_to_policy` 中 full-illegal row 的 clamp(让它产生 NaN,前置 validate 保护)。删除 `_sample_action` 的 total validation(`_sampling_dist` 已 renormalize)
- **成本**:10 min
- **风险**:低,按 CLAUDE.md 规则

---

## D. 架构

### D1. ParallelCFRTrainer 继承 smell (CFR #19)
- **修**:抽 `_CFRTrainerBase`(无 env_factory + `_run_traversals` abstract);`SequentialCFRTrainer(env_factory)` + `ParallelCFRTrainer(worker_cfg, n_workers)` 都继承 base
- **成本**:4 小时
- **风险**:中(改 public API — tests 和 CLI 都要改)

### D2. 无树复用 (MCTS #27)
- **设计讨论**:AlphaZero 式实现通常不 reuse tree across turns,因为 action 很多时 subtree 索引复杂,reuse 收益有限。**defer**
- **成本**:设计决策,留 TODO 注释

### D3. _AgentMCTSPlayer 硬编码 config (MCTS #28)
- **修**:`_AgentMCTSPlayer.__init__` 接受 `dirichlet_eps / temperature_switch_step / value_mix_lambda / prior_mix_lambda` 覆盖。默认保持当前值,gauntlet 可调
- **成本**:1 小时
- **风险**:低

### D4. CFRAgent via AZ MCTS 语义不匹配 (MCTS #29)
- **修**:`training/cfr/agent.py` docstring 加"Known approximation: CFR strategy head's output is being used as the MCTS prior via the Agent protocol. AZ's policy head represents visit-count prior; CFR's head represents average Nash strategy. Two distinct semantics collapsed to one interface — MCTS treats it as a numerically identical prior but the value distribution differs (Nash mix vs visit-distribution)."
- **成本**:15 min
- **风险**:无(纯文档标注)

### D5. MCTS missing imports (MCTS #30)
- **修**:`rollout.py` / `parallel.py` 加 `from typing import Optional` + `import numpy` 其中未 import 的
- **成本**:5 min
- **风险**:无

### D6. `_commit_parallel_rollout` Optional config (MCTS #31)
- **修**:去掉 `Optional`,config 变 required。更新 caller
- **成本**:30 min
- **风险**:低

### D7. _make_eval_callbacks single-goroutine assumption (MCTS #20)
- **修**:加注释 + assert that Python-side receives send/recv in same thread,或 wrap list 成 queue.Queue 做真 thread-safe
- **成本**:30min for doc/assert,2h for queue refactor
- **推荐**:doc/assert

---

## E. 测试

### E1. toy convergence depth=1 only (CFR #15)
- **修**:加 Kuhn Poker (depth=4 sequential with chance) convergence test。Python 手写 env(3 cards,bet/pass,1 round) + 跑 CFR 10K iter,验 avg strategy 收敛到解析解
- **成本**:半天
- **风险**:中(需实现 toy env + 验证 Nash 参考值)

### E2. 与 B1 合并(同一 toy game 覆盖)

### E3. id() net swap test (CFR #17)
- **修**:`assert next(net.parameters()).data_ptr() != old_data_ptr`
- **成本**:5 min

### E4. weights_per_player length test (CFR #18)
- **修**:加 `test_wrong_weights_length_raises` 测试
- **成本**:15 min

### E5. pickle drain roundtrip (CFR #16)
- **修**:现有 `TestIngestBatches.test_replay_into_reservoirs` 增强,添加 dtype + shape + numeric content equality 断言
- **成本**:30 min

### E6. MCTS mirror symmetry (MCTS #22)
- **修**:`test_mcts_mirror_symmetry`:mirror 游戏 root state 运行搜索,验两边 visit 分布对称(容许随机噪声)
- **成本**:2 小时

### E7. N_virtual rollback (MCTS #23)
- **修**:parallel 跑 N rollouts 后遍历树,`assert all n.n_virtual == 0`
- **成本**:1 小时

### E8. determinize diversity (MCTS #26)
- **修**:N=1000 样本,检查 hand refs 多样性(unique count 合理)
- **成本**:1 小时

### E9. prior blend sum=1 (MCTS #25b)
- **修**:expand + leaf mix 后 `assert abs(sum(prior) - 1) < 1e-6`
- **成本**:30 min

---

## F. 文档

### F1. reservoir docstring vs train.py Linear claim (CFR #25)
- **修**:同步文案,解释 hybrid 实现
- **成本**:10 min

### F2. r008 timeline realistic (CFR #23)
- **修**:跑 medium preset 一次实测,用数据校准 r008_plan 里的 estimate
- **成本**:medium preset 跑一次 ~1h + 更新 plan 15 min
- **风险**:无

---

## 批次与排序

建议 6 个 commit:

### Commit 1 — Blocker fixes(30 min)
- A1 launcher
- A2 send_matchup tool

### Commit 2 — CFR algorithm verification + optional fix(1-2 天)
- B1 推导 W 公式 + Kuhn Poker toy
- B2 per-player static hook_emb 独立
- B3 Linear-CFR weighting 对齐
- 集成 test

### Commit 3 — MCTS correctness(半天)
- B5 Python parallel copy
- B6 FIFO assertion
- B7 rollout depth semantics
- B8 prior sum=1
- E6/E7/E9 测试

### Commit 4 — Gauntlet improvements(2 小时)
- B4 CFR sample mode
- D3 _AgentMCTSPlayer knobs
- r008_plan gauntlet 协议更新

### Commit 5 — Resource / performance(半天)
- C1 NaN fallback
- C2 seed dispersion
- C3 CFRAgent composition
- C4 shared file weights
- C5 static content dedup
- C6 prune set
- C9 KeyboardInterrupt msg
- C10 dead defensive

### Commit 6 — Cleanup(1 小时)
- D4/D5/D6/D7 注释 + imports + required config
- E3/E4/E5/E8 小测试
- F1/F2 文档
- 3.10 dead branch
- 小 nit

**总成本估算**:4-5 个工作日,主要 cost 在 B1 算法验证 + B2 static 重构 + E1 toy env。

**r008 启动条件**:Commit 1 + Commit 2(最小集)。其余 commit 可平行或 r008 后做。

## 明确 defer(不做)

- **D2 MCTS 树复用**:收益不对称,AlphaZero-style 惯例不 reuse
- **C8 rng 跨模式**:需要整个训练栈改 torch.Generator,大重构,defer
- **MCTS 早期项 #1-17**:subagent 输出截断,没拿到完整列表,需要再跑一次 review 才能覆盖。在本轮 plan 不处理
