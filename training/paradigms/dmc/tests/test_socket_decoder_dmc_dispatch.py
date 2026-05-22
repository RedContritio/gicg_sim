"""I29 P1.5 fix — verify socket forward callback handles production DMCNetwork。

Regression test for the I29 Win box stress blocker:DMCNetwork.forward 故意 raise
NotImplementedError(driver / loss 走 forward_batch,Player 走 select_action,
``__call__(obs_dict)`` 无合法语义),但 InfServer socket listener 直调
``network(obs_dict)``。 Production go_collector 装的 network 是 DMCNetwork(per
DMCParadigm.make_network),所以每 step=1 全 actor fatal NotImplementedError。

Pre-fix:test_inference_server_socket_integration / test_go_actor_perf_smoke /
test_go_collector_e2e 全用 _ZeroLogitsNet stub bypass 真 DMCNetwork — production
path 零覆盖。 本测试构 real DMCNetwork → wrap via DMCInferenceNet → forward 不抛
NotImplementedError + returns InferResponse with logits len = max_actions。

不跑 GicgEnv(避真 scenario 复杂度);用 _build_static_obs 模式构 minimal
static_obs + dyn_obs,只验 dispatch contract,not RL signal。
"""

from __future__ import annotations

import hashlib
import pickle

import numpy as np
import pytest
import torch

from training.core.network import AgentConfig
from training.core.actor.inference_server_socket_wire import (
    INFER_STATUS_OK,
    InferRequest as SocketInferRequest,
)
from training.paradigms.dmc.inference_net import DMCInferenceNet
from training.paradigms.dmc.network import DMCNetwork
from training.paradigms.dmc._socket_decoder import (
    build_dmc_socket_forward_callback,
    socket_request_to_pickled_payload,
)


# Sizes must match ActorCritic layout — small for fast test, but real shape。
# n_counter_slots 必须 ≥ N_STRUCTURAL(=66, obs_constants)— compute_structural_obspos
# 把 sid 当 scatter target index,sid 范围 [0, n_counter_slots) 决定 valid scatter dim,
# struct_readout 取 first N_STRUCTURAL — 小于 66 时 struct_readout Linear shape mismatch。
_N_COUNTER_SLOTS = 70  # > N_STRUCTURAL=66
_N_HOOKS = 4
_MAX_OPS_PER_HOOK = 2
_FIELDS_PER_OP = 5  # gicg_engine ObsFieldsPerOp
_MAX_ACTIONS = 6
_D_MODEL = 16


def _build_agent_cfg() -> AgentConfig:
    return AgentConfig(
        n_counter_slots=_N_COUNTER_SLOTS,
        n_hooks=_N_HOOKS,
        max_ops_per_hook=_MAX_OPS_PER_HOOK,
        max_actions=_MAX_ACTIONS,
        d_model=_D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )


def _build_static_obs_int32() -> np.ndarray:
    """Minimal static_obs as int32(Go wire dtype)。

    与 ``_server_encode_static`` 的 layout 一致(``decode_dmc_request`` 走
    ``np.ascontiguousarray(static_obs_np, dtype=np.float32)`` 把 int32 → float32
    by-value cast → sids 等小 int 在 .long() 时正确恢复):
    counter_meta(n_counter_slots × 3 int)+ char_skill_refs(OBS_CHAR_SKILL_REFS_SIZE int)
    + hook_ir(n_hooks × max_ops × fields int)。 SIDs ∈ [0, n_counter_slots) 必须 ≤
    structural scatter target dim(详 compute_structural_obspos:scatter_(1, sids, ...))。

    counter_meta 列序 = (min, max, sid)— ``_server_encode_static`` 通过
    ``(min != 0) | (max != 0)`` 判 active,sid := col[2]。
    """
    from training.core.obs_constants import (
        OBS_CHAR_SKILL_REFS_SIZE,
    )

    meta_size = _N_COUNTER_SLOTS * 3
    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    hook_size = _N_HOOKS * _MAX_OPS_PER_HOOK * _FIELDS_PER_OP

    # counter_meta:全 active(max=100)+ sid := slot index(0..n_slots-1,满足 scatter 边界)。
    counter_meta = np.zeros(meta_size, dtype=np.int32)
    for i in range(_N_COUNTER_SLOTS):
        counter_meta[i * 3 + 0] = 0  # min
        counter_meta[i * 3 + 1] = 100  # max(active)
        counter_meta[i * 3 + 2] = i  # sid ∈ [0, n_slots) — scatter target safe

    # char_skill_refs:全 -1(no chars/skills)— shape 正确即可,内容不重要。
    char_skill_refs = -np.ones(refs_size, dtype=np.int32)

    # hook_ir:第 1 个 hook 有 1 个非空 op(opcode != 0)→ n_active = 1。
    hook_ir = np.zeros(hook_size, dtype=np.int32)
    hook_ir[0] = 1  # hook[0] op[0] opcode=1 → non_empty

    return np.concatenate([counter_meta, char_skill_refs, hook_ir])


def _build_dyn_obs_np() -> np.ndarray:
    """Minimal dyn_obs matching ``decode_dmc_request`` layout for n_counter_slots。"""
    from training.core.obs_constants import (
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        OBS_META_SIZE,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
    )
    from training.core.step_encoding import typed_segment_offsets

    off = typed_segment_offsets(_N_COUNTER_SLOTS)
    n = off['ml_end']  # total dyn obs length
    return np.zeros(n, dtype=np.float32)


def _build_socket_request(static_obs_int32: np.ndarray, dyn_obs_np: np.ndarray) -> SocketInferRequest:
    """Build a SocketInferRequest carrying int32 static_obs + f32 dyn_obs + 1 legal action。

    static_hash 算法跟 Go side 一致(_server_encode_static / mp_factories.py 同样):
    int32 → float32 by-value cast → tobytes → sha256[:16]。
    """
    static_f32 = static_obs_int32.astype(np.float32)
    static_hash = hashlib.sha256(static_f32.tobytes()).digest()[:16]
    refs_flat = np.zeros(_MAX_ACTIONS * 3, dtype=np.int64)
    pay_flat = np.zeros(_MAX_ACTIONS * 8, dtype=np.float32)
    return SocketInferRequest(
        static_hash=static_hash,
        client_id=0,
        req_id=1,
        dyn_obs=dyn_obs_np,
        refs=refs_flat,
        pay=pay_flat,
        static=static_obs_int32,
    )


def test_dmcnetwork_socket_forward_does_not_raise_notimplementederror():
    """Regression:build_dmc_socket_forward_callback wraps DMCNetwork properly。

    Pre-fix:network(obs_dict) → DMCNetwork.forward → NotImplementedError → 全 actor
    step=1 fatal。 Fix wraps with DMCInferenceNet inside the builder,production path
    走 ActorCritic.forward via DMCInferenceNet。
    """
    cfg = _build_agent_cfg()
    network = DMCNetwork(cfg, device='cpu', epsilon=0.0)
    shared_cache: dict = {}

    cb = build_dmc_socket_forward_callback(
        device_str='cpu',
        shared_cache=shared_cache,
        network=network,
        max_actions=_MAX_ACTIONS,
    )

    static_obs_np = _build_static_obs_int32()
    dyn_obs_np = _build_dyn_obs_np()
    req = _build_socket_request(static_obs_np, dyn_obs_np)

    resp = cb(req)

    assert resp.status == INFER_STATUS_OK, f'forward callback returned ERR: {resp.err_msg!r}'
    assert resp.logits is not None, 'OK response should carry logits'
    assert resp.logits.dtype == np.float32
    assert len(resp.logits) == _MAX_ACTIONS, f'logits length {len(resp.logits)} != max_actions {_MAX_ACTIONS}'
    # Cache should be populated with the static_obs_hash.
    assert req.static_hash in shared_cache, 'expected static_obs_hash cached after first request'


def test_dmcnetwork_socket_forward_cache_hit_second_request():
    """Second request without embedded static (size 0) → cache hit by hash → no error。

    Verifies the production fast-path:actor on subsequent turns omits static (Go side
    sends static_n=0)+ server reuses cached hook_emb。
    """
    cfg = _build_agent_cfg()
    network = DMCNetwork(cfg, device='cpu', epsilon=0.0)
    shared_cache: dict = {}

    cb = build_dmc_socket_forward_callback(
        device_str='cpu',
        shared_cache=shared_cache,
        network=network,
        max_actions=_MAX_ACTIONS,
    )

    static_obs_np = _build_static_obs_int32()
    dyn_obs_np = _build_dyn_obs_np()

    # First request:embeds static → populates cache。
    req1 = _build_socket_request(static_obs_np, dyn_obs_np)
    resp1 = cb(req1)
    assert resp1.status == INFER_STATUS_OK
    assert req1.static_hash in shared_cache

    # Second request:no static embedded(size 0)→ cache lookup via hash。
    req2 = SocketInferRequest(
        static_hash=req1.static_hash,
        client_id=0,
        req_id=2,
        dyn_obs=dyn_obs_np,
        refs=np.zeros(_MAX_ACTIONS * 3, dtype=np.int64),
        pay=np.zeros(_MAX_ACTIONS * 8, dtype=np.float32),
        # static omitted = default zero-length int32 array → 'no static embedded'。
    )
    resp2 = cb(req2)
    assert resp2.status == INFER_STATUS_OK, f'second request failed: {resp2.err_msg!r}'
    assert len(resp2.logits) == _MAX_ACTIONS


def test_socket_forward_handles_test_stub_with_logit_as_q_key():
    """Test stubs(``_ZeroLogitsNet`` etc)return dict keyed by 'logit_as_q' — accepted。

    Backwards-compat with existing perf-smoke / integration tests using stub nets。
    """
    import torch.nn as nn

    class _StubNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.dummy = nn.Linear(1, _MAX_ACTIONS)

        def forward(self, obs_dict):  # noqa: ARG002
            return {'logit_as_q': torch.zeros(1, _MAX_ACTIONS)}

    shared_cache: dict = {'dummy': True}  # bypass decode_dmc_request via custom path?

    # _socket_decoder still calls decode_dmc_request which needs the network's
    # actor_critic attrs (n_counter_slots etc) — stub must expose them as
    # actor_critic-shaped。 Simplest:reuse DMCInferenceNet over a real ActorCritic
    # so decode works,then verify the dict 'logit_as_q' branch fires when an
    # unwrapped stub is passed directly。
    # Direct stub path:bypass via decode by injecting cache up-front。

    # Pre-populate the cache so decode never re-encodes static。
    cfg = _build_agent_cfg()
    real_network = DMCNetwork(cfg, device='cpu', epsilon=0.0)
    static_obs_np = _build_static_obs_int32()
    dyn_obs_np = _build_dyn_obs_np()
    req = _build_socket_request(static_obs_np, dyn_obs_np)

    # Warm cache via real network。
    cb_real = build_dmc_socket_forward_callback(
        device_str='cpu', shared_cache=shared_cache, network=real_network, max_actions=_MAX_ACTIONS
    )
    cb_real(req)
    assert req.static_hash in shared_cache

    # Now build callback with stub net + same cache → decode hits cache,
    # then forward goes through stub's 'logit_as_q' branch。
    stub = _StubNet()
    cb_stub = build_dmc_socket_forward_callback(
        device_str='cpu', shared_cache=shared_cache, network=stub, max_actions=_MAX_ACTIONS
    )
    req2 = SocketInferRequest(
        static_hash=req.static_hash,
        client_id=0,
        req_id=2,
        dyn_obs=dyn_obs_np,
        refs=np.zeros(_MAX_ACTIONS * 3, dtype=np.int64),
        pay=np.zeros(_MAX_ACTIONS * 8, dtype=np.float32),
    )
    # NOTE:cb_stub uses shared_cache 但 decode 内 ``_server_encode_static`` 是被
    # cache 接管(hit by hash)— stub 的 ``.net.hook_encoder`` 不会调用,所以
    # stub 不需要 real ActorCritic attrs。 Cache hit 是关键。
    resp = cb_stub(req2)
    assert resp.status == INFER_STATUS_OK, f'stub forward failed: {resp.err_msg!r}'
    assert len(resp.logits) == _MAX_ACTIONS


def test_socket_request_refs_size_mismatch_raises():
    """refs/pay size != max_actions padded → fail-loud ValueError(I29 T-RR.6)。

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
