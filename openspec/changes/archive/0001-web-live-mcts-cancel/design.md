# Design (retrospective)

## Consequences

Default selected = **D (accept + cap)**:
- Zero engineering cost.
- Live play is a developer tool, not a public-facing product. Real CFR validation runs via gauntlet
  (non-interactive), where search time doesn't block a user.
- Permanently caps opponent strength in live mode at ~5s budget per move (n_simulations ≤ 100 at d_model=64).
- Tab can be terminated by browser if server stall is long enough (uvicorn default WS timeout 5 min).

Upgrade path = **A (worker process)**:
- Implementation sketch (when picked up):
  - New file `web/backend/live_worker.py` — worker entrypoint; receives player spec + env state updates
    over pipe; runs `load_player(spec)` once at init.
  - New file `web/backend/session_worker.py` — per-WS-session manager; spawns one `live_worker` on first
    AI turn; shutdown via pipe + join + kill on WS close.
  - Modified `live_api.py::_auto_advance_agent` becomes async; uses `asyncio.wait_for` + `worker.terminate()`.
- Test pass: worker spawn/shutdown timing; cancel-after-disconnect (join within 5s); slow-AI fairness
  across concurrent WS sessions.

## Tradeoffs revisited

| Approach | Cost     | Cancel-safety | Live-perf                |
|----------|----------|---------------|--------------------------|
| A worker | 1-2 days | clean         | event loop responsive    |
| B threaded + flag | 2-3 days | cooperative | GIL-bounded         |
| C async search | 1 week+ | clean | async, no extra procs      |
| D accept + cap | 2 hours | n/a | capped budget               |

Default: D. Upgrade path: A.

Per-session Python process cost ~80 MB resident; small deployments OK, multi-tab browsing scales linearly.
`Process.terminate()` is SIGTERM — a libgicg DSL evaluation mid-step may leave global Go state in an
unusual condition; bounded to child address space by `spawn` context.

## References

- `docs/2_decisions/adr-0001-web_live_mcts_cancel.md` (mirror, P1+ phase will remove)
- `web/backend/live_api.py::_auto_advance_agent` (current synchronous implementation)
- `training/cfr/worker.py` (Phase-2 worker pattern, reusable for option A)
