# core-network-generic-promotion — Design Retrospective

> Archive-time summary (≤ 200 lines per archive cap)。详细 Architecture
> + Migrations 内容已拆到 `design/` subdir,见 ↓ 索引。

## Verdict

**部分成功** — 4 新结构层 + 5 paradigm 全切 + 6 follow-up 全 ship,但
PPO 收编(T3)scope 超出 batch 阈值,deferred 到 follow-up change
`ppo-structural-backbone-migration`(同日 2026-05-17 ship,完整闭环)。
整体 5 paradigm 共用 backbone + DI + cfg shared base + ckpt
self-describing 全部落地,parent + 6 follow-up 单 session 30+ commit 闭
环(per memory `project_session_ship_2026_05_17_core_network_redesign`)。

## What we built

- `core/network/` 重设计:`legacy/` 子目录退役,generic `ActorCritic`
  thin composition(~80 行)+ DI 接口(`AgentBase.__init__(cfg,
  hook_encoder, device)`)+ `make_actor_critic(cfg, head_kinds,
  use_typed_damage)` 工厂函数
- `core/cfg/` 共享 base:`ObsShape` + `ParadigmConfigBase`(version +
  paradigm + shape)5 paradigm cfg 共享,paradigm-local 替代全删
- Ckpt self-describing schema:`torch.save` 多 7 字段(paradigm /
  cfg_version / cfg / net_kind / git_commit / created_at);load 校验
- `tools/runs/` registry:`register/complete/list/show/sync` 5 CLI 取代
  人手 `registry.md`;metadata 落 `artifacts/runs/<id>.toml`
  (gitignored);跨机 sync via `rsync` wrapper
- 5 paradigm 切到 generic backbone(AZ/BC/CFR/DMC 完整,PPO 通过
  follow-up `ppo-structural-backbone-migration` 完成)

详 `design/architecture.md`。

## Tradeoffs revisited

- **T1 (god class → thin composition)**:预期 ~80 行,实际 ~80 行 ✓ —
  test 友好性显著提升(可 inject mock encoders),5 paradigm 装配代码
  ~10 行 each
- **T2 (DI 注入 vs Protocol-based)**:预期继承 + DI;实际 5 paradigm
  全部 adopt `super().__init__(cfg, hook_encoder=self.net.encoders['hook'],
  device)` pattern,IDE 友好性符合预期
- **T3 (PPO 收编)**:**预期 500 LOC 一次完成,实际 scope 失控** —
  评估后 deferred 到 follow-up change `ppo-structural-backbone-migration`
  (同日 2026-05-17 ship)。原因:PPO 改 structural obs + collector
  rewrite + buffer schema 改造 + AgentBase 集成 是 4 子项目,parent
  change 7-day batch 跑不完且违反 manageable batch 原则
- **T4 (legacy 扁平化)**:预期 bc/cfr/legacy 扁平化保留,实际 ✓ —
  BC `bc/legacy/{bc_train,bc_dataset}.py` mv 上,`bc_loss.py` inline 到
  `train.py`;CFR `cfr/legacy/{agent,network/strategy_net}.py` 扁平化
- **T5 (TOML)**:预期沿用 ✓ — 0 迁移成本
- **T6 (per-run TOML + CLI registry)**:预期 + 实际 ✓ —
  `tools.runs.list` 取代 markdown,11 个历史 r001-r012 一次性 dump 到
  `docs/5_history/runs_pre_redesign_2026_05_17.md`
- **T7 (rsync wrapper)**:预期 + 实际 ✓ — `tools.runs.sync pull/push`
  跟 GPU box ssh 工作流契合
- **T8 (mini-train+eval smoke)**:预期 ≤ 2min mini-train + eval probe,
  实际 ✓ — smoke ≤ 60s/paradigm(5 paradigm ~5s wall),smoke_full
  tier 5-15min opt-in;详 follow-up `paradigm-smoke-full-tier`

## Surprises

- **smoke_full tier 发现 4 production bugs**:`paradigm-smoke-full-tier`
  follow-up 实施过程中,5 paradigm smoke_full 暴露 4 个 pre-existing
  production driver path contract gaps(per memory
  `project_smoke_full_discovered_bugs_2026_05_17`)— 4 follow-up changes
  queued:`az-pool-spec-type-fix` / `ppo-rollout-card-pool-none-fix` /
  `cfr-driver-buffer-multihead-fix` / `bc-smoke-dataset-fixture`
- **DI 改造 ≠ 测试 regression**:R2 预测高概率破 ~30 tests;实际
  Phase 2 每 paradigm 切完立即跑 paradigm test 0 regression(归功于
  paradigm-by-paradigm 串行 dispatch,不批 dispatch)
- **PPO outlier 收编 scope 远超预算**:T3 评估 500 LOC,实际看着像
  500-1000 LOC + 多个 collector / buffer schema 改造,parent batch 跑
  不下,触发 scope adjustment 决策(2026-05-17 split-out)
- **paradigm cfg dataclass 对称度**:6 follow-up `ppo-cfg-shape-alignment`
  收尾时发现 5 paradigm cfg dataclass 完整对称(per memory
  `reference_hybrid_toml_structure`),整体 ~92-95% 统一度

## Spec delta summary

本 change 修订 8 个 capability spec + 3 个 subtopic(training-architecture):

- **config-schema**:+5 SHALL N1-N5(CS5.1-CS5.5)— ObsShape unification
  + ParadigmConfigBase + cfg version + ckpt self-describing schema +
  configs/<paradigm>/ layout;-R1/R2(paradigm-local AgentShapeCfg + 旧
  ckpt schema)SUPERSEDED
- **network-architecture**:+4 SHALL 12-15(generic ActorCritic / AgentBase
  DI / typed_damage first-class / 5 paradigm backbone unification);
  MODIFY SHALL 2(typed obs 所有 5 paradigm 消费)+ SHALL 11(DI 注解);
  5 subtopic 内 `legacy/` + `az_losses` 引用一并 path 改 → `core/network`
  root + paradigm-local `AZLoss`
- **training-architecture**:invariants.md +2 SHALL(#18 smoke 契约 +
  #19 backbone unification);paradigm-onboarding.md +§8 Smoke 契约 /
  paradigm-specific probe 章节(AZ/BC/DMC/CFR/PPO 各自 probe 要点);
  network-sharing.md +§6 Backbone unification + DI 接口 + typed_damage DI
- **tools-layout**:+5 SHALL T1-T5(TL6.1-TL6.5)— tools/runs/ layout +
  metadata SoT + CLI enforced lifecycle + cross-machine sync via rsync
  wrapper + TOML schema;-R1(docs/4_runs/registry.md SUPERSEDED)
- **paradigm-az**:MODIFY A4.2(generic ActorCritic + DI hook_encoder);
  +A6.2 r009 ckpt production fallback SUPERSEDED(ADR-0009 同步)
- **paradigm-bc**:MODIFY BC4.2(generic ActorCritic + DI);+BC6.3 r009
  BC pretrain ckpt SUPERSEDED;+BC7 扁平化 layout(bc/legacy/ 退役 + BC
  PPO variant 一并删除)
- **paradigm-cfr**:MODIFY C6.2(r008 ckpt reproducibility SUPERSEDED);
  +C7 扁平化 layout + DI(CFRAgent → CFRStrategyNet.hook_encoder)+
  typed_damage skip(CFR not consume typed segments)
- **paradigm-dmc**:MODIFY D5.1/D5.2(generic ActorCritic via
  `make_actor_critic` with `head_kinds={'q'}` 单 Q head + DI)
- **paradigm-ppo**:⚠ **deferred banner only** — backbone migration 推迟
  到 follow-up change `ppo-structural-backbone-migration`(同日 ship)

## 索引

- **[`design/architecture.md`](./design/architecture.md)** — 4 新结构层
  + 5 paradigm 全切详细形态(`core/network/` 新形态 + `core/cfg/` 共
  享 base + ckpt self-describing schema + `tools/runs/` registry 工具集
  + `configs/` 按 paradigm 重组)
- **[`design/migrations.md`](./design/migrations.md)** — 旧 ckpt / cfg /
  registry / dossier / ADR 处理 + 备份步骤(Phase 0 一次性)
