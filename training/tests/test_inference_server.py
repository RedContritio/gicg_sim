"""Tests for training/inference_server.py.

Covers:
  - Server lifecycle (start, push_weights, stop)
  - Protocol round-trip: game_start → eval → game_end on a single pipe
  - Numerical parity between server-batched eval and local Agent eval
  - Weight sync: pushing new weights changes subsequent eval outputs

These run an actual subprocess via multiprocessing.spawn — they're
~2-3s each due to interpreter startup. Kept small (n_workers=1 or 2)
so the full suite stays under 20s.
"""

from __future__ import annotations

import os
import time

import numpy as np
import pytest
import torch

from gicg_env import GicgEnv
from training.core.inference.server import InferenceServer, InferenceServerConfig
from training.paradigms.az.network import Agent, AgentConfig

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

# Small shapes matching the bundled 赤蝶 smoke scenario.
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS = 900
MAX_TOK = 64
MAX_ACTIONS = 256
D_MODEL = 16


def _cfg() -> AgentConfig:
    return AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )


def _build_env() -> GicgEnv:
    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=0, data_dir=DATA_DIR)
    env.reset(seed=0)
    while env._engine.phase == 1:
        env.step(0)
        if env.done:
            break
    return env


def _cpu_state_dict(agent: Agent) -> dict:
    return {k: v.detach().cpu() for k, v in agent.net.state_dict().items()}


@pytest.fixture
def env_state():
    """Build a fresh env in PhaseAction and pull a single rollout's
    worth of inputs (static_obs, dyn, refs, payments)."""
    env = _build_env()
    try:
        static = env.static_obs.copy()
        dyn = env._get_obs().copy()
        refs = env.get_action_refs().copy()
        payments = env.get_legal_action_payments().copy()
        return static, dyn, refs, payments
    finally:
        env.close()


class TestInferenceServerLifecycle:
    def test_start_and_stop_clean(self):
        torch.manual_seed(0)
        srv = InferenceServer(_cfg(), n_workers=1)
        srv.start()
        srv.stop()
        # Second stop is a no-op (idempotent).
        srv.stop()

    def test_game_start_eval_game_end_roundtrip(self, env_state):
        static, dyn, refs, payments = env_state
        torch.manual_seed(0)
        srv = InferenceServer(_cfg(), n_workers=1)
        srv.start()
        pipe = srv.get_worker_pipe(0)
        try:
            pipe.send(
                {
                    'kind': 'game_start',
                    'worker_id': 0,
                    'game_id': 0,
                    'static_obs': static,
                }
            )
            resp = pipe.recv()
            assert resp['kind'] == 'game_start_ack'
            gs = resp['game_static']
            assert set(gs.keys()) == {
                'hook_ir',
                'hook_mask',
                'counter_sids',
                'active_slot_mask',
                'char_skill_refs',
            }

            pipe.send(
                {
                    'kind': 'eval',
                    'worker_id': 0,
                    'game_id': 0,
                    'dyn': dyn,
                    'refs': refs,
                    'payments': payments,
                }
            )
            resp = pipe.recv()
            assert resp['kind'] == 'eval_ack'
            prior = resp['prior']
            value = resp['value']
            assert prior.shape == (len(refs),)
            assert abs(prior.sum() - 1.0) < 1e-4
            assert -1.0 <= value <= 1.0

            pipe.send(
                {
                    'kind': 'game_end',
                    'worker_id': 0,
                    'game_id': 0,
                }
            )
            resp = pipe.recv()
            assert resp['kind'] == 'game_end_ack'
        finally:
            srv.stop()


class TestInferenceServerParity:
    def test_server_eval_matches_local_agent(self, env_state):
        """End-to-end: same seed + same weights → server eval and
        local Agent eval return bit-equal prior / value."""
        static, dyn, refs, payments = env_state

        torch.manual_seed(42)
        local = Agent(_cfg())
        # Ensure server starts with identical weights.
        sd = _cpu_state_dict(local)

        srv = InferenceServer(_cfg(), n_workers=1)
        srv.start()
        srv.push_weights(sd)
        # Give the server a moment to apply the weight update.
        time.sleep(0.2)

        pipe = srv.get_worker_pipe(0)
        try:
            pipe.send(
                {
                    'kind': 'game_start',
                    'worker_id': 0,
                    'game_id': 0,
                    'static_obs': static,
                }
            )
            pipe.recv()
            pipe.send(
                {
                    'kind': 'eval',
                    'worker_id': 0,
                    'game_id': 0,
                    'dyn': dyn,
                    'refs': refs,
                    'payments': payments,
                }
            )
            resp = pipe.recv()
            server_prior = resp['prior']
            server_value = resp['value']

            # Local reference
            local.game_start(static)
            local_prior, local_value = local.eval_state(dyn, refs, payments)

            np.testing.assert_allclose(server_prior, local_prior, atol=1e-5)
            assert abs(server_value - local_value) < 1e-5
        finally:
            srv.stop()


class TestInferenceServerWeightVersion:
    def test_game_start_ack_reports_version_after_pushes(self, env_state):
        """Each weight_update the server applies bumps its
        ``weight_version`` counter. Subsequent ``game_start`` acks
        must report the current version so main can compute the
        stale-gap per game."""
        static, _dyn, _refs, _pay = env_state

        torch.manual_seed(0)
        local = Agent(_cfg())
        srv = InferenceServer(_cfg(), n_workers=1)
        srv.start()
        try:
            # Push 3 weight updates BEFORE the first game_start.
            for _ in range(3):
                srv.push_weights(_cpu_state_dict(local))
            time.sleep(0.2)

            pipe = srv.get_worker_pipe(0)
            pipe.send(
                {
                    'kind': 'game_start',
                    'worker_id': 0,
                    'game_id': 0,
                    'static_obs': static,
                }
            )
            resp = pipe.recv()
            assert resp['kind'] == 'game_start_ack'
            assert resp['weight_version'] >= 3, (
                f'expected weight_version >= 3 after 3 pushes, got {resp["weight_version"]}'
            )
        finally:
            srv.stop()


class TestInferenceServerWeightSync:
    def test_push_weights_changes_output(self, env_state):
        """Eval result must change after a weight push with perturbed
        weights. If it doesn't, the server isn't applying updates."""
        static, dyn, refs, payments = env_state

        torch.manual_seed(100)
        srv = InferenceServer(_cfg(), n_workers=1)
        srv.start()
        pipe = srv.get_worker_pipe(0)
        try:
            pipe.send(
                {
                    'kind': 'game_start',
                    'worker_id': 0,
                    'game_id': 0,
                    'static_obs': static,
                }
            )
            pipe.recv()
            pipe.send(
                {
                    'kind': 'eval',
                    'worker_id': 0,
                    'game_id': 0,
                    'dyn': dyn,
                    'refs': refs,
                    'payments': payments,
                }
            )
            before = pipe.recv()['prior'].copy()

            # Perturb a fresh local agent and push its weights.
            torch.manual_seed(999)
            perturbed = Agent(_cfg())
            srv.push_weights(_cpu_state_dict(perturbed))
            time.sleep(0.2)

            pipe.send(
                {
                    'kind': 'eval',
                    'worker_id': 0,
                    'game_id': 0,
                    'dyn': dyn,
                    'refs': refs,
                    'payments': payments,
                }
            )
            after = pipe.recv()['prior']
            # Some entry must have changed.
            assert not np.allclose(before, after, atol=1e-6), 'server ignored weight update — prior unchanged'
        finally:
            srv.stop()
