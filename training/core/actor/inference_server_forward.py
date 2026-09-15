"""Per-request forward path of the ``InferenceServer`` loop.

The counterpart of :func:`training.core.actor._inference_helpers._run_batched_path`:
that helper scatters one ``network.batched_forward`` over a whole batch,
while this one walks a batch request-by-request. ``_run_batched_path`` cannot
host it because ``_inference_helpers`` is already close to the source-line
cap, so the singleton path lives in this sibling module.

Split out of ``inference_server.py`` so each module stays within the
300-line source cap; the public ``InferenceServer`` handle stays in
``inference_server.py``.
"""

from __future__ import annotations

import time
from typing import Any

import torch

from training.core.actor._inference_helpers import (
    _from_bytes,
    _infer_stream_ctx,
    _to_bytes,
    _to_bytes_numpy,
    _to_device,
)
from training.core.perf import trace


def _run_singleton_path(
    network,
    batch: list,
    device_str: str,
    response_qs: list,
    request_decoder,
    shared_cache: Any,
    accel,
    *,
    return_numpy: bool = False,
    measure: bool = False,
) -> dict:
    """Per-request decode → forward → dispatch over ``batch``.

    The only path that exercises trace/compile acceleration (``accel``);
    the batched path bypasses it. One request's failure is reported back
    to that request's own client as an ``'err'`` reply and never aborts
    the rest of the batch.

    When ``request_decoder`` is supplied, each request is decoded via
    ``decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)``.
    When ``return_numpy=True`` the response is NumPy bytes so the client
    can unpickle without Torch.

    ``measure`` gates every ``perf_counter`` call, matching the loop's
    stats-enabled flag; when false nothing is timed and the returned
    dict is all zeros.

    Returns summed ``decode_ms``, ``forward_ms`` and ``dispatch_ms``.
    """
    timing = {'decode_ms': 0.0, 'forward_ms': 0.0, 'dispatch_ms': 0.0}
    for msg in batch:
        _kind, client_id, req_id, obs_bytes, mask_bytes = msg
        tt0 = time.perf_counter() if measure else 0.0
        try:
            with trace.span('inf_server.decode'):
                if request_decoder is not None:
                    obs, mask = request_decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)
                else:
                    obs = _from_bytes(obs_bytes)
                    mask = _from_bytes(mask_bytes) if mask_bytes is not None else None
                    obs = _to_device(obs, device_str)
                    if mask is not None:
                        mask = _to_device(mask, device_str)
            tt1 = time.perf_counter() if measure else 0.0
            net = accel.select(obs, mask)
            with trace.span('inf_server.forward'), _infer_stream_ctx(device_str):
                with torch.inference_mode():
                    out = net(obs, mask) if mask is not None else net(obs)
                if measure and device_str.startswith('cuda'):
                    # Synchronize before the forward timer ends so host
                    # transfer is accounted for in dispatch.
                    torch.cuda.synchronize()
            tt2 = time.perf_counter() if measure else 0.0
            with trace.span('inf_server.dispatch'):
                out = _to_device(out, 'cpu')
                payload_bytes = _to_bytes_numpy(out) if return_numpy else _to_bytes(out)
                response_qs[client_id].put(('ok', req_id, payload_bytes))
            if measure:
                tt3 = time.perf_counter()
                timing['decode_ms'] += (tt1 - tt0) * 1000.0
                timing['forward_ms'] += (tt2 - tt1) * 1000.0
                timing['dispatch_ms'] += (tt3 - tt2) * 1000.0
        except Exception as exc:
            response_qs[client_id].put(('err', req_id, f'{type(exc).__name__}: {exc}'))
    return timing
