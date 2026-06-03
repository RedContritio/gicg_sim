---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: network-architecture
---

# Network Architecture — AZ 主网络规约

> 本 capability spec 治理 GICG 的 shipped 神经网络架构(C1v7,2026-04-18
> 之后):observation schema、encoder/pool 组件、value/policy/delta head、
> loss、training pipeline(进程拓扑 + RPC)。各 paradigm(AZ/CFR/BC/DMC)
> 共享同一主干,paradigm-specific 偏离在各自 dossier 治理,不属本 spec
> 范围。
>
> 当前 shipped run 为 C1v7(`az_c1v7`),首个"反 ID + 结构性引用分
> 离"架构公平验证通过的训练(argmax vs mcts_200 = 45%)。本 spec 从
> `docs/1_specs/network/current.md`(472 行,P1-T2 之前的 narrative
> snapshot)抽取规约,SHALL 化 + 按 5 subtopic 拆分。design 推导 + C1v6
> 修复历史保留在 `docs/5_history/network_design_history.md`。

## 1. Purpose

GICG 网络架构需被规约化,否则会出现:

- shipped 实际结构与 design intent 不一致(已发生:`CharEncoder` /
  `card_feature_proj` 历史 design 节但从未 shipped),阅读者无判据
- C1v7 结构性 sid pinning + struct_readout 的设计契约(零空间绕过 +
  反 ID 原则)在跨 paradigm 复用时被无意破坏
- Encoder / head / loss 的核心 invariant(例如 CounterEncoder 用
  `active_slot_mask` 而非 `value≠0`、policy head 是 pointer-net 而非
  softmax-over-IDs)在 refactor 中静默偏离

本 spec 提供 5 大类约束:

- **Observation schema**(详 [`./obs.md`](./obs.md))
- **Encoders + pool**(详 [`./encoders.md`](./encoders.md))
- **Heads**(详 [`./heads.md`](./heads.md))
- **Loss**(详 [`./loss.md`](./loss.md))
- **Training pipeline**(详 [`./training-pipeline.md`](./training-pipeline.md))

## 2. Scope

**In scope**:

- AZ 主网络的 shipped 结构(C1v7 + 之前的 hook-gradient / L2-skip /
  active-slot-mask 等修复)
- Static + Dynamic obs 数据契约(从 `gicg_env` 经 `GameGetStaticObs` /
  `GameGetDynamicObs` 流入网络的格式)
- Trainer / self-play worker / inference server 的进程拓扑与 RPC 契约

**Out of scope**:

- 各 paradigm 的算法层(MCTS PUCT 公式、CFR regret 更新、BC dataset
  生成)— 由各自 paradigm dossier 治理
- `gicg_engine` 内 counter / hook 的底层数据布局 — 由 engine-dsl
  capability spec 治理(`openspec/specs/engine-dsl/`)
- Training infrastructure(driver loop / SHM ring buffer / opponent
  mix)— 由 training-architecture capability spec 治理
- 历史推导(C1v0 → C1v7 的 ablation/decision 链)— 由
  `docs/5_history/network_design_history.md` 保留

## 3. Core SHALL invariants

以下 15 条 invariant 是本 capability 的硬约束。任意冲突应作为
OpenSpec change 提案修订,而非在代码中静默偏离。

1. **C1v7 baseline**:Shipped network SHALL follow C1v7 — structural
   sid pinning(HP/Energy/Alive/Active/dice/alive_count 每局 sid 稳定
   在 0..65)+ struct_readout(`Linear(66 → d_model)` 直通 value/policy/
   delta head,绕过 CounterEncoder + CrossAttention + pool)+ 反 ID
   mechanical counters(shields/buffs/summons 仍每局 shuffle)。详
   [`./encoders.md`](./encoders.md) struct_head section。

2. **Typed obs separation**:Observation SHALL split into **static**
   (per-game,一次 compute)和 **dynamic**(per-step,每决策 compute)
   两个 schema。Per-decision action features 作为第三层,绑 legal_actions。
   **所有 5 paradigm SHALL 消费此 schema**(per invariant 15 backbone
   unification),SHALL NOT 用 flat obs vector 旁路 structural primitives。
   详 [`./obs.md`](./obs.md)。

3. **Static obs scope**:Static obs SHALL contain HookEncoder 的 raw
   tokens(types + values + mask)、CounterEncoder 的 sid / min / max
   元信息、CardEncoder 的静态 slot table。Counter values **不在** static
   obs(为 dynamic),hook tokens **在** static(per-game 不变)。

4. **CounterEncoder sparsity by mask**:CounterEncoder SHALL filter
   active slots via `active_slot_mask = (min≠0 or max≠0)`,SHALL NOT
   filter by `value ≠ 0`(value=0 对破盾/解冻/归零瞬间是有效信息)。

5. **CrossAttention depth**:CrossAttention SHALL have **2 layers**
   (`n_cross_layers=2`,d=128, 4 heads)。增减层数视为架构变更,需
   change proposal。背景:C1v7 ablation 证实增层无收益,删层让 pool
   零空间问题恶化。

6. **Pool via char_skill_refs**:Pool layer SHALL use
   `char_skill_refs`(`(2, 6, 10)`)gather from post-attention hook_emb
   + mask-based masked mean。SHALL NOT collapse all slots to single
   global pool(避免 C18 pool 零空间)。详 [`./encoders.md`](./encoders.md)。

7. **Policy head as pointer-net**:Policy head SHALL be pointer-net —
   `logit[a] = ⟨state_vec, action_emb[a]⟩` dot product。SHALL NOT use
   softmax over a fixed action-ID table(违反反 ID 原则)。action_emb
   按 kind 分三路 gather(SKILL/CARD ← post-xattn hook_emb,SWITCH ←
   char_slot_emb,END_TURN ← learned const)+ dice_combo_proj 残差。
   详 [`./heads.md`](./heads.md)。

8. **Value head bounded**:Value head SHALL output `v = tanh(MLP(state))`
   范围 `[-1, 1]`,与 MSE 目标 `z ∈ {-1, 0, +1}` 对齐。SHALL NOT 输出
   unbounded scalar(防 logit 爆炸 + 训练不稳)。

9. **Delta head auxiliary**:Delta head SHALL be optional auxiliary
   supervision(预测 `counter_after - counter_before`),受
   `delta_aux_coef` 控制,SHALL be skippable by paradigm。当
   `delta_aux_coef = 0` 时 delta head 仍 forward 但不计 loss(避免
   架构变更)。

10. **Loss composition**:Total loss SHALL combine 5 terms — policy
    masked CE + value MSE + L2(skip `dim < 2` params)+ entropy(via
    `entropy_coef`)+ delta aux(via `delta_aux_coef`)。L2 SHALL skip
    bias + LayerNorm weight(防 LN scale 塌缩)。详
    [`./loss.md`](./loss.md)。

11. **Training process topology**:Self-play SHALL run via inference
    server(1 proc)+ N self-play workers(MCTS + env step)+ trainer
    main proc(buffer + train_step + arena/gauntlet)。Worker → server
    RPC SHALL be one-way query(`game_start` / `eval` / `game_end`),
    weight push SHALL flow trainer → server(单向)。**`AgentBase` 通过
    DI 注入 `hook_encoder`**(per invariant 13),server 持有 `(cfg,
    net)` 即可构造,不依赖 `self.net.hook_encoder` 隐性查找。详
    [`./training-pipeline.md`](./training-pipeline.md);RPC 协议与
    training-architecture capability 的
    [`protocols.md`](../training-architecture/protocols.md)
    NetworkProvider 接口对齐。

> Invariants 12-15 added by `core-network-generic-promotion` (archived
> 2026-05-17) — generic primitives 提升 + 5 paradigm 共用 backbone +
> AgentBase DI + typed_damage first-class component。`core/network/legacy/`
> 子树 SHALL 不存在。

12. **Generic ActorCritic composition**:`ActorCritic` SHALL be thin
    composition class — `__init__(encoders: nn.ModuleDict, readout, heads:
    nn.ModuleDict, typed_damage: Optional)` 接受所有 component 作 DI 注入,
    SHALL NOT 内部 hardcode encoder/head/typed_damage 实例化。Paradigm
    SHALL 通过 `make_actor_critic(cfg, head_kinds: set[str],
    use_typed_damage: bool)` 工厂函数装配,各自选择需要的 head subset
    (`'policy' | 'value' | 'q' | 'avg_policy' | 'delta'`)。

    **A12.1**(deterministic head ordering pre-condition):`make_actor_critic`
    (`training/core/network/actor_critic.py`)SHALL iterate `head_kinds`
    in **`HEAD_REGISTRY` insertion order**(module-level dict:`{'policy',
    'value', 'q', 'avg_policy', 'delta'}` — Python ≥ 3.7 dict 保插入顺序
    stable across processes)。SHALL NOT 直接 `for kind in head_kinds:`
    迭代 — `head_kinds` typed as `set[str]` / `frozenset[str]`,默认
    `PYTHONHASHSEED=random` 下 iteration order 跨 subprocess 不同,导致
    `nn.ModuleDict heads` 插入顺序、`model.parameters()` 顺序、
    `optimizer.state_dict()` positional state mapping 跨 save / resume 错位
    → `optimizer.step()` post-resume `addcdiv_` 因 `exp_avg.shape` 与
    `param.shape` 不一致 raise `RuntimeError: output with shape [...]
    doesn't match the broadcast shape [...]`。Canonical form:
    `for kind in sorted(head_kinds, key=_REGISTRY_ORDER.__getitem__):`,
    `_REGISTRY_ORDER = {k: i for i, k in enumerate(HEAD_REGISTRY)}`。
    Guard test:`training/tests/test_head_order_deterministic.py` 跨 ≥ 3
    fresh subprocess assert `list(net.heads.keys())` identical for
    AZ / BC / PPO head sets。

13. **AgentBase DI contract**:`AgentBase.__init__(cfg, hook_encoder,
    device)` SHALL 接受 `hook_encoder` 作 DI 注入参数,SHALL NOT 通过
    `self.net.hook_encoder` 属性查找。子类 SHALL 在构造时显式传入(典型:
    `super().__init__(cfg, hook_encoder=self.net.encoders['hook'],
    device)`)。测试 SHALL 可以 inject mock `hook_encoder`,无需构造完整
    `ActorCritic`。

14. **typed_damage_encoder first-class**:`TypedDamageEncoder`(ADR-0019
    §B.3a 引入)SHALL be `core/network/typed_damage.py` 独立 module,SHALL
    NOT 嵌入 `ActorCritic` 内部。`ActorCritic` SHALL 通过 DI 接收
    `typed_damage: Optional[TypedDamageEncoder]`,`use_typed_damage=False`
    时跳过 typed segments encode。

15. **Backbone unification**:所有 5 paradigm(AZ/BC/CFR/DMC/**PPO**)
    SHALL 使用同一 `core/network/ActorCritic` backbone,SHALL NOT 维护
    paradigm-local 替代 trunk(如 PPO 历史 `_PPOMLPTrunk`)。Paradigm
    间差异 SHALL 仅在:(a) head subset 选择;(b) `use_typed_damage` 开关;
    (c) loss / collector / inference 策略;不在 backbone 本身。**Status
    (2026-05-17)**:5 paradigm 全部满足 — AZ / BC / CFR / DMC / PPO 全
    走 generic ActorCritic backbone(PPO 收编 ship via
    `ppo-structural-backbone-migration` archive 2026-05-17)。spec
    invariant 100% 闭环。

## 4. Subtopics

本 capability 由本文件 + 5 个 subtopic 组成。每个 subtopic 专注一组
正交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [Obs schema](./obs.md) — Static obs(counter_meta / char_skill_refs /
  hook_tokens)+ Dynamic obs(meta / counter_values / card_buckets /
  enemy_sizes)+ Per-decision action_refs / action_payments + 视角约定
- [Encoders + pool](./encoders.md) — HookEncoder(Transformer)/
  CounterEncoder(sid + val proj)/ CardEncoder(bucket + slot)/
  CrossAttention × 2 / struct_head / char_skill pool 与 global_state
  组装
- [Heads](./heads.md) — Value head(tanh-MLP)/ Delta head(aux MLP)/
  Policy head(pointer-net + dice_combo residual)
- [Loss](./loss.md) — Policy CE(legal mask)/ Value MSE / L2 with
  bias-LN skip / Entropy regularization / Delta aux(masked)/ Total
  combination
- [Training pipeline](./training-pipeline.md) — 进程拓扑(server +
  workers + trainer)/ self-play worker loop / trainer loop /
  `train_step` 流程 / inference RPC schema / stale weights 容忍

## 5. Cross-references

**Sibling capability specs**:

- [`openspec/specs/engine-dsl/`](../engine-dsl/spec.md) — 底层
  counter / hook 数据布局(本 spec 的 obs 入口由 engine 提供)
- [`openspec/specs/training-architecture/`](../training-architecture/spec.md) —
  paradigm-agnostic training infra(protocol / pipeline / network
  sharing / eval);本 spec 的 training-pipeline 与 training-architecture
  的 protocols.md 衔接
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) —
  本 spec 的格式与阈值由其治理

**Active OpenSpec changes** (cross-cutting):

- `openspec/changes/archive/0019-dsl-v6-semantic-engine/` — Typed
  damage encoder + DSL v6 semantic obs(本 spec obs.md 内详 cross-ref)

**History / postmortems**:

- [`docs/5_history/network_design_history.md`](../../../docs/5_history/network_design_history.md) —
  C1v0 → C1v7 演化推导 + C1v6 前六项修复摘要 + 设计意图(含未 shipped
  组件标注)
- `docs/1_specs/network/current.md` (deleted, migrated here) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理

## 6. Status

- **Created**:2026-05-15(P1-T2)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)— +4
  SHALL 12-15(generic ActorCritic / AgentBase DI / typed_damage first-class
  / 5 paradigm backbone unification);MODIFY SHALL 2(typed obs 所有 5
  paradigm 消费)+ SHALL 11(DI 注解)。`core/network/legacy/` 子树物理
  退役 → loss.md / training-pipeline.md `az_losses` 引用一并改 path
  (AZ paradigm-local `paradigms/az/loss.py::AZLoss`)。
- **Revised**:2026-05-17(`ppo-structural-backbone-migration` archive)—
  MODIFY SHALL 15 closure update:PPO outlier 退役,5 paradigm
  backbone unification 100% 闭环;`_PPOMLPTrunk` flat MLP + `obs_size`
  flat probe 物理删除,PPO 走 generic `make_actor_critic(head_kinds=
  {'policy','value'}, use_typed_damage=True)` 与其它 4 paradigm 对称。
- **Revised**:2026-05-17(`az-resume-shape-fix` archive)— +A12.1
  sub-invariant on SHALL 12(deterministic head iteration order in
  `make_actor_critic`,治理 frozenset `head_kinds` iteration 跨 subprocess
  不一致 → ckpt save / resume optimizer state 错位 broadcast fail)。
  修复 AZ smoke_full A1.6.3 resume-phase 阻塞,unskip
  `test_az_smoke_full.py`,加 guard test
  `test_head_order_deterministic.py`(3 paradigm head sets stress)。
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/network/current.md` + `design.md`
- **Expected revision triggers**:
  - 跨 paradigm 网络分歧实化(BC/CFR 偏离 AZ 主干)
  - 新 head 加入(D11 deckbuild policy / D7 dice-aware action features)
  - C1v8+ 架构演化(若 struct_readout 之外又增结构性绕路)
  - ADR-0019 typed obs 全量上线后,obs.md 改为引用 dsl-v6 schema
