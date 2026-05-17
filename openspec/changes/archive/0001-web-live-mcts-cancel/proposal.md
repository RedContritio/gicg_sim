# Web live MCTS search cancellation

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0001-web_live_mcts_cancel.md` at P1-T1)
**Original date:** 2026-04 (Phase-4 review era)
**Original status:** Proposed plan (option D default; option A upgrade path)
**Supersedes:** —
**Superseded by:** —

## Why

`web/backend/live_api.py::_auto_advance_agent` runs MCTS-backed AI turns synchronously in the WebSocket
handler. A 200-rollout search at d_model=64 takes ~30s, during which:

1. The WS handler is blocked — `await ws.receive_json()` can't run; client clicks (Restart, new opponent)
   queue in OS TCP buffer; tab appears frozen.
2. No cancellation — if the client disconnects mid-search, Python keeps running mcts_search to completion,
   burning CPU + holding ckpt memory.
3. Zero back-pressure — N=1000 rollouts ≈ 30s; UX cliff is abrupt.

Phase-4 review flagged this as "hard / not recommended" because cancellation requires coordinating Python
asyncio with a cgo-calling synchronous search loop. ADR records the plan in case the trade-off changes.

## What

Four approaches sorted by cost / blast radius:

- **A (worker process)** — `multiprocessing.Process` per WS session; `process.terminate()` for clean
  cancel. Reuses Phase-2 CFR worker pattern. Cost: 1-2 days. Cancel-safety: clean.
- **B (threaded + cancel flag)** — `asyncio.to_thread` + poll-flag inside `mcts_search`. Cost: 2-3 days.
  Cancel-safety: cooperative; needs hooks in every player type.
- **C (async search coroutine)** — refactor `mcts_search` to yield every K rollouts. Cost: ~1 week.
  Cancel-safety: clean but trades weeks of risk for marginal live-UX gains.
- **D (accept + cap)** — keep sync, expose UX affordance (spinner + budget cap n_simulations ≤ 100).
  Cost: 2 hours.

**Recommendation:** D as default. A as upgrade path if high-budget opponents ever become necessary in live
mode. Do NOT pursue B or C — B leaks cancel-hook responsibility across MCTS; C is a training-stack
refactor.

## Affected specs

n/a (operational decision for `web/backend/live_api.py`; P1+ web-live spec backfill if needed)
