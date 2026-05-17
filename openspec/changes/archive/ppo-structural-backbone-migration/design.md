# ppo-structural-backbone-migration — Design Retrospective

> Archive-time summary (≤ 200 lines per archive cap)。详细 Architecture +
> Tradeoffs + Migrations 内容已拆到 `design/` subdir,见 ↓ 索引。

## Verdict

**成功** — PPO 完整收编进 generic `core/network/ActorCritic` backbone +
structural obs flow + `AgentBase` DI,关闭 `core-network-generic-promotion`
parent change 中 [D-101] PPO defer 决策。5 paradigm backbone unification
100% 闭环:network-architecture invariant 15 + training-architecture
invariant 19 from PPO outlier 例外 → all 5 paradigm 满足,无 follow-up
defer 残留。Phase 2 13/13 + Phase 3 sweep verify green(PPO 4 test files
全 pass + 全 repo 0 new regression)。

## What we built

- `paradigms/ppo/network.py` rewrite — 删 `_PPOMLPTrunk` flat MLP class
  整体 + PPONetwork 退化为 thin nn.Module wrapper(`add_module('net',
  self._agent.net)` 协议兼容);新签名 `PPONetwork(agent_cfg: AgentConfig,
  device: str = 'cpu')` 替换历史 `(obs_size, max_actions, d_model,
  n_hidden_layers)`
- `paradigms/ppo/agent.py` NEW — `PPOAgent(AgentBase)` + DI hook_encoder +
  `act(env, rng, deterministic) -> (action_idx, meta_dict)` + `forward_batch(
  collated) -> (policy_logits, value)`;PPO_HEAD_KINDS = `frozenset({'policy',
  'value'})`,use_typed_damage=True 与其它 4 paradigm 对称
- `paradigms/ppo/_rollout.py` rewrite — `agent.game_start(env.static_obs)`
  cache + per-step `agent.act` pattern;`TrajBuf` 存 `(dyn_obs, refs,
  payments, n_legal, action, log_prob, value, reward, done)` 不再存 flat obs
- `paradigms/ppo/collector.py` rewrite — Transition.payload 改 structured
  dict `(dyn_obs, refs, payments, n_legal, log_prob, value, advantage,
  return)`;collate_batch 把 batch transitions stack 为 structural
  `forward_batch` 期望 dict shape
- `paradigms/ppo/loss.py` adjust — `compute()` 走
  `network.forward_batch(d['collated'])` → `(policy_logits, value)`;clip
  + min(surr1,surr2) + value MSE + entropy 数学不变,clip_frac breakdown
  保留
- `paradigms/ppo/paradigm.py` rewrite — 删 `_probe_obs_size` + `GicgEnv`
  探针;`make_network` 走 `AgentConfig` 从 `pcfg.agent` 派生
- `paradigms/ppo/policy.py` adjust — `provider.forward()` 接 dict path,
  tuple `(logits, value)` fallback removed
- `paradigms/ppo/config.py` adjust — `PPOAgentShapeCfg` 字段对齐
  `(n_counter_slots, n_hooks, max_tokens_per_hook, max_actions, d_model,
  n_cross_layers, dropout)`,删 flat MLP 专用 `n_hidden_layers`;BC
  AgentShapeCfg 同字段集
- `paradigms/ppo/_async.py` adjust — drain 路径 Transition payload schema
  适配新 collector 输出
- 4 test files rewrite — `test_ppo_paradigm.py / test_ppo_smoke.py /
  test_ppo_collector_smoke.py / test_ppo_async.py` 走 AgentConfig +
  structural batch dict

详 [`design/architecture.md`](./design/architecture.md)。

## Tradeoffs revisited

- **2.1 PPOAgent inherits AgentBase**:预期 + 实际 SELECTED ✓ — 与
  AZ/DMC/BC 100% 对称,encode_static / parse_dynamic_single 复用,
  hook_encoder DI 已经在 base;PPOAgent.net = ActorCritic 满足
  `self.net is nn.Module` 假设,AgentBase save/load self-describing schema
  PPO 自动受益
- **2.2 log_prob_old 在 agent.act 内同步算 + 返回**:预期 + 实际 ✓ — 一
  次 forward 同时算 logits + log_prob 无 redundant forward,collector 直
  接存 meta['log_prob'],loss 时不重算
- **2.3 transition payload static_idx**:预期 + 实际 SELECTED idx ✓ — PPO
  on-policy buffer 每 iter clear 无 lifecycle issues,O(1) 直查 vs hash 比对
  overhead
- **2.4 PPOAgentShapeCfg 字段对齐 ObsShape 字段集**:预期 + 实际 ✓ — 与
  BC/AZ/DMC AgentShapeCfg 字段一致,后续 `cfg-schema-unification` follow-up
  之 PPOAgentShapeCfg = ObsShape alias 化是 1 步切完(本 change 字段层对
  齐已是前置)
- **2.5 typed_damage on**:预期 + 实际 ✓ — 与 AZ/BC/DMC 7-pool 一致,
  ckpt schema 同源 → 未来 cross-paradigm warm-start 可能;PPO frozen
  marginal cost 可忽略

## Surprises

- **`_async.py` drain 路径影响最小**:原 design.md 4.3 担心 mp pickling
  schema 同步是 medium-high risk;实际 PPOAgent.forward_batch 走
  serial path,actor 端 mock 充分,_async.py 只需 drain 路径 Transition
  payload schema 字段映射调整,LOC -20/+30 一次过
- **PPOEpisodePolicy 不在 serial path 走**:原 design.md 4.4 担心
  policy/provider 接口 churn 大;实际 serial collector path `_rollout` 里
  直接 `net.forward`,PPOEpisodePolicy 仅 mp/async path 走;改 stub
  expectation 即足够,无须深 refactor
- **4 test files rewrite LOC 比 estimate 准**:`test_ppo_paradigm.py`
  (-200/+250)+ `test_ppo_smoke.py`(-80/+90)+ `test_ppo_collector_smoke.py`
  (-130/+130)+ `test_ppo_async.py`(-30/+30)= estimate -440/+500 一次跑通,
  无 cascading test rewrite scope creep
- **PPO smoke wall 远低于 60s**:原 design.md 4.1 担心 structural backbone
  3-5× slower 可能超 60s;tiny shape(d_model=16 / n_hooks=4 /
  max_tokens_per_hook=8 / max_actions=6 / n_counter_slots=128)实测 ~3-10s
  与 BC/DMC smoke 同档

## Spec delta summary

本 change 修订 3 capability spec:

- **paradigm-ppo**:`spec.md` 移除 deferred banner(2026-05-17
  `core-network-generic-promotion` archive 加的)+ MODIFY P5.1(generic
  backbone via `make_actor_critic` + DI 注解,对齐 BC4.2 模板)+ ADD §P7
  8 SHALL(P7.1-P7.8:generic backbone / structural obs / AgentBase / Transition
  payload / loss forward / policy dict / no probe / cfg field alignment)+
  MODIFY P6.2 加 exception note(老 ckpt strict-load 不可用,复现路径
  改 git checkout 老代码)
- **network-architecture**:`spec.md` MODIFY SHALL 15 closure update
  — PPO 从 outlier(deferred backbone migration via follow-up)→ "5
  paradigm 全部满足 — AZ / BC / CFR / DMC / PPO 全走 generic ActorCritic
  backbone";Status section 加 revision 注解
- **config-schema**:`obs-shape-unification.md` MODIFY 顶部 banner +
  N1.4 + N5.5:
  - 适用范围 4 paradigm → 5 paradigm
  - N1.4 PPO defer → PPO 字段对齐已 ship,`PPOAgentShapeCfg` 字段集与
    `ObsShape` 完全一致,`n_hidden_layers` 删除
  - N5.5 PPO `configs/ppo/{default,smoke}.toml` partial compliance → SHALL
    be present 字段对齐 structural backbone

## 索引

- **[`design/architecture.md`](./design/architecture.md)** — §1 Architecture
  (component map + PPOAgent 接口 + Transition payload schema + loss path +
  rollout simplification)+ §2 Tradeoffs(5 个 SELECTED + Pros/Cons/Verdict)
- **[`design/migrations.md`](./design/migrations.md)** — §3 Migration plan
  (Phase 顺序 T0-T12 + test rewrite 策略 + async collector adaptation)+
  §4 Risks(smoke wall / loss numerical / async schema / policy provider /
  ckpt 不兼容)+ §5 Rollback + §6 Verification matrix + §7 LOC estimate
