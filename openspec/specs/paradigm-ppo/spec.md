---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: paradigm-ppo
---

# Paradigm PPO — Proximal Policy Optimization 算法层不变量

> PPO(Proximal Policy Optimization)paradigm 的算法层 SHALL invariants。
> 架构层继承 [`../training-architecture/spec.md`](../training-architecture/spec.md),
> 本 spec 只列 PPO-specific 约束。

## 1. Purpose

PPO 是 GICG 2026-04 早期 RL 主路径,Stage 3 30+ ablation(s021-s054)+
F1-D2 ≥ 0.40 物理不可达诊断后,由 `archive/0008-rl-paradigm-pivot` closed
转 `frozen` tier。本 spec 治理 PPO 算法层不变量,保证可复盘 + lever 验证:

- On-policy GAE rollout
- Clipped surrogate + value MSE + entropy bonus 三项 loss
- (Policy, value)双 head 网络
- Rollout buffer(每 iter clear)

D2 决策(unified-training-pipeline 内):PPO **迁移**而非 archive,通过
新管线 reproducible(memory `project_stage3_full_diagnosis` 信息密度高,
值得长期可访问)。

## 2. Scope

**In scope**:
- PPO paradigm 实现的 6 protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider PPO-specific 实现要求)
- GAE return / advantage 估计
- Clipped surrogate loss 数学契约
- Rollout buffer 每 iter clear
- 复盘范围(s021-s054 ablation reproducibility)

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture`
- PPO run 历史 / Stage 3 closure → `docs/paradigms/ppo/` +
  `docs/5_history/ablations/stage3_ppo_closure.md`
- Opponent pool / ELO(memory `project_pool_elo_design` OBSOLETE)→ AZ D4
  废除,本 spec 不重申

## 3. Core SHALL invariants

### P1. PPO 算法核心

1. **P1.1** PPO paradigm SHALL use on-policy rollout(no replay)+ GAE
   advantage estimation,λ default 0.95。
2. **P1.2** Rollout horizon SHALL be cfg-driven `pipeline.rollout.n_steps`,
   default 2048;vec env optional(`vec_env_size` cfg,default 1)。
3. **P1.3** Discount γ default 0.99(PPO 时代沿用,与 AZ/DMC γ=1.0 不同
   是 paradigm decision,不变)。

### P2. Loss(三项 sum)

4. **P2.1** PPO loss SHALL = `clipped_surrogate + value_coef * value_mse -
   entropy_coef * entropy_bonus`,3 项 sum;clipping ε default 0.2。
5. **P2.2** Value loss MAY use clipped value form(详 Schulman 原文)。
6. **P2.3** Entropy bonus SHALL be paradigm cfg,default `entropy_coef =
   0.01`;value coef default 0.5。

### P3. Actor policy

7. **P3.1** PPO actor SHALL sample from policy logits(`Categorical(logits).sample()`)
   during rollout;NOT argmax。
8. **P3.2** Eval policy SHALL be deterministic argmax(rollout sampling for
   exploration only)。
9. **P3.3** Old-policy log_prob SHALL be stored in rollout buffer for
   importance ratio computation(loss 计算 prerequisite)。

### P4. Buffer

10. **P4.1** PPO buffer SHALL be `RolloutBuffer`(from
    `training/core/buffer/rollout.py`),**SHALL be cleared after each
    optimization iteration**(on-policy invariant)。
11. **P4.2** Buffer capacity = rollout_horizon × vec_env_size(no replay,
    no static dedup)。
12. **P4.3** Sample SHALL be sequential minibatch shuffle within rollout
    (no cross-iteration sampling)。

### P5. Network heads(generic backbone)

> Revised by `ppo-structural-backbone-migration` (archived 2026-05-17) —
> PPO 完整收编进 generic `core/network/ActorCritic` backbone + AgentBase
> DI;`_PPOMLPTrunk` flat MLP 完全退役。详 § P7。

13. **P5.1** PPO network SHALL have 2 heads:`policy_head(logits)` +
    `value_head(scalar)`,both fed by shared encoder。Encoder SHALL be
    paradigm-agnostic generic `core/network/ActorCritic` backbone(共享 with
    AZ/BC/CFR/DMC)。`PPONetwork` SHALL 通过 `make_actor_critic(cfg,
    head_kinds={'policy', 'value'}, use_typed_damage=True)` 装配,`AgentBase`
    通过 DI 注入 `hook_encoder=self.net.encoders['hook']`(详
    `network-architecture/spec.md` invariants 12-13 + 15)。
14. **P5.2** Heads MAY be separated(no shared trunk)by paradigm cfg
    `network.heads_share_trunk = false`;default `true`(GICG 沿用 AZ-style
    shared encoder)。

### P6. Tier

15. **P6.1** PPO tier SHALL be `frozen`(per archived `0008-rl-paradigm-pivot`)。
16. **P6.2** PPO migration to unified pipeline SHALL preserve s021-s054
    ablation reproducibility(同 cfg + 同 seed → 同 F1-D2 ±0.02 noise band)。
    **Exception**(per `ppo-structural-backbone-migration` archive
    2026-05-17):backbone migration 后 s021-s054 老 ckpt 不再 strict-loadable
    (state_dict 形状全变);复现路径改为 `git checkout
    pre-core-network-redesign-2026-05-17` + 老代码 + 老 cfg。
17. **P6.3** New PPO production run SHALL NOT be launched without OpenSpec
    change unfreezing tier(避免重复 PPO 时代 closure 上的资源浪费)。

### P7. Generic backbone + structural obs(2026-05-17 收编)

> Added by `ppo-structural-backbone-migration` (archived 2026-05-17) —
> 关闭 5 paradigm backbone unification 最后一项 outlier。`_PPOMLPTrunk`
> flat MLP + `env.obs_size` flat dynamic vector 旁路 SHALL 不存在。

18. **P7.1 Generic backbone**:`PPONetwork` SHALL internally use
    `make_actor_critic(cfg, head_kinds={'policy', 'value'},
    use_typed_damage=True)` 作为 backbone,SHALL NOT 维护 paradigm-local
    trunk(如历史 `_PPOMLPTrunk` flat MLP)。`PPONetwork` 退化为 thin
    nn.Module wrapper(`add_module('net', self._agent.net)` 让 state_dict
    / parameters 协议兼容)。

19. **P7.2 Structural obs flow**:PPO collector + rollout SHALL 走
    `agent.game_start(env.static_obs)` cache + per-step `dynamic_obs` 切
    typed segments 模式(与 AZ / BC / CFR / DMC 一致),SHALL NOT 使用
    `env.obs_size` flat dynamic vector 旁路 hook / counter / typed segments
    encoding。

20. **P7.3 AgentBase 集成**:`paradigms/ppo/agent.py::PPOAgent` SHALL 继承
    `AgentBase`,使用 `encode_static()` 缓存 static obs(per-game once),
    `parse_dynamic_single()` 切 per-step dynamic obs into typed tensors(对
    齐其它 4 paradigm)。`PPO_HEAD_KINDS = frozenset({'policy', 'value'})`。

21. **P7.4 Transition payload structured schema**:`paradigms/ppo/collector.py`
    Transition.payload SHALL be structured dict 含 `dyn_obs / refs / payments
    / n_legal / log_prob / value / advantage / return`,SHALL NOT 仅 flat
    obs vector。collate_batch SHALL 把 batch transitions stack 为 structural
    backbone `forward_batch` 期望的 dict shape。

22. **P7.5 Loss forward path**:PPO loss `compute(network, batch)` SHALL
    call `network.forward_batch(d['collated'])` → `(policy_logits, value)`;
    SHALL NOT call legacy `network.forward(obs)` flat MLP path。clip +
    `min(surr1, surr2)` + value MSE + entropy 数学公式不变;clip_frac
    breakdown 保留。

23. **P7.6 Policy provider dict output**:PPO `provider.forward(...)` SHALL
    返回 dict `{'policy', 'value'}` 或同含 `'logits'` key 的 dict;tuple
    fallback `(logits, value)` removed。`PPOEpisodePolicy.act` SHALL 走
    dict path。

24. **P7.7 No flat obs probe**:`paradigms/ppo/paradigm.py` SHALL NOT 含
    `_probe_obs_size` 方法(historically built `GicgEnv` 探针拿
    `env.obs_size`);structural shape SHALL 从 `pcfg.agent` 派生
    (`AgentConfig(n_counter_slots=..., n_hooks=..., max_tokens_per_hook=...,
    max_actions=..., d_model=..., n_cross_layers=..., dropout=...)`)。

25. **P7.8 PPOAgentShapeCfg ObsShape alias**:`paradigms/ppo/config.py::
    PPOAgentShapeCfg` SHALL be `PPOAgentShapeCfg = ObsShape` type alias
    (per `cfg-schema-unification` [CC-202] pattern,与 BC/AZ/DMC
    `AgentShapeCfg = ObsShape` 对称);historical flat-MLP 专用字段
    `n_hidden_layers: int` SHALL 不存在(per `network-architecture/spec.md`
    invariant 15 + `config-schema/obs-shape-unification.md` PPO defer
    closure 由 `ppo-cfg-shape-alignment` archive 2026-05-17 完成)。

> Revised by `ppo-cfg-shape-alignment` (archived 2026-05-17) — PPO cfg
> dataclass 完全对齐 4 paradigm,关闭 `cfg-schema-unification` [CC-206]
> PPO defer。详 § P7.9-P7.11 + P7.8 升级注解。

26. **P7.9 PPOParadigmConfig inherit ParadigmConfigBase**:
    `paradigms/ppo/config.py::PPOParadigmConfig` SHALL inherit
    `ParadigmConfigBase`(from `training.core.cfg`),override
    `paradigm: str = 'ppo'`;`version: str = '1.0.0'` inherited from base
    (per `cfg-schema-unification` N2 + [CC-204])。`agent: ObsShape =
    field(default_factory=make_ppo_default_shape)` SHALL compose ObsShape
    via factory(不允许 paradigm-local dataclass 重定义 shape 字段)。

27. **P7.10 from_dict version + paradigm 校验**:
    `PPOParadigmConfig.from_dict(d)` SHALL validate(a)`version` ∈
    `_VALID_VERSIONS` closed enum `{'1.0.0'}`(per [CC-204] enum
    validation);(b)`paradigm` field 值(若提供)SHALL == `'ppo'`,
    mismatch raise(per [CC-205] paradigm mismatch raise pattern);
    (c)agent dict merge SHALL 走 `build_shape_from_toml(agent_d,
    make_ppo_default_shape)`(per CC-303 dict merge pattern),不允许
    直接 `ObsShape(**agent_d)` 构造跳过 default factory。

28. **P7.11 make_ppo_default_shape factory**:`training/core/cfg/factories.py`
    SHALL provide `make_ppo_default_shape() -> ObsShape`(d_model=128 /
    n_cross_layers=2,与 AZ baseline 同;post-#4 structural defaults,flat-MLP
    历史 d_model=256 + n_hidden_layers=3 已 retire)。SHALL be exported via
    `training.core.cfg.__init__.__all__`,与其它 4 paradigm factory
    (`make_az_default_shape` / `make_bc_default_shape` /
    `make_cfr_default_shape` / `make_dmc_default_shape`)对称(5 paradigm
    × 1 factory each)。

## 4. Cross-references

- 主 training architecture →
  [`../training-architecture/spec.md`](../training-architecture/spec.md)
- 网络架构 (5 paradigm 共用 backbone) →
  [`../network-architecture/spec.md`](../network-architecture/spec.md)
  invariants 12-15
- Config schema (PPO ObsShape 对齐) →
  [`../config-schema/obs-shape-unification.md`](../config-schema/obs-shape-unification.md)
- PPO paradigm dossier → `docs/paradigms/ppo/`
- Stage 3 closure → `archive/0008-rl-paradigm-pivot` + memory
  `project_stage3_full_diagnosis`
- Pool/ELO history(OBSOLETE)→ memory `project_pool_elo_design` +
  `project_pool_elo_followups`
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)
- Backbone migration change(archived)→
  [`../../changes/archive/ppo-structural-backbone-migration/`](../../changes/archive/ppo-structural-backbone-migration/)
- Cfg dataclass alignment change(archived)→
  [`../../changes/archive/ppo-cfg-shape-alignment/`](../../changes/archive/ppo-cfg-shape-alignment/)
- Cfg schema unification(archived,CC-206 PPO defer closure)→
  [`../../changes/archive/cfg-schema-unification/`](../../changes/archive/cfg-schema-unification/)

## 5. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)—
  仅加 deferred banner;完整 backbone migration(PPO 收编进 generic
  `ActorCritic` + structural obs + AgentBase DI + collector/rollout 重
  写)推迟到 follow-up change `ppo-structural-backbone-migration`(2026-05-17
  propose),理由:500-1000 LOC 独立 sub-project,混入 parent change 让
  scope 失控。
- **Revised**:2026-05-17(`ppo-structural-backbone-migration` archive)—
  +P7 (8 SHALL,generic backbone + structural obs + AgentBase + Transition
  payload + loss forward + policy dict + no probe + cfg field alignment);
  MODIFY P5.1(generic backbone via `make_actor_critic` + DI 注解);
  +P6.2 exception(老 ckpt strict-load 不可用,复现路径改 git checkout
  老代码);deferred banner 移除。
- **Revised**:2026-05-17(`ppo-cfg-shape-alignment` archive)— MODIFY
  P7.8 升级为 `PPOAgentShapeCfg = ObsShape` type alias(原"字段对齐",
  per CC-202 pattern);+P7.9 PPOParadigmConfig inherit ParadigmConfigBase;
  +P7.10 from_dict version + paradigm 校验;+P7.11 make_ppo_default_shape
  factory。关闭 `cfg-schema-unification` [CC-206] PPO defer,5/5 paradigm
  cfg 完全对称。
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied;backbone
  migration 在 `ppo-structural-backbone-migration` 2026-05-17 ship(8 paradigm
  files rewrite + 4 test files rewrite + 0 production regression per Phase
  3 sweep verify)
- **Tier**:frozen — 仅保留 reproducibility,不接受 new run
