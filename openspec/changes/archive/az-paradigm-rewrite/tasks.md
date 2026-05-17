# AZ paradigm rewrite — tasks

5 phase 实施。**严格按顺序**(Phase 4 r009 regression test gate 必过才进 Phase 5)。

## Phase 1 — adapter rewrite safe parts(无 production risk)

预估 ~500 LOC / 1-2 days / **Low risk**

- [x] T1.1 `paradigms/az/config.py` rewrite — inline legacy/config.py AZConfig 必要部分到 AZParadigmConfig,删 wrap
- [x] T1.2 `paradigms/az/loss.py` rewrite — 切到 core/network/legacy/loss.az_losses(P5-F mv),adapter 不直接 import legacy.az
- [x] T1.3 `paradigms/az/network.py` 部分 rewrite — basic head 组合直接 core/network/{encoder,heads,actor_critic};**保留 Agent class 引用** Phase 2 处理
- [x] T1.4 verify:`pytest -n 4 training/tests/test_az_paradigm.py` 34 test 全 pass
- [x] T1.5 commit

> **Phase 1 status (2026-05-16)**: COMPLETE
> Shipped in commits `ead430f` (T1.1-T1.5 main) + `e779c21` (F401 + Phase 2 seam lock test) + `a61ce7b` (SKILL.md dispatch table). T1.4 GATE 34/34 + 19 new Phase 1 tests = 53/53 pass. **Resume from Phase 2 T2.1**.

## Phase 2 — consolidate 核心 logic(中等 risk)

预估 ~2000 LOC / 3-5 days / **Medium risk**

将 legacy 核心 logic 提升到 adapter 顶层:

- [x] T2.1 `paradigms/az/mcts.py` — consolidate from `legacy/mcts/*.py`(1074 LOC)to adapter top-level;subdir `mcts/` if 拆 subtopic
- [x] T2.2 `paradigms/az/determinize.py` — mv from `legacy/determinize.py`(11 refs 全部 sync)
- [x] T2.3 `paradigms/az/selfplay.py` — mv from `legacy/selfplay.py`(play_self_game canonical impl,6 refs sync)
- [x] T2.4 `paradigms/az/arena.py` — mv from `legacy/arena.py`(1 ref:test_arena)
- [x] T2.5 `paradigms/az/buffer.py` rewrite — inline `legacy/buffer.ReplayBuffer`(rich obs schema + static dedup)
- [x] T2.6 `paradigms/az/network.py` complete rewrite — **inline AZAgent class**(static_obs cache + game_start/end lifecycle);**保 r009 ckpt format 兼容**
- [x] T2.7 `paradigms/az/pool_spec.py` — mv from `legacy/pool_spec.py`(ADR-0011 pool spec resolution)
- [x] T2.8 `paradigms/az/train_az.py` — mv from `legacy/train_az.py`(production training loop;5 refs)
- [x] T2.9 `paradigms/az/inference.py` 或 `paradigms/az/inference/` — consolidate `legacy/inference_pool.py + inference_worker.py`
- [x] T2.10 keep Go ctypes binding:`paradigms/az/mcts_go.py + mcts_go_bindings.py`(mv from legacy)
- [x] T2.11 verify:adapter test pass + paradigms/az/ 自足(grep `from training.paradigms.az.legacy` in adapter = 0)
- [x] T2.12 commit(可分多 commit)

> **Phase 2 status (2026-05-16)**: COMPLETE
> Shipped across the Phase 2 ζ chain (T2.1-T2.12) — MCTS / determinize /
> selfplay / arena / buffer / network (AZAgent inline) / pool_spec /
> train_az / inference (pool + worker) / mcts_go bindings 全部 mv 到
> adapter top-level;`grep from training.paradigms.az.legacy
> training/paradigms/az/` 0 hit;test_az_paradigm.py 34/34。

## Phase 3 — update external refs(高 risk,scope 大)

预估 ~1000 LOC / 2-3 days / **High risk**(scope 跨 tools/core/tests)

### 3a. core/ refs(production)

- [x] T3a.1 `core/matchup/loaders.py` line 181-182 — `from training.paradigms.az.legacy.network.agent import Agent` → adapter path
- [x] T3a.2 `core/inference/server_loop/loop.py` — adapter path
- [x] T3a.3 verify:`pytest test_core_eval_baselines.py + test_matchup.py + test_inference_server.py` pass

### 3b. 11 active tools

- [x] T3b.1-T3b.11 each:tools/debug/diag_*.py(6)+ tools/probe/probe_numeric_*.py(2)+ tools/profile/profile_*.py(2)+ tools/bench/bench_rollout.py(1) — import path update
- [x] T3b.12 verify:smoke run 至少 3 个 active diag tool(user 可手动)

### 3c. 20+ tests

- [x] T3c.1 batch update test_*.py 内 `from training.paradigms.az.legacy.X` → adapter path
  - test_mcts.py / test_selfplay.py / test_buffer.py / test_train.py / test_arena.py / test_determinize.py / test_dice_posterior.py / test_inference_server.py / test_mcts_go.py / test_parallel_inference.py / test_parallel_pool_deadlock.py / test_per_opponent_pool.py / test_rollout_mixing.py / test_actor_critic_mirror.py / test_network_az_*.py / test_config_loader.py / test_eval_service_*.py / test_train_az.py / test_matchup.py / test_scenario_sampling.py
- [x] T3c.2 verify:`pytest -n 4 training/tests/ -q` baseline 不增加 fail count(8 pre-existing fail 不变)

> **T3c status (2026-05-16)**: PARTIAL (10/20+ production tests). Shipped 10
> NON-phase2-path production tests (test_actor_critic_mirror, test_arena,
> test_buffer, test_config_loader, test_core_eval_baselines,
> test_eval_service_{errors,matchup,schema}, test_inference_server,
> test_matchup) — all switched legacy.* → adapter; verified with new
> `test_production_tests_az_refs_phase3c.py` AST guard (10 + 1 negative
> counter-test = 11 pass). Phase 1 gate 34/34. Inference_server sandbox-mode
> 3 pre-existing fails unchanged (torch.Tensor pickle in sandbox);
> non-sandbox 5/5 pass. Full training/tests -q (excl. slow CFR convergence)
> = 833/833. Phase 2 path tests (`test_az_*phase2_path.py`) intentionally
> KEEP legacy.* as negative assertions (mv'd modules should raise
> ImportError); excluded from scan via explicit allowlist. Remaining ~10
> tests (test_mcts, test_selfplay, test_train, test_determinize,
> test_dice_posterior, test_mcts_go, test_parallel_inference,
> test_parallel_pool_deadlock, test_per_opponent_pool, test_rollout_mixing,
> test_network_az_*, test_train_az, test_scenario_sampling) deferred to a
> follow-up T3c.3 — outside the current batch scope. Also inlined
> `paradigms/az/config_loader.py` from legacy/ to enable test_config_loader's
> import switch (extends Phase 2 ζ inline pattern; 95 LOC).

### 3d. archived + docs

- [x] T3d.1 `tools/_archived/launch_config.py` 同步 import(若不删除)
- [x] T3d.2 stale `from training.paradigms.az.legacy` in openspec/ docs 同步(若有,排除 archived change)
- [x] T3d.3 verify:`grep -rln "training\.paradigms\.az\.legacy" --include="*.py" --include="*.md" .` 应只剩 archived(`5_history/` / `changes/archive/`)
- [x] T3d.4 commit(整 phase 3 单 commit 或拆 3a/3b/3c/3d 4 commits)

> **Phase 3 status (2026-05-16)**: COMPLETE
> 3a core/ refs + 3b 11 active tools(commits `389364f` + adjacent)+ 3c
> 20+ tests (`5ba9a3a` + `2a08de3`) + 3d archived/docs sweep。Final grep
> verify:`from training.paradigms.az.legacy` 仅出现在 changes/archive/
> + 5_history/(预期保留)。

## Phase 4 — r009 production regression test(gate)

**必过 gate**!失败 → rollback 全部 rewrite。

预估 ~半天 / **Critical**

- [x] T4.1 准备 r009 ckpt:`artifacts/202604270918_r009_bc_pretrain_stage3/epoch_3.pt`(production fallback)
- [x] T4.2 跑 gauntlet via `core/matchup/loaders.py`(更新后 path)加载 r009 ckpt
- [x] T4.3 baselines:F1-D2 / F1-D3 / random / mcts_pure_200 n=16(同 ADR-0009 测试)
- [x] T4.4 verify:r009 vs F1-D2 = 0.75 ± noise(per ADR-0009 钦定)
- [x] T4.5 若失败:rollback Phase 1-3,标 BLOCKED,报告失败位置(static_obs cache mismatch / Agent lifecycle 异常 / 数值 drift)
- [x] T4.6 若成功:commit gate-passing snapshot ref(可选)

> **Phase 4 status (2026-05-16)**: COMPLETE (reframed — per user)
> Per implementer + user reframe:full r009 production-gauntlet rerun is
> not the gating criterion here;instead the **adapter-path e2e smoke
> via `core/matchup/loaders.py`** (commit `2fc5678`) is the regression
> gate that proves the ckpt-load signature unbroken after Phase 1-3
> consolidation。Smoke pass → Phase 5 git rm 解锁。

## Phase 5 — git rm legacy + final cleanup

预估 ~半天 / **Low risk**(若 Phase 4 过)

- [x] T5.1 `git rm -r training/paradigms/az/legacy/`(31 files / 3680 LOC)
- [x] T5.2 `git rm tools/_archived/launch_config.py`(若 Phase 3d 切换 OK + 已无引用)
- [x] T5.3 update `paradigms/az/__init__.py` final cleanup
- [x] T5.4 verify:全 pytest pass + ruff + line + index hooks 全过
- [x] T5.5 update `docs/paradigms/az/README.md` 反映 retire 完成
- [x] T5.6 update `openspec/specs/paradigm-az/spec.md` 实施引用 path
- [x] T5.7 final commit:
  ```
  training/paradigms/az: legacy/ retire complete (FU-W4-AZ-rewrite)
  ```

> **Phase 5 status (2026-05-16)**: COMPLETE
> Shipped in commit `d305a10`(`training/paradigms/az: Phase 5 git rm
> legacy/ + final cleanup (AZ-rewrite-phase5)`). Removed 12 final legacy
> files;adapter 完全自足;spec delta(paradigm-az adapter paths)同
> commit merge 进 `openspec/specs/paradigm-az/spec.md`(Step 2 已在
> Phase 5 完成,Phase 6 archive 不再带 specs/ delta)。

## Phase 6 — archive this change(完成后)

- [x] T6.1 `/opsx:archive az-paradigm-rewrite` 5 步 SOP
- [x] T6.2 spec delta merge to `openspec/specs/paradigm-az/spec.md`
- [x] T6.3 design 摘要化(留 ≤200 行 retrospective)
- [x] T6.4 `git mv changes/az-paradigm-rewrite/ → changes/archive/az-paradigm-rewrite/`

> **Phase 6 status (2026-05-16)**: COMPLETE
> 走 `tools/_meta/openspec_archive.py`(#10 自动化)Step 1/4/5;
> Step 2 spec delta 早在 Phase 5 commit `d305a10` 合入
> `openspec/specs/paradigm-az/spec.md`(本 change 无 `specs/` 子目录,
> tool 自动跳过 Step 2 gate);Step 3 行数 check_line_limits delegate;
> Step 4 design.md 加 `## Verdict + What we built + Tradeoffs revisited +
> Surprises + Spec delta summary` 5 段(原始 158 行设计描述保留,顶
> 部 retrospective 块新增 ≤ 50 行 — 合计 ≤200);Step 5 `git mv` 由
> tool 执行,archive commit 由 tool 创建。

## 新 session resume instructions

新 session 起来时:
1. 读 `openspec/project.md` + `docs/0_status/README.md`(项目状态)
2. 读本 change folder 全部 3 files(proposal / design / tasks)
3. 读 archived `unified-training-pipeline` change 内 5 paradigm 历史(参考 DMC / PPO retire 模式)
4. 读 `docs/paradigms/az/`(architecture 演化 + r009 / r010-012 数据点)
5. Verify 当前 `paradigms/az/legacy/` 状态(可能与 freeze point 不同,若 user 在 session 间做了 manual 改动)
6. 从 Phase 1 开始,subagent driven dev 模式(per `superpowers:subagent-driven-development` skill)
7. **Phase 4 r009 regression test 是 hard gate**,失败必须 rollback + 评估是否继续
