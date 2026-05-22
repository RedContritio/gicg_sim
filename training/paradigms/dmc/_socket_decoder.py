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

    callback 接 socket InferRequest → adapt → decode_dmc_request → forward_net.forward
    → InferResponse。 Per-call thread-safe via Python GIL(forward not parallel
    within a process)。

    Paradigm dispatch:``DMCNetwork.__call__`` 故意 raise NotImplementedError
    (driver / loss 走 ``forward_batch(collated)``,Player 走 ``select_action(env)``,
    bare ``__call__(obs_dict)`` 没合法 semantics)。 Socket inference 必须用
    ``DMCInferenceNet`` wrap underlying ActorCritic — 与 Python mp 路径
    (``mp_factories.py`` / ``test_dmc_mp_factories.py:113``)走同一 dispatch
    契约,不在 DMCNetwork 上 shadow ``__call__`` 以免破坏既有 invariant。

    Test stubs(``_ZeroLogitsNet`` etc)直接接 ``obs_dict``,无需 wrap — 通过
    ``isinstance(network, DMCNetwork)`` 区分。 Wrap 不复制权重(``DMCInferenceNet``
    通过 ``add_module`` 共享 ActorCritic),weight update via main loop
    ``network.load_state_dict`` in-place mutate 共享 reference 自动看到新权重。
    """
    import torch

    from training.paradigms.dmc._decoder import decode_dmc_request
    from training.paradigms.dmc.inference_net import DMCInferenceNet
    from training.paradigms.dmc.network import DMCNetwork
    from training.core.actor.inference_server_socket_wire import (
        INFER_STATUS_OK,
        InferResponse,
    )

    # Resolve forward callable once at build time(spawned InfServer child)。
    # DMCNetwork(production driver):wrap underlying ActorCritic with
    # DMCInferenceNet so forward(obs_dict) → dict-with-'q'-head works。
    # 其它 nn.Module(test stubs / future paradigm):trust 直接 callable。
    if isinstance(network, DMCNetwork):
        forward_net: Any = DMCInferenceNet(network.net).to(device_str).eval()
    else:
        forward_net = network

    def forward_callback(req: SocketInferRequest) -> InferResponse:
        obs_bytes = socket_request_to_pickled_payload(req, max_actions=max_actions)
        obs_dict, _mask = decode_dmc_request(obs_bytes, b'', device_str, shared_cache, network)
        with torch.no_grad():
            out = forward_net(obs_dict)
            if isinstance(out, dict):
                # DMCInferenceNet returns ActorCritic dict keyed by head;
                # DMC uses 'q' (DMC_HEAD_KINDS = {'q'})。 Test stubs may
                # legacy-return 'logit_as_q';accept both, fail loud otherwise。
                if 'q' in out:
                    logits = out['q']
                elif 'logit_as_q' in out:
                    logits = out['logit_as_q']
                else:
                    raise KeyError(
                        f'DMC socket forward: net output dict has no q / logit_as_q key (keys={sorted(out.keys())})'
                    )
            else:
                logits = out
            logits_np = logits.detach().cpu().numpy().astype(np.float32).ravel()
        return InferResponse(status=INFER_STATUS_OK, logits=logits_np)

    return forward_callback
