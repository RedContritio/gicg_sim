"""Socket adapter — bridge Go actor socket InferRequest → existing pickled
``decode_dmc_request`` decoder。

I29 T-RR.4 — Route A:socket inference 请求经 InfServer ``_server_loop`` 的
``forward_cb`` 走 ``request_q`` 批处理(与 mp.Queue 客户端共用),``forward_cb``
仅用此模块的 ``socket_request_to_pickled_payload`` 把 socket InferRequest 适配成
``decode_dmc_request`` 已接受的 pickled dict payload。 旧的 socket-direct-forward
``build_dmc_socket_forward_callback``(自行 decode+forward,绕过批处理)已删 —
Route A 是唯一 socket 路径。

边界:
- Go side wire schema:dyn_obs (f32 1D)、refs (i64 1D shape max_actions*3)、
  pay (f32 1D shape max_actions*8)、static (i32 1D 可空)。 socket adapter
  把 1D flatten 还原成 2D shape decode_dmc_request 要的样子。
"""

from __future__ import annotations

import pickle

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
    # refs/pay 必为 max_actions padded shape(Go BuildInferRequest 保证)。 size 不符 =
    # wire / max_actions 配置不一致 —— fail-loud,不静默退化为 1D(I29 T-RR.6)。
    if req.refs.size != max_actions * 3:
        raise ValueError(
            f'socket InferRequest refs size {req.refs.size} != max_actions*3 ({max_actions * 3}) '
            f'— wire/max_actions mismatch'
        )
    if req.pay.size != max_actions * 8:
        raise ValueError(
            f'socket InferRequest pay size {req.pay.size} != max_actions*8 ({max_actions * 8}) '
            f'— wire/max_actions mismatch'
        )
    refs_2d = req.refs.reshape(max_actions, 3)
    pay_2d = req.pay.reshape(max_actions, 8)
    payload = {
        'static_obs_hash': req.static_hash,
        'static_obs': req.static if req.static.size > 0 else None,
        'dyn_obs': req.dyn_obs,
        'refs_padded': refs_2d,
        'pay_padded': pay_2d,
    }
    return pickle.dumps(payload)
