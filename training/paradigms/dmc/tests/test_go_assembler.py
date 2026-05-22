"""DmcTransitionAssembler unit tests — verify Go socket transition → DmcTransition assembly。

走 encode_dmc_payload 构造合成 transition,assembler.ingest → assemble。 不依赖 actual
Go pool — 纯 Python unit。
"""

from __future__ import annotations

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import Transition, encode_dmc_payload
from training.paradigms.dmc._go_assembler import DmcTransitionAssembler


# Realistic scenario-level params (mirror StaticObsSize for typical 1-char-team game)
_SCENARIO = {
    'n_counter_slots': 32,
    'n_hooks': 64,
    'max_ops_per_hook': 8,
    'fields_per_op': 5,
    'max_actions': 30,
}


def _build_static_obs(n_counter_slots: int, n_hooks: int, max_ops_per_hook: int, fields_per_op: int) -> np.ndarray:
    """Stub static_obs with non-trivial structure — counter_meta + char_skill_refs + hook_ir。"""
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE, OBS_CHAR_ELEMENT_SLOTS

    meta_size = n_counter_slots * 3
    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    hook_size = n_hooks * max_ops_per_hook * fields_per_op
    elem_size = OBS_CHAR_ELEMENT_SLOTS
    total = meta_size + refs_size + hook_size + elem_size
    obs = np.arange(total, dtype=np.int32)
    return obs


def _build_dyn_obs(n_counter_slots: int) -> np.ndarray:
    """Stub dyn_obs sized to match scenario(real call goes through parse_dynamic_np)。"""
    # 走 parse_dynamic_np 算 dynamic obs size,这里 over-allocate 然后 trim
    # 实际 sizing logic 在 engine.DynamicObsSize();这里走个保守 4096
    return np.arange(4096, dtype=np.float32)


def _build_refs_pay(max_actions: int) -> tuple[np.ndarray, np.ndarray]:
    refs = np.arange(max_actions * 3, dtype=np.int64)
    pay = np.arange(max_actions * 8, dtype=np.float32)
    return refs, pay


def _build_payload(
    *,
    step: int,
    reward: float,
    static_hash: bytes,
    with_static: bool,
    n_legal: int = 5,
) -> bytes:
    static_obs = (
        _build_static_obs(
            _SCENARIO['n_counter_slots'],
            _SCENARIO['n_hooks'],
            _SCENARIO['max_ops_per_hook'],
            _SCENARIO['fields_per_op'],
        )
        if with_static
        else None
    )
    refs, pay = _build_refs_pay(_SCENARIO['max_actions'])
    return encode_dmc_payload(
        chosen_action=0,
        step_in_episode=step,
        reward=reward,
        n_legal=n_legal,
        static_hash=static_hash,
        dyn_obs=_build_dyn_obs(_SCENARIO['n_counter_slots']),
        refs=refs,
        pay=pay,
        static=static_obs,
    )


def test_assembler_single_episode_win():
    """Single episode 3-transition,last done=True reward=+1 → winner=1。"""
    hash_ = b'\xaa' * 16
    a = DmcTransitionAssembler(**_SCENARIO)

    # Step 0 — first transition carries static
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=False,
            payload=_build_payload(step=0, reward=0.0, static_hash=hash_, with_static=True),
        )
    )
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=1,
            done=False,
            payload=_build_payload(step=1, reward=0.0, static_hash=hash_, with_static=False),
        )
    )
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=2,
            done=True,
            payload=_build_payload(step=2, reward=1.0, static_hash=hash_, with_static=False),
        )
    )

    ready = a.drain_ready()
    assert len(ready) == 1
    ep = ready[0]
    assert ep.client_id == 0
    assert ep.episode_id == 1
    assert ep.winner == 1  # +1 reward → won
    assert len(ep.transitions) == 3
    for t in ep.transitions:
        # Each DmcTransition.obs_dict contains the parsed fields
        assert 'action_refs' in t.obs_dict
        assert 'action_payments' in t.obs_dict
        assert 'counter_sids' in t.obs_dict


def test_assembler_loss():
    """Final reward -1 → winner=-1。"""
    hash_ = b'\xbb' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=False,
            payload=_build_payload(step=0, reward=0.0, static_hash=hash_, with_static=True),
        )
    )
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=1,
            done=True,
            payload=_build_payload(step=1, reward=-1.0, static_hash=hash_, with_static=False),
        )
    )
    ready = a.drain_ready()
    assert len(ready) == 1
    assert ready[0].winner == -1


def test_assembler_draw():
    """Final reward 0 → winner=0(timeout / draw)。"""
    hash_ = b'\xcc' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=True,
            payload=_build_payload(step=0, reward=0.0, static_hash=hash_, with_static=True),
        )
    )
    ready = a.drain_ready()
    assert len(ready) == 1
    assert ready[0].winner == 0


def test_assembler_multi_episode_shared_static_cache():
    """N actor 同 scenario 共享 static cache — episode 2 不带 static 也能 assemble。"""
    hash_ = b'\xdd' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    # Actor 0 episode 1 — carries static
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=True,
            payload=_build_payload(step=0, reward=1.0, static_hash=hash_, with_static=True),
        )
    )
    # Actor 1 episode 1 — does NOT carry static(其 episode 0 不 reach here scenario;但 cache hit)
    a.ingest(
        Transition(
            client_id=1,
            episode_id=1,
            step=0,
            done=True,
            payload=_build_payload(step=0, reward=-1.0, static_hash=hash_, with_static=False),
        )
    )
    ready = a.drain_ready()
    assert len(ready) == 2
    cids = sorted(e.client_id for e in ready)
    assert cids == [0, 1]
    # Stats — 1 static cache entry, 0 pending, 0 ready (just drained)
    s = a.stats()
    assert s['n_static_cache_entries'] == 1
    assert s['n_pending_episodes'] == 0
    assert s['n_ready_episodes'] == 0


def test_assembler_drain_clears():
    """drain_ready 后 stats 显示 0 ready。"""
    hash_ = b'\xee' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=True,
            payload=_build_payload(step=0, reward=1.0, static_hash=hash_, with_static=True),
        )
    )
    assert a.n_ready() == 1
    _ = a.drain_ready()
    assert a.n_ready() == 0


def test_assembler_pending_until_done():
    """非 done transition 保持 pending,不入 ready。"""
    hash_ = b'\xff' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=False,
            payload=_build_payload(step=0, reward=0.0, static_hash=hash_, with_static=True),
        )
    )
    assert a.n_pending() == 1
    assert a.n_ready() == 0


def test_assembler_static_cache_miss_drops(capsys):
    """First-transition forgot static + no cache hit → episode dropped + stderr warn。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    # 故意:第一 transition 没带 static + cache 空 → drop
    a.ingest(
        Transition(
            client_id=0,
            episode_id=1,
            step=0,
            done=True,
            payload=_build_payload(step=0, reward=1.0, static_hash=b'\x99' * 16, with_static=False),
        )
    )
    captured = capsys.readouterr()
    assert 'static cache miss' in captured.err
    assert a.n_ready() == 0


def test_assembler_terminal_marker_n_legal_zero():
    """Terminal marker(n_legal=0, done=True)finalize episode 但不产 DmcTransition。

    契约回归 for I29 T-RR.1:Go runEpisode 对所有 in-loop transition 置 Done=false,
    episode 末尾统一推一条 n_legal=0 的 terminal marker(Done=true)。 assembler 必须:
    assemble episode、winner 取自 marker reward、marker 自身不产 DmcTransition(因
    _capture_obs_np 对 n_legal==0 返 {})、_buffers 释放(no leak)。
    """
    hash_ = b'\x77' * 16
    a = DmcTransitionAssembler(**_SCENARIO)
    # 2 条真 transition,Done=false
    a.ingest(
        Transition(
            client_id=3,
            episode_id=9,
            step=0,
            done=False,
            payload=_build_payload(step=0, reward=0.0, static_hash=hash_, with_static=True),
        )
    )
    a.ingest(
        Transition(
            client_id=3,
            episode_id=9,
            step=1,
            done=False,
            payload=_build_payload(step=1, reward=0.0, static_hash=hash_, with_static=False),
        )
    )
    # terminal marker — n_legal=0, done=True, reward=+1
    marker = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=2,
        reward=1.0,
        n_legal=0,
        static_hash=hash_,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
        static=None,
    )
    a.ingest(Transition(client_id=3, episode_id=9, step=2, done=True, payload=marker))

    ready = a.drain_ready()
    assert len(ready) == 1
    ep = ready[0]
    assert ep.winner == 1  # winner 取自 marker reward
    assert len(ep.transitions) == 2  # marker 不产 DmcTransition
    assert a.n_pending() == 0  # _buffers 释放 — 无泄漏


def test_assembler_decode_error_does_not_crash(capsys):
    """Wire 解码失败 → drop transition + stderr 报错,不 raise。"""
    a = DmcTransitionAssembler(**_SCENARIO)
    bad_payload = b'\x00' * 5  # < header size
    a.ingest(Transition(client_id=0, episode_id=1, step=0, done=True, payload=bad_payload))
    captured = capsys.readouterr()
    assert 'decode error' in captured.err
    assert a.n_ready() == 0
    assert a.n_pending() == 0  # buffer 没被分配(早 return)
