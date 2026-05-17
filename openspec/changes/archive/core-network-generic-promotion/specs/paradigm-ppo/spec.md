---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-ppo
---

# Spec delta — paradigm-ppo

**Status (2026-05-17 scope adjustment):** PPO backbone 切换 **deferred to follow-up change** `ppo-structural-backbone-migration` (尚未 propose)。本 change 仅 docstring cleanup。完整规约见 follow-up change 提案。

**Why deferred:** PPO 已 fully self-contained(0 functional legacy 依赖),Phase 2.6 git rm `core/network/legacy/` zero break PPO。完整 backbone 切换(flat MLP → structural ActorCritic + 重写 obs flow + collector + buffer + rollout)是 500-1000 LOC 独立 sub-project,混入本 change 让 scope 失控,违反 user "auto-commit batch 报告" 的 manageable batch 原则。Spec invariant "5 paradigm 共用 backbone" 仍是 follow-up TODO。

本 delta 原是**本 change 中最大的 paradigm 改动**(PPO 从 outlier 收编进 generic backbone,从 flat MLP 改用 structural obs + ActorCritic)— 现 defer。下方 ADD/MODIFY/REMOVE 段保留为 follow-up change 的草案 reference,本 change 不实施。

## ADD

### A1. Generic backbone unification

> **P1. PPO MUST use generic ActorCritic backbone**:`PPONetwork` SHALL
> internally use `make_actor_critic(cfg, head_kinds={'policy', 'value'},
> use_typed_damage=True)` 作为 backbone,SHALL NOT 维护 paradigm-local
> trunk(如历史 `_PPOMLPTrunk` flat MLP)。

### A2. Structural obs flow

> **P2. PPO MUST consume structural obs**:PPO collector + rollout SHALL
> 走 `game_start(env.static_obs) cache + per-step dynamic_obs` 模式(与
> AZ / DMC / BC / CFR 一致),SHALL NOT 使用 `env.obs_size` flat dynamic
> vector 旁路 hook / counter / typed segments encoding。

### A3. AgentBase 集成

> **P3. PPO MUST integrate with AgentBase per-game cache**:`PPONetwork`
> (or new `PPOAgent`)SHALL 继承 `AgentBase` 或 compose 它,使用
> `encode_static()` 缓存 static obs(per-game once),`parse_dynamic()`
> 切 per-step dynamic obs into typed tensors(matching other 4 paradigm)。

## MODIFY

### M1. PPONetwork 完全重写

**Before**:
```python
class _PPOMLPTrunk(nn.Module):
    def __init__(self, obs_size, max_actions, d_model=256, n_hidden_layers=2):
        layers = [nn.Linear(obs_size, d_model), nn.ReLU(), ...]
        # forward(obs flat tensor) -> (logits, value)

class PPONetwork(nn.Module):
    def __init__(self, obs_size, max_actions, ...):
        self._trunk = _PPOMLPTrunk(obs_size=obs_size, ...)
```

**After**:
```python
class PPONetwork(nn.Module):
    """PPO adapter wrapper around generic ActorCritic backbone."""
    def __init__(self, cfg: PPOParadigmConfig, device: str = 'cpu') -> None:
        super().__init__()
        self._agent = PPOAgent(cfg, device=device)
        self.add_module('net', self._agent.net)

class PPOAgent(AgentBase):
    def __init__(self, cfg, device='cpu'):
        self.net = make_actor_critic(cfg, head_kinds={'policy', 'value'}, use_typed_damage=True)
        super().__init__(cfg, hook_encoder=self.net.encoders['hook'], device=device)
```

### M2. `_rollout.py` obs flow 重写

**Before**:
```python
# trajectory step:
obs = env.get_dynamic_obs()         # flat vector
logits, value = net.forward(obs)
```

**After**:
```python
# at episode start:
agent.game_start(env.static_obs)    # 一次性 encode_static cache

# per-step:
out = agent.eval_state(env.get_dynamic_obs(), refs, payments)
logits, value = out['policy'], out['value']
```

### M3. `collector.py` trajectory buffer schema

**Before**:`obs: list[ndarray]`(flat dynamic obs per step)

**After**:`(dyn_obs, refs, payments, cached_static_hash): list[tuple]` — dynamic + per-decision tensors + 缓存校验(防 game lifecycle 不一致)

### M4. `paradigm.py` 删除 `_probe_obs_size`

**Before**:
```python
def _probe_obs_size(self, cfg) -> int:
    """PPONet is flat MLP and needs obs_size at construction."""
    # ...
```

**After**:DELETE。`PPOAgent` 用 `AgentConfig` 派生 shape,不需要 probe flat obs_size。

### M5. `loss.py` 不变

PPO loss(masked CE + clip + GAE)与 backbone 无关,SHALL NOT 改 — 只接受 `(logits, value)` tuple 输出,backbone 怎么 produce 不影响 loss 数学。

## REMOVE

### R1. `_PPOMLPTrunk` class

`paradigms/ppo/network.py::_PPOMLPTrunk` SHALL be 完全删除。

理由:flat MLP backbone 是早期工程选择(s015-s054 ablation 期),不是 PPO 算法约束。collect into generic backbone 后,5 paradigm 完全对称。

### R2. `obs_size: int` 字段

`PPOParadigmConfig` 内 `obs_size` 字段 SHALL 删除。Shape 从 `cfg.shape: ObsShape`(per config-schema delta A1)派生。

### R3. PPO outlier 描述

`paradigm-ppo/spec.md` 主体若有 "PPO 用 flat MLP / outlier / 不消费 structural primitives" 表述 SHALL 全部删除。

## Risks(本 spec 特有)

- **R-PPO-1**:smoke 收敛失败 — PPO structural backbone 在 ≤ 2min mini-train 上无法跑出有意义的 clip ratio / advantage。**缓解**:smoke 不要求收敛,只要求 train loop alive + clip ratio bounded + final reward bounded(详 `../../design.md` Risks R1)。
- **R-PPO-2**:s015-s054 历史 ablation 复现失效。**缓解**:user 已接受(ckpt + cfg 失效 = reproducibility 同失效);若未来复现需要,通过 `git checkout pre-core-network-redesign-2026-05-17` + 老代码 + 老 cfg 走老路径。
- **R-PPO-3**:structural backbone forward 比 flat MLP 慢 ~3-5×。**缓解**:smoke 允许 batch size / step 数下调到能 ≤ 2min wall。

## Cross-references

- `../../proposal.md` — PPO 收编决策(T3 推荐)
- `../../design.md` Tradeoffs T3 + Risks R1 — 决策 + 缓解
- `../network-architecture/spec.md` invariant A4 — 5 paradigm 共用 backbone
- `../../tasks.md` Phase 2E — PPO 重写实施
- W4-PPO retire commit `2e5bc6f` — 历史 inline 化背景(legacy retire,非 paradigm retire)
