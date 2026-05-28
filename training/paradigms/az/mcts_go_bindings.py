"""ctypes bindings + eval-callback wrappers for mcts_go.

Split out of the main mcts_go module so each file stays below the
300-line cap. The main public entry point is ``mcts_search_go`` in
``mcts_go.py``."""

from __future__ import annotations

import ctypes

import numpy as np

# W2-5: 公开 `get_lib_path()` 替代 `_find_lib` underscore（audit 低优 — file
# path leak）。 旧 import 路径 `_find_lib` 仍存在(internal),但 paradigm 外部
# 调用一律 `get_lib_path()`。
from gicg_env.engine import get_lib_path


_lib: ctypes.CDLL | None = None

SendCallbackType = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_int,
)

RecvCallbackType = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_float),
    ctypes.POINTER(ctypes.c_float),
)


def ensure_lib() -> ctypes.CDLL:
    """Lazy-load + bind the MCTSSearch symbol signature."""
    global _lib
    if _lib is not None:
        return _lib
    lib = ctypes.CDLL(get_lib_path())
    lib.MCTSSearch.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_char_p,
        SendCallbackType,
        RecvCallbackType,
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_char_p),
    ]
    lib.MCTSSearch.restype = ctypes.c_int
    _lib = lib
    return _lib


def make_eval_callbacks(evaluator):
    """Build (send_cb, recv_cb) CFUNCTYPE instances forwarding to the
    evaluator. The returned callables must outlive the MCTSSearch
    call (ctypes drops them on GC).

    Two evaluator shapes are supported:
      - InferenceClient: has send_eval / recv_eval
      - Agent (local torch forward): has only eval_state — we simulate
        the async split with a 1-slot queue.
    """
    if hasattr(evaluator, 'send_eval') and hasattr(evaluator, 'recv_eval'):
        send_impl = evaluator.send_eval
        recv_impl = evaluator.recv_eval
    else:
        pending: list[tuple] = []

        def send_impl(dyn, refs, pay):
            pending.append((dyn, refs, pay))

        def recv_impl():
            dyn, refs, pay = pending.pop(0)
            return evaluator.eval_state(dyn, refs, pay)

    def send_cb(worker_id, game_id, dyn_ptr, dyn_len, refs_ptr, pay_ptr, n_legal):
        try:
            dyn = np.ctypeslib.as_array(dyn_ptr, shape=(dyn_len,))
            refs = np.ctypeslib.as_array(refs_ptr, shape=(n_legal, 3))
            pay = np.ctypeslib.as_array(pay_ptr, shape=(n_legal, 8))
            send_impl(dyn.copy(), refs.copy(), pay.copy())
            return 0
        except Exception as e:
            import sys

            print(f'mcts_go send callback error: {e!r}', file=sys.stderr)
            return -1

    def recv_cb(n_legal, prior_out_ptr, value_out_ptr):
        try:
            prior, value = recv_impl()
            prior_out = np.ctypeslib.as_array(prior_out_ptr, shape=(n_legal,))
            prior_np = np.asarray(prior, dtype=np.float32)
            if prior_np.shape[0] != n_legal:
                raise RuntimeError(
                    f'mcts_go recv: evaluator returned prior of len {prior_np.shape[0]} but n_legal={n_legal}'
                )
            prior_out[:] = prior_np
            value_out_ptr[0] = float(value)
            return 0
        except Exception as e:
            import sys

            print(f'mcts_go recv callback error: {e!r}', file=sys.stderr)
            return -1

    return SendCallbackType(send_cb), RecvCallbackType(recv_cb)
