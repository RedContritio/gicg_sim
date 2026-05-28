"""I29 — InferenceServer 内嵌 socket listener integration test(Route A)。

验证 InfServer spawn with socket_port > 0 → listener thread up → Go side(this test
模拟 Go via Python client)发 InferRequest → Route A:listener forward_cb 把请求
``put`` 进 ``request_q``,与 mp.Queue 客户端共用 main loop 批处理 →
``decode_dmc_request`` + ``DMCInferenceNet.forward`` → response 回。

mp 路径 不变 — 同 InfServer 同时支持 mp.Queue 老路径 + socket 新路径,本测仅 socket 路径。

I29 T-RR.4(Route A)后无 socket forward builder:InfServer 的 network 必须是
``DMCInferenceNet``(wrap ActorCritic),``request_decoder_path`` + ``socket_max_actions``
+ ``socket_clients`` 三参数驱动。 socket 请求必须 carry 真 obs(refs/pay padded 到
max_actions),走 ``decode_dmc_request``。
"""

from __future__ import annotations

import hashlib
import socket
import threading

import numpy as np

from training.core.network import AgentConfig
from training.core.actor.inference_server import InferenceServer
from training.core.actor.inference_server_socket_wire import (
    INFER_STATUS_OK,
    InferRequest,
    decode_infer_response,
    encode_infer_request,
    read_length_prefixed,
)
from training.paradigms.dmc.inference_net import DMCInferenceNet
from training.paradigms.dmc.network import DMCNetwork


# Small-but-real ActorCritic shape — n_counter_slots ≥ N_STRUCTURAL(=66)。
_N_COUNTER_SLOTS = 70
_N_HOOKS = 4
_MAX_OPS_PER_HOOK = 2
_FIELDS_PER_OP = 5
_MAX_ACTIONS = 6
_D_MODEL = 16


def _build_dmc_inference_net() -> DMCInferenceNet:
    cfg = AgentConfig(
        n_counter_slots=_N_COUNTER_SLOTS,
        n_hooks=_N_HOOKS,
        max_ops_per_hook=_MAX_OPS_PER_HOOK,
        max_actions=_MAX_ACTIONS,
        d_model=_D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    network = DMCNetwork(cfg, device='cpu', epsilon=0.0)
    return DMCInferenceNet(network.net)


def _build_static_obs_int32() -> np.ndarray:
    """Minimal static_obs as int32(Go wire dtype)— layout 同
    ``test_socket_decoder_dmc_dispatch._build_static_obs_int32``。"""
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE

    meta_size = _N_COUNTER_SLOTS * 3
    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    hook_size = _N_HOOKS * _MAX_OPS_PER_HOOK * _FIELDS_PER_OP

    counter_meta = np.zeros(meta_size, dtype=np.int32)
    for i in range(_N_COUNTER_SLOTS):
        counter_meta[i * 3 + 1] = 100  # max(active)
        counter_meta[i * 3 + 2] = i  # sid ∈ [0, n_slots)

    char_skill_refs = -np.ones(refs_size, dtype=np.int32)
    hook_ir = np.zeros(hook_size, dtype=np.int32)
    hook_ir[0] = 1  # hook[0] op[0] opcode=1 → non_empty

    return np.concatenate([counter_meta, char_skill_refs, hook_ir])


def _build_dyn_obs_np() -> np.ndarray:
    from training.core.step_encoding import typed_segment_offsets

    off = typed_segment_offsets(_N_COUNTER_SLOTS)
    return np.zeros(off['ml_end'], dtype=np.float32)


def _build_socket_request(client_id: int, req_id: int, *, embed_static: bool) -> InferRequest:
    """Build a SocketInferRequest carrying int32 static_obs + f32 dyn_obs。

    refs/pay 必须 padded 到 max_actions(Route A 的 socket_request_to_pickled_payload
    fail-loud 校验)。 embed_static=False 时 static 空 → server 走 hash cache。
    """
    static_obs_int32 = _build_static_obs_int32()
    static_f32 = static_obs_int32.astype(np.float32)
    static_hash = hashlib.sha256(static_f32.tobytes()).digest()[:16]
    return InferRequest(
        static_hash=static_hash,
        client_id=client_id,
        req_id=req_id,
        dyn_obs=_build_dyn_obs_np(),
        refs=np.zeros(_MAX_ACTIONS * 3, dtype=np.int64),
        pay=np.zeros(_MAX_ACTIONS * 8, dtype=np.float32),
        static=static_obs_int32 if embed_static else np.zeros(0, dtype=np.int32),
    )


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
    """InfServer spawn with socket_port → Python TCP client connects → req → resp(Route A)。

    走真 DMCInferenceNet + decode_dmc_request — Route A 唯一 socket 路径,验证 socket
    请求经 request_q 批处理后正确回程。
    """
    port = _free_port()
    server = InferenceServer(
        network=_build_dmc_inference_net(),
        device='cpu',
        max_batch=1,
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        socket_payload_encoder_path='training.paradigms.dmc._socket_decoder.socket_request_to_pickled_payload',
        socket_port=port,
        socket_max_actions=_MAX_ACTIONS,
        socket_clients=1,
    )
    server.start(wait_ready_s=10.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        req = _build_socket_request(client_id=0, req_id=99, embed_static=True)
        client.sendall(encode_infer_request(req))
        resp_payload = _read_length_prefixed_from_socket(client)
        resp = decode_infer_response(resp_payload)
        client.close()

        assert resp.status == INFER_STATUS_OK, f'forward returned ERR: {resp.err_msg!r}'
        assert resp.logits is not None
        assert len(resp.logits) == _MAX_ACTIONS, f'logits len {len(resp.logits)} != max_actions {_MAX_ACTIONS}'
    finally:
        server.stop()


def test_inference_server_socket_cache_hit_second_request():
    """第二个请求不带 static(size 0)→ server 走 hash cache → 仍 OK(Route A)。"""
    port = _free_port()
    server = InferenceServer(
        network=_build_dmc_inference_net(),
        device='cpu',
        max_batch=1,
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        socket_payload_encoder_path='training.paradigms.dmc._socket_decoder.socket_request_to_pickled_payload',
        socket_port=port,
        socket_max_actions=_MAX_ACTIONS,
        socket_clients=1,
    )
    server.start(wait_ready_s=10.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))

        # First request embeds static → server caches by hash.
        req1 = _build_socket_request(client_id=0, req_id=1, embed_static=True)
        client.sendall(encode_infer_request(req1))
        resp1 = decode_infer_response(_read_length_prefixed_from_socket(client))
        assert resp1.status == INFER_STATUS_OK

        # Second request omits static → cache hit by hash.
        req2 = _build_socket_request(client_id=0, req_id=2, embed_static=False)
        client.sendall(encode_infer_request(req2))
        resp2 = decode_infer_response(_read_length_prefixed_from_socket(client))
        client.close()

        assert resp2.status == INFER_STATUS_OK, f'cache-hit request failed: {resp2.err_msg!r}'
        assert len(resp2.logits) == _MAX_ACTIONS
    finally:
        server.stop()


def test_inference_server_socket_concurrent_multi_client():
    """N socket client 并发各发 1 请求 → Route A 批处理路径(socket_clients>1,
    触发 _run_batched_path)+ 每 client 经独立 response_qs 拿回各自响应,无串话/死锁。

    此前 socket integration 测试全 socket_clients=1 / max_batch=1 → batched 路径
    (_run_batched_path + DMCInferenceNet.batched_forward 经 socket)零覆盖
    (I29 T-RR.4 review #7)。 threading.Barrier 同步起跑,使 N 请求并发入 request_q。
    """
    n = 3
    port = _free_port()
    server = InferenceServer(
        network=_build_dmc_inference_net(),
        device='cpu',
        max_batch=n,
        request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
        socket_payload_encoder_path='training.paradigms.dmc._socket_decoder.socket_request_to_pickled_payload',
        socket_port=port,
        socket_max_actions=_MAX_ACTIONS,
        socket_clients=n,
    )
    server.start(wait_ready_s=10.0)
    results: dict = {}
    errors: list = []
    barrier = threading.Barrier(n)

    def _client(cid: int) -> None:
        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.connect(('127.0.0.1', port))
            req = _build_socket_request(client_id=cid, req_id=100 + cid, embed_static=True)
            barrier.wait(timeout=10.0)  # 同步起跑 → N 请求并发入 request_q,逼出 batch>1
            conn.sendall(encode_infer_request(req))
            resp = decode_infer_response(_read_length_prefixed_from_socket(conn))
            conn.close()
            results[cid] = resp
        except Exception as exc:  # noqa: BLE001 — 收集到主线程断言
            errors.append((cid, exc))

    try:
        threads = [threading.Thread(target=_client, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
        assert not errors, f'client error(s): {errors}'
        assert len(results) == n, f'only {len(results)}/{n} clients got a response'
        for cid in range(n):
            resp = results[cid]
            assert resp.status == INFER_STATUS_OK, f'client {cid} ERR: {resp.err_msg!r}'
            assert resp.logits is not None and len(resp.logits) == _MAX_ACTIONS
    finally:
        server.stop()


def test_inference_server_socket_route_a_requires_decoder_and_max_actions():
    """Route A:socket_port > 0 但 request_decoder_path 缺 / socket_max_actions=0 → fail-loud。

    _server_loop 在 socket listener 分支前校验,违约即 ready_event.set + stop_event.set
    + raise(子进程 ready signal 到达但 listener 未起 → start() 看到 proc 已死)。
    """
    port = _free_port()
    # socket_max_actions=0 + no request_decoder_path → server 子进程 raise。
    server = InferenceServer(
        network=_build_dmc_inference_net(),
        device='cpu',
        max_batch=1,
        socket_port=port,
        socket_max_actions=0,
        socket_clients=1,
    )
    try:
        server.start(wait_ready_s=10.0)
        # ready_event set 后 _server_loop raise → 进程退出。
        assert server._proc is not None
        server._proc.join(timeout=5.0)
        assert not server._proc.is_alive(), 'server should die on Route A contract violation'
        assert server._proc.exitcode not in (0, None), 'server should exit non-zero on RuntimeError'
    finally:
        server.stop()


def test_inference_server_no_socket_when_port_zero():
    """socket_port=0 (default) 时无 listener — InfServer 跑 mp.Queue 原路径,启动正常。"""
    server = InferenceServer(network=_build_dmc_inference_net(), device='cpu', max_batch=1, socket_port=0)
    server.start(wait_ready_s=5.0)
    try:
        assert server._proc is not None
        assert server._proc.is_alive()
    finally:
        server.stop()
