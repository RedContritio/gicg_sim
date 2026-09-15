"""Child-process network/decoder construction for the ``InferenceServer`` loop.

Split out of ``inference_server.py`` so the spawn target loop and this
one-time child setup each stay within the 300-line source cap; the public
``InferenceServer`` handle stays in ``inference_server.py``.
"""

from __future__ import annotations

import pickle
import traceback

from training.core.actor._inference_helpers import _AccelState


def _init_child_process(
    network_bytes: bytes,
    device_str: str,
    inference_acceleration: str,
    request_decoder_path: str,
    ready_event,
    stop_event,
):
    """Rebuild the network in the child and wire the optional request decoder.

    Returns ``(network, request_decoder, return_numpy, shared_cache, accel)``.
    A failed unpickle sets both events (so the parent's ``start()`` does not
    hang on the ready signal) and raises ``RuntimeError``.

    ``request_decoder`` stays ``None`` on the generic decode path;
    ``return_numpy`` follows the decoder path, because decoder-path actors
    stay torch-free and therefore must receive NumPy bytes.
    """
    try:
        network = pickle.loads(network_bytes).to(device_str).eval()
    except Exception as exc:  # pragma: no cover — startup failure surface
        ready_event.set()
        stop_event.set()
        raise RuntimeError(f'InferenceServer init failed: {exc}\n{traceback.format_exc()}')

    request_decoder = None
    # Decoder-path implies actor stays torch-free → response must be
    # numpy bytes. Legacy callers (test nets, AZ-loopback fallback)
    # keep the pickled torch tensor response.
    return_numpy = bool(request_decoder_path)
    if request_decoder_path:
        from training.core.actor.actor_process import resolve_builder

        request_decoder = resolve_builder(request_decoder_path)
    # Server-wide decoder cache (shared across all clients). Decoder
    # internally keys by static_obs hash so multiple actors sharing the
    # same scenario hit the same cache entry — for fixed-scenario DMC,
    # this means hook_encoder runs **once total**, not once per
    # actor×episode. Server wipes on weight update.
    shared_cache: dict = {}

    # _AccelState builds compile-once net up-front + lazy-traces on first
    # request when mode='trace'; both failures fall back to raw forward.
    accel = _AccelState(network, inference_acceleration)
    return network, request_decoder, return_numpy, shared_cache, accel
