"""Socket adapter — bridge Go actor socket InferRequest → existing pickled
``decode_dmc_request`` decoder。

P1.4 minimum:走 adaptation (pickle the socket-typed fields into a dict shape
``decode_dmc_request`` already expects)。 这避免重写 obs_dict 构建逻辑,但带
~50-100μs / request pickle 开销。 P3 perf 优化用直接 socket decoder
(unpickle 路径 zero-copy,reuse static cache by hash)替换。

边界:
- Go side wire schema:dyn_obs (f32 1D)、refs (i64 1D shape max_actions*3)、
  pay (f32 1D shape max_actions*8)、static (i32 1D 可空)。 socket adapter
  把 1D flatten 还原成 2D shape decode_dmc_request 要的样子。
- 行内 import torch / DMC 内部模块 — actor side 不该 import,这里在 InfServer
  process 中调用,torch 已 in scope。
"""

from __future__ import annotations

import pickle
from typing import Any

import numpy as np

from training.core.actor.inference_server_socket_wire import InferRequest as SocketInferRequest


def socket_request_to_pickled_payload(req: SocketInferRequest, *, max_actions: int) -> bytes:
    """Adapt socket-decoded InferRequest → dict 形 payload 走 decode_dmc_request。

    refs / pay 在 Go side 是 flat 1D 序列;decode_dmc_request 要求 refs_padded shape
    (max_actions, 3) + pay_padded shape (max_actions, 8)。 这里 reshape(取自 wire
    schema 的隐式 shape)。

    static 可空(len=0)时 payload['static_obs'] = None,server 走 cache by
    static_obs_hash。 server 端 cache miss + None 会 raise loud(actor 必须在
    weight update 后重发 static)。
    """
    refs_2d = req.refs.reshape(max_actions, 3) if req.refs.size == max_actions * 3 else req.refs
    pay_2d = req.pay.reshape(max_actions, 8) if req.pay.size == max_actions * 8 else req.pay
    payload = {
        'static_obs_hash': req.static_hash,
        'static_obs': req.static if req.static.size > 0 else None,
        'dyn_obs': req.dyn_obs,
        'refs_padded': refs_2d,
        'pay_padded': pay_2d,
    }
    return pickle.dumps(payload)


def build_dmc_socket_forward_callback(
    *,
    device_str: str,
    shared_cache: dict,
    network: Any,
    max_actions: int,
) -> Any:
    """Return a forward_callback function 适用 InferServer socket listener。

    callback 接 socket InferRequest → adapt → decode_dmc_request → network.forward →
    InferResponse。 Per-call thread-safe via Python GIL(forward not parallel
    within a process)。

    network 的 forward 期望 obs_dict + 返 logits;DMC InferenceNet 走
    `forward(obs_dict)['logit_as_q']` 返 shape (1, max_actions)。
    """
    import torch

    from training.paradigms.dmc._decoder import decode_dmc_request
    from training.core.actor.inference_server_socket_wire import (
        INFER_STATUS_OK,
        InferResponse,
    )

    def forward_callback(req: SocketInferRequest) -> InferResponse:
        obs_bytes = socket_request_to_pickled_payload(req, max_actions=max_actions)
        obs_dict, _mask = decode_dmc_request(obs_bytes, b'', device_str, shared_cache, network)
        with torch.no_grad():
            out = network(obs_dict)
            logits = out['logit_as_q'] if isinstance(out, dict) else out
            logits_np = logits.detach().cpu().numpy().astype(np.float32).ravel()
        return InferResponse(status=INFER_STATUS_OK, logits=logits_np)

    return forward_callback
