---
last_updated: 2026-05-17
status: ARCHIVE
schema_version: 0
change_id: paradigm-smoke-full-tier
---

# Risks & mitigations — smoke_full tier rollout

## R1:tools.run 子进程慢启动

- **现象**:Python startup + torch import ~1-2s per invoke;1 paradigm
  smoke_full = 2 subprocess(train + resume)= ~3-4s overhead
- **缓解**:在 5-10min budget 内 acceptable;5 paradigm full sweep
  ~40 min 总,overhead 20s

## R2:smoke_full 8 min wall budget 不足以达 100 step + 2 ckpt save

- **缓解**:per paradigm 实测调整 termination 字段;target 是"≥ 100 step
  train + ≥ 2 ckpt 写"而非死板 100 step。AZ MCTS 慢,smoke_full 用
  `n_rollouts=2 / total_games=20`(每 game ~10 step → 200 step total)

## R3:pre-existing paradigm bug 阻塞 smoke_full

- **现象**:CFR `max_game_steps=30` 偏紧导致 traversal raise;AZ
  `card_pool_spec` dict 类型 vs `CardPoolSpec` 不匹配;PPO scenario
  `card_pool=None` 但 `_rollout.py:130` 用 `list()` wrap;BC 缺
  NPZ dataset 无法 load
- **缓解**:本 change scope 不修这些 paradigm bug。受影响 paradigm 的
  smoke_full test 用 `pytest.skip(reason="blocked by <bug>: see DECISIONS")`
  + DECISIONS 列出 follow-up changes 需修哪些。DMC 是唯一现状跑通的
- **Spec impact**:invariant A1.6 表述"smoke_full applies to all
  paradigms whose `tools.run <cfg>` path is functional";paradigm
  blocked → skip,不算 spec violation。后续 paradigm 修复后,通过
  remove `pytest.skip` 来 enable

## R4:resume 后 ckpt 数没增长(falsy assertion)

- **现象**:某些 paradigm resume 后立刻 terminate(若 ckpt 已 = terminus),
  无新 ckpt 写
- **缓解**:smoke_full toml 把 terminus 设得 > 第一个 ckpt 的 state.step
  (eg `save_every=30 + total_games=60`,第一 ckpt at step 30,resume
  跑到 step 60 + 终局 save)
- **Fallback**:assert 改为"resume run completes + latest.pt mtime
  newer than original",functional verify
