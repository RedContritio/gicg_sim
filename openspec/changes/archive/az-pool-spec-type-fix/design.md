# az-pool-spec-type-fix — Design Retrospective

> Archive-time retrospective(≤ 200 lines per archive-workflow.md SOP)。
> 轻量 follow-up(~25 LOC code + ~130 LOC docs),无 design/ subdir 必要。

## Verdict

**部分成功** — 3 处 `dict→CardPoolSpec` 违规全部 wrap 为
`make_pool_spec(scenario, resolve_pool_refs(scenario))`,spec 层 +A5.4
single-point construction discipline 治理 future copy/paste 风险。Baseline
verify 暴露 sequential blocker(`AZNetwork.game_start` drop return value)
bundled 修(per ppo-cfg-shape-alignment T2 bundled fix 先例)。

smoke_full **train-phase**(A1.6.1+.2)post 本 change ship PASS(subprocess
wall 25.2s,远低于 SF-104 15min cap;30 ckpts + latest.pt + metrics.jsonl
全 OK);但 **resume-phase**(A1.6.3)暴露第三个 pre-existing deeper AZ
ckpt-resume optimizer state shape mismatch bug:`RuntimeError: output with
shape [1, 64] doesn't match the broadcast shape [1832, 64]` at
`adam.py:547 _single_tensor_adam`。OUT of "wrap with make_pool_spec" scope
→ test keeps `pytest.skip` 但 reason 切到新 follow-up
**`az-resume-shape-fix`**(2026-05-17 queued)。

实施单 session / 6 task all done / `pytest test_az_*.py + test_determinize.py`
without smoke_full marker:72/72 baseline pass / full sweep `pytest -n 4
training/tests/` 995 passed / 3 skipped / 0 failed(3 skipped 现仍包括 4
paradigm smoke_full not collected by default per #6 marker design;AZ skip
reason 已切到 `az-resume-shape-fix`)。

## What we built

- `training/paradigms/az/collector.py`:
  - line 19 import:+`make_pool_spec`
  - line 72-76(`AZSelfPlayCollector.__init__`):wrap + A5.4 comment
  - line 168-178(`_az_build_policy` async actor 工厂):wrap + A5.4 comment
- `training/paradigms/az/paradigm.py`:
  - line 131 import:+`make_pool_spec`
  - line 152-153(`AZParadigm.make_episode_policy`):wrap + A5.4 comment
- `training/paradigms/az/network.py`(bundled fix per smoke_full baseline verify):
  - line 280-287(`AZNetwork.game_start`):add `return` + annotate `-> dict`
    + 内联 bundle 理由(原来 wrapper drop `self._agent.game_start()` 的 dict
    return,annotated `-> None`,但 selfplay → buffer.push 期望 dict
    → `AttributeError: 'NoneType' object has no attribute 'keys'`)
- `training/tests/test_az_smoke_full.py`:
  - 原计划 unskip → 改 rewrite skip reason:keep `@pytest.mark.skip` 但
    reason 切到新 follow-up `az-resume-shape-fix`;docstring 详记 partial
    unblock 现状(train PASS / resume fail)+ 新 follow-up pointer + skip
    解除条件
- `openspec/specs/paradigm-az/spec.md`:
  - ADD A5.4(invariant 15)pool spec single-point construction discipline
  - Status section +Revised entry(2026-05-17 `az-pool-spec-type-fix` archive)

## Tradeoffs revisited

- **Option A(wrap in caller)vs Option B(改 helper return type)vs
  Option C(inline class construction)**:预期 A / 实际 A ✓ —
  改 helper return type(B)会破 `inference_worker.py:87-88` 已 proven
  pattern(它依赖 `pool_by_player` dict 做 per-actor lookup);inline class
  (C)让 collector 感知 `disjoint_teams` cfg + 重新发明 helper 内逻辑,无
  收益。Wrap pattern 与 `inference_worker.py` 完全一致,4 个 caller 行为
  对称。
- **spec invariant 必要性**:预期 加 SHALL / 实际 加 SHALL ✓ —
  3 处 caller 独立 copy 同 anti-pattern 说明 implicit 约定不够,spec 层
  SHALL 写明 single entry point + 显式列 3 个 caller site + 禁止直接 import
  `PerOpponentPool` / `SharedFixedPool`。Future paradigm contributor 加新
  caller 时 grep spec 即可避免重蹈覆辙。
- **bundled fix `AZNetwork.game_start` return**:预期 独立 follow-up /
  实际 bundled ✓ — 同一 smoke_full 启用 path 的 sequential blocker,scope
  1 LOC(加 `return`),独立 change 开销(propose/tasks/archive)远大于
  bundle 收益。沿用 ppo-cfg-shape-alignment T2 bundled fix 先例(也是
  smoke_full baseline verify 暴露的 false positive bundle)。
- **不改 `resolve_pool_refs()` 自身**:预期 + 实际 ✓ — helper 责任纯
  (return dict),construction 在 caller。SRP + 与 `inference_worker.py`
  pattern 一致 + 0 API breakage,无任何 caller 因 helper signature 变化
  需改动。

## Surprises

- **smoke_full 触发后 sequential blocker `AZNetwork.game_start` drop return**:
  Phase 1 propose 时只识别了 `_card_pool_spec` 一个 bug;fix 后 smoke_full
  subprocess 立即触发下一个,buffer.push 报 `'NoneType' has no attribute
  'keys'`。Root cause:`AgentBase.game_start` 返回 dict(`agent_base.py:267-277`),
  但 `AZNetwork` wrapper(`network.py:280-281`)忘 `return`,annotation 还
  错标 `-> None`。这是同一 smoke_full 启用 path 的 pre-existing 第二 bug,
  与 dict→spec bug 独立 root cause,但 trigger path 相同,bundle 修。
- **smoke_full train-phase wall time 仅 25.2s**:cfg 设 30 game / 100 step /
  n_rollouts=2,实际 subprocess wall 25.2s(远低于 SF-104 15min cap)。
  SF-105 估的 "5-15min/paradigm" 在 AZ-cheap-cfg 下不成立 — n_rollouts=2
  + 100 step + serial 模式让单 game 1-2s 即结束,30 game ~25-30s。
- **resume-phase 暴露 deeper 第三 bug**:Phase 1 propose 时只识别 dict→spec
  bug;train-phase 启用 + game_start return bundled fix 后,resume-phase
  subprocess 触发 `RuntimeError: output with shape [1, 64] doesn't match
  the broadcast shape [1832, 64]` at adam.py:547 `_single_tensor_adam`。
  这是第三个 pre-existing 独立 root cause bug — 某 parameter / buffer 在
  train iter 间 shape 变化(可能是动态 card_pool 相关 tensor 或 lazy-init
  embedding),Adam optimizer state load 按旧 shape → addcdiv_ broadcast fail。
  与本 change dict→spec 修法独立,scope 不 bundle(需独立诊断 parameter
  origin + 决定 max-size init vs re-init optimizer state vs tolerate via
  per-param state rebuild)→ new follow-up id `az-resume-shape-fix`。
- **inference_worker.py 已正确,3 个 collector/policy site 独立违规**:
  说明 implicit 约定的脆弱性 — 同 paradigm module 内一处正确不足以阻止
  其他 caller 重复 anti-pattern。spec invariant A5.4 显式列 3 个 caller +
  禁直接 import,是 future-proof guardrail。

## Spec delta summary

本 change 修订 **1 个 capability spec**(paradigm-az):

- **paradigm-az/spec.md §3.A5(Collector)**:
  - **ADD A-A5-4**(invariant 15):`card_pool_spec` 字段 SHALL construct
    via `make_pool_spec(scenario, resolve_pool_refs(scenario))`,SHALL NOT
    直接 assign dict;列 3 个 caller site;single entry point 约束
    (paradigm caller SHALL NOT 直接 import `PerOpponentPool` / `SharedFixedPool`)
  - **Status +Revised**:2026-05-17 entry(本 change archive)

合并后行数:158 → 174(+16),仍 << 300 阈值。

## DECISIONS index

无独立 DECISIONS 文件(轻量 follow-up,所有决策 inline 本 retrospective):

- [D-API]:Option A wrap in caller(reject B/C)— **SELECTED**
- [D-SCOPE]:bundled `AZNetwork.game_start` fix in same change — **SELECTED**
  (per smoke_full sequential blocker + ppo-cfg-shape-alignment T2 先例)
- [D-SPEC]:spec invariant 加 single-point discipline + 显式列 3 caller —
  **SELECTED**(治理 future copy/paste)
- 不接 closure:`resolve_pool_refs()` return 类型不改(B/C reject 理由)

## Cross-references

- 原 blocker change:`openspec/changes/archive/paradigm-smoke-full-tier/`
  DECISIONS.md SF-105(此 follow-up change id 由 SF-105 创建)
- bundled fix 先例:`openspec/changes/archive/ppo-cfg-shape-alignment/`
  T2(smoke_full baseline verify bundled false-positive fixes)
- helper proven pattern:`training/paradigms/az/inference_worker.py:87-88`
- 受影响 spec:`openspec/specs/paradigm-az/spec.md` A5.4(15 invariants 后)
