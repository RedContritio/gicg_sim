---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: invariants
---

# Training Architecture — Core SHALL Invariants

> 本文件承载 training-architecture capability 的 25 条 SHALL invariant
> 详细约束。任意冲突应作为 OpenSpec change 提案修订,而非在 training/
> 代码中静默偏离。详细实施(protocol 方法签名、driver state 字段、SHM
> 协议)留 P2 unified-training-pipeline change 与各 subtopic 承接。

## Invariants

1. **Top-level layout**:`training/` SHALL contain only `core/` and
   `paradigms/<name>/` subdirectories。`training/framework/` SHALL NOT
   exist — 全部融入 `core/`(P2 物理 mv 落地)。

2. **Paradigm protocol**:每 paradigm SHALL implement the `Paradigm`
   protocol defined in `training/core/protocols.py`,提供 `make_network` /
   `make_collector` / `make_buffer` / `make_loss` / `make_optimizer` /
   `step_schedule` / `make_episode_policy`。`step_schedule(state:
   PipelineState) -> StepPlan` 返回字段 `collect, n_episodes, train,
   n_train_batches, batch_size, eval, advance_step`;`make_episode_policy(cfg,
   instance_id, deterministic=False) -> EpisodePolicy` 供 actor + EvalWorker
   调用。`make_*` 方法 SHALL be stateless / reentrant(idempotent factory
   契约)。详 [`./protocols.md`](./protocols.md)。

3. **Core paradigm-agnostic**:`training/core/` SHALL NOT import from
   `training/paradigms/*`;反向(paradigm 可 import core)允许。

4. **Inference placement orthogonal**:Inference SHALL support two
   placement modes(`local` / `remote`)and any PyTorch device,placement
   × device 二维正交。NetworkProvider 抽象屏蔽差异。详
   [`./protocols.md`](./protocols.md)。

5. **EpisodeRunner shared**:EpisodeRunner SHALL be the shared atomic
   episode-execution unit,reused by ActorProcess(train data collection)
   and EvalWorker(periodic eval),parameterized only by `EpisodeSpec`
   (scenario_seed / opp / epsilon / deterministic)。详
   [`./eval.md`](./eval.md)。

6. **Eval inference isolation**:Eval inference path SHALL be independent
   from train inference path — 独立 weights snapshot,actors 与 eval
   workers SHALL NOT share inference state。详 [`./eval.md`](./eval.md)。

7. **Pipeline mode dispatch**:Pipeline mode SHALL be selectable via cfg
   `pipeline.mode = "serial" | "async"`。Driver loop SHALL be
   mode-agnostic — paradigm 提供 Collector,Collector 实施处理并行细节。
   详 [`./pipeline.md`](./pipeline.md)。

8. **Cfg 多层继承**:`device` 与 `seed` cfg 字段 SHALL 支持多层继承,任
   意 inner section MAY override outer。详细字段规约由
   `openspec/specs/config-schema/` capability spec 承接(P2 落地)。

9. **Weights sync 协议**:Weights synchronization in async mode SHALL use
   versioned SHM slots(`latest` for actors,`snapshot_<eval-id>` for
   eval workers)。Multi-version slot 保证 actors 与 eval workers 不互
   相阻塞。详 [`./pipeline.md`](./pipeline.md) + [`./eval.md`](./eval.md)。

10. **BC first-class**:BC paradigm SHALL be a first-class registered
    paradigm 在 `training/paradigms/bc/`,SHALL NOT 嵌入 AZ 或 PPO。BC
    collector 从 dataset 读取,no env episode loop;但仍遵循 Paradigm
    protocol。

11. **Encoder paradigm-agnostic**:Network encoder SHALL be
    paradigm-agnostic 位于 `training/core/network/`。Heads(policy /
    value / Q-logits / avg-policy / CE)per paradigm。Paradigm SHALL
    NOT 修改 encoder 结构。详 [`./network-sharing.md`](./network-sharing.md)。

12. **Single entry tool**:Paradigm-specific 启动工具 SHALL 由单入口
    `tools/run.py <cfg.toml>` 替代,paradigm 从 `meta.paradigm` cfg 字段
    auto-dispatch。详 [`../tools-layout/spec.md`](../tools-layout/spec.md)。

13. **NetworkProvider 抽象**:`NetworkProvider` protocol SHALL be defined
    in `training/core/protocols.py` with 4 methods:`forward` /
    `update_weights` / `current_version` / `close`。Local 与 Remote 实现
    SHALL both honor protocol;cfg `pipeline.inference.placement` +
    `eval.inference.placement` 字段决定 factory 返回哪种实现。任何
    paradigm 的 `EpisodePolicy.act()` SHALL only call `provider.forward`,
    SHALL NOT access network 内部状态。详
    [`./network-sharing.md`](./network-sharing.md)。

14. **EpisodeRunner contract 详细**:EpisodeRunner SHALL 接受
    `EpisodeSpec(scenario_seed, opponent_id, starting_player, max_rounds,
    deterministic, epsilon, record_mcts_stats, record_value_pred)`;SHALL
    NOT 持 paradigm 知识(通过 `policy: EpisodePolicy` + `provider:
    NetworkProvider` 注入);单进程内 reentrant(同 spec 同 seed → 同
    episode trace);返回 `EpisodeRecord(transitions, final_reward,
    length, opponent_id, scenario_seed, runtime_metrics)`。Actor +
    EvalWorker SHALL both use EpisodeRunner via the same code path
    (`training/core/actor/episode_runner.py`)。详
    [`./eval.md`](./eval.md)。

15. **Paradigm spec 引用**:Each paradigm SHALL have a dedicated capability
    spec at `openspec/specs/paradigm-<name>/spec.md`,covering algorithm-level
    invariants(loss formula / network heads / collector type)。Algorithm-
    specific SHALL SHALL live in paradigm spec,SHALL NOT 在本 spec 重复:
    - [`paradigm-az`](../paradigm-az/spec.md) — IS-MCTS + KL+MSE loss + replay
    - [`paradigm-dmc`](../paradigm-dmc/spec.md) — MC + logit-as-Q + ε-greedy + SHM
    - [`paradigm-cfr`](../paradigm-cfr/spec.md) — OS-MCCFR + reservoir + advantage+strategy
    - [`paradigm-ppo`](../paradigm-ppo/spec.md) — GAE + clipped surrogate + rollout
    - [`paradigm-bc`](../paradigm-bc/spec.md) — dataset + CE/KL + no env

16. **Config schema 引用**:Cfg schema(R1-R7 placement rules +
    INHERITED_FIELDS registry)SHALL live in
    [`../config-schema/spec.md`](../config-schema/spec.md)。本 spec 的 cfg
    字段引用 SHALL 通过 path reference,SHALL NOT 重复字段定义。

17. **Tools layout 引用**:Tools 重组(`tools/run.py` 单入口 + 子目录分
    类)SHALL by [`../tools-layout/spec.md`](../tools-layout/spec.md)。
    本 spec SHALL 引用 tools-layout 而 SHALL NOT 列具体目录结构。

> Invariants 18-19 added by `core-network-generic-promotion` (archived
> 2026-05-17) — e2e smoke 契约(每 paradigm `@pytest.mark.smoke` 必有)+
> 5 paradigm 共用 generic backbone(配合 `network-architecture` SHALL 15)。
> SHALL #18 后由 `paradigm-smoke-full-tier`(archived 2026-05-17)扩展
> 加 smoke_full tier(opt-in 完整 driver e2e + ckpt save / resume verify)。
> Paradigm-specific smoke probe + smoke_full tier 详节见
> [`./smoke-contract.md`](./smoke-contract.md);backbone unification 实施
> 细节见 [`./network-sharing.md`](./network-sharing.md)。

18. **Smoke test contract(two-tier)**:每 paradigm SHALL provide e2e
    smoke test `training/tests/test_<paradigm>_smoke.py` with
    `@pytest.mark.smoke` marker(default tier)。Default smoke SHALL:
    (1) 从零启动(无 ckpt 依赖,random init);(2) 真走
    `collector → buffer → forward → backward → optimizer.step`,SHALL
    NOT stub training loop;(3) eval probe ≥ 1 局 e2e episode,terminal
    reward 在 `[-1, +1]` 流通;(4) paradigm-specific invariant(per
    [`./smoke-contract.md`](./smoke-contract.md) §3);(5) wall time ≤
    2 min(CI / pre-commit 友好)。Default smoke pass 是 paradigm 接入
    merge gate。Additionally,每 paradigm SHALL provide a second-tier
    smoke test `training/tests/test_<paradigm>_smoke_full.py` with
    `@pytest.mark.smoke_full` marker covering full `tools.run` driver
    path(100-step train + ≥ 2 ckpt save + resume verify)— opt-in only,
    SHALL NOT be collected by default `pytest`。Full smoke_full 协议
    (7 子约束 A1.6.1-A1.6.7,covering subprocess driver / ckpt cadence /
    resume functional verify / addopts exclusion / wall budget / toml
    extends / pytest.skip allowance for pre-existing paradigm bugs)详
    [`./smoke-contract.md`](./smoke-contract.md) §4。

19. **Backbone unification across paradigms**:所有 5 paradigm(AZ / BC
    / CFR / DMC / **PPO**)SHALL consume `core/network/ActorCritic` via
    `make_actor_critic(cfg, head_kinds, use_typed_damage)` 工厂函数,
    SHALL NOT 维护 paradigm-local backbone(如 PPO 历史 `_PPOMLPTrunk`)。
    Paradigm 间差异 SHALL 仅在:(a) head subset 选择;(b) `use_typed_damage`
    开关;(c) loss / collector / inference 策略;不在 backbone 本身。
    PPO 历史 outlier 通过 `ppo-structural-backbone-migration` archive
    (2026-05-17 ship)收编,5 paradigm 100% 闭环。

> Invariants 20-25 added by `env-factory-unification` (archived
> 2026-05-17) — `make_env_factory` 公共契约(canonical signature + 3
> required arg + cfg scoping + obs_config_json semantics + per-game
> seed + single source-of-truth)。canonical signature + usage examples
> 详节见 [`./env-factory.md`](./env-factory.md);anti-pattern(`_legacy.py`
> 后缀禁止)落 [`./paradigm-onboarding.md`](./paradigm-onboarding.md) §7.6。

20. **PA-EF1 — `make_env_factory` 3 arg required**:`make_env_factory` 的
    3 个 arg SHALL 全 required — `cfg` / `obs_config_json` /
    `master_seed`。**NOT** 允许 default 值(无 `master_seed=None` magic
    从 cfg 读取 seed)。详 [`./env-factory.md`](./env-factory.md)。

21. **PA-EF2 — cfg 只读 scenario**:`cfg` 参数 SHALL 只读 `cfg.scenario`
    (ScenarioConfig)。**NOT** 允许直接读 `cfg.obs` / `cfg.seed` /
    `cfg.meta.seed` 等其它 cfg 字段;这些由 caller 转换后通过
    `obs_config_json` / `master_seed` 显式传入。

22. **PA-EF3 — obs_config_json=None 合法**:`obs_config_json=None` SHALL
    be 合法输入,语义 == engine 默认 obs config(all-on shuffle +
    include_char_skill_refs)。适用于 paradigm 不持有 `ObsConfig` 字段
    时(如 DMC / CFR / BC)。

23. **PA-EF4 — AZ 调用方式**:`obs_config_json=cfg.obs.to_engine_json()`
    SHALL 是 AZ paradigm 调用方式(AZ 持有 `cfg.obs: ObsConfig`,转 dict
    显式传)。

24. **PA-EF5 — per-game seed 协议**:返回 closure
    `env_factory(game_idx: int) -> GicgEnv` SHALL 满足:per-game seed =
    `master_seed + game_idx`,reset 后返回。GicgEnv 构造参数 SHALL 严格
    从 `cfg.scenario` 转发(`team_0` / `team_1` / `card_pool` /
    `data_dir` / `max_rounds` / `fix_dice` / `obs_mask` / `deck_padding` /
    `pool`)。

25. **PA-EF6 — single source-of-truth**:**SHALL** be the only
    `make_env_factory` symbol in `training/core/`。**SHALL NOT** 共存
    `env_factory_legacy.py` / `env_factory_v2.py` 等并行版本。`_legacy.py`
    后缀禁止规则见 [`./paradigm-onboarding.md`](./paradigm-onboarding.md) §7.6。
