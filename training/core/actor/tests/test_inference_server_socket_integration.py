"""I29 P1.4e — InferenceServer 内嵌 socket listener integration test。

验证 InfServer spawn with socket_port > 0 → listener thread up → Go side(this test
模拟 Go via Python client)发 InferRequest → callback forward → response 回。

mp 路径 不变 — 同 InfServer 同时支持 mp.Queue 老路径 + socket 新路径,本测仅 socket 路径。
"""

from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pytest
import torch
import torch.nn as nn

from training.core.actor.inference_server import InferenceServer
from training.core.actor.inference_server_socket_wire import (
    INFER_STATUS_OK,
    InferRequest,
    decode_infer_response,
    encode_infer_request,
    read_length_prefixed,
)


class _ZeroLogitsNet(nn.Module):
    """Minimal net — returns dict with logit_as_q of zeros。"""

    def __init__(self, max_actions: int = 30) -> None:
        super().__init__()
        self.max_actions = max_actions
        # ensure module has at least one param (some pytorch ops touch parameters)
        self.dummy = nn.Linear(1, 1)

    def forward(self, obs_dict):  # noqa: ARG002 — we don't read obs
        return {'logit_as_q': torch.zeros(1, self.max_actions)}


def build_zero_logits_forward(*, device_str, shared_cache, network, max_actions=30):  # noqa: ARG001
    """Builder returning a callback that ignores the request and returns zero logits。"""
    from training.core.actor.inference_server_socket_wire import InferResponse

    def cb(req):  # noqa: ARG001
        return InferResponse(status=INFER_STATUS_OK, logits=np.zeros(max_actions, dtype=np.float32))

    return cb


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _read_length_prefixed_from_socket(conn: socket.socket) -> bytes:
    class _R:
        def read(self, n):
            return conn.recv(n)

    return read_length_prefixed(_R())


def test_inference_server_socket_listener_roundtrip():
    """InfServer spawn with socket_port → Python TCP client connects → req → resp。

    使用 stub builder 不走真 DMC network,纯验证 socket 集成。
    """
    port = _free_port()
    net = _ZeroLogitsNet(max_actions=10)
    server = InferenceServer(
        network=net,
        device='cpu',
        max_batch=1,
        socket_port=port,
        socket_forward_builder_path=(
            'training.core.actor.tests.test_inference_server_socket_integration.build_zero_logits_forward'
        ),
        socket_forward_builder_kwargs={'max_actions': 10},
    )
    server.start(wait_ready_s=10.0)
    try:
        # Python client connect + send request + read response
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        req = InferRequest(
            static_hash=b'\xab' * 16,
            client_id=7,
            req_id=99,
            dyn_obs=np.array([1.0, 2.0, 3.0], dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
            static=np.array([42, -1, 0], dtype=np.int32),  # provide static (server will cache)
        )
        client.sendall(encode_infer_request(req))
        resp_payload = _read_length_prefixed_from_socket(client)
        resp = decode_infer_response(resp_payload)
        client.close()

        assert resp.status == INFER_STATUS_OK
        assert resp.logits is not None
        assert len(resp.logits) == 10
        assert np.array_equal(resp.logits, np.zeros(10, dtype=np.float32))
    finally:
        server.stop()


def test_inference_server_no_socket_when_port_zero():
    """socket_port=0 (default) 时无 listener — InfServer 跑 mp.Queue 原路径,启动正常。"""
    net = _ZeroLogitsNet(max_actions=5)
    server = InferenceServer(network=net, device='cpu', max_batch=1, socket_port=0)
    server.start(wait_ready_s=5.0)
    try:
        # Just verify server started + no listener side effects.
        assert server._proc is not None
        assert server._proc.is_alive()
    finally:
        server.stop()
