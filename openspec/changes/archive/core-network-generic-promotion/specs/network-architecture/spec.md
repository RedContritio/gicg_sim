---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: network-architecture
---

# Spec delta — network-architecture

本 delta 修订 `core/network/` 主体结构(generic primitives 提升 + 物理消除 `core/network/legacy/`)。详 `../../proposal.md`。

## ADD

### A1. Generic ActorCritic composition(thin layer)

新 SHALL invariant(加在主 spec invariant 列表末尾):

> **12. Generic ActorCritic composition**:`ActorCritic` SHALL be thin
> composition class — `__init__(encoders: nn.ModuleDict, readout, heads:
> nn.ModuleDict, typed_damage: Optional)` 接受所有 component 作 DI 注入,
> SHALL NOT 内部 hardcode encoder/head/typed_damage 实例化。Paradigm SHALL
> 通过 `make_actor_critic(cfg, head_kinds: set[str], use_typed_damage:
> bool)` 工厂函数装配,各自选择需要的 head subset(`'policy' | 'value' |
> 'q' | 'avg_policy' | 'delta'`)。

### A2. AgentBase DI 接口

> **13. AgentBase DI contract**:`AgentBase.__init__(cfg, hook_encoder,
> device)` SHALL 接受 `hook_encoder` 作 DI 注入参数,SHALL NOT 通过
> `self.net.hook_encoder` 属性查找。子类 SHALL 在构造时显式传入(典型:
> `super().__init__(cfg, hook_encoder=self.net.encoders['hook'], device)`)。
> 测试 SHALL 可以 inject mock `hook_encoder`,无需构造完整 `ActorCritic`。

### A3. typed_damage first-class component

> **14. typed_damage_encoder first-class**:`TypedDamageEncoder`(ADR-0019
> §B.3a 引入)SHALL be `core/network/typed_damage.py` 独立 module,SHALL
> NOT 嵌入 `ActorCritic` 内部。`ActorCritic` SHALL 通过 DI 接收
> `typed_damage: Optional[TypedDamageEncoder]`,`use_typed_damage=False` 时
> 跳过 typed segments encode。

### A4. 5 paradigm 共用 backbone

> **15. Backbone unification**:所有 5 paradigm(AZ/BC/CFR/DMC/**PPO**)
> SHALL 使用同一 `core/network/ActorCritic` backbone,SHALL NOT 维护
> paradigm-local 替代 trunk(如 PPO 之前的 `_PPOMLPTrunk`)。Paradigm
> 间差异 SHALL 仅在:(a) head subset 选择;(b) `use_typed_damage` 开关;
> (c) loss / collector / inference 策略;不在 backbone 本身。

## MODIFY

### M1. invariant 2(Typed obs separation)

**Before**:
> Observation SHALL split into static / dynamic / per-decision 三层。

**After**(增 PPO 必须遵守):
> Observation SHALL split into static / dynamic / per-decision 三层。**所有 5 paradigm SHALL 消费此 schema**,SHALL NOT 用 flat obs vector 旁路 structural primitives。

理由:PPO 之前 flat MLP 完全忽略 structural information,现 PPO 收编进 generic backbone 后,统一遵守。

### M2. invariant 11(Training pipeline)

**Before**:
> Worker → server RPC SHALL 通过 NetworkProvider 接口,server 通过 `AgentBase` subclass instance 服务 inference 请求。

**After**(无内容变化,加 DI 注解):
> ... server 通过 `AgentBase` subclass instance 服务 inference 请求。**`AgentBase` 通过 DI 注入 `hook_encoder`(per invariant 13),server 持有 `(cfg, net)` 即可构造,不依赖 `self.net.hook_encoder` 隐性查找**。

## REMOVE

### R1. legacy/ 子目录 invariant(若存在)

主 `spec.md` 若引用 `core/network/legacy/`,SHALL 删除该引用。Subtopic `encoders.md` / `heads.md` / `loss.md` 若引用 `legacy/trunk.py` / `legacy/actor_critic.py` / `legacy/loss.py`,SHALL 改为 root path(`core/network/encoder.py` / `core/network/actor_critic.py` / paradigm `loss.py`)。

理由:`core/network/legacy/` 整目录 git rm(Phase 1 T1.7)。

### R2. `az_losses` 函数 invariant(若存在)

主 spec 若引用 `training.core.network.legacy.loss.az_losses(...)` 作为 paradigm-agnostic loss 函数,SHALL 删除。AZ paradigm 已 inline 自己的 loss(`paradigms/az/loss.py::AZLoss`),无 paradigm 还消费 `az_losses` 函数。

## Cross-references

- `proposal.md` — 本 change 整体动机
- `design.md` Architecture 节 — ActorCritic / AgentBase 重设计具体形态
- `tasks.md` Phase 1 — generic primitives 重设计实施
- ADR-0019(typed obs ckpt break)— typed_damage_encoder 引入的历史决策
