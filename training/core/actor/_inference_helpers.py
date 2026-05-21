"""Helpers extracted from inference_server.py to keep that file below
the 300-LOC file budget. Three concerns live here:

1. ``_to_bytes`` / ``_from_bytes`` — pickle wire encoding for the
   request_q / response_qs protocol.
2. ``_to_device`` — recursive tensor.to(device) over the obs container
   shapes that paradigms use (single tensor / dict / tuple-of-tensors).
3. ``_run_batched_path`` — paradigm-aware batched-forward scatter:
   decode all obs in a batch, run network.batched_forward once, scatter
   one row to each client's response_q. Called by ``_server_loop``
   whenever the wrapped network exposes ``batched_forward``.

Single-forward fallback stays inline in ``_server_loop`` because the
``trace`` / ``compile`` acceleration branches mutate that loop's closure
(``traced_net``, ``compiled_net``, ``trace_attempted``); moving the
fallback would require threading that state into a helper signature for
no real gain.
"""

from __future__ import annotations

import pickle
from typing import Any

import torch

from training.core.perf import trace


class _AccelState:
    """Lazy compile/trace state for ``_server_loop``.

    Encapsulates the closure that used to live inline (``compiled_net``
    one-shot, ``traced_net`` first-batch-lazy, ``_select_net``,
    ``_invalidate_trace``) so the server loop body stays compact.
    ``mode == 'none'`` → ``select`` always returns the raw network.
    """

    def __init__(self, network: Any, mode: str) -> None:
        self.network = network
        self.mode = mode
        self.compiled: Any = None
        self.traced: Any = None
        self.trace_attempted = False
        if mode == 'compile':
            try:
                self.compiled = torch.compile(network, mode='reduce-overhead', dynamic=True)
            except Exception as exc:
                print(
                    f'[InferenceServer] torch.compile failed ({type(exc).__name__}: {exc}); '
                    f'falling back to raw forward for remainder of process lifetime.'
                )
                self.compiled = None

    def _maybe_trace(self, obs: Any, mask: Any) -> Any:
        if self.trace_attempted:
            return self.traced if self.traced is not None else self.network
        self.trace_attempted = True
        try:
            example = (obs, mask) if mask is not None else (obs,)
            self.traced = torch.jit.trace(self.network, example, check_trace=False)
        except Exception as exc:
            print(
                f'[InferenceServer] torch.jit.trace failed ({type(exc).__name__}: {exc}); '
                f'falling back to untraced forward for remainder of process lifetime.'
            )
            self.traced = None
        return self.traced if self.traced is not None else self.network

    def select(self, obs: Any, mask: Any) -> Any:
        if self.mode == 'compile':
            return self.compiled if self.compiled is not None else self.network
        if self.mode == 'trace':
            return self._maybe_trace(obs, mask)
        return self.network

    def invalidate_trace(self) -> None:
        # compile mode: parameter tensors mutated in place; no invalidate.
        if self.mode == 'trace':
            self.traced = None
            self.trace_attempted = False


def _to_bytes(t: Any) -> bytes:
    return pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)


def _to_bytes_numpy(t: Any) -> bytes:
    """Pickle response as a numpy array — actor unpickle stays torch-free.

    Used on the decoder-path (DMC mp) where the actor process is
    intentionally numpy-only: returning a pickled torch.Tensor would
    force the actor's ``pickle.loads`` to ``import torch``, which mmaps
    ~400 MB of CUDA libs per actor (the actual reason the I25 cutover
    exists — see ``training/paradigms/dmc/mp_factories.py`` docstring).

    Torch tensors are converted via ``detach().cpu().numpy()``. Anything
    that already lacks ``detach`` (numpy arrays, lists of either) falls
    through to ``_to_bytes``. Dicts / tuples / lists are walked
    recursively so structured outputs (head dicts) survive intact.
    """
    return pickle.dumps(_as_numpy(t), protocol=pickle.HIGHEST_PROTOCOL)


def _as_numpy(obj: Any) -> Any:
    """Recurse into dict / tuple / list / Tensor; cast tensors to numpy.

    Mirrors ``_to_device`` recursion shape. Non-tensor leaf values pass
    through unchanged so a numpy array or python scalar already in the
    structure stays as-is.
    """
    if isinstance(obj, torch.Tensor):
        return obj.detach().cpu().numpy()
    if isinstance(obj, dict):
        return {k: _as_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return type(obj)(_as_numpy(v) for v in obj)
    return obj


def _from_bytes(b: bytes) -> Any:
    return pickle.loads(b)


def _to_device(obj: Any, device: str) -> Any:
    """Recurse into dict / tuple / Tensor and ``.to(device)`` each tensor.

    obs may be a single tensor, a dict of tensors (DMC), or a tuple
    (legacy). Non-tensor leaf values pass through unchanged.
    """
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, dict):
        return {k: _to_device(v, device) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return type(obj)(_to_device(v, device) for v in obj)
    return obj


def _run_batched_path(
    network,
    batch: list,
    device_str: str,
    response_qs: list,
    request_decoder=None,
    shared_cache: Any = None,
    return_numpy: bool = False,
    batched_decoder=None,
) -> dict:
    """Decode all obs once, run ``network.batched_forward``, scatter rows.

    Per-request decode failures surface as a single 'err' on that
    client; a batched_forward exception broadcasts the same err msg to
    every client whose obs was in the batch. Output is sliced
    ``[i : i + 1]`` so each client unpickles a tensor with the same
    shape the per-request path returns.

    When ``request_decoder`` is supplied, each request is decoded via
    ``decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)``.
    ``shared_cache`` is a single server-wide dict the decoder internally
    keys by content hash — multiple clients sharing the same scenario
    therefore hit the same cache entry.

    When ``return_numpy=True``, the row is converted to numpy bytes via
    :func:`_to_bytes_numpy` so the client process can unpickle without
    importing torch (I25 — decoder-path actors stay torch-free).

    Returns timing dict ``{decode_ms, forward_ms, dispatch_ms}`` so caller
    can accumulate per-phase stats(2026-05-21 — verify "GPU 38ms forward"
    hypothesis via实证 phase 拆分,而不是合并 process_ms 一个字段)。
    """
    import time as _time

    t0 = _time.perf_counter()

    # 优先 batched_decoder 路径 — 一次 H2D / op launch 替代 N×。 失败时 fall
    # back per-request decode 路径(保留 fault isolation:某 request payload
    # malformed 不该 kill 整 batch)。
    if batched_decoder is not None and len(batch) > 1:
        payloads = [(msg[3], msg[4]) for msg in batch]
        client_ids = [(msg[1], msg[2]) for msg in batch]
        try:
            obs_batched, _mask = batched_decoder(payloads, device_str, shared_cache, network)
            decoded = client_ids  # all rows mapped 1:1 by index
            t1 = _time.perf_counter()
        except Exception as exc:
            err_msg = f'{type(exc).__name__}: {exc}'
            for client_id, req_id in client_ids:
                try:
                    response_qs[client_id].put(('err', req_id, err_msg))
                except Exception:
                    pass
            t1 = _time.perf_counter()
            return {'decode_ms': (t1 - t0) * 1000.0, 'forward_ms': 0.0, 'dispatch_ms': 0.0}
        # batched_forward 接的是 list of obs_dict (1, ...)。 batched_decoder
        # 已经返 batch dim N 的单一 dict — split 出 N 个 (1, ...) 喂
        # batched_forward 即可(零 copy view)。
        decoded_dicts = [{k: v[i : i + 1] for k, v in obs_batched.items()} for i in range(len(batch))]
    else:
        decoded_dicts = []
        decoded = []
        with trace.span('inf_server.decode'):
            for msg in batch:
                _kind, client_id, req_id, obs_bytes, mask_bytes = msg
                try:
                    if request_decoder is not None:
                        obs, _mask = request_decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)
                    else:
                        obs = _from_bytes(obs_bytes)
                        obs = _to_device(obs, device_str)
                        if mask_bytes is not None:
                            _ = _from_bytes(mask_bytes)
                    decoded.append((client_id, req_id))
                    decoded_dicts.append(obs)
                except Exception as exc:
                    response_qs[client_id].put(('err', req_id, f'{type(exc).__name__}: {exc}'))
        t1 = _time.perf_counter()
    if not decoded_dicts:
        return {'decode_ms': (t1 - t0) * 1000.0, 'forward_ms': 0.0, 'dispatch_ms': 0.0}
    try:
        with trace.span('inf_server.batched_forward_inner'):
            with torch.inference_mode():
                batched_out = network.batched_forward(decoded_dicts)
            # CUDA sync 显式 — 否则 .to('cpu') 触发 sync 把 forward 时间
            # 算到 dispatch 里,GPU forward wall 看起来假性低。
            if device_str.startswith('cuda'):
                torch.cuda.synchronize()
            batched_out = _to_device(batched_out, 'cpu')
    except Exception as exc:
        err_msg = f'{type(exc).__name__}: {exc}'
        for client_id, req_id in decoded:
            try:
                response_qs[client_id].put(('err', req_id, err_msg))
            except Exception:
                pass
        return {'decode_ms': (t1 - t0) * 1000.0, 'forward_ms': 0.0, 'dispatch_ms': 0.0}
    t2 = _time.perf_counter()
    encode = _to_bytes_numpy if return_numpy else _to_bytes
    with trace.span('inf_server.dispatch'):
        for i, (client_id, req_id) in enumerate(decoded):
            row = batched_out[i : i + 1]
            try:
                response_qs[client_id].put(('ok', req_id, encode(row)))
            except Exception as exc:  # pragma: no cover — queue closed
                print(f'[InferenceServer] response_q put failed: {exc}')
    t3 = _time.perf_counter()
    return {
        'decode_ms': (t1 - t0) * 1000.0,
        'forward_ms': (t2 - t1) * 1000.0,
        'dispatch_ms': (t3 - t2) * 1000.0,
    }
