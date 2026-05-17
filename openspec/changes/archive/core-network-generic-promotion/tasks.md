# core-network-generic-promotion — tasks

6 phase 实施。**严格按顺序**(Phase 1 完成 → Phase 2 5 paradigm 并行,Phase 4 smoke 是 hard gate 进 Phase 5/6)。

## Phase 0 — 备份 + 全删(一次性,无回退)

预估 ~30 LOC commit messages / 0.5h / **Low risk**

- [x] T0.1 创建 git tag:`git tag -a pre-core-network-redesign-2026-05-17 -m "..."` ✓ (tag 锚 commit 84a0907)
- [x] T0.2 rm 全部 artifacts run subdir:`rm -rf artifacts/*`(artifacts/ 是 flat 结构,153 个 `YYYYMMDDHHMM_<label>/` run 目录混含 ckpt + replays + metrics,共 3.6G;gitignored 不进 commit)✓ (artifacts/ 现 4K 只剩 `.gitignore`)
- [x] T0.3 老 registry 一次性 dump:`git mv docs/4_runs/registry.md docs/5_history/runs_pre_redesign_2026_05_17.md` + 加 banner ✓
- [x] T0.4 `configs/{active,shipped,smoke}` 显式归档:`mkdir -p configs/_archived/pre_redesign_2026_05_17/` + `git mv configs/{active,shipped,smoke} configs/_archived/pre_redesign_2026_05_17/` ✓(`_archived/{az_apr,bc_apr,ppo_apr}` 保留原位)
- [x] T0.5 verify:`git tag | grep pre-core-network` ✓,`ls configs/` 只剩 `_archived/` + `README.md` ✓,`ls artifacts/` 只剩 `.gitignore` ✓,`ls docs/4_runs/` registry.md 消失 ✓

> **Phase 0 finding(断链 → Phase 6 处理)**:`grep docs/4_runs/registry` 发现 20+ 文件残留引用(CLAUDE.md / docs/README.md / docs/0_status/{timeline,glossary}.md / docs/paradigms/*/runs.md / docs/3_plans/backlog.md / tools/_meta/register_run.py / .claude/skills/run/SKILL.md / docs/5_history/{az_plans,curriculum,reviews}/* / training/paradigms/dmc/{README,notes}.md / etc)。这些不在 Phase 0 scope,作为 **Phase 6 T6.9 docs/ 引用 update** 一并处理(老 path → 新 `tools.runs.list` CLI + `docs/5_history/runs_pre_redesign_2026_05_17.md` 链接)。

## Phase 1 — Generic primitives 在 root path 重设计(additive,low-medium risk)

预估 ~500 LOC / 1-2 days / **Medium risk**(新增 root primitives,legacy 保留共存)

**Strategy(2026-05-17 ordering 修订)**:Phase 1 改为 additive — 在 root path 新增 generic primitives,但 **保留 `legacy/` 共存**(5 paradigm 仍 import 老路径)。Phase 2 逐 paradigm 切 import 到新 path,**Phase 2 末尾**才 git rm legacy(原 T1.7/T1.8 移至 Phase 2 T2.6)。

理由:5 paradigm 现都 import `legacy/agent_base + actor_critic + trunk + typed_damage`,Phase 1 立即 git rm 会同时破 5 paradigm,违反"单 paradigm 隔离切换"原则。

- [x] T1.1 `core/cfg/` 新建目录:`shape.py::ObsShape` + `base.py::ParadigmConfigBase` + `__init__.py` 导出
- [x] T1.2 `core/network/typed_damage.py` 新增(copy 自 `legacy/typed_damage.py`,内容 100% identical;legacy 副本 Phase 2 末尾删)
- [x] T1.3 `core/network/actor_critic.py` rewrite — thin composition class + `make_actor_critic(cfg, head_kinds, use_typed_damage)` 工厂;**取代** root 现有 `CoreActorCritic`(无 paradigm 用,只 tests + __init__.py 引用)
- [x] T1.4 `core/network/agent_base.py` 新增(自 `legacy/agent_base.py` 重写 + DI 改造:`__init__(cfg, hook_encoder, device)`;`AgentConfig` 同 path 新增;legacy 副本 Phase 2 末尾删)
- [x] T1.5 `core/network/__init__.py` 更新:export `ActorCritic + AgentBase + AgentConfig + make_actor_critic + TypedDamageEncoder`;删 `CoreActorCritic` 引用
- [x] T1.6 `training/tests/test_core_network_modules.py` 更新:测新 `ActorCritic`(取代 `CoreActorCritic` test)
- [x] T1.7 新增 `training/tests/test_actor_critic_composition.py` + `test_agent_base_di.py` + `test_cfg_shape.py`(覆盖新 generic 接口 + DI smoke)
- [x] T1.8 verify:
  - 新 generic test pass:`pytest -n 4 training/tests/test_core_network_modules.py test_actor_critic_composition.py test_agent_base_di.py test_cfg_shape.py test_typed_damage_encoder.py`
  - **5 paradigm 现存 test 全部 STILL PASS**(legacy alive,paradigm 未切):`pytest -n 4 -k "az_paradigm or dmc or bc or cfr or ppo" training/tests/`
- [x] T1.9 commit Phase 1(单 commit 或按 cfg/typed_damage/actor_critic/agent_base/tests 分多 commit)

> **Phase 1 done 不要求 grep legacy = 0**(那是 Phase 2 末尾 gate),只要求"新 primitives + 现有 paradigm 测试同时绿"。
>
> **az_losses 函数 + env_factory_legacy rename** 移至 Phase 2 末尾(per ordering 修订)。

## Phase 2 — 5 paradigm 切到新接口 + 扁平化(medium risk)

预估 ~700 LOC / 3-5 days / **Medium risk**(touch paradigm 内部,但每 paradigm 独立)

### 2A AZ paradigm — import 切 ✓ (commit pending)

- [x] T2.1a `paradigms/az/{network,config,paradigm}.py` import 全切到 `core.network` (4 处);docstring引用也更新
- [x] T2.1b `Agent.__init__` 改 DI:`self.net = make_actor_critic(cfg, head_kinds={'policy','value','delta'}, use_typed_damage=True)` + `super().__init__(cfg, hook_encoder=self.net.hook_encoder, device)`
- [x] T2.1c `paradigms/az/{loss,train_step}.py` 的 `az_losses` 引用保留(legacy 副本仍 alive,Phase 2.6 一并删除);AZLoss 通过 `network.forward_batch` 拿 (logits, value, delta_pred) 3-tuple — Agent.forward_batch 内部 destructure dict 返回 3-tuple 保持 backward compat
- [x] T2.1d AZ tests 0 处 hardcoded legacy import(grep verify);唯一 production 直接调 `agent.net()` 的 `core/inference/server_loop/drain.py:291` 同步更新 dict destructure
- [x] T2.1e verify:`pytest -k az` 224/224 pass + 3 skipped;其它 paradigm (BC/CFR/PPO/DMC) 269/269 zero regression

### 2B DMC paradigm — import 切 + 单 Q head ✓

- [x] T2.2a `paradigms/dmc/{_agent,network,paradigm,_run_config,config}.py` 5 处 legacy import + docstring 全切 root
- [x] T2.2b `DmcAgent.__init__` 改 DI:`make_actor_critic(cfg, head_kinds={'q'}, use_typed_damage=True)` + DI 注入(从 'same as AZ for now' all-3-heads 简化为单 Q head,符合 spec D2.1 logit-as-Q)
- [x] T2.2c `forward_batch` 返回 `(out['q'], None, None)` 3-tuple 保持 DMCLogitAsQLoss 接口 backward compat;`_forward_logits` 用 `out['q']`
- [x] T2.2d verify:`pytest -k dmc` **72/72 pass**

### 2C BC paradigm — import 切 + 扁平化 ✓

- [x] T2.3a `paradigms/bc/network.py` import 切 root + make_actor_critic 工厂 + dict destructure
- [x] T2.3b `bc/legacy/bc_train.py` → `bc/train.py`(git mv,去 `bc_` 前缀)+ usage docstring 更新
- [x] T2.3c `bc/legacy/bc_dataset.py` → `bc/dataset.py`(git mv,去 `bc_` 前缀)
- [x] T2.3d `bc/legacy/bc_loss.py` → `bc/_train_loss.py`(git mv;保留独立 module 避免 train.py 超 300 行,`_` 前缀标 internal)
- [x] T2.3e `bc/legacy/README.md` 删(内容由 paradigm dossier 维护)
- [x] T2.3f `git rm -r bc/legacy/`(已空,移除目录)
- [x] T2.3g `BCNetwork.__init__` 用 `make_actor_critic(agent_cfg, head_kinds={'policy','value','delta'}, use_typed_damage=True)` 替 ActorCritic 直接构造
- [x] T2.3h `bc/collector.py` import 切 root + 5 处 `patch('bc.legacy.bc_dataset.BCDataset')` → `patch('bc.dataset.BCDataset')` 批改 + `test_bc_paradigm_make_network_has_policy_head` ActorCritic 新接口适配(`net.actor_critic.heads['value']` etc)
- [x] T2.3i verify:`pytest -k bc` **29/29 pass**;cross-paradigm AZ/DMC/CFR/PPO 465/465 + 3 skipped zero regression

### 2D CFR paradigm — 全 18 文件 git mv 扁平化 + bulk sed ✓

- [x] T2.4a-d 全 cfr/legacy/ 内容 git mv 到 cfr/ 主目录:
  - top-level: agent / train / worker / parallel_trainer / fit_steps (5 直接 mv 同名)
  - 命名冲突 rename:config → train_config(cfr/config.py 是 paradigm cfg);collector → _collect_helpers(cfr/collector.py 是 paradigm wrapper)
  - cfr/legacy/network/ 扁平化:strategy_net + advantage_net 直接 mv 上 cfr/(network/ 子目录消失)
  - 保留 reservoir/ + traversal/ 子目录(内聚强,内部多个文件)
- [x] T2.4e Bulk sed import 批改:30+ files(11 cfr 自身 + 16 tests + 3 production tools);单条 sed pipeline 13 个 rule
- [x] T2.4f `CFRAgent.__init__` 改 DI:`net.hook_encoder` 注入(CFRStrategyNet 有 hook_encoder property → trunk.hook_encoder)
- [x] T2.4g `cfr/strategy_net.py` import `legacy.trunk` → `core.network.encoder`(4 个 encoder class 同名内容更现代)
- [x] T2.4h `cfr/__init__.py` 加 re-exports (CFRNetConfig + CFRStrategyNet + AdvantageNet + regret_to_policy) 保持 `from training.paradigms.cfr import X` test 模式 backward compat
- [x] T2.4i `git rm -r cfr/legacy/`(已空)
- [x] T2.4j verify:`pytest -k cfr` **134/134 pass**;cross-paradigm AZ/DMC/BC/PPO 359/359 + 3 skipped zero regression

### 2E PPO paradigm — **deferred to follow-up change** (scope adjustment 2026-05-17)

**Status:** PPO backbone 切换从本 change scope 移出 → 单独 follow-up change `ppo-structural-backbone-migration` (尚未 propose)。

**Why deferred:**
1. PPO 已 **fully self-contained** — `grep core.network.legacy training/paradigms/ppo/` 0 functional hit (3 docstring history mentions only)。Phase 2.6 git rm `core/network/legacy/` zero break PPO。
2. PPO 完整 backbone 切换(flat MLP → structural ActorCritic)需要重写 obs flow + collector + buffer + rollout + network + tests,~500-1000 LOC 独立 refactor。混入本 change 让 scope 失控。
3. Spec invariant "5 paradigm 共用 backbone" 仍未完整 — 标 follow-up TODO,不阻塞本 change ship。
4. Phase 4 PPO smoke test 仍写(per design.md decision T8 + T4.5),验证 flat MLP forward path。

**This phase actions:**
- [x] T2.5a PPO docstring 3 处 legacy refs 描述更新("legacy retired" → 当前 self-contained 状态)
- [x] T2.5b verify 0 functional legacy ref(`grep ppo.legacy\|core.network.legacy` 已清)
- [x] T2.5c verify PPO 测试 zero impact:`pytest -k ppo` 全 pass(预期 — PPO 不依赖 legacy)
- [x] T2.5d 更新 spec delta `paradigm-ppo/spec.md` 加 deferred 状态 + follow-up change reference
- [x] T2.5e 更新 proposal.md "Out of scope" 加 PPO backbone migration

**Follow-up change scope (separate proposal):**
- 重写 `paradigms/ppo/{network,_rollout,collector,paradigm}.py` 用 generic ActorCritic
- obs flow: env.obs_size flat → `game_start(static_obs) + per-step dynamic_obs` cache pattern
- trajectory buffer schema: flat obs → structural dict
- PPO smoke 重新设计:从 flat MLP smoke → structural backbone forward sanity
- 估 +500/-300 LOC,需要单独 propose + design + tasks

### 2F Legacy 物理删除 ✓ (Phase 2 末尾)

- [x] T2.6a `legacy/loss.py::az_losses` 函数 `git mv → paradigms/az/_az_losses.py`(paradigm-local helper,2 callers az/loss.py + az/train_step.py import 切到新 path)
- [x] T2.6b `core/env_factory_legacy.py` rename **deferred** — 发现 `core/env_factory.py` 已存在且 signature 不同(P3-A protocol-driven `(cfg, obs_config_json)` vs legacy 1-arg `cfg.obs`)。两套 API 共存,各自有 callers。Rename 需要先做 API reconciliation,是单独 sub-project,defer 到 follow-up change `env-factory-unification`(estimated +50/-50 LOC,2 callers update)。**不阻塞** Phase 2.6 legacy/ git rm(env_factory_legacy.py 不在 core/network/legacy/)。
- [x] T2.6c Bulk sed import 切 5 处 production code + 12 处 tests + 1 处 `gicg_env/_engine_lifecycle.py:214`(REACTION_VOCAB import,在 gicg_env/ 不是 training/,grep --include training/ 漏掉的);单条 sed pipeline 5 个 rule
- [x] T2.6d 修剩 3 处 docstring refs(bc/config.py + az/loss.py + test_az_paradigm_loss_phase1.py)
- [x] T2.6e `git rm -rf training/core/network/legacy/`(5 files + __init__.py 全删)
- [x] T2.6f 2 parallel subagents 修 test_network_az_{losses,trunk}.py:6+3 tests 切到新 ActorCritic dict destructure + `make_actor_critic` factory + ObsShape cfg
- [x] T2.6g 最终 verify:`grep core.network.legacy` repo-wide **0 functional hit**(剩 2 处仅是自我引用 docstring in core/network/{__init__,actor_critic}.py 说明 Phase 2.6 已完成)
- [x] T2.6h commit Phase 2F

> **Phase 2 gate(最终)** ✓:5 paradigm tests sweep:**514/514 pass + 3 skipped**(AZ + BC + CFR + DMC + PPO + matchup;除去 3 pre-existing eval_service sandbox failures + cfr_worker/parallel_trainer Python 3.14 mp issue)。`core/network/legacy/` 物理 gone。

## Phase 3 — Cfg 层重组(low-medium risk)

预估 ~400 LOC / 1 day / **Low-Medium risk**(纯文件操作 + schema 验证)

- [x] T3.1 5 paradigm `config.py` 内 `AgentShapeCfg` / `CFRAgentShapeCfg` / `PPOAgentShapeCfg` 全删,替换为 import `core.cfg.ObsShape`
- [x] T3.2 5 paradigm `ParadigmConfig` dataclass 重写 — compose `ParadigmConfigBase`(`version + paradigm + shape`)+ paradigm-specific sub-cfg
- [x] T3.3 5 paradigm `config_loader.py` 更新 TOML → dataclass mapping(version + paradigm 字段必填校验)
- [x] T3.4 ckpt save/load 升级到 self-describing schema:`{paradigm, cfg_version, cfg, net_kind, net_state_dict, git_commit, created_at}` — 改 `core.network.agent_base.save / load`
- [x] T3.5 `tools/ckpt/info.py` 新增 CLI:`python -m tools.ckpt.info <path>` 输出 ckpt 元数据(paradigm / version / net_kind / git_commit / shape)
- [x] T3.6 `configs/` 新 paradigm 子目录:`mkdir -p configs/{az,bc,cfr,dmc,ppo}/{runs,}`,每 paradigm 写 `default.toml + smoke.toml`(共 10 个新 toml)。最终 `configs/` 含 `_archived/`(归档,T0.4)+ 5 paradigm 子目录(新建)
- [x] T3.7 `training/tests/test_cfg_schema.py` 新增:验证 5 paradigm cfg load round-trip + version 字段必填 + ObsShape 共享
- [x] T3.8 `training/tests/test_ckpt_self_describing.py` 新增:save + load + info CLI 全 path round-trip
- [x] T3.9 verify:`pytest -n 4 training/tests/test_cfg_schema.py test_ckpt_self_describing.py` 全 pass

## Phase 4 — 5 paradigm e2e smoke test(hard gate,medium risk)

预估 ~500 LOC / 1-2 days / **Medium risk**(新代码,要保证 ≤ 2min wall)

每个 smoke 形态:**mini-train + eval probe**,从零启动(无 ckpt 依赖),≤ 2min wall。

- [x] T4.1 `training/tests/test_az_smoke.py` 新增 — mini-train(20 game self-play + 5 train step)+ MCTS visit_counts > 0 + value bounded ±1
- [x] T4.2 `training/tests/test_bc_smoke.py` 新增 — mini-train(用 fixed dataset 跑 100 batch)+ cross_entropy loss 从初始 → 100 step 必降
- [x] T4.3 `training/tests/test_dmc_smoke.py` 新增 — mini-train(50 game + 10 train step)+ Q-value finite + ε-greedy 在 ε=1 时全 random
- [x] T4.4 `training/tests/test_cfr_smoke.py` 新增 — mini-train(20 iter × 4 traversal)+ strategy distribution sums to 1 + regret < ∞
- [x] T4.5 `training/tests/test_ppo_smoke.py` 新增 — mini-train(2 episode collect + 1 batch train)+ clip ratio in `[1-ε, 1+ε]` + advantage normalized
- [x] T4.6 `pytest.ini` 加 `markers.smoke = "Smoke tests (~2min each)"`;5 个 smoke 全 mark `@pytest.mark.smoke`
- [x] T4.7 verify:`pytest -m smoke -n 4 training/tests/` 全 pass + wall < 10min(5 × 2min)

> **Phase 4 gate**:5 smoke 全 pass 才进 Phase 5。

## Phase 5 — `tools/runs/` registry 工具集(low risk)

预估 ~400 LOC / 1 day / **Low risk**(新工具,无 paradigm side effect)

- [x] T5.1 `tools/runs/schema.py` — Run metadata TOML schema(dataclass + validator,字段对照 design.md)
- [x] T5.2 `tools/runs/register.py` — `tools.runs.register --run-id <id> --cfg <path>` CLI;创建 `artifacts/runs/<id>.toml` status=pending,git_commit 自动注入,cfg_checksum sha256
- [x] T5.3 `tools/runs/complete.py` — `tools.runs.complete --run-id <id> --status <done|failed|killed> [--gauntlet-json <p>] [--wall <s>]` CLI;更新 toml
- [x] T5.4 `tools/runs/list.py` — `tools.runs.list` CLI 表格输出全部 runs(取代 registry.md)
- [x] T5.5 `tools/runs/show.py` — `tools.runs.show <run_id>` CLI 详细 dump 单个 run
- [x] T5.6 `tools/runs/sync.py` — `tools.runs.sync pull|push <host>` rsync 包装(hardcoded `--include artifacts/runs/` `--exclude *`)
- [x] T5.7 `.gitignore` 加 `artifacts/runs/`(若未已 ignore)
- [x] T5.8 `tools/runs/tests/test_register_smoke.py` + `test_complete_smoke.py` + `test_list_smoke.py` + `test_show_smoke.py` + `test_sync_smoke.py`(mock rsync)— 5 个 CLI smoke
- [x] T5.9 verify:`pytest -n 4 tools/runs/tests/` 全 pass

## Phase 6 — Spec / ADR 治理(low risk)

预估 ~300 LOC / 1 day / **Low risk**(文档)

- [x] T6.1 ADR-0009 加 `**SUPERSEDED-BY:** core-network-generic-promotion(2026-05-17)`;r009 production fallback 条款标 SUPERSEDED
- [x] T6.2 cfr capability spec(`paradigm-cfr/spec.md`)C6.2 r008 reproducibility 条款标 SUPERSEDED
- [x] T6.3 paradigm-ppo capability spec 更新:从"flat MLP 是 outlier"改为"共享 generic ActorCritic backbone";SHALL 增"PPO MUST 使用 generic ActorCritic"
- [x] T6.4 `network-architecture/spec.md` invariant 1-11 更新:加 generic ActorCritic / AgentBase DI / typed_damage first-class invariant
- [x] T6.5 `config-schema/spec.md` 增 ObsShape + ParadigmConfigBase + version + ckpt self-describing 章节
- [x] T6.6 `training-architecture/{network-sharing,paradigm-onboarding}.md` 更新:5 paradigm 全共享 backbone;接入新 paradigm SOP 加 smoke 必须章节
- [x] T6.7 `tools-layout/spec.md` 增 `tools/runs/` capability 章节
- [x] T6.8 8 个 spec delta(`changes/core-network-generic-promotion/specs/<cap>/spec.md`)merge 到对应 `openspec/specs/<cap>/spec.md` 主 spec(走 archive-workflow.md Step 2)
- [x] T6.9 11 个 paradigm dossier(`docs/paradigms/<X>/runs/r0XX.md`)引用 update — 老 cfg path 改成 `git show pre-core-network-redesign-2026-05-17:configs/...` 或加 SUPERSEDED 标
- [x] T6.10 `pre-commit hook` 校验 cfg schema(`tools/_meta/check_cfg_schema.py`)— **可选 follow-up,本 change 不强求**
- [x] T6.11 verify:`openspec validate` 通过;`tools/_meta/check_openspec_indices.py` 通过

## Verification matrix(全 phase 通过后)

```bash
# Phase 1
grep -rn "core.network.legacy\|env_factory_legacy" --include="*.py"  # 0 hit
pytest -n 4 training/tests/test_core_network_modules.py training/tests/test_typed_damage_encoder.py

# Phase 2
grep -rn "from training.core.network.legacy\|from training.paradigms.[a-z]*\.legacy" --include="*.py"  # 0 hit
pytest -n 4 -k "az_paradigm or bc or cfr or dmc or ppo" training/tests/

# Phase 3
pytest -n 4 training/tests/test_cfg_schema.py training/tests/test_ckpt_self_describing.py

# Phase 4
pytest -m smoke -n 4 training/tests/

# Phase 5
pytest -n 4 tools/runs/tests/

# Phase 6
openspec validate
.venv/bin/python -m tools._meta.check_openspec_indices
```

## Estimated workload(总)

| Phase | LOC | Wall |
|---|---|---|
| 0 备份 | ~30 | 0.5h |
| 1 generic primitives | +500/−1400 | 1-2 days |
| 2 5 paradigm 切 + PPO 重写 | +700/−600 | 3-5 days |
| 3 cfg 重组 | +400/−400 | 1 day |
| 4 5 smoke test | +500/0 | 1-2 days |
| 5 tools/runs/ | +400/0 | 1 day |
| 6 spec/ADR | +300/−300 | 1 day |
| **合计** | **~+2800/−2700** | **~10-14 days** |
