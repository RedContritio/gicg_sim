---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: ppo-structural-backbone-migration
---

# Tasks — ppo-structural-backbone-migration

> Phase 1 = propose(本提案落盘)
> Phase 2 = impl(component-by-component rewrite)
> Phase 3 = verify + commit

## Phase 1 — Propose

- [x] **T0**:propose commit — artifacts 落盘
  - `proposal.md`
  - `design.md`
  - `tasks.md`(本文件)
  - `specs/paradigm-ppo/spec.md`(delta)
  - `specs/network-architecture/spec.md`(delta)
  - `specs/config-schema/spec.md`(delta)
  - **LOC**:~+1200(artifacts only)
  - **依赖**:无

## Phase 2 — Implementation

- [x] **T1**:rewrite `paradigms/ppo/config.py` — PPOAgentShapeCfg 字段对齐
  - **改动**:replace `(d_model, n_hidden_layers, max_actions)` 字段为
    `(n_counter_slots, n_hooks, max_tokens_per_hook, max_actions, d_model,
    n_cross_layers, dropout)` — 与 BC AgentShapeCfg 字段一致
  - **defaults**:用 BC AgentShapeCfg 同样 production 值(`n_counter_slots
    = 2*6*128 + 2*140 + 16`, `n_hooks=900`, `max_tokens_per_hook=120`,
    `max_actions=2048`, `d_model=128`, `n_cross_layers=2`, `dropout=0.0`);
    smoke / test 通过 from_dict override
  - **LOC**:~-10/+30
  - **依赖**:T0

- [x] **T2**:add `paradigms/ppo/agent.py` — PPOAgent(AgentBase)
  - **接口**:
    - `__init__(cfg: AgentConfig, device: str = 'cpu')` — build
      ActorCritic via make_actor_critic + AgentBase super().__init__
    - `act(env, rng, *, deterministic=False) -> (action_idx, meta_dict)` —
      sample action;meta = {'log_prob','value','n_legal'}
    - `forward_batch(collated: dict) -> (policy_logits, value)` — 训练
      forward,对齐 BC/DMC/AZ 模式
  - **PPO_HEAD_KINDS = {'policy', 'value'}**
  - **LOC**:~+130
  - **依赖**:T1

- [x] **T3**:rewrite `paradigms/ppo/network.py` — PPONetwork thin wrapper
  - **改动**:
    - 删 `_PPOMLPTrunk` 完整 class
    - PPONetwork 改 ctor `(agent_cfg: AgentConfig, device: str = 'cpu')`
    - 构造 PPOAgent;`add_module('net', self._agent.net)` 让 state_dict /
      parameters 通过 nn.Module 协议;exposes forward_batch / act
    - 删除 forward(obs) + masked_policy(obs, mask) 老接口;新建
      `act(env, rng, deterministic)` + `forward_batch(collated)`
  - **LOC**:~-50/+50
  - **依赖**:T2

- [x] **T4**:rewrite `paradigms/ppo/_rollout.py` — game_start cache + per-step
  - **改动**:
    - `run_training_game(agent, scen, pcfg, rng, device, p1_opponent)` —
      agent 而非 net
    - 首步前调 `agent.game_start(env.static_obs)`
    - per step:`a, meta = agent.act(env, rng, deterministic=False)`;
      用 meta['log_prob'] / meta['value'];
    - TrajBuf 改存 `(dyn_obs, refs, payments, n_legal, action, log_prob,
      value, reward, done)`;不再存 flat `obs`
    - GreedyPlayer / random opponent path 不变(它们 select_action(env)
      不走 net)
  - **LOC**:~-180/+120
  - **依赖**:T3

- [x] **T5**:rewrite `paradigms/ppo/collector.py` — structured transition payload
  - **改动**:
    - `PPORolloutCollector.collect` 每 trajectory 一次性产 transitions;
      Transition.payload 改 dict with `(dyn_obs, refs, payments, n_legal,
      log_prob, value, advantage, return)`
    - obs / legal_mask 字段:Transition.obs 改 None 或保留 dyn_obs
      reference;legal_mask 字段沿用现 build_legal_mask
    - GAE compute 路径不变(`compute_gae(rewards, values, dones, gamma, lam)`)
    - collate_batch 内部 helper:把 list[Transition] → structural
      collated dict + (action, old_log_prob, advantage, return) tensors
  - **LOC**:~-100/+130
  - **依赖**:T4

- [x] **T6**:adjust `paradigms/ppo/loss.py` — forward_batch 取代 forward(obs)
  - **改动**:
    - `compute(network, batch)`:read `batch.data` 含 'collated' /
      'action' / 'old_log_prob' / 'advantage' / 'return'
    - call `network.forward_batch(d['collated'])` → (logits, value)
    - 合法性 mask 从 collated['legal_mask'] 取(forward_batch 内 padded
      to max_actions)
    - clip + min(surr1, surr2) + value MSE + entropy 数学不变;clip_frac
      breakdown 保留
  - **LOC**:~-10/+30
  - **依赖**:T5

- [x] **T7**:adjust `paradigms/ppo/policy.py` — Categorical 接 structural
  - **改动**:
    - PPOEpisodePolicy.act 接 provider — 改期望 provider.forward 返回
      dict {'policy' / 'logits', 'value'};从 dict 取 logits 应付现 BC/AZ
      generic ActorCritic 输出
    - 删除对 (logits, value) tuple 接口的 fallback(structural 后只走
      dict path);保留 sample / argmax / log_prob 计算
    - compute_gae helper 不动(数学独立)
  - **LOC**:~-20/+20
  - **依赖**:T6

- [x] **T8**:rewrite `paradigms/ppo/paradigm.py` — 删 _probe_obs_size +
       AgentConfig 派生
  - **改动**:
    - 删 `_probe_obs_size` 方法 + GicgEnv 探针(structural shape 从
      pcfg.agent 派生)
    - `make_network(cfg)`:
      ```python
      agent_cfg = AgentConfig(
          n_counter_slots=pcfg.agent.n_counter_slots,
          n_hooks=pcfg.agent.n_hooks,
          max_tokens_per_hook=pcfg.agent.max_tokens_per_hook,
          max_actions=pcfg.agent.max_actions,
          d_model=pcfg.agent.d_model,
          n_cross_layers=pcfg.agent.n_cross_layers,
          dropout=pcfg.agent.dropout,
      )
      self._network = PPONetwork(agent_cfg, device=cfg.meta.device)
      ```
    - make_optimizer / make_buffer / make_loss / make_collector /
      make_episode_policy / step_schedule 不动
  - **LOC**:~-60/+40
  - **依赖**:T2 + T3

- [x] **T9**:adjust `paradigms/ppo/_async.py` — drain 路径适配新 payload
  - **改动**:
    - `_PPOActorProvider.forward(obs, mask)` 接 dict — 不变(actor 端
      构造 mock;实际 _async 在 frozen tier 不接 production train)
    - drain 路径(collect 内的 `for src in item: pl=dict(src.payload)`)
      不变 — Transition.payload schema 字段在 collector.py T5 重设计后
      已对齐
    - build_policy / build_provider / spec_sampler 不动
  - **LOC**:~-20/+30
  - **依赖**:T5 + T7

- [x] **T10a**:rewrite `training/tests/test_ppo_paradigm.py`
  - **改动**:
    - 删 obs_size 参数的 PPONetwork 构造;改用 AgentConfig + PPOAgent
    - PPONetwork heads attribute 检查:仍是 ('policy', 'value')
    - Loss tests(clipped_surrogate / value_mse / entropy_bonus /
      clip_frac)— batch.data 改 collated dict(走
      `make_structural_batch_dict`)+ chosen action / old_log_prob /
      advantage / return
    - PPOEpisodePolicy tests — _StubProvider.forward 返回 dict
      {'policy','value'}
    - PPOParadigm 接口测试 — step_schedule / name / make_episode_policy
      不动
  - **LOC**:~-200/+250
  - **依赖**:T6 + T7 + T8

- [x] **T10b**:rewrite `training/tests/test_ppo_smoke.py` — 升级到 structural backbone
  - **改动**:
    - 删 `_obs_size` cached + flat MLP construction path
    - `build_network` 改 `paradigm.make_network(cfg)`(自然走 structural)
    - `build_batch` 改 collated structural dict(via
      `make_structural_batch_dict`)+ PPO 字段(chosen action /
      old_log_prob / normalized advantage / return)
    - `eval_probe` 改:forward_batch → 取 legal logits softmax 算 log_prob;
      value 取 batch[0]
    - paradigm_invariant 仍验:log_prob ≤ 0 / advantage normalized /
      clip_frac ∈ [0, 1]
  - **LOC**:~-80/+90
  - **依赖**:T10a

- [x] **T10c**:rewrite `training/tests/test_ppo_collector_smoke.py`
  - **改动**:
    - 删 `_probe_obs_size` 探针(structural shape 从 cfg.agent 派生)
    - PPOParadigmConfig.from_dict({...}) — agent 字段改对齐(`n_counter_slots
      / n_hooks / max_tokens_per_hook / max_actions / d_model /
      n_cross_layers`)
    - PPONetwork(agent_cfg=AgentConfig(...)) 构造
    - 走 real GicgEnv collect(2 games);确认 transitions 含 structured
      payload(dyn_obs / refs / payments + log_prob / value / advantage /
      return)
    - env_factory_none_raises / asymmetric_random / unknown_spec_raises /
      random_returns_callable 保留(行为不变)
  - **LOC**:~-130/+130
  - **依赖**:T5 + T8

- [x] **T10d**:adjust `training/tests/test_ppo_async.py`
  - **改动**:
    - `test_ppo_async_n_actors_validation_and_paradigm_dispatch` 内
      `PPONetwork(obs_size=4, max_actions=2, d_model=4, n_hidden_layers=1)`
      调用改 `PPONetwork(agent_cfg=AgentConfig(...))` 同 T10c
    - `test_ppo_async_collect_compute_gae_per_episode` 内 mock Transition
      payload schema 与 T5 对齐(payload 新增 'dyn_obs' 等字段;'value'
      / 'log_prob' 保留)
    - `_PPOActorProvider.forward` mock 接口不变(test 端 stub 仍简单)
  - **LOC**:~-30/+30
  - **依赖**:T9

- [x] **T11**:pytest sweep verify
  - **Command**:
    ```bash
    .venv/bin/python -m pytest -n 4 training/tests/ tools/ -q --no-header \
      --ignore=training/tests/test_cfr_worker.py \
      --ignore=training/tests/test_cfr_parallel_trainer.py \
      --ignore=training/tests/test_eval_service_errors.py \
      --ignore=training/tests/test_eval_service_schema.py \
      --ignore=training/tests/test_eval_service_matchup.py \
      --ignore=training/tests/test_inference_server.py
    ```
  - **Additional smoke**:
    - `pytest training/tests/test_ppo_smoke.py training/tests/test_ppo_paradigm.py training/tests/test_ppo_collector_smoke.py training/tests/test_ppo_async.py -v` — PPO 4 个 test 文件全 green
    - `grep -rn "_PPOMLPTrunk\|flat MLP" training/paradigms/ppo/ --include='*.py'` — 0 hit
    - `grep -rn "make_actor_critic" training/paradigms/ppo/ --include='*.py'` — ≥ 1 hit
  - **Pass**:pre-existing sandbox-ignored tests 之外全 pass;PPO 4 个文件全 green
  - **LOC**:0(只跑测试)
  - **依赖**:T1-T10d

## Phase 3 — Commits

- [x] **T12**:commits
  - **C1**:propose — 6 artifacts(proposal + design + tasks + 3 spec deltas)
    - message:`ppo-structural-backbone-migration: propose — flat MLP → generic ActorCritic + structural obs flow`
  - **C2**:impl part 1 — config + agent + network + paradigm(component bootstrap)
    - message:`ppo-structural-backbone-migration: impl part 1 — config/agent/network/paradigm structural backbone wiring`
  - **C3**:impl part 2 — rollout + collector + loss + policy + _async(obs flow)
    - message:`ppo-structural-backbone-migration: impl part 2 — rollout/collector/loss/policy structural obs flow`
  - **C4**:impl part 3 — 4 PPO test files rewrite + sweep verify
    - message:`ppo-structural-backbone-migration: impl part 3 — 4 PPO test files rewrite + sweep verify`
  - **LOC**:per commit ~150-600
  - **依赖**:T11 green

## 总进度

- Phase 1:1/1 (propose artifacts ✅)
- Phase 2:13/13 (impl ✅)
- Phase 3:1/1 (verify + commit ✅)
- 总计:15/15

## 依赖图

```
T0(propose)
  └── T1(config)
       └── T2(agent)
            ├── T3(network)
            │    └── T8(paradigm)
            └── T4(_rollout)
                 └── T5(collector)
                      ├── T6(loss)
                      │    └── T7(policy)
                      │         └── T9(_async)
                      └── ───┐
                            T10a(test_paradigm) ─┐
                            T10b(test_smoke)     │
                            T10c(test_collector) ├── T11(sweep) ── T12(commits)
                            T10d(test_async)     ┘
```
