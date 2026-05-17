# Web live play: MCTS search cancellation (C1 from Phase-4 review)

> **MOVED to `openspec/changes/archive/0001-web-live-mcts-cancel/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0001-web-live-mcts-cancel/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0001-web-live-mcts-cancel/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


## Problem

`web/backend/live_api.py::_auto_advance_agent` runs synchronously in
the WebSocket handler. For every AI-controlled turn it calls
`player.select_action(env)`; when the opponent is MCTS-backed (`az`
+ `n_simulations>0`, `cfr` + `n_simulations>0`, or `mcts_pure`),
that method does a full N-rollout search synchronously in the event
loop thread.

Consequences during a long search:

1. **The WS handler is blocked.** `await ws.receive_json()` can't
   run — any client messages (e.g. a second Restart click, a new
   `new` with a different opponent) queue in the OS TCP buffer.
   From the user's view the tab is frozen.
2. **No cancellation.** If the client disconnects mid-search, the
   Python thread keeps driving `mcts_search` to completion, burning
   CPU + holding ckpt memory. The next `ws.receive_json()` raises
   `WebSocketDisconnect` only after the search finishes.
3. **Back-pressure is zero.** N=1000 rollouts ≈ 30 s at d_model=64;
   the UX cliff is abrupt.

Phase-4 review flagged this as "hard / not recommended" because the
cancellation path requires coordinating Python asyncio with a
cgo-calling synchronous search loop. Recording a plan here in case
the trade-off changes later.

## Approaches (sorted by cost / blast radius)

### A. Run search in a worker process, cancel via terminate

Simplest actually-cancelable variant. The `live_api` session spawns
one dedicated `multiprocessing.Process` per active WS session. AI
turns send a `SelectAction` request over a pipe; the worker returns
the action or honors a `Cancel` request by dropping the in-flight
search.

Pros:
- Reuses the Phase-2 CFR worker pattern (`training/cfr/worker.py`).
  `spawn` context is safe with libgicg cgo.
- Clean cancel: if the WS disconnects, `process.terminate()` kills
  the worker mid-search. OS signals handle the libgicg internals.
- Event loop stays responsive — receive_json runs alongside a
  bounded-time `asyncio.wait_for(pipe_recv, timeout)` poll.

Cons:
- Per-session Python process costs ~80 MB resident (ckpt + engine
  + libgicg runtime). Small deployments OK; multi-tab browsing
  scales linearly.
- ckpt loading happens in the child process too, re-reading from
  disk unless we add a fork-from-loaded-parent variant. The Phase-2
  builder LRU cache in `live_api` doesn't help the child.
- `Process.terminate()` is SIGTERM; a libgicg DSL evaluation mid-
  step might leave global Go state in an unusual condition. We use
  `spawn` so this is bounded to the child's address space, but the
  child itself exits uncleanly — no-op since it's throwaway.
- Adds ~150 LOC of pipe protocol + health check + reap loop.

### B. Threaded search + cooperative cancel flag

Run `player.select_action` in `asyncio.to_thread` and poll a
cancel flag inside `mcts_search`. Requires modifying `training.mcts`
to check the flag every K rollouts.

Pros:
- No process overhead. Simple control structure.
- Cooperative cancel is lightweight.

Cons:
- Needs a cancel hook injected into every player type (`MCTSPlayer`,
  `_AgentMCTSPlayer`, future `_CFRMCTSPlayer`). Threads through the
  mcts_search internals — 10+ touch sites.
- Python GIL: while the search thread runs Python (most of
  `mcts_search` is Python + numpy), the event loop can schedule
  but gets preempted back to the search thread every GIL-sched
  tick. Receive latency is bounded by the GIL interval (~5 ms)
  plus whatever Python runs between yield points; interactive feel
  is acceptable.
- cgo calls inside `env.step` hold the GIL (Python→C boundary
  doesn't release unless the Go side wraps work behind `go`). If
  a single rollout is >100 ms of cgo work, event loop stalls for
  that long. In practice a rollout is fast; worst case is not
  terrible.
- Testing cancellation across thread boundaries is fiddly — race
  windows where the flag is set just after the search's final
  rollout dispatch, etc.

### C. Async-friendly search: rollout as coroutine

Refactor `mcts_search` into a generator / coroutine that yields
every K rollouts. The WS handler awaits a step at a time,
interleaving with `receive_json`. Cancellation is trivial
(`task.cancel()` unwinds the coroutine).

Pros:
- Most correct from an async design perspective. No extra threads
  or processes.
- Cancellation is guaranteed at yield points.

Cons:
- `mcts_search` is called from Python training code AND web backend.
  Making it async requires duplicate sync + async variants, or
  migrating every caller to async. Substantial churn.
- Interleaving tree descent across yields complicates the snapshot/
  restore accounting; the current code assumes the tree walk runs
  to completion under one `root_snap`.
- ~1 week of refactoring. Risks breaking training's IS-MCTS path.

### D. Accept the limitation; document UX

Keep the current synchronous behavior. Expose a small UI affordance:
grey out the page + show a "thinking…" spinner with the search
budget; disable the Restart button until the search finishes. Cap
user-exposed `n_simulations` at whatever keeps the worst case under
5 s (e.g. ≤ 100 at d_model=64). Longer searches are for gauntlet,
not live play.

Pros:
- Zero engineering cost.
- Live play is a developer tool, not a public-facing product.
- The real CFR validation happens via the gauntlet (non-interactive),
  where search time doesn't block a user.

Cons:
- Tab can still be terminated by browser if the server stall is
  long enough for the WS to timeout (uvicorn's default is 5 min,
  which we hit at absurd budgets).
- Permanently caps opponent strength in live mode.

## Recommendation

**Option A (worker-process)** if the ability to explore higher-budget
opponents in live mode ever becomes important. Has the cleanest
cancellation semantics and reuses existing Phase-2 worker
infrastructure. Cost: ~1-2 days of engineering.

**Option D (accept + cap)** as the default until a concrete use
case forces a change. The cost-benefit weighs toward D because
interactive play is already capped by human reaction time — no one
plays a game with 30s/move opponent willingly, so forcing
`n_simulations ≤ 100` matches real UX expectations anyway.

**Do NOT pursue B or C** unless forced. B leaks cancel-hook
responsibility across the MCTS codebase; C is a training-stack
refactor that trades weeks of risk for marginal live-UX gains.

## Implementation sketch for Option A (when we pick this up)

New files:
- `web/backend/live_worker.py` — worker entrypoint. Receives player
  spec + env state updates from pipe; runs `load_player(spec)` once
  at init; per-turn: `env.restore(state); action =
  player.select_action(env); pipe.put(action)`.
- `web/backend/session_worker.py` — per-WS-session manager. Spawns
  one `live_worker` subprocess on first AI turn, keeps it across
  subsequent turns. Shutdown on WS close via pipe + join + kill.

Modified files:
- `live_api.py::_auto_advance_agent` becomes async. Each AI turn is:
  ```python
  state_snap = env.snapshot()
  await session.worker.send_select(state_snap, timeout=30)
  action = await session.worker.recv_action()
  env.restore(state_snap)
  env.step(action)
  ```
  Cancellable via `asyncio.wait_for` timeout + `worker.terminate()`
  on WS disconnect.

- State transport: env snapshot is a numpy blob (counters + hand +
  phase + RNG seed). ~kilobytes. Send as pickled dict over pipe.
  Worker rebuilds env from snapshot, then calls select_action.

Test pass:
- Worker spawn + shutdown timing (reuse Phase-2 parallel trainer
  test pattern).
- AI turn cancel after WS disconnect: worker joins within 5s.
- Slow-AI fairness: while worker searches, main process serves
  another WS's status request without blocking.

## Cost summary

| Approach | Cost | Cancel-safety | Live-perf |
|---------|------|---------------|-----------|
| A (worker process) | 1-2 days | ✓ clean | event loop responsive |
| B (threaded + flag) | 2-3 days | cooperative | GIL-bounded |
| C (async search) | 1 week + | ✓ clean | async, no extra procs |
| D (accept + cap)   | 2 hours (UI note + cap) | N/A | capped budget |

Default: D. Upgrade path: A.
