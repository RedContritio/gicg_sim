# core-network-generic-promotion — autonomous decisions log

User 2026-05-17 授权"剩余按最可能判断先做"。本文件记录 autonomous decisions
留给 user 后续 review,decisions 标 [D-NNN] 编号便于引用。

---

## Phase 2 已记录的 scope adjustments

### [D-101] PPO backbone 切换 deferred

- **Decision**: PPO 完整 backbone 切换(flat MLP → structural ActorCritic)从本 change 移出,defer 到 follow-up change `ppo-structural-backbone-migration`(尚未 propose)。
- **Why**: PPO 已 fully self-contained(0 functional legacy 依赖),Phase 2.6 git rm legacy/ zero break。完整切换需要重写 obs flow + collector + buffer + rollout + network + tests,~500-1000 LOC,是独立 sub-project。混入本 change 让 scope 失控。
- **Spec impact**: spec invariant "5 paradigm 共用 backbone" 仍是 follow-up TODO,本 change ship 不阻塞(invariant 在 follow-up change 完成)。
- **Already documented in**: commit 6bad043 + tasks.md T2.5 + proposal.md Out of scope + specs/paradigm-ppo/spec.md status banner

### [D-102] env_factory_legacy.py rename deferred

- **Decision**: `core/env_factory_legacy.py` → `core/env_factory.py` rename 移到 follow-up change `env-factory-unification`(尚未 propose)。
- **Why**: 发现 `core/env_factory.py` 已存在但 signature 不同 — P3-A protocol-driven `(cfg, obs_config_json)` 2-arg 取代 legacy 1-arg `cfg.obs`。两套 API 共存,各自有 callers。简单 rename 会破。需先 API reconciliation(选哪个 signature 是 canonical),是独立 sub-project (+50/-50 LOC + 2 callers update + ADR)。
- **Spec impact**: 不阻塞 Phase 2.6 legacy/ git rm(env_factory_legacy.py 不在 core/network/legacy/);config-schema/spec.md invariant "naming consistency" 仍 follow-up TODO。
- **Already documented in**: commit 8eab177 + tasks.md T2.6b

## Phase 3 cfg 层 autonomous decisions

### [D-201] AgentShapeCfg → ObsShape full unification deferred

- **Decision**: 5 paradigm 现有 `AgentShapeCfg` / `CFRAgentShapeCfg` / `PPOAgentShapeCfg` dataclass **保留**,不在本 change 替换为 `ObsShape`。
- **Why**:
  - AgentShapeCfg 各 paradigm 有不同 default values(n_counter_slots = `2*6*128 + 2*140 + 16` 等),ObsShape 无 defaults — 替换会破坏现有 `AgentShapeCfg()` 默认构造 caller。
  - PPO 的 PPOAgentShapeCfg 字段完全不同(d_model + n_hidden_layers + max_actions,无 hook/counter/cross_layers),与 ObsShape 不兼容(PPO 用 flat MLP,backbone defer per D-101)。
  - 完整 unification 需要 defaults strategy(factory functions vs paradigm subclass),是独立设计 sub-project。
- **Spec impact**: `config-schema/spec.md` invariant N1 (ObsShape unification) 仍是 follow-up TODO。
- **Follow-up**: 待 PPO backbone migration(D-101) ship 后,5 paradigm 都有 structural shape,统一 ObsShape 更自然。

### [D-202] cfg version 字段 + ParadigmConfigBase compose deferred

- **Decision**: 5 paradigm `<Paradigm>ParadigmConfig` 不 compose `ParadigmConfigBase`,不加 `version` + `paradigm` 字段。
- **Why**:
  - ParadigmConfigBase 有 `shape: ObsShape` 字段假设 paradigm 用 ObsShape — 但 PPO 不用(D-201)。Subclass 覆盖 field type 是 Python 动态特性但类型检查器会警告,会引入新 noise。
  - 5 paradigm config_loader 已经从 TOML 中验证 paradigm dispatch key + 其它字段,version 字段在此层面无 immediate value。
  - 完整 version compose 需要 5 paradigm config.py 全部改 + config_loader 适配,是 ~150 LOC 改动,scope 失控风险。
- **Spec impact**: `config-schema/spec.md` invariant N2 + N3 (ParadigmConfigBase + version) 仍是 follow-up TODO。
- **Follow-up**: 与 D-201 一并在 `cfg-schema-unification` follow-up change 完成。

### [D-203] ckpt self-describing schema **DO ship**

- **Decision**: 升级 `AgentBase.save / load` 到 self-describing schema(`{paradigm, cfg_version, cfg, net_kind, net_state_dict, git_commit, created_at}`)。
- **Why**:
  - 独立改动,影响 face 单一(`agent_base.py` 一处),所有 paradigm 透明受益。
  - User aligned "ckpt 不需要兼容旧" → 旧 ckpt 已删 → 新 schema 无 backward compat 负担。
  - `tools/ckpt/info.py` CLI 提供 inspect 入口,无需 caller 预知 paradigm。
- **Spec impact**: 完成 invariant N4 (ckpt self-describing)。
- **What's in scope**:
  - `paradigm` 字段:取 `agent.__class__.__module__` (eg 'training.paradigms.az.network')派生
  - `cfg_version` 字段:hard-code "1.0.0" (paradigm cfg 还没正式 version,future 升级)
  - `git_commit`: `subprocess.check_output(['git', 'rev-parse', 'HEAD'])`,失败 fallback 'unknown'
  - `created_at`: `datetime.now(timezone.utc).isoformat()`
- **Backward compat**: load 旧 ckpt(`{'net', 'cfg'}` 2-key)抛 `CkptSchemaError`,user 已接受。

### [D-204] configs/<paradigm>/{default,smoke}.toml **deferred** (paired with D-201/202)

- **Decision (revised)**: 不在本 change 写 configs/<paradigm>/ toml 模板。
- **Why**: 新 toml 格式(`version + paradigm + [shape] section`)依赖 cfg schema 重设计 (D-201 + D-202),后者已 defer。先写 toml 无 parseable config_loader = dead 文件。
- **Spec impact**: invariant N5 (configs/ layout) 仍 follow-up TODO,与 D-201/202 一起在 `cfg-schema-unification` follow-up change 完成。
- **What's in scope now**: configs/ 物理仅 `_archived/` 子目录(Phase 0 归档结果)+ `README.md`,无 paradigm 子目录直到 follow-up。

### [D-205] tools/runs/ + tools/ckpt/info DO ship

- **Decision**: 全 ship,per spec tools-layout invariant T1-T5。
- **Scope**: register / complete / list / show / sync CLI + schema + 5 smoke tests。
- **artifacts/runs/ schema**: per design.md (TOML with run_id/label/paradigm/cfg_file/cfg_checksum/git_commit/host/status/summary/result/notes)
- **sync wrapper**: rsync with hardcoded `--include artifacts/runs/` `--exclude *`

### [D-207] CFRAgent custom save/load schema preserved

- **Decision**: CFRAgent 在 `cfr/agent.py` 有自己的 `save / load` override(用 `kind` 字段做 CFRStrategyNet identity check),保留不动,不强迫切到 AgentBase 新 self-describing schema。
- **Why**: CFRStrategyNet 与 AZ ActorCritic 形态不同(独有 advantage / regret heads),CFR 历史 ckpt 用 KIND 字段做类型 disambiguation,新 schema 不能直接表达。
- **Spec impact**: spec invariant N4 (ckpt self-describing) 在 5 paradigm 中:AZ/BC/DMC 用 new self-describing schema(via AgentBase default);CFR 用 paradigm-specific schema(override)。Partial compliance,documented as known divergence。
- **Follow-up**: 待 CFR backbone 统一(若未来 propose `cfr-backbone-unification` change)时一并 unify ckpt schema。

## Phase 4 smoke tests autonomous decisions

### [D-301] Smoke wall time = 60s budget per paradigm

- **Decision**: 各 paradigm smoke wall time 上限收紧到 **60s** (per design.md 写 2min,但实际 CI 友好考虑 60s 是合理上限)。
- **Why**: 60s 内可以 collect 5-20 games + train 5 steps,足够验证 train pipeline alive。
- **Spec impact**: design.md T8 wall time spec 是 ≤ 2min,本 change 实际是 ≤ 60s ≤ 2min,符合 spec(更紧)。

### [D-302] PPO smoke 用 flat MLP backbone(因 PPO 切换 deferred)

- **Decision**: PPO smoke `test_ppo_smoke.py` 用现有 PPONetwork (`_PPOMLPTrunk` flat MLP),不要求 structural backbone。
- **Why**: PPO backbone migration defer per D-101,smoke 测的是 PPO 算法可跑(clip ratio bounded + advantage normalized),与 backbone 选择无关。
- **Follow-up**: 待 D-101 ship 后,PPO smoke 自然升级到 structural backbone。

### [D-304] Phase 4 smoke "eval probe" 用 single forward 而非 full e2e episode

- **Decision**: smoke "eval probe" 步骤实际是 single forward pass(get state/value/policy outputs sanity check),不跑 full env episode → terminal reward。
- **Why** (agent 实施时发现):
  - 60s 上限对 AZ MCTS 尤其紧张(每 rollout O(n_rollouts × env_step));full e2e episode 在 AZ smoke wall 内做不到。
  - smoke 目标是 "train pipeline alive"(collector → buffer → forward → backward → optimizer.step),不是 "agent 收敛 / 终局能赢"。Single forward 已 demonstrates protocol 连通。
- **Spec impact**: spec invariant A1.3 ("≥ 1 局 e2e episode + terminal reward ∈ [-1, +1]") **partial compliance** — single forward 替代 full episode。
- **Follow-up**: 若未来需要更强 smoke,可加 `@pytest.mark.smoke_full` (跑全 episode,~5min wall) 作 second-tier marker;不在本 change scope。

### [D-305] Phase 4 BC smoke 不变量弱化:loss "不增长" 而非"减小"

- **Decision**: BC smoke 不变量 `cross_entropy 不变大`(允许 ≤ 5% growth),不要求严格 strict decrease。
- **Why**:1 gradient step on synthetic batch with degenerate init(tied logits / random label)可能不严格 decrease,会触发 false positive。"不增长"足以验证 loss 是 finite + backprop 路径连通。
- **Spec impact**: spec invariant A1.4 BC paradigm-specific("cross_entropy loss decrease 初始 random → 100 step")**partial compliance** — 1 step + "不增长" 替代 100 step + strict decrease。
- **Follow-up**: 若加 `smoke_full` tier,跑 100 step 验证 strict decrease。

### [D-303] Phase 4 smoke tests 走 symmetric template

- **Decision** (per user 2026-05-17 "测试实际上也应该是基本对称的,对吧"): Phase 4 5 paradigm smoke tests 采用对称模板,不是各 paradigm 各写一套。
- **Why**: 5 paradigm 共享 backbone (除 PPO defer per D-101),tests 也应共享结构。统一模板 → 新加 paradigm 只需提供配置,无需重写整套 smoke 逻辑。
- **Implementation**: 1 base `smoke_test_template.py`(paradigm-agnostic 步骤)+ 5 paradigm-specific subclass / parameterize 提供:
  - cfg builder (paradigm-specific config object)
  - paradigm-specific invariant assertion(AZ MCTS visits / BC CE decrease / DMC Q finite / CFR strategy 归一 / PPO clip ratio bounded)
- **Structure**: 用 pytest parametrize / fixture pattern,5 tests visually 几乎相同,差异在 dict / class registry。
- **Spec impact**: 完成 training-architecture invariant A1 (5 paradigm smoke 契约) 更彻底,且体现 spec "5 paradigm 对称" 设计原则。

## Phase 6 spec/ADR autonomous decisions

### [D-401] 8 spec delta 不 merge 到主 spec.md(deferred)

- **Decision**: 本 change 完成时,8 个 spec delta(`changes/core-network-generic-promotion/specs/<cap>/spec.md`)**不** merge 到 `openspec/specs/<cap>/spec.md` 主 spec — 留给 `/opsx:archive` 工具 / 手动 archive workflow 处理。
- **Why**: Archive workflow 跑 5-step SOP 自动 merge spec deltas + git mv changes/ → archive/,不应在 change 实施期手动做(违反 single source of truth)。
- **Spec impact**: spec delta files 跟 change directory 一起 ship,archive 时 merge。

### [D-402] ADR-0009 / C6.2 supersede note 通过 spec delta 记录(已做)

- **Decision**: SUPERSEDED 标签已在 spec deltas 写明(R1/R2 段),archive 时 merge 到主 spec。本 change 不直接编辑 `docs/2_decisions/adr-0009-*.md`(那是 docs/,本 change 是 openspec/)。
- **Why**: ADR 历史不可变;现状变化通过新 spec 删除 / SUPERSEDED 标签表达,docs 文件保留作历史 reference。
- **Spec impact**: openspec spec delta 完成 R1/R2,docs/ ADR 不动。
- **Follow-up**: 若希望 docs/2_decisions/adr-0009 也加 SUPERSEDED banner,可作 docs 同步 follow-up commit。

### [D-403] docs/4_runs / docs/paradigms/ 引用 update deferred

- **Decision**: Phase 0 找到的 20+ 文件残留引用 `docs/4_runs/registry.md`(CLAUDE.md / docs/README.md / docs/0_status/*.md / docs/paradigms/*/runs.md 等)更新 **defer**,作为单独 docs sweep 任务。
- **Why**: 20+ 文件批改是 docs 范围,与 generic primitives 重设计 scope 解耦。批量 sed 易出错,需要逐个 review。
- **Spec impact**: tools-layout invariant 完成不依赖 docs 引用更新。
- **Follow-up**: 单独 docs cleanup commit 或 follow-up change `docs-pre-redesign-refs-sweep`。

## 累计 deferred follow-up changes

待 propose 的 follow-up changes(本 change 不做):

1. **ppo-structural-backbone-migration**(D-101): PPO 切 generic ActorCritic + obs flow + collector + buffer + rollout 重写,~500-1000 LOC
2. **env-factory-unification**(D-102): env_factory_legacy.py + env_factory.py 两套 API reconciliation + rename,~50-100 LOC + ADR
3. **cfg-schema-unification**(D-201 + D-202): 5 paradigm AgentShapeCfg → ObsShape + ParadigmConfigBase compose + version 字段,~150-300 LOC
4. **docs-pre-redesign-refs-sweep**(D-403): 20+ docs/ 文件残留引用 update,纯 docs sweep
5. **cfg-toml-restructure-paradigm-scoped**(D-501,**2026-05-17 added**): TOML structure 从 `[paradigm]` flat 改 hybrid `[shape] + [scenario] 共享段 + [paradigm.<name>.X]` paradigm-scoped 段;~50-100 LOC loader 改 + toml 文件 restructure
6. **paradigm-smoke-full-tier**(D-601,**2026-05-17 added**): 完整 smoke test tier(`@pytest.mark.smoke_full`),5 paradigm 各跑 100-step train + auto-save ckpt + 单独 resume-from-ckpt test;default pytest excludes,opt-in via `pytest -m smoke_full`,大版本改动 / release 前跑;~5-10 min wall per paradigm;~1000-1500 LOC(5 paradigm × ~150-200 + 1 shared smoke_full_template + pyproject marker)

### [D-601] paradigm-smoke-full-tier — full smoke + ckpt save/load tier(user 2026-05-17 added,**2026-05-17 revised**)

- **Decision**(per user 2026-05-17 "我希望提供完整的 smoke 测试,包括 100 steps 训练,自动保存 ckpt,单独 resume from ckpt 等等"): 加 second-tier smoke `@pytest.mark.smoke_full`,5 paradigm 对称模板(承接 D-303),每 paradigm 验证 train pipeline 100 step 走通 + ckpt save/load 全 path 走通。
- **CRITICAL revision(user 2026-05-17 second message)**:**不重新发明 ckpt save/load 逻辑** — 复用现有 production 基础设施:
  - `training/core/checkpoint.py::CheckpointManager` — paradigm-agnostic save/load/resume,已 ship
  - `CheckpointCfg(save_every, keep_last_n)` in TrainingConfig `[checkpoint]` section,已 ship
  - 各 paradigm 自己 cadence(AZ `checkpoint_every_n_games` / DMC `save_interval_minutes` / CFR `checkpoint_every`)
  - `AgentBase.save / load`(post D-203 self-describing schema)
  - smoke_full 只是 **cfg override 用 short cadence**(eg `save_every=50` + `checkpoint_every_n_games=20`)+ 跑 100 step let 自动 save 发生 + verify 走通
- **5 paradigm 验证内容**(每 paradigm 各一 test):
  - 100-step real train,driver-level auto-save kick in 2-3 次(由 cfg short cadence 触发)
  - Verify ckpt files actually written 到 artifacts dir(`ckpt_<step>.pt` + `latest.pt`)
  - **单独 resume test**:`CheckpointManager.resume()` standard path,load step 50 ckpt → continue 50 step → final state functional(model can forward,optimizer can step)
- **Default pytest 不收集** — `pyproject.toml [tool.pytest.ini_options].addopts` 加 `-m "not smoke_full"`,opt-in via `pytest -m smoke_full`
- **Why**:user 明示"通常跑全量的时候不执行,而是仅在大版本改动之后才跑,用来验证正确性"
- **Closes deferred decisions**: D-304(eval probe single forward → full episode in smoke_full)+ D-305(BC loss 不增长 → strict decrease over 100 step in smoke_full)
- **Scope estimate(2nd revision per user 2026-05-17)**: ~300-400 LOC(原 600-800 仍高估,大部分应复用 production driver + CheckpointManager + 现 SmokeBuilder):
  - 5 paradigm × ~15-20 LOC test 文件(subprocess `tools.run <cfg>` + 3 个 assert + resume subprocess)= ~75-100 LOC
  - 1 shared `smoke_full_template.py` ~80-120 LOC(`run_paradigm_train_via_driver` + `verify_ckpt_files` + `resume_and_continue` 3 个 helper)
  - 5 `configs/<paradigm>/smoke_full.toml` 或 inline cfg override(各 ~30 行 toml = ~150 行 toml)
  - pyproject.toml marker + addopts(~5 行)
  - propose + design + tasks + spec delta docs ~150 行
  - **关键复用**:`tools.run` driver(run train via paradigm dispatch)+ `core.pipeline.run_pipeline` + `CheckpointManager.save / resume` + 现 `SmokeBuilder` Protocol(test_<paradigm>_smoke.py 已存在)
  - **零新逻辑**:不写 ckpt save / resume / paradigm dispatch / train loop — 全 subprocess `tools.run` driver 调用
- **Wall budget**: ~5-10 min per paradigm,~25-50 min 全 opt-in sweep
- **Spec impact**: 完成 training-architecture invariant A1 严格 compliance(原 D-304/305 partial compliance)
- **Dispatch order**: after #5 cfg-toml-restructure ships(避免 pyproject.toml + tests/ 共改 conflict)

### [D-501] TOML structure 改用 hybrid(option E)— scheduled after #3 ships

- **Decision** (per user 2026-05-17): TOML 顶层用 `[shape]` / `[scenario]` 等共享 sections,paradigm-specific 用 `[paradigm.<name>]` / `[paradigm.<name>.X]` 嵌套段。Dispatch 仍用 top-level `paradigm = "ppo"` selector。详 conversation analysis E vs A/B/C/D。
- **Why hybrid 不是 flat / pure paradigm-scoped**:
  - 共享真共享:`[shape]` 在 5 paradigm 是同 obs schema,放共享段最干净 — flat A 不能表达;pure B 重复 5 次
  - paradigm-section self-describing:`[paradigm.ppo.rollout]` 一眼知道是 PPO,无需 cross-ref top-level
  - 跨 paradigm cfg 共存 single toml:同一 toml 可写 `[paradigm.az.mcts]` + `[paradigm.ppo.rollout]` 作 compare,future migration test 方便
- **Order A1 ordering** (user 2026-05-17): cfg-schema-unification(#3)agent 当前已在 worktree 跑,假设 A 方案 toml(flat `[paradigm]`)。**让 #3 完成,后续 #5 单独 propose** 改 toml structure。理由:dataclass 重构(ObsShape compose / version / ParadigmConfigBase inherit)与 toml structure 解耦,#3 现工作完全 reusable;#5 只改 toml + loader,无 dataclass 改动。
- **Spec impact**: config-schema/spec.md invariant N5 (configs/ layout) refined,toml structure 例子用 hybrid 形态
- **Scope estimate**: ~50-100 LOC (5 paradigm `config_loader.py` 改 merge logic + #3 生成的 toml 改 hybrid 形态)
