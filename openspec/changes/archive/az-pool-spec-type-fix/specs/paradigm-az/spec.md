---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-az
---

# Spec delta — paradigm-az(A5 collector pool spec construction)

post `paradigm-smoke-full-tier`(#6)D-601 baseline 5 paradigm 触发后 SF-105
暴露 AZ smoke_full SKIP 根因:3 处 collector/policy 工厂 site 把
`resolve_pool_refs()` 的 dict return 直接当作 `CardPoolSpec` 用,运行时
`AttributeError: 'dict' object has no attribute 'sample_opponent_deck'`。
本 delta 加 A5.4 SHALL invariant 治理 pool spec construction discipline。

## ADD

### A-A5-4: Pool spec single-point construction discipline

加入 paradigm-az/spec.md §3.A5(Collector)末尾,编号 **A5.4**(延续
A5.1-A5.3 = 现 15 invariants):

```markdown
15. **A5.4** AZ paradigm 内任何持有 `card_pool_spec` 字段的 site SHALL
    construct via `make_pool_spec(scenario, resolve_pool_refs(scenario))`
    (`training/paradigms/az/pool_spec.py`)。SHALL NOT 把
    `resolve_pool_refs()` 的 dict return 直接 assign 给 `card_pool_spec`
    或传给 `sample_hidden_state` / `mcts_search` 等下游 — 后者 expects
    `determinize.CardPoolSpec` protocol(`.sample_opponent_deck(rng, pub)`
    method),dict 不 conform → 运行时 AttributeError。
    
    3 个 caller site SHALL share 同一 construction discipline:
    - `AZSelfPlayCollector.__init__`(`collector.py`)
    - `_az_build_policy`(`collector.py`,async actor 工厂)
    - `AZParadigm.make_episode_policy`(`paradigm.py`)
    
    与 `inference_worker.py` 已 proven pattern 一致。`make_pool_spec()`
    内 `disjoint_teams=True` → `PerOpponentPool`,else → `SharedFixedPool`,
    paradigm 内 caller SHALL NOT 直接 import 这两个 class —
    `make_pool_spec` 是 single entry point。
```

## Status Revised entry

`paradigm-az/spec.md` §6 Status 加:

```markdown
- **Revised**:2026-05-17(`az-pool-spec-type-fix` archive)— +A5.4
  pool spec single-point construction discipline(治理 3 处 site
  copy/paste 同 dict→spec anti-pattern)。
```

## Rationale

3 处 caller 独立 copy 同 anti-pattern,说明 implicit 约定不够;spec 层
SHALL 明确 single-point-of-construction discipline,future paradigm
contributor 加新 caller 时 grep spec 即可避免重蹈覆辙。`make_pool_spec()`
helper 已存在 + proven,本 invariant 只是把"必须用它"写入 spec。

## Cross-references

- 既有 A5.1-A5.3:Collector 算法层(selfplay / 双 side network / requires_network_in_collect)
- `determinize.CardPoolSpec` protocol(`training/paradigms/az/determinize.py:41-48`)
- `make_pool_spec()` helper(`training/paradigms/az/pool_spec.py:38-44`)
- 同 paradigm-az 实施 refs §4:`pool_spec.py` 在列(line 127)
