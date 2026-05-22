"""I29 — socket_request_to_pickled_payload adapter tests。

``socket_request_to_pickled_payload`` 把 Go actor socket InferRequest 适配成
``decode_dmc_request`` 接受的 pickled dict payload。 I29 T-RR.4(Route A)后,
InfServer ``_server_loop`` 的 socket forward_cb 直接调用此 adapter,旧的
``build_dmc_socket_forward_callback``(socket-direct-forward,绕过批处理)已删 —
Route A 端到端覆盖移到 ``test_inference_server_socket_integration.py``。

本文件只验 adapter 的纯函数契约:flat 1D refs/pay → 2D reshape + fail-loud
size 校验(T-RR.6)。
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest

from training.core.actor.inference_server_socket_wire import InferRequest as SocketInferRequest
from training.paradigms.dmc._socket_decoder import socket_request_to_pickled_payload


_MAX_ACTIONS = 6


def _build_socket_request(*, embed_static: bool) -> SocketInferRequest:
    return SocketInferRequest(
        static_hash=b'\xab' * 16,
        client_id=0,
        req_id=1,
        dyn_obs=np.zeros(16, dtype=np.float32),
        refs=np.zeros(_MAX_ACTIONS * 3, dtype=np.int64),
        pay=np.zeros(_MAX_ACTIONS * 8, dtype=np.float32),
        static=np.arange(8, dtype=np.int32) if embed_static else np.zeros(0, dtype=np.int32),
    )


def test_socket_request_to_pickled_payload_reshapes_refs_pay():
    """flat 1D refs/pay → payload 内 2D (max_actions, 3) / (max_actions, 8)。"""
    req = _build_socket_request(embed_static=True)
    payload = pickle.loads(socket_request_to_pickled_payload(req, max_actions=_MAX_ACTIONS))

    assert payload['static_obs_hash'] == req.static_hash
    assert payload['refs_padded'].shape == (_MAX_ACTIONS, 3)
    assert payload['pay_padded'].shape == (_MAX_ACTIONS, 8)
    np.testing.assert_array_equal(payload['dyn_obs'], req.dyn_obs)
    # static 非空 → payload 携带 raw static_obs。
    assert payload['static_obs'] is not None
    np.testing.assert_array_equal(payload['static_obs'], req.static)


def test_socket_request_to_pickled_payload_empty_static_is_none():
    """static 空(size 0)→ payload['static_obs'] = None(server 走 hash cache)。"""
    req = _build_socket_request(embed_static=False)
    payload = pickle.loads(socket_request_to_pickled_payload(req, max_actions=_MAX_ACTIONS))
    assert payload['static_obs'] is None


def test_socket_request_refs_size_mismatch_raises():
    """refs size != max_actions*3 → fail-loud ValueError(I29 T-RR.6)。

    旧逻辑 ``refs.reshape(...) if size==max_actions*3 else refs`` 静默退化为 1D ——
    wire/max_actions 配置不一致被掩盖,下游 obs shape 错。 改为 size 不符即 raise。
    """
    bad_req = SocketInferRequest(
        static_hash=b'\x00' * 16,
        client_id=0,
        req_id=1,
        dyn_obs=np.zeros(16, dtype=np.float32),
        refs=np.zeros(10, dtype=np.int64),  # 错:10 != _MAX_ACTIONS*3
        pay=np.zeros(_MAX_ACTIONS * 8, dtype=np.float32),
        static=np.zeros(0, dtype=np.int32),
    )
    with pytest.raises(ValueError, match='refs size'):
        socket_request_to_pickled_payload(bad_req, max_actions=_MAX_ACTIONS)


def test_socket_request_pay_size_mismatch_raises():
    """pay size != max_actions*8 → fail-loud ValueError(I29 T-RR.6)。"""
    bad_req = SocketInferRequest(
        static_hash=b'\x00' * 16,
        client_id=0,
        req_id=1,
        dyn_obs=np.zeros(16, dtype=np.float32),
        refs=np.zeros(_MAX_ACTIONS * 3, dtype=np.int64),
        pay=np.zeros(7, dtype=np.float32),  # 错:7 != _MAX_ACTIONS*8
        static=np.zeros(0, dtype=np.int32),
    )
    with pytest.raises(ValueError, match='pay size'):
        socket_request_to_pickled_payload(bad_req, max_actions=_MAX_ACTIONS)
