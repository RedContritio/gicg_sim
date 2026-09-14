"""DmcTransitionAssembler.ingest_episode unit tests — F1 episode-granularity fast path。

Tests:
1. ingest_episode win/loss/draw → correct winner
2. ingest_episode terminal marker not producing DmcTransition
3. ingest_episode static cache populate
4. ingest_episode static cache hit (second episode, no static in payload)
5. ingest_episode static cache miss → drop + stderr
6. ingest_episode decode error → drop + stderr, no crash
7. ingest_episode + drain_ready sequence
"""

from __future__ import annotations

from training.paradigms.dmc.tests.test_go_assembler import _build_dyn_obs

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import EpisodeBatch, Transition, encode_dmc_payload
from training.paradigms.dmc._go_assembler import DmcTransitionAssembler

# ─── Fixture ──────────────────────────────────────────────────────────────────

_SCENARIO = {
    'n_counter_slots': 32,
    'n_hooks': 64,
    'max_ops_per_hook': 8,
    'fields_per_op': 5,
    'max_actions': 30,
}


def _build_static_obs() -> np.ndarray:
    from training.core.obs_constants import (
        OBS_CHAR_ELEMENT_SLOTS,
        OBS_CHAR_SKILL_REFS_SIZE,
        OBS_DEFINITION_LINK_SCHEMA_VERSION,
        OBS_DEFINITION_LINK_SLOTS,
    )

    n = _SCENARIO['n_counter_slots']
    h = _SCENARIO['n_hooks']
    moph = _SCENARIO['max_ops_per_hook']
    fpo = _SCENARIO['fields_per_op']
    total = n * 3 + OBS_CHAR_SKILL_REFS_SIZE + h * moph * fpo + OBS_CHAR_ELEMENT_SLOTS
    trailer = np.zeros(OBS_DEFINITION_LINK_SLOTS, dtype=np.int32)
    trailer[0] = OBS_DEFINITION_LINK_SCHEMA_VERSION
    return np.concatenate((np.arange(total, dtype=np.int32), trailer))


def _make_payload(
    *,
    step: int,
    reward: float,
    static_hash: bytes,
    with_static: bool,
    n_legal: int = 5,
) -> bytes:
    static = _build_static_obs() if with_static else None
    n_legal_eff = n_legal
    dyn = np.zeros_like(_build_dyn_obs(_SCENARIO['n_counter_slots']))
    refs = np.zeros(n_legal_eff * 3, dtype=np.int64)
    pay = np.zeros(n_legal_eff * 8, dtype=np.float32)
    return encode_dmc_payload(
        chosen_action=0,
        step_in_episode=step,
        reward=reward,
        n_legal=n_legal_eff,
        static_hash=static_hash,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        static=static,
    )


def _make_episode_batch(
    client_id: int,
    episode_id: int,
    *,
    static_hash: bytes,
    n_steps: int,
    reward: float,
) -> EpisodeBatch:
    """Build an EpisodeBatch with n_steps non-terminal transitions + terminal marker。"""
    txs = []
    for step in range(n_steps):
        with_static = step == 0
        txs.append(
            Transition(
                client_id=client_id,
                episode_id=episode_id,
                step=step,
                done=False,
                payload=_make_payload(
                    step=step,
                    reward=0.0,
                    static_hash=static_hash,
                    with_static=with_static,
                ),
            )
        )
    # terminal marker: n_legal=0, done=True
    marker = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=n_steps,
        reward=reward,
        n_legal=0,
        static_hash=static_hash,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
        static=None,
    )
    txs.append(Transition(client_id=client_id, episode_id=episode_id, step=n_steps, done=True, payload=marker))
    return EpisodeBatch(client_id=client_id, episode_id=episode_id, transitions=txs)


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_ingest_episode_win():
    """ingest_episode reward=+1 → winner=1, n_transitions = n_steps。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xaa' * 16
    batch = _make_episode_batch(0, 1, static_hash=h, n_steps=3, reward=1.0)
    a.ingest_episode(batch)
    ready = a.drain_ready()
    assert len(ready) == 1
    ep = ready[0]
    assert ep.winner == 1
    assert ep.client_id == 0
    assert ep.episode_id == 1
    assert len(ep.transitions) == 3  # marker (n_legal=0) doesn't produce DmcTransition


def test_ingest_episode_loss():
    """ingest_episode reward=-1 → winner=-1。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xbb' * 16
    batch = _make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=-1.0)
    a.ingest_episode(batch)
    ready = a.drain_ready()
    assert len(ready) == 1
    assert ready[0].winner == -1


def test_ingest_episode_draw():
    """ingest_episode reward=0 → winner=0。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xcc' * 16
    batch = _make_episode_batch(0, 1, static_hash=h, n_steps=1, reward=0.0)
    a.ingest_episode(batch)
    ready = a.drain_ready()
    assert len(ready) == 1
    assert ready[0].winner == 0


def test_ingest_episode_drain_clears():
    """drain_ready after ingest_episode clears ready queue。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xdd' * 16
    a.ingest_episode(_make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=1.0))
    assert a.n_ready() == 1
    _ = a.drain_ready()
    assert a.n_ready() == 0


def test_ingest_episode_no_pending_after_done():
    """After ingest_episode, _buffers should not retain the episode。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xee' * 16
    a.ingest_episode(_make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=1.0))
    assert a.n_pending() == 0


def test_ingest_episode_static_cache_populate():
    """First episode populates static cache。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\x11' * 16
    a.ingest_episode(_make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=1.0))
    s = a.stats()
    assert s['n_static_cache_entries'] == 1


def test_ingest_episode_static_cache_hit():
    """Second episode same hash, no static in batch → assembles via cache hit。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\x22' * 16
    # First episode carries static
    a.ingest_episode(_make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=1.0))
    # Second episode — no static (all with_static=False from step 1 onward, but first trans has it)
    # Build manually: 2 steps no static, terminal marker
    txs = []
    for step in range(2):
        txs.append(
            Transition(
                client_id=0,
                episode_id=2,
                step=step,
                done=False,
                payload=_make_payload(step=step, reward=0.0, static_hash=h, with_static=False),
            )
        )
    marker_payload = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=2,
        reward=-1.0,
        n_legal=0,
        static_hash=h,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    txs.append(Transition(client_id=0, episode_id=2, step=2, done=True, payload=marker_payload))
    batch2 = EpisodeBatch(client_id=0, episode_id=2, transitions=txs)
    a.ingest_episode(batch2)
    ready = a.drain_ready()
    assert len(ready) == 2
    winners = {ep.episode_id: ep.winner for ep in ready}
    assert winners[1] == 1
    assert winners[2] == -1
    # Still only 1 cache entry (same hash)
    assert a.stats()['n_static_cache_entries'] == 1


def test_ingest_episode_static_cache_miss_drops(capsys):
    """No static in any transition, empty cache → episode dropped + stderr warn。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\x33' * 16
    # Build batch without static anywhere
    txs = [
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=True,
            payload=_make_payload(step=0, reward=1.0, static_hash=h, with_static=False),
        )
    ]
    batch = EpisodeBatch(client_id=0, episode_id=1, transitions=txs)
    a.ingest_episode(batch)
    captured = capsys.readouterr()
    assert 'static cache miss' in captured.err
    assert a.n_ready() == 0


def test_ingest_episode_decode_error_no_crash(capsys):
    """Corrupt payload → drop episode + stderr, no crash, no ready。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    bad_tx = Transition(client_id=0, episode_id=1, step=0, done=True, payload=b'\x00' * 5)
    batch = EpisodeBatch(client_id=0, episode_id=1, transitions=[bad_tx])
    a.ingest_episode(batch)
    captured = capsys.readouterr()
    assert 'decode error' in captured.err
    assert a.n_ready() == 0
    assert a.n_pending() == 0


def test_ingest_episode_obs_dict_correct():
    """DmcTransitions produced by ingest_episode contain obs_dict keys。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\x55' * 16
    batch = _make_episode_batch(0, 1, static_hash=h, n_steps=2, reward=1.0)
    a.ingest_episode(batch)
    ready = a.drain_ready()
    assert len(ready) == 1
    for t in ready[0].transitions:
        assert 'action_refs' in t.obs_dict
        assert 'action_payments' in t.obs_dict
        assert 'counter_sids' in t.obs_dict


# ─── IPC Risk #5 (2026-05-28 audit): stale-episode + eviction-with-age ────────


def _make_pending_batch(client_id: int, episode_id: int, static_hash: bytes) -> EpisodeBatch:
    """Build a batch with done=False so episode stays in _buffers (orphan candidate)。"""
    txs = [
        Transition(
            client_id=client_id,
            episode_id=episode_id,
            step=0,
            done=False,
            payload=_make_payload(step=0, reward=0.0, static_hash=static_hash, with_static=True),
        )
    ]
    return EpisodeBatch(client_id=client_id, episode_id=episode_id, transitions=txs)


def test_stale_episode_detected_after_threshold(monkeypatch):
    """IPC Risk #5:ingest non-done batch (留 LRU),时间 fast-forward 超 STALE
    threshold → stats n_stale_episodes 报 1。 下次 long-run train 直接 grep 看
    actor crash orphan 趋势。"""
    from training.paradigms.dmc._go_assembler import STALE_EPISODE_THRESHOLD_S
    import training.paradigms.dmc._go_assembler as _asm

    a = DmcTransitionAssembler(**_SCENARIO)
    h = b'\xaa' * 16

    # ingest at t=100
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 100.0)
    a.ingest_episode(_make_pending_batch(0, 1, h))
    assert a.n_pending() == 1

    # Half threshold elapsed → not stale yet
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 100.0 + STALE_EPISODE_THRESHOLD_S / 2)
    assert a.stats()['n_stale_episodes'] == 0

    # Beyond threshold → stale
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 100.0 + STALE_EPISODE_THRESHOLD_S + 1)
    assert a.stats()['n_stale_episodes'] == 1


def test_eviction_warn_includes_age(monkeypatch, capsys):
    """IPC Risk #5:LRU evict 触发时 stderr 必须报 age=Xs 让 debug 看 orphan 卡多久。"""
    import training.paradigms.dmc._go_assembler as _asm

    a = DmcTransitionAssembler(**_SCENARIO, max_inflight_episodes=2)
    h = b'\xbb' * 16

    # ep_id=1 created at t=100
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 100.0)
    a.ingest_episode(_make_pending_batch(0, 1, h))
    # ep_id=2 at t=130
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 130.0)
    a.ingest_episode(_make_pending_batch(0, 2, h))
    # ep_id=3 at t=160 → triggers evict of ep_id=1 (oldest, age=60s)
    monkeypatch.setattr(_asm.time, 'monotonic', lambda: 160.0)
    a.ingest_episode(_make_pending_batch(0, 3, h))

    captured = capsys.readouterr()
    assert 'evicting client=0 ep=1' in captured.err
    assert 'age=60.0s' in captured.err
    assert 'actor crash suspected' in captured.err
    assert a.stats()['n_evicted_inflight'] == 1
