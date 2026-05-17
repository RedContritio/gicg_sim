---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: training-architecture
---

# Spec delta — training-architecture

本 delta 修订 `network-sharing.md` + `paradigm-onboarding.md` subtopic:5 paradigm 全部共享 generic backbone + 接入新 paradigm SOP 增 smoke 契约。详 `../../proposal.md`。

## ADD

### A1. Smoke test 契约

新 subtopic 或在 `paradigm-onboarding.md` 中加章节:

> **每 paradigm SHALL provide e2e smoke test** `training/tests/test_<paradigm>_smoke.py`
> with `@pytest.mark.smoke` marker. Smoke SHALL:
>
> 1. **从零启动**:无 ckpt 依赖,从 random init 跑
> 2. **mini-train**:真走 `collector → buffer → forward → backward → optimizer.step`,SHALL NOT stub training loop
> 3. **eval probe**:训练后 ≥ 1 局 e2e episode,terminal reward 在 `[-1, +1]` 流通
> 4. **paradigm-specific invariant**:
>    - AZ: MCTS visit_counts > 0 + value ∈ [-1, 1]
>    - BC: cross_entropy loss decrease(初始 random vs 100 step)
>    - DMC: Q-value finite + ε-greedy 在 ε=1 时全 random
>    - CFR: strategy distribution sums to 1 + regret < ∞
>    - PPO: clip ratio in `[1-ε, 1+ε]` + advantage normalized
> 5. **Wall time ≤ 2min**:CI / pre-commit 友好

### A2. Generic backbone unification(network-sharing.md)

> **Backbone unification SHALL apply to all 5 paradigms**:AZ / BC / CFR /
> DMC / **PPO** all SHALL consume `core/network/ActorCritic` via
> `make_actor_critic(cfg, head_kinds, use_typed_damage)` factory. SHALL
> NOT maintain paradigm-local backbone(如 PPO 历史 `_PPOMLPTrunk`)。

## MODIFY

### M1. paradigm-onboarding.md — 接入新 paradigm SOP

加新章节 "Smoke 必须项":

**Before**(若有):
> 新 paradigm SHALL 提供 `paradigm.py` 入口、`config.py` cfg、`network.py` wrapper、`loss.py` 等。

**After**:
> 新 paradigm SHALL 提供 ... 以及 **`test_<paradigm>_smoke.py` e2e smoke test**(详 smoke 契约章节)。Smoke pass 是 paradigm 接入 merge gate。

### M2. network-sharing.md — DI 接口

**Before**:
> Paradigm 通过继承 `AgentBase` 共享 per-game cache,子类 SET `self.net` 后即可调用 `AgentBase.encode_static()` 等(隐性依赖 `self.net.hook_encoder`)。

**After**:
> Paradigm 通过继承 `AgentBase` 共享 per-game cache,**子类 SHALL 在 `super().__init__(cfg, hook_encoder=..., device=...)` 显式注入 `hook_encoder`**(DI 接口,详 `network-architecture/spec.md` invariant 13)。SHALL NOT 依赖 `self.net.hook_encoder` 隐性查找。

## REMOVE

### R1. PPO outlier 描述

`network-sharing.md` 若存在 "PPO 用 paradigm-local flat MLP,不消费 structural primitives" 表述,SHALL 全部删除。PPO 现 first-class generic backbone user(per network-architecture invariant 15)。

理由:PPO 收编进 generic backbone(本 change Phase 2E)。

## Cross-references

- `../network-architecture/spec.md` invariant A1/A2/A4 — generic backbone + DI + 5 paradigm unification
- `../config-schema/spec.md` invariant A1/A2 — ObsShape 共享 + ParadigmConfigBase 是 backbone 共享的 cfg 前提
- `../../proposal.md` — change 整体
- `../../tasks.md` Phase 4 — 5 smoke test 实施
