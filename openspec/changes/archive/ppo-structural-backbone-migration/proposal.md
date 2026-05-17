---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: ppo-structural-backbone-migration
---

# Proposal — ppo-structural-backbone-migration

## 1. Why

post `core-network-generic-promotion` Phase 2E,DECISIONS log [D-101]
把 PPO backbone 完整切换推迟到本 follow-up change。当前 PPO 是 5
paradigm 中 **唯一** 仍使用 `_PPOMLPTrunk` flat MLP 的 outlier:

| Paradigm | Backbone | Static obs cache | Structural typed segments |
|---|---|---|---|
| AZ | ✅ generic ActorCritic | ✅ AgentBase | ✅ typed_damage on |
| BC | ✅ generic ActorCritic | ✅ AgentBase | ✅ typed_damage on |
| DMC | ✅ generic ActorCritic | ✅ AgentBase | ✅ typed_damage on |
| CFR | ✅ generic backbone(CFRStrategyNet) | ✅ AgentBase | (6-pool legacy) |
| **PPO** | ❌ flat MLP `_PPOMLPTrunk` | ❌ flat obs vector | ❌ 完全忽略 |

PPO 当前 `_rollout.py` 直接 `env._get_obs()` → `net.forward(obs_flat)`,
**完全跳过 hook encoding / counter / typed damage / structural readout**,
退化为 generic 通用 MLP。这与 spec invariant "5 paradigm 共用 backbone"
(network-architecture A4 + training-architecture A1)直接矛盾。

`core-network-generic-promotion` 期间 user 接受 [D-101]:PPO 切换是 500-1000
LOC sub-project,scope 太大,defer 到本 follow-up change。

## 2. What

**6 bullets**:

1. 完全 **重写** `paradigms/ppo/network.py`:删 `_PPOMLPTrunk` flat MLP,
   改用 `make_actor_critic(cfg, head_kinds={'policy','value'},
   use_typed_damage=True)` generic backbone;PPONetwork 退化为 thin
   nn.Module wrapper(driver state_dict/parameters 协议兼容)。

2. **新增** `paradigms/ppo/agent.py` `PPOAgent(AgentBase)`:DI hook_encoder
   注入,per-game cache + `eval_state(dyn_obs, refs, payments)` 接口,
   返回 `(legal_logits, value, log_prob_old)` — log_prob_old 给 PPO clip
   ratio 用。与 AZ/DMC/BC 对称。

3. **重写** `paradigms/ppo/_rollout.py`:`agent.game_start(env.static_obs)`
   cache + per-step `agent.eval_state(dyn_obs, refs, payments)` pattern。
   `TrajBuf` 改为存 structured payload(`dyn_obs / refs / payments /
   action / log_prob / value / reward`),不再存 flat `obs`。

4. **改造** `paradigms/ppo/collector.py` Transition payload schema:
   每 transition 含 `dyn_obs + refs + payments + static_cache_ref`,
   后者通过 episode-level append 一次性 attach,buffer 内 trajectory
   per-game 共享 static 部分。

5. **改造** `paradigms/ppo/loss.py`:`forward_batch` 路径取代 flat
   `network.forward(obs)`;loss 读 structural batch dict + 调
   `network.forward_batch(collated)` 返回 `(policy_logits, value)`;clip
   surrogate + GAE 数学不变。

6. **改造** `paradigms/ppo/paradigm.py`:删 `_probe_obs_size`(structural
   shape 从 cfg.agent 派生);PPOParadigmConfig.agent 新增结构字段
   `n_counter_slots / n_hooks / max_tokens_per_hook / n_cross_layers /
   dropout`(replace `n_hidden_layers` flat MLP 字段)。

## 3. Affected specs

- `paradigm-ppo/spec.md` — invariant P1 / P5 重写(backbone 改 structural),
  invariant P3 / P4 文字微调(actor / buffer schema 描述对齐);P2 loss
  数学 / P6 frozen tier 不变
- `network-architecture/spec.md` — 完成 invariant A4 "5 paradigm 共用
  backbone";本 change ship 后 invariant 100% 满足
- `config-schema/spec.md` — PPOAgentShapeCfg 字段重设计(去 `d_model /
  n_hidden_layers / max_actions`,加 `n_counter_slots / n_hooks /
  max_tokens_per_hook / d_model / n_cross_layers / dropout / max_actions`,
  与其它 paradigm AgentShapeCfg 字段集对齐 — 但仍保留 paradigm-local 类型
  per D-201)

## 4. Out of scope

- **不** 引入 ObsShape unification(D-201 仍 defer 到 `cfg-schema-unification`
  follow-up change;本 change 只在 PPOAgentShapeCfg 字段层面与其它 paradigm
  对齐,不替换 dataclass 类型)
- **不** 引入 ParadigmConfigBase compose(D-202 同 defer)
- **不** 改 PPO loss 数学(clip + GAE + value MSE + entropy 公式不变,
  per spec P2)
- **不** 改 PPO frozen tier(per spec P6;new production run 仍需要
  OpenSpec change 解冻)
- **不** 改 PPOAsyncCollector 整体架构(W3b mp 路径基本独立;本 change
  对齐 serial collector + transition payload schema,async 同步改 payload
  drain 路径但不重设计 mp 模型)
- **不** 保证 historical PPO ablation(s021-s054)的 ckpt 兼容 — 已 accept
  per D-302(reproducibility 通过 git checkout + 老代码走老路径)

## 5. Decision summary

- Backbone: `_PPOMLPTrunk` → `make_actor_critic` 5 paradigm 完全对称
- AgentBase pattern: `PPOAgent(AgentBase)` 走 game_start cache + eval_state
- Transition payload: flat `obs: ndarray` → structured `(dyn_obs, refs,
  payments, static_idx)` dict
- Loss API: `network.forward(obs) -> (logits, value)` →
  `network.forward_batch(collated_dict) -> (policy_logits, value)`
- 5 invariants in spec delta(P1/P5/P3/P4 + A4 closure);historical
  ablation 不要求 bit-reproducible
- Effort: ~500-800 LOC across 7 files + 3 test files;medium-high risk
  (PPO async path mp pickling 是主要不确定性)
