"""I5 regression: ParallelInferencePool.next_result(timeout=None)
must not deadlock when a worker stops producing results — whether
by crash (SIGKILL) or by hang (alive process stuck in a C-extension
or pipe wait, modelled here via SIGSTOP).

Scenarios
---------

Two failure modes are covered; r007 is believed to be the SIGSTOP-
style one (worker process still alive after 22 h but emitting no
results — no core dump, no exception, no log).

**test_no_deadlock_on_worker_sigkill** — worker dies hard.
``mp.Process.is_alive() == False`` after SIGKILL. A fix that polls
``alive_workers()`` catches this.

**test_no_deadlock_on_worker_sigstop** — worker alive but frozen.
SIGSTOP keeps ``is_alive() == True`` indefinitely while the process
never resumes its main loop, so no result is ever put on the queue.
A liveness check alone doesn't catch this; a progress-timeout fix
does. This test is the stronger one for r007's failure mode.

Both tests do:
  1. Dispatch N=6 games round-robin (worker 0: [0,2,4], worker 1: [1,3,5])
  2. Block on first result (proves happy-path not broken by the test)
  3. Disrupt worker 0
  4. Drain the remaining 5 results in a daemon thread with a 20 s join
  5. Assert the drain returned (regardless of how many it consumed —
     the fix may raise, may return fewer, but must not deadlock)
"""

from __future__ import annotations

import os
import signal
import threading
from typing import Callable, Optional, Tuple

from training.paradigms.az.config import smoke_config
from training.paradigms.az.inference_pool import ParallelInferencePool

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _run_disruption_scenario(
    disrupt_fn: Callable[[ParallelInferencePool], None],
    cleanup_fn: Optional[Callable[[ParallelInferencePool], None]] = None,
    n_games: int = 6,
    drain_timeout_s: float = 20.0,
) -> Tuple[bool, int]:
    """Shared test harness.

    Returns ``(drain_done_within_timeout, consumed_after_disrupt)``.
    """
    cfg = smoke_config(data_dir=DATA_DIR)
    cfg.n_workers = 2
    cfg.n_games = n_games

    pool = ParallelInferencePool(cfg)
    pool.start()
    try:
        for i in range(n_games):
            pool.dispatch(game_idx=i, env_seed=cfg.seed + i)

        # Happy-path proof: pool produces at least one result before
        # we disrupt anything. If this times out, the test is broken
        # (not a deadlock of the kind we're hunting).
        first = pool.next_result(timeout=60.0)
        assert first.get('winner') in (0, 1, 2), f'first result looks malformed: {first!r}'

        disrupt_fn(pool)

        consumed_after = [0]
        drain_done = threading.Event()

        def _drain() -> None:
            try:
                for _ in range(n_games - 1):
                    pool.next_result(timeout=None)
                    consumed_after[0] += 1
            except Exception:
                # Any exception (e.g. a fix raising WorkerDied) unblocks
                # the caller. Deadlock = no exception, no return.
                pass
            finally:
                drain_done.set()

        drainer = threading.Thread(target=_drain, daemon=True)
        drainer.start()
        drainer.join(timeout=drain_timeout_s)
        return drain_done.is_set(), consumed_after[0]
    finally:
        if cleanup_fn is not None:
            try:
                cleanup_fn(pool)
            except Exception:
                pass
        pool.stop()


def test_no_deadlock_on_worker_sigkill():
    """Worker crashes hard (SIGKILL). mp.Process.is_alive() → False.

    A liveness-based fix can catch this. This is the easier of the
    two failure modes to handle.
    """

    def sigkill_worker_0(pool: ParallelInferencePool) -> None:
        os.kill(pool._worker_procs[0].pid, signal.SIGKILL)

    done, consumed = _run_disruption_scenario(sigkill_worker_0)
    assert done, (
        f'DEADLOCK after SIGKILL: drain thread stuck after consuming {consumed}/5 remaining games. See backlog I5.'
    )


def test_no_deadlock_on_worker_sigstop():
    """Worker frozen (SIGSTOP). mp.Process.is_alive() → True forever.

    Models r007's failure mode: worker process kept running in
    ``ps`` for 22 h without ever producing results, no core dump,
    no traceback. A pure liveness check (``proc.is_alive()``) cannot
    distinguish this from a worker that happens to be mid-long-game;
    the fix needs a progress timeout — "if dispatched > consumed and
    no new result in N seconds, abort."

    Cleanup: SIGSTOPped processes ignore SIGTERM (pool.stop's first
    attempt), so we SIGKILL the victim in ``cleanup_fn`` before
    ``pool.stop()`` tries to join it.
    """

    def sigstop_worker_0(pool: ParallelInferencePool) -> None:
        os.kill(pool._worker_procs[0].pid, signal.SIGSTOP)

    def sigkill_victim_for_cleanup(pool: ParallelInferencePool) -> None:
        # SIGKILL works on SIGSTOPped processes; SIGTERM does not.
        try:
            os.kill(pool._worker_procs[0].pid, signal.SIGKILL)
        except (ProcessLookupError, IndexError):
            pass

    done, consumed = _run_disruption_scenario(
        sigstop_worker_0,
        cleanup_fn=sigkill_victim_for_cleanup,
    )
    assert done, (
        f'DEADLOCK after SIGSTOP: drain thread stuck after consuming '
        f'{consumed}/5 remaining games. This is the r007 failure '
        f'mode — alive-but-hung worker. See backlog I5.'
    )
