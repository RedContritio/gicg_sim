---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: network-sharing
---

# Network Sharing — encoder/heads 共享 vs paradigm-specific

> 本 subtopic 锚定 `training/core/network/` 共享部分(encoder + heads
> 基类)与 `training/paradigms/<name>/network.py` paradigm-specific 部分
> 的边界。详细模块切分、ActorCritic 组装 API、与 ADR-0019 strict 时序
> 表的交互细节在 P2 `unified-training-pipeline` change 落地。

## 1. Scope

本 subtopic 覆盖:

- `training/core/network/` 内 paradigm-agnostic encoder 与 heads 基类
- 各 paradigm 对应的 head 类型(AZ KL policy / DMC logit-as-Q / CFR
  avg policy / PPO value+policy / BC policy CE)
- ActorCritic 组装规则 — paradigm 选 heads 子集而非自由组合
- Encoder 修改边界 — paradigm SHALL NOT 修改 encoder

不覆盖:

- 具体 obs 张量字段(`rl-obs` capability spec 落地)
- 具体 encoder 结构(transformer / MLP / 何种 attention)— `core/network/`
  实现细节,SHALL 由本 spec 锚定边界即可
- 各 paradigm 内部网络 hyperparam(d_model / n_layer 等)— paradigm
  dossier

## 2. 总体形态

```
training/core/network/
    encoder.py        — paradigm-agnostic encoder(obs → latent)
    heads/
        policy.py     — policy head 基类(logits over action)
        value.py      — value head 基类(scalar)
        q.py          — Q head 基类(logits-as-Q,DMC)
        avg_policy.py — average policy head(CFR)
    actor_critic.py   — ActorCritic 组装容器

training/paradigms/<name>/network.py
    — paradigm-specific ActorCritic 实例,选 heads 子集
    — paradigm-specific loss-tied head 参数(详 paradigm dossier)
```

## 3. Core SHALL invariants

**核心 SHALL**:

1. Encoder SHALL be paradigm-agnostic 位于 `training/core/network/
   encoder.py`(SHALL 11 in 主 spec)。所有 paradigm 共享同一 encoder
   类(可参数化 hyperparam),不允许 paradigm-specific encoder。

2. Paradigm SHALL NOT 修改 encoder 结构 — paradigm-specific 行为通过
   heads 与 cfg 实现,而非改 encoder 层结构。

3. Heads SHALL live in `training/core/network/heads/` 提供基类,各
   paradigm 在 `training/paradigms/<name>/network.py` 中 instantiate
   并组装 ActorCritic。

4. ActorCritic SHALL be a composition container — encoder + 0..N heads
   组合;forward(obs) → dict[str, Tensor]({"policy": ..., "value": ...}
   等)。组合关系由 paradigm 决定。

5. Each head class SHALL be paradigm-independent in interface(同种
   head 不同 paradigm 共用一份基类),paradigm-specific 仅在
   hyperparam 与 loss-tying 上区别。

6. Network parameters SHALL be ckpt-able as a single state_dict —
   load_state_dict 可跨 paradigm 复用 encoder 权重(BC warm-start →
   AZ fine-tune 等场景);head 部分按 paradigm 选择 load / skip。

## 4. Paradigm × heads 对照

各 paradigm 选用 heads 的对照(详细 hyperparam 在各 paradigm dossier
落地):

- **AZ**:`policy(KL target via MCTS visit count)` + `value(MSE target
  via TD)` — 详 `training/az/`(P1 后 `paradigms/az/`)
- **DMC**:`q(logits-as-Q,MSE target via Monte Carlo return)` — 详
  Phase 3.5 review
- **CFR**:`policy(strategy CE)` + `avg_policy(historical avg via
  reservoir)` + `q(advantage MSE)` — 详 r008 实现
- **PPO**:`policy(clip ratio loss)` + `value(MSE)` + entropy bonus —
  详 `training/paradigms/ppo/`(post `core-network-generic-promotion`
  archive 2026-05-17:PPO 收编进 generic backbone via follow-up change
  `ppo-structural-backbone-migration`,详 §6 Backbone unification 节)
- **BC**:`policy(CE against expert action)` only — P2 后
  `paradigms/bc/`(SHALL 10 in 主 spec)

## 5. ActorCritic 组装规则

ActorCritic 是 paradigm 持有的 nn.Module,组装规则:

**SHALL**:

1. ActorCritic SHALL hold one encoder instance + 1..N head instances —
   forward order:encoder(obs) → latent → 每 head(latent) → outputs。

2. ActorCritic SHALL expose `forward(obs) -> dict[str, Tensor]` —
   返回 dict 而非 tuple,字段名 paradigm-specific 但 head 类型相同时
   字段名 SHALL 一致(`"policy"` / `"value"` / `"q"` / `"avg_policy"`)。

3. ActorCritic SHALL be constructed by `paradigm.make_network(cfg)`
   (详 [`./protocols.md`](./protocols.md))— driver 不直接实例化。

4. ActorCritic SHALL support partial load — `load_state_dict(strict=
   False)` 允许跨 paradigm 复用 encoder 部分参数(BC warm-start 场景)。

## 6. Backbone unification + DI 接口

> Added by `core-network-generic-promotion` (archived 2026-05-17),配合
> `invariants.md` SHALL 19 backbone unification 落地。本节锚定 5 paradigm
> 共用 `core/network/ActorCritic` backbone 的具体形态 + DI 接口的实施
> 契约。详细 SHALL 条款见 `../network-architecture/spec.md` invariants
> 12-15。

### 6.1 5 paradigm 共用 backbone

所有 5 paradigm(AZ / BC / CFR / DMC / **PPO**)SHALL consume
`core/network/ActorCritic` via `make_actor_critic(cfg, head_kinds,
use_typed_damage)` 工厂函数。各 paradigm 通过 `head_kinds` set 选择需要
的 head subset:

| Paradigm | head_kinds | use_typed_damage |
|---|---|---|
| AZ  | `{'policy', 'value', 'delta'}` | True |
| BC  | `{'policy', 'value', 'delta'}` | True |
| CFR | `{'policy', 'avg_policy', 'q'}`(via own `CFRStrategyNet`,non-ActorCritic) | False |
| DMC | `{'q'}`(logit-as-Q)| True |
| PPO | `{'policy', 'value'}` | True |

SHALL NOT 维护 paradigm-local backbone(如 PPO 历史 `_PPOMLPTrunk` flat
MLP)。Paradigm 间差异 SHALL 仅在:(a) head subset 选择;(b)
`use_typed_damage` 开关;(c) loss / collector / inference 策略;不在
backbone 本身。

### 6.2 AgentBase DI 接口

Paradigm 通过继承 `AgentBase` 共享 per-game cache,**子类 SHALL 在
`super().__init__(cfg, hook_encoder=..., device=...)` 显式注入
`hook_encoder`**(DI 接口,详 `network-architecture/spec.md` invariant
13)。SHALL NOT 依赖 `self.net.hook_encoder` 隐性查找。典型构造:

```python
class <X>Agent(AgentBase):
    def __init__(self, cfg, device='cpu'):
        self.net = make_actor_critic(cfg, head_kinds={...}, use_typed_damage=True)
        super().__init__(cfg, hook_encoder=self.net.encoders['hook'], device=device)
```

DI 设计的核心收益:测试 SHALL 可以 inject mock `hook_encoder`,无需构造
完整 `ActorCritic`;server 持有 `(cfg, net)` 即可构造,paradigm onboard
不依赖隐性属性查找。

### 6.3 typed_damage_encoder DI

`TypedDamageEncoder`(ADR-0019 §B.3a)SHALL be `core/network/typed_damage.py`
独立 module,通过 DI 注入 `ActorCritic(typed_damage: Optional)`。CFR 当
前 not consume typed segments,SHALL 用 `use_typed_damage=False`(与
`core-network-generic-promotion` design Tradeoffs 决策对齐)。

## 7. Cross-references

- Paradigm protocol `make_network` 详 [`./protocols.md`](./protocols.md)
- Pipeline driver 持有 network 的 lifecycle 详 [`./pipeline.md`](./pipeline.md)
- Eval worker 加载 network snapshot 详 [`./eval.md`](./eval.md)
- ADR-0019 strict 8 时机表对 head 设计的影响 → `memory
  project_adr_0019_strict`
- TypedDamageEncoder 历史 → `memory project_typed_obs_ckpt_break`
- BC warm-start 历史与 encoder 复用 → `memory project_bc_warmstart_progress`
- 具体 encoder 结构 / head hyperparam 在 P2 `unified-training-pipeline`
  change 与各 paradigm dossier 落地
