"""decode_dmc_requests (batched) — 数值等价 + schema 测试。

ROI 杠杆:14 个 request 一次 H2D + 1 个 op launch / tensor vs 14 次 串行。
production Win 实测 decode 占 InfServer 总 wall 69.6% (35.7 ms),batched
化是降 fps 瓶颈最直接的杠杆。本测试守 batched decode 与 per-request decode
N + cat 数值 bit-exact,不允许 silent 数值漂移。
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest
import torch

from training.core.obs_constants import (
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
)
from training.core.step_encoding import typed_segment_offsets
from training.paradigms.dmc._decoder import decode_dmc_request, decode_dmc_requests


@pytest.fixture
def fake_static_cache():
    """Pre-baked static cache — 跳过 _server_encode_static(需 hook_encoder)。

    包含 batched decoder 所需所有 static field, batch=1 form."""
    n_counter_slots = 4
    d_model = 8
    n_active_hooks = 3
    return {
        'counter_sids': torch.zeros((1, n_counter_slots), dtype=torch.long),
        'active_slot_mask': torch.ones((1, n_counter_slots), dtype=torch.bool),
        'hook_emb': torch.randn(1, n_active_hooks, d_model),
        'hook_mask': torch.ones((1, n_active_hooks), dtype=torch.bool),
        'char_skill_refs': torch.zeros((1, 2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR), dtype=torch.long),
        'structural_obspos': torch.zeros((1, n_counter_slots), dtype=torch.long),
        'n_counter_slots': n_counter_slots,
    }


def _make_payload(n_counter_slots: int, max_actions: int, seed: int) -> dict:
    """构造一个合法 dyn_obs payload — typed_segment_offsets 算总长 + 随机填值。"""
    rng = np.random.default_rng(seed)
    off = typed_segment_offsets(n_counter_slots)
    dyn_dim = off['ml_end']
    dyn_obs = rng.standard_normal(dyn_dim).astype(np.float32)
    refs_padded = rng.integers(0, 10, size=(max_actions, 3)).astype(np.int64)
    pay_padded = rng.standard_normal((max_actions, 4)).astype(np.float32)
    return {
        'static_obs_hash': b'fake_hash_shared',
        'dyn_obs': dyn_obs,
        'refs_padded': refs_padded,
        'pay_padded': pay_padded,
    }


def test_batched_decode_numerically_equivalent_to_per_request_cat(fake_static_cache):
    """N=4 batched decode == N 次 per-request decode + cat,逐 key bit-exact。"""
    shared_cache = {b'fake_hash_shared': fake_static_cache}
    n_counter_slots = fake_static_cache['n_counter_slots']
    max_actions = 8

    payloads_dict = [_make_payload(n_counter_slots, max_actions, seed=s) for s in range(4)]
    payloads_bytes = [(pickle.dumps(p), None) for p in payloads_dict]

    # Per-request baseline.
    per_request: list[dict] = []
    for obs_bytes, mask_bytes in payloads_bytes:
        d, _ = decode_dmc_request(obs_bytes, mask_bytes, 'cpu', shared_cache, network=None)
        per_request.append(d)
    keys = list(per_request[0].keys())
    expected = {k: torch.cat([d[k] for d in per_request], dim=0) for k in keys}

    # Batched.
    actual, _mask = decode_dmc_requests(payloads_bytes, 'cpu', shared_cache, network=None)

    assert set(actual.keys()) == set(expected.keys())
    for k in keys:
        e = expected[k]
        a = actual[k]
        assert a.shape == e.shape, f'key {k!r}: batched shape {a.shape} != per-request cat {e.shape}'
        assert a.dtype == e.dtype, f'key {k!r}: dtype mismatch'
        assert torch.equal(a, e), f'key {k!r}: batched != per-request cat (bit-exact required)'


def test_batched_decode_empty_raises(fake_static_cache):
    """N=0 不该过 — payload list 为空时 fail loud。"""
    shared_cache = {b'fake_hash_shared': fake_static_cache}
    with pytest.raises(ValueError, match='empty'):
        decode_dmc_requests([], 'cpu', shared_cache, network=None)


def test_batched_decode_single_request_works(fake_static_cache):
    """N=1 等价于 decode_dmc_request 一次。"""
    shared_cache = {b'fake_hash_shared': fake_static_cache}
    n_counter_slots = fake_static_cache['n_counter_slots']
    p = _make_payload(n_counter_slots, max_actions=8, seed=42)
    pb = pickle.dumps(p)

    single, _ = decode_dmc_request(pb, None, 'cpu', shared_cache, network=None)
    batched, _ = decode_dmc_requests([(pb, None)], 'cpu', shared_cache, network=None)
    for k in single.keys():
        assert torch.equal(single[k], batched[k]), f'key {k!r}: N=1 batched != single decode'


def test_batched_decode_missing_static_hash_raises(fake_static_cache):
    """Payload 缺 static_obs_hash → RuntimeError(防 silent 用 stale embedding)。"""
    shared_cache = {b'fake_hash_shared': fake_static_cache}
    n_counter_slots = fake_static_cache['n_counter_slots']
    p = _make_payload(n_counter_slots, max_actions=8, seed=0)
    del p['static_obs_hash']
    with pytest.raises(RuntimeError, match='missing static_obs_hash'):
        decode_dmc_requests([(pickle.dumps(p), None)], 'cpu', shared_cache, network=None)


def test_batched_decode_cache_miss_no_static_obs_raises(fake_static_cache):
    """Cache miss + 不带 static_obs → fail loud(同单 decode 行为)。"""
    shared_cache: dict = {}  # empty,no cached entry
    n_counter_slots = fake_static_cache['n_counter_slots']
    p = _make_payload(n_counter_slots, max_actions=8, seed=0)
    p['static_obs_hash'] = b'missing_hash'
    # 不带 static_obs。
    with pytest.raises(RuntimeError, match='cache miss'):
        decode_dmc_requests([(pickle.dumps(p), None)], 'cpu', shared_cache, network=None)
