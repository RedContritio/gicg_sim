---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: network-architecture
---

# Spec delta — network-architecture

> 本 delta 完成 `core-network-generic-promotion` 中 invariant A4
> 的最后一步 — PPO 收编到 generic backbone。

## MODIFY

### M1. invariant A4 "5 paradigm 共用 backbone" 达成

**Before**(prior change `core-network-generic-promotion` 已表述):
> A4. 5 paradigm SHALL 共用 generic ActorCritic backbone via
> `make_actor_critic(cfg, head_kinds=..., use_typed_damage=...)`,SHALL
> NOT 各自维护 paradigm-local trunk。
>
> **Status (2026-05-17)**:AZ / BC / DMC / CFR ✅;**PPO 仍是 outlier**
> (per `core-network-generic-promotion` D-101 defer),follow-up change
> `ppo-structural-backbone-migration` ship 后完成。

**After**(本 change ship 后):
> A4. 5 paradigm SHALL 共用 generic ActorCritic backbone via
> `make_actor_critic(cfg, head_kinds=..., use_typed_damage=...)`,SHALL
> NOT 各自维护 paradigm-local trunk。
>
> **Status (2026-05-17)**:5 paradigm 全部满足 — AZ / BC / DMC / CFR /
> PPO 全走 generic ActorCritic backbone。spec invariant 100% 闭环。

## Cross-references

- `../../proposal.md` — 本 change 全 scope
- `../paradigm-ppo/spec.md` — PPO 切换 ADD invariants P1-P4 + MODIFY M1-M6
- `core-network-generic-promotion/specs/network-architecture/spec.md`
  — 原 invariant A4 定义 + D-101 defer 说明
- `core-network-generic-promotion/DECISIONS.md` [D-101] — 本 change 起源
