"""Verify that assembler.ingest emits the 4 expected perf-trace spans.

Pattern mirrors training/tests/test_perf_trace.py — enable_explicit + configure +
ingest 2 transitions (non-terminal + terminal) + close + parse jsonl.

Reuses payload-building helpers from test_go_assembler.py (local module, same dir).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import training.core.perf.trace as _trace_mod
from training.core.actor.transition_sink_wire import Transition, encode_dmc_payload
from training.paradigms.dmc._go_assembler import DmcTransitionAssembler


_SCENARIO = {
    'n_counter_slots': 32,
    'n_hooks': 64,
    'max_ops_per_hook': 8,
    'fields_per_op': 5,
    'max_actions': 30,
}


def _static_obs() -> np.ndarray:
    from training.core.obs_constants import OBS_CHAR_SKILL_REFS_SIZE, OBS_CHAR_ELEMENT_SLOTS

    s = _SCENARIO
    total = s['n_counter_slots'] * 3 + OBS_CHAR_SKILL_REFS_SIZE + s['n_hooks'] * s['max_ops_per_hook'] * s['fields_per_op'] + OBS_CHAR_ELEMENT_SLOTS
    return np.arange(total, dtype=np.int32)


def _payload(step: int, reward: float, static_hash: bytes, with_static: bool, n_legal: int = 5) -> bytes:
    refs = np.arange(n_legal * 3, dtype=np.int64)
    pay = np.arange(n_legal * 8, dtype=np.float32)
    return encode_dmc_payload(
        chosen_action=0,
        step_in_episode=step,
        reward=reward,
        n_legal=n_legal,
        static_hash=static_hash,
        dyn_obs=np.arange(4096, dtype=np.float32),
        refs=refs,
        pay=pay,
        static=_static_obs() if with_static else None,
    )


@pytest.fixture
def perf_on(tmp_path):
    _trace_mod.enable_explicit(flush_window=5, flush_interval_s=1.0, log_dir=str(tmp_path))
    yield _trace_mod, tmp_path
    try:
        _trace_mod.close()
    except Exception:
        pass
    _trace_mod._ENABLED = False
    _trace_mod._state = None
    _trace_mod._FLUSH_WINDOW = 200
    _trace_mod._FLUSH_INTERVAL_S = 1.0
    _trace_mod._LOG_DIR = 'artifacts/_perf_logs'


def test_assembler_perf_spans_all_four_stages(perf_on):
    """ingest non-terminal + terminal → 4 span names all appear in perf jsonl。"""
    trace, tmp_path = perf_on
    trace.configure(role='test', id=0)

    hash_ = b'\xbb' * 16
    a = DmcTransitionAssembler(**_SCENARIO)

    # Non-terminal: emits decode_payload + append_buffer (no try_assemble)
    a.ingest(Transition(client_id=0, episode_id=1, step=0, done=False, payload=_payload(0, 0.0, hash_, True)))
    # Terminal: emits decode_payload + append_buffer + try_assemble
    a.ingest(Transition(client_id=0, episode_id=1, step=1, done=True, payload=_payload(1, 1.0, hash_, False)))

    trace.close()

    log = tmp_path / 'test_0.jsonl'
    assert log.exists(), 'perf trace log not created'
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert rows, 'perf trace log is empty'

    all_stages: set[str] = set()
    for row in rows:
        all_stages.update(row.get('stages', {}).keys())

    expected = {'assembler.decode_payload', 'assembler.append_buffer', 'assembler.try_assemble'}
    missing = expected - all_stages
    assert not missing, f'missing perf spans: {missing}  (found: {all_stages})'
