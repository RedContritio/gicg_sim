---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-ppo
---

# Spec delta — paradigm-ppo

> 本 delta 把 `core-network-generic-promotion` 内 deferred PPO backbone
> 切换激活。来自 [D-101] 的 follow-up change。spec deltas 沿用 prior
> change `paradigm-ppo/spec.md` 的 ADD/MODIFY/REMOVE 三段(原作 draft),
> 在此 change 内 **激活** 落地。

## ADD

### A1. Generic backbone unification

> **P1.new. PPO MUST use generic ActorCritic backbone**:`PPONetwork`
> SHALL internally use `make_actor_critic(cfg, head_kinds={'policy',
> 'value'}, use_typed_damage=True)` 作为 backbone,SHALL NOT 维护
> paradigm-local trunk(如历史 `_PPOMLPTrunk` flat MLP)。

### A2. Structural obs flow

> **P2.new. PPO MUST consume structural obs**:PPO collector + rollout
> SHALL 走 `game_start(env.static_obs) cache + per-step dynamic_obs`
> 模式(与 AZ / DMC / BC / CFR 一致),SHALL NOT 使用 `env.obs_size`
> flat dynamic vector 旁路 hook / counter / typed segments encoding。

### A3. AgentBase 集成

> **P3.new. PPO MUST integrate with AgentBase per-game cache**:
> `paradigms/ppo/agent.py::PPOAgent` SHALL 继承 `AgentBase`,使用
> `encode_static()` 缓存 static obs(per-game once),`parse_dynamic_single()`
> 切 per-step dynamic obs into typed tensors(matching other 4 paradigms)。

### A4. Transition payload structured schema

> **P4.new. PPO Transition payload SHALL be structured dict**:
> `paradigms/ppo/collector.py` Transition.payload SHALL 含 `dyn_obs /
> refs / payments / n_legal / log_prob / value / advantage / return`,
> SHALL NOT 仅 flat obs vector。collate_batch SHALL 把 batch transitions
> stack 为 structural backbone forward_batch 期望的 dict shape。

## MODIFY

### M1. PPONetwork 完全重写

**Before**(`paradigms/ppo/network.py`):
```python
class _PPOMLPTrunk(nn.Module):
    def __init__(self, obs_size, max_actions, d_model=256, n_hidden_layers=2):
        layers = [nn.Linear(obs_size, d_model), nn.ReLU(), ...]

class PPONetwork(nn.Module):
    def __init__(self, obs_size, max_actions, ...):
        self.net = _PPOMLPTrunk(obs_size=obs_size, ...)
```

**After**:
```python
class PPONetwork(nn.Module):
    """PPO adapter wrapper around generic ActorCritic backbone."""
    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu') -> None:
        super().__init__()
        self._agent = PPOAgent(agent_cfg, device=device)
        self.add_module('net', self._agent.net)

class PPOAgent(AgentBase):
    PPO_HEAD_KINDS = frozenset({'policy', 'value'})
    def __init__(self, cfg: AgentConfig, device: str = 'cpu') -> None:
        net = make_actor_critic(cfg, head_kinds=self.PPO_HEAD_KINDS,
                                use_typed_damage=True).to(torch.device(device))
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.net = net
```

### M2. `_rollout.py` obs flow 重写

**Before**:
```python
# trajectory step:
obs = env._get_obs()                  # flat vector
logits, value = net.forward(obs)
```

**After**:
```python
# at episode start:
agent.game_start(env.static_obs)      # 一次性 encode_static cache

# per-step:
a, meta = agent.act(env, rng, deterministic=False)
# meta = {'log_prob','value','n_legal'}
```

### M3. `collector.py` Transition payload schema

**Before**:`Transition(obs: np.ndarray, action: int, legal_mask:
np.ndarray, ..., payload={'log_prob','value','advantage','return'})`(obs
= flat dynamic obs)。

**After**:`Transition(obs: None, action: int, legal_mask: np.ndarray,
..., payload={'dyn_obs','refs','payments','n_legal','log_prob','value',
'advantage','return'})`(structural 字段全在 payload,obs 字段 deprecated
但保留 protocol shape compat 设 None)。

### M4. `paradigm.py` 删除 `_probe_obs_size`

**Before**:
```python
def _probe_obs_size(self, cfg) -> int:
    """PPONet is flat MLP and needs obs_size at construction."""
    from gicg_env import GicgEnv
    env = GicgEnv(...)
    return int(env.obs_size)
```

**After**:DELETE。`PPOAgent` 用 `AgentConfig` 派生 shape,不需要 probe
flat obs_size。

### M5. `loss.py` forward 路径

**Before**:`logits, value = network.forward(d['obs'])`(flat MLP path)。

**After**:`policy_logits, value = network.forward_batch(d['collated'])`
(structural backbone path);clip + min(surr1,surr2) + value MSE +
entropy 数学不变;clip_frac breakdown 保留。

### M6. `policy.py` provider 输出 dict

**Before**:`provider.forward(obs, mask)` 接 `(logits, value)` tuple **或**
dict — PPOEpisodePolicy.act 接 fallback 两路。

**After**:`provider.forward(...)` SHALL 返回 dict {'policy','value'}
或同含 'logits' key 的 dict;tuple fallback removed。

## REMOVE

### R1. `_PPOMLPTrunk` class

`paradigms/ppo/network.py::_PPOMLPTrunk` SHALL be 完全删除。

理由:flat MLP backbone 是早期工程选择(s015-s054 ablation 期),不是
PPO 算法约束。collect into generic backbone 后,5 paradigm 完全对称。

### R2. `obs_size: int` 字段

`PPONetwork.__init__(obs_size, max_actions, d_model, n_hidden_layers)`
所有 flat MLP 专用字段 SHALL 全删。新签名:`PPONetwork(agent_cfg:
AgentConfig, device: str = 'cpu')`。

### R3. PPO outlier 描述

`paradigm-ppo/spec.md`(主 spec)若有 "PPO 用 flat MLP / outlier / 不消费
structural primitives" 表述 SHALL 全部删除。

### R4. `n_hidden_layers` cfg 字段

`PPOAgentShapeCfg.n_hidden_layers: int` SHALL 删除(flat MLP 专用);
替换为 `n_cross_layers: int` 与其它 AgentShapeCfg 一致。

## Risks(本 spec 特有)

- **R-PPO-1**:smoke 收敛失败 — PPO structural backbone 在 ≤ 60s mini-train
  上无法跑出有意义的 clip ratio / advantage。**缓解**:smoke 不要求收敛,
  只要求 clip ratio bounded ∈ [0,1] + log_prob ≤ 0 + advantage normalized
  + train loop alive(详 `../../design.md` Risks R-1)。
- **R-PPO-2**:s015-s054 历史 ablation 复现失效。**缓解**:user 已接受
  per `core-network-generic-promotion` D-302(ckpt + cfg 失效 = reproducibility
  同失效);若未来复现需要,通过 `git checkout pre-core-network-redesign-2026-05-17`
  + 老代码 + 老 cfg 走老路径。
- **R-PPO-3**:structural backbone forward 比 flat MLP 慢 ~3-5×。**缓解**:
  smoke 用 tiny d_model=16 + max_actions=6,wall 实测 < 30s;PPO frozen
  tier 不预期 production train。
- **R-PPO-4**:_async.py mp 路径 drain transition payload schema 不对齐
  collector.py 新 schema → mock test fail。**缓解**:T9 同步调整,
  test_ppo_async.py mock 同步改 expectation。

## Cross-references

- `../../proposal.md` — PPO 收编决策
- `../../design.md` Tradeoffs T1-T5 + Risks R1-R5 — 决策 + 缓解
- `../network-architecture/spec.md` invariant A4 — 5 paradigm 共用 backbone
- `../config-schema/spec.md` invariant CS-PPO-1 — PPOAgentShapeCfg 字段对齐
- `../../tasks.md` Phase 2 T2-T9 — PPO 重写实施
- `core-network-generic-promotion/DECISIONS.md` [D-101] / [D-302] —
  本 change 起源
