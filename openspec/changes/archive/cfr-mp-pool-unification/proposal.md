---
last_updated: 2026-05-29
status: DRAFT
schema_version: 0
change_id: cfr-mp-pool-unification
---

# Proposal — CFR mp actor pool 统一到 core/actor + actor_main batch lifecycle

## 1. Why

I31 backlog #88 (AZ/CFR/PPO mp actor pool 统一到 core/actor.actor_main) 第二
波 — PPO change 已 ship (`openspec/changes/ppo-mp-pool-unification/`,AB13
provider_kwargs escape hatch 已立)。 CFR 是本 backlog 三个目标 paradigm 中
**架构距离 DMC 模板最远**的一个,与 PPO 简单 env-var-cleanup 不同,本 change
本质是把一个 trainer-shaped 的 mp 子系统 collapse 到 collector-shaped 模板。

CFR 现状 (`training/paradigms/cfr/parallel_trainer.py` 170 LOC +
`worker.py` 203 LOC = 373 LOC) 三层痛点:

1. **完全独立的 mp orchestration**:`ParallelCFRTrainer.__init__` 用
   `mp.get_context('spawn')` + 自建 N 个 in_q + 1 个 out_q + `spawn_worker
   ` (`worker.py:189`) → 不走 `Runtime.start_actors` / `ActorProcess` /
   `actor_main`。 与 DMC (`paradigms/dmc/collector.py:_bootstrap`) + PPO
   (`paradigms/ppo/_async.py:__init__` 已 ship) 完全双轨;新加 paradigm /
   修 mp lifecycle bug / hardening child env (CPU affinity / SIGTERM / perf
   trace) 每条路径都要分别修。

2. **trainer-shaped 而非 collector-shaped 的 lifecycle**:CFR 当前
   `ParallelCFRTrainer extends CFRTrainer`,owns 全部 N worker process +
   advantage_nets + buffer + fit pass(per `collector.py:205`
   `CFRAsyncCollector` NotImplementedError docstring 已诚实记录这个架构问
   题)。 worker.py 持续运行 (`while True: in_q.get()`),每 WorkItem 含
   `n_traversals` 个 traversal,worker 在 spawn 后**持久** advantage nets +
   collector 实例,只 reload state_dict — 与 actor_main 的 `EpisodeSpec
   → EpisodeRunner.run` per-episode 模式 mismatch。

3. **weight transfer 仍走 pickle-over-Queue,与 DMC/PPO 分歧**:
   `ParallelCFRTrainer._run_traversals` (`parallel_trainer.py:89`) 每
   iteration `weights_per_player = [{k: v.detach().cpu().clone() for k, v
   in net.state_dict().items()} for net in self.advantage_nets]`,把 2 个
   state_dict 直接 push 进 WorkItem (pickle 走 mp.Queue) → 每 iter ~5-50
   MB transfer。 DMC 走 InferenceServer + GPU forward,PPO 走 WeightsSHM
   broadcast — CFR 第三条 wire。

cleanup risk / 收益评估:
- **CFR 是 frozen-research tier** (per `paradigm.py:11` C6.1 + memory
  `project_rl_routes_closure_2026_05_12`),production 投入低 → refactor
  risk 可控 (no perf regression 担忧),但收益主要在统一性 + 模板复用,不
  在 perf。
- **mp race / weight sync / deadlock 是 latent bug 重灾区** (memory backing
  I31 backlog #88 risk note) — CFR 的独立 mp orchestration 是当前 3 个
  paradigm 里**最复杂**的(N in_q + 1 out_q + per-WorkItem state_dict +
  同步 barrier),统一后 actor lifecycle bug 集中在 core/actor 一处治理。
- ~373 LOC duplication 删除 (`parallel_trainer.py` 170 + `worker.py` 203
  - 新 `mp_factories.py` ~250) ≈ **净 -120 LOC**,但更重要的是删除 1 整套
  独立 mp 子系统。

## 2. What

**5 part refactor** (LOC budget: 净 -100 ~ -180, 看 D1 决策):

1. **(可选,看 D1) `actor_main` 增 `episode_runner_factory` 字段**
   (`training/core/actor/actor_process.py:actor_main`):paradigm-agnostic
   escape hatch,默认 `EpisodeRunner(env_factory, opp_registry)`,CFR 传
   `CFRTraversalRunner` (定义在 `paradigms/cfr/mp_factories.py`,实现
   `run(spec, policy, provider) → EpisodeRecord-shaped 输出` 但内部跑
   `CFRTraverser.traverse`)。 该 factory 是 actor_main 中**唯一**与
   episode-vs-traversal lifecycle 差异相关的接口 — 加上后 EpisodeRunner
   保持 paradigm-agnostic, traversal runner 是 CFR-local。

2. **新建 `training/paradigms/cfr/mp_factories.py`** (~ 250 LOC):
   - `build_env_factory(cfg, seed)` — 同 PPO/DMC 模板,从 `cfg.scenario`
     build GicgEnv factory closure。
   - `build_opp_registry(cfg)` — CFR traversal 不需 opponent(双方都遍历),
     stub 一个 empty registry 满足 actor_main 强制字段需求 (actor_main 在
     line 162 验 build_opp_registry 不为 None,empty registry OK)。
   - `build_policy(cfg, actor_id)` — 同样 stub `CFRTraversalPolicy` (内部
     由 traverser 控制 action,policy.act 不被 EpisodeRunner-style 调用)。
   - `build_provider(cfg, actor_id, *, weights_shm_info, worker_blueprint)`
     — 持久化 2 个 AdvantageNet 实例 + WeightsSHM attach + 内部 hold
     `CFRTraverser` 实例。 provider.update_weights 从 SHM read 新 state_dict
     load 到 2 个 net。
   - `spec_sampler(cfg, actor_id)` — sample 1 个 `EpisodeSpec` (字段被
     CFRTraversalRunner 解读为 `(iteration, traverser_player, traversal_seed)`
     —— spec.scenario_seed = workitem.seed_base + k;spec.opponent_id 字段
     重用承载 traverser_player ('p0' / 'p1');spec.epsilon 重用承载 iteration
     的 packed 编码 ALT (不优雅,详 design.md D1 决策))。

   注: 5 件套字段名固定来自 actor_main signature,内容 paradigm-specific。

3. **删 `training/paradigms/cfr/parallel_trainer.py` + `worker.py`** (-373
   LOC),新建 ~120 LOC `training/paradigms/cfr/_async.py` (类比 PPO `_async.py`):
   - `class CFRAsyncCollector` implements core protocol `Collector`(取代
     `collector.py:205` `CFRAsyncCollector` NotImplementedError stub)。
   - `__init__`:WeightsSHM publish + Runtime.start_actors + IPCQueue 收
     `CFRGameBatch` (不收 transitions — CFR collector output 是 cfr_batches
     list,见 `paradigm.py:72` `_CFRBufferBundle.push`)。
   - `collect(n_units, provider)`:drain queue 到 `n_units` batches,返
     `CollectorOutput(transitions=[], runtime_metrics={'cfr_batches': ...})`
     与 `CFRTraversalCollector.collect` 输出契约对齐。
   - `sync_weights(network)` — publish 2 个 AdvantageNet 的 state_dict
     到 WeightsSHM (2 个 slot:'cfr_adv_p0' / 'cfr_adv_p1')。
   - close — runtime.close + tmpdir cleanup。

4. **改 `training/paradigms/cfr/paradigm.py:make_collector`** (改 ~ 10 LOC):
   按 `cfg.pipeline.mode` dispatch:`'serial'` → 现状
   `CFRTraversalCollector`,`'async'` → 新 `CFRAsyncCollector`。 这取代
   `collector.py:CFRAsyncCollector` 的 NotImplementedError stub —
   `parallel_trainer.py` 完全删除 (其 trainer-loop 责任由 unified driver
   通过 collector→buffer→loss path 承载)。

5. **改 tests** (~ -150 LOC):
   - 删 `training/tests/test_cfr_parallel_trainer.py` (186 LOC) — 旧
     `ParallelCFRTrainer` API 已不存在。
   - 删 `training/tests/test_cfr_worker.py` (162 LOC) — 旧 `cfr_worker_main`
     已不存在。
   - 新建 `training/tests/test_cfr_mp_factories.py` (~ 80 LOC) — 单元测
     build_provider 接 weights_shm_info / CFRTraversalRunner.run 1 traversal
     / spec_sampler 编解码契约。
   - 新建 `training/tests/test_cfr_async_mp_e2e.py` (~ 120 LOC,smoke_full
     marker) — 2-actor 真 spawn + 1 iter (8 traversal) + weight sync
     + clean shutdown。

## 3. Affected specs

- `openspec/specs/training-architecture/actor-backend.md`:
  - 看 D1 决策:
    - **D1 选 B (episode_runner_factory)** → ADD AB14 (paradigm-agnostic
      episode/traversal lifecycle runner factory)
    - **D1 选 C (bypass actor_main with paradigm-local cfr_actor_main)**
      → 无新 SHALL (only AB1-AB13 reaffirmed,paradigm-local CFR runner
      复用 Runtime + harden_child_env + sigterm 但不复用 actor_main loop)
    - **D1 选 A (fake episode)** → 无新 SHALL (现有 AB13 + EpisodePolicy
      足够,本 change 只是 implementation pattern)
- 暂时 PLACEHOLDER (待 design.md 决策后填实):
  `openspec/changes/cfr-mp-pool-unification/specs/training-architecture/spec.md`
  内 `# Spec changes: TBD per D1 decision in design.md` 占位。

## 4. Out of scope

- **不改 CFR 算法**:`traversal.py` (OS+ES MCCFR) / `advantage_net.py` /
  `strategy_net.py` / `fit_steps.py` 一律不动,本 change 只搬 mp wire。
- **不动 DMC / PPO / AZ / BC**:CFR-local change,DMC golden 模板保留,PPO
  刚 ship 不动,AZ 留下一波 (backlog #88 第三步)。
- **不解 frozen tier**:`CFRParadigmConfig.tier = 'frozen-research'` 不改,
  本 change 是 maintenance refactor,不解除 production 投入限制。
- **不优化 CFR perf**:traversal 是 game-tree 走法,perf 优化与本 change
  无关 (frozen tier 不投入 production)。
- **不换 IPC wire**:仍 mp.Queue (IPCQueue wrapper); CFRGameBatch pickle
  走 Queue,SHM ring 不引入 (CFR per-iter throughput 远低于 DMC/PPO,无 SHM
  必要)。
- **不接 InferenceServer**:CFR worker 是 advantage net forward 走 local
  net (per actor process hold cpu net + SHM 拉 latest state_dict),与
  PPO frozen tier 同模式,不引 InfServer batched forward (无收益)。
- **不破 ParallelCFRTrainer public API 的下游 callers**:grep 显示仅 2
  test file 用 (`test_cfr_parallel_trainer.py` + `test_cfr_worker.py`),
  不在 production 或 `configs/cfr/*.toml` 任何路径,删除直接,no migration
  shim。
- **不引入新 cfg 字段**:weights_shm_info / spec encoding 走运行时 kwargs
  + spec 字段 packing,不进 cfg.toml (与 PPO change 一致)。

## 5. Decision summary

- **[CC-1] CFR 不重用 EpisodeRunner**:本质架构 mismatch — EpisodeRunner
  假设 our_player 单边步,traversal 双边递归。 不应让 EpisodeRunner 变
  general "1 episode-or-traversal 运行器" (会污染 episode 语义)。 用
  paradigm-local `CFRTraversalRunner` 接口 (实现 `run(spec, policy,
  provider) → CFRTraversalOutput`)。
- **[CC-2] D1 推荐 B (actor_main 加 episode_runner_factory)**:对偶
  AB13 inference_client / provider_kwargs 的 paradigm-agnostic 模板扩展。
  C 方案 (bypass actor_main) 失去 harden_child_env + perf_trace +
  actor log 等 core/actor 资产; A 方案 (fake episode) 违反 EpisodePolicy
  契约(traversal 不是 episode)。 详 design.md D1。
- **[CC-3] D2 推荐 A (WeightsSHM)**:与 PPO 完全对齐,WeightsSHM 写两 slot
  ('cfr_adv_p0' / 'cfr_adv_p1'),worker poll latest。 CFR 训练频次低
  (~ 每 N 秒一次 iter),SHM 写不是瓶颈;统一 wire 简化 testing。
- **[CC-4] D3 推荐 C (actor 连续 loop)**:打破当前 synchronous barrier
  设计,让 actor 持续产 CFRGameBatch 进 queue,trainer 端 drain N batch
  + 推进 fit;失去 per-iter weight version sharp boundary 但 CFR 算法
  对 stale weights 容忍度高(per memory `feedback_stale_weights_ok`)。
- **[CC-5] D4 推荐 A (复用 cfg.pipeline.num_actors / mode='async')**:
  与 PPO 完全对齐, no new cfg field; CFRAsyncCollector 仅在
  `actor_backend='python'` 路径 dispatch (AB3 status: CFR not
  supporting `'go'` backend, 与现状一致)。
- **Effort**:~ 净 -100 LOC code + ~ 300 LOC OpenSpec artifact ≈ 净 +200
  total。 切口干净 (PPO 已 ship + DMC 模板已立 + CFR 是 frozen tier),
  risk 集中在 lifecycle 决策 (D1) 一处,确定后实施 mechanical。
