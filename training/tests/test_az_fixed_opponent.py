"""Fixed-opponent (non-mirror) AZ selfplay — ExIt 支线 tests.

Covers the three layers of the fixed-opponent slice (CPU, seconds):

- ``FixedOpponentCfg`` parsing / validation (default None = mirror,
  byte-identical legacy behavior).
- ``FixedOpponentPool`` sampling semantics (greedy/random/historical
  ring, cold-start fallback, seeded determinism).
- ``play_vs_opponent_game`` full-game smoke vs GreedyPlayer F1-D1:
  buffer rows present, row schema identical to the mirror path
  (STEP_DYNAMIC_KEYS), z_target uniformly from the AGENT seat's
  perspective, pi_target a proper distribution.
- ``AZParadigm.make_collector`` both branches (mirror / fixed), the
  async + fixed_opponent explicit NotImplementedError, and
  ``make_opponent_pool`` historical snapshot player end-to-end.
"""

from __future__ import annotations

import os
import random

import pytest

from gicg_env import GicgEnv
from training.core.matchup.greedy_player import GreedyPlayer
from training.paradigms.az import AZParadigm
from training.paradigms.az._opponent import (
    AZSnapshotPlayer,
    FixedOpponentPool,
    RandomPlayer,
)
from training.paradigms.az.buffer import STEP_DYNAMIC_KEYS
from training.paradigms.az.collector import AZSelfPlayCollector
from training.paradigms.az.config import AZParadigmConfig, FixedOpponentCfg
from training.paradigms.az.determinize import SharedFixedPool
from training.paradigms.az.mcts import MCTSConfig
from training.paradigms.az.network import Agent, AgentConfig
from training.paradigms.az.selfplay import play_vs_opponent_game
from training.tests.smoke_template import SMOKE_MIRROR_DECK

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')

# Full DSL obs shape (mirrors test_selfplay.py) — selfplay's dynamic-obs
# parsing requires the real counter-slot layout even at tiny d_model.
N_COUNTER_SLOTS = 2 * 6 * 128 + 2 * 140 + 16
N_HOOKS = 900
MAX_TOK = 128
MAX_ACTIONS = 512
D_MODEL = 16

SELFPLAY_DECK = list(SMOKE_MIRROR_DECK)

# Mirror rows are exactly STEP_DYNAMIC_KEYS + 'buffs' (both produced by
# the shared ``_build_step_dict``); ReplayBuffer requires the
# STEP_DYNAMIC_KEYS subset.
EXPECTED_STEP_KEYS = set(STEP_DYNAMIC_KEYS) | {'buffs'}


def _make_agent(seed: int = 0) -> Agent:
    import torch

    torch.manual_seed(seed)
    cfg = AgentConfig(
        n_counter_slots=N_COUNTER_SLOTS,
        n_hooks=N_HOOKS,
        max_ops_per_hook=MAX_TOK,
        max_actions=MAX_ACTIONS,
        d_model=D_MODEL,
        n_cross_layers=1,
        dropout=0.0,
    )
    return Agent(cfg)


def _make_env(seed: int = 0) -> GicgEnv:
    # ADR-0011: explicit deck_padding pins the legacy 15-slot 碌碌无为
    # shape so the legal-action count stays under MAX_ACTIONS=512.
    env = GicgEnv(
        ['赤蝶'],
        ['赤蝶'],
        seed=seed,
        data_dir=DATA_DIR,
        deck_padding={'card': '碌碌无为', 'target_size': 15},
        pool=['v_legacy', 'test_basic'],
        decks=[SELFPLAY_DECK, SELFPLAY_DECK],
    )
    env.reset(seed=seed)
    return env


def _pool_refs(env: GicgEnv) -> list[int]:
    view = env.export_view()
    hand = view['players'][0]['hand']
    deck = view['players'][0]['deck_count']
    if not hand:
        return []
    filler = hand[0]['ref']
    return [c['ref'] for c in hand] + [filler] * deck


def _greedy_f1d1(seed: int = 0) -> GreedyPlayer:
    return GreedyPlayer(features='F1', depth=1, dice_greedy=True, seed=seed)


def _agent_perspective_z(winner: int) -> float:
    # Agent seat is fixed at player 0 this slice.
    return {0: 1.0, 1: -1.0, 2: 0.0}[winner]


# ---------- FixedOpponentCfg parsing ---------- #


def test_fixed_opponent_default_none_is_mirror():
    cfg = AZParadigmConfig.from_dict({})
    assert cfg.fixed_opponent is None


def test_fixed_opponent_from_dict_greedy_spec():
    cfg = AZParadigmConfig.from_dict(
        {'fixed_opponent': {'type': 'greedy', 'features': 'F1', 'depth': 1, 'dice_greedy': True}}
    )
    fo = cfg.fixed_opponent
    assert isinstance(fo, FixedOpponentCfg)
    assert fo.depth == 1
    assert fo.greedy == 1.0 and fo.random == 0.0 and fo.historical == 0.0


def test_fixed_opponent_weight_sum_validated():
    with pytest.raises(ValueError, match='weights must sum to 1.0'):
        AZParadigmConfig.from_dict({'fixed_opponent': {'random': 0.5}})


def test_fixed_opponent_unknown_key_raises():
    with pytest.raises(TypeError):
        AZParadigmConfig.from_dict({'fixed_opponent': {'no_such_field': 1}})


def test_fixed_opponent_dataclass_instance_passes_through():
    """from_dict_strict forwards non-dict section values unchanged."""
    fo = FixedOpponentCfg(depth=1)
    cfg = AZParadigmConfig.from_dict({'fixed_opponent': fo})
    assert cfg.fixed_opponent is fo


# ---------- FixedOpponentPool sampling ---------- #


def test_pool_sample_greedy_kind():
    pool = FixedOpponentPool(FixedOpponentCfg(depth=1), seed=3)
    player = pool.sample()
    assert isinstance(player, GreedyPlayer)
    assert player.cfg.depth == 1
    assert player.dice_greedy is True
    assert pool.last_kind == 'greedy'


def test_pool_mixed_weights_seeded_determinism():
    kinds = []
    for _ in range(2):
        pool = FixedOpponentPool(
            FixedOpponentCfg(depth=1, random=0.5, greedy=0.5),
            seed=7,
        )
        kinds.append([type(pool.sample()).__name__ for _ in range(8)])
    assert kinds[0] == kinds[1]


def test_pool_historical_cold_start_falls_back_random():
    pool = FixedOpponentPool(
        FixedOpponentCfg(depth=1, random=0.0, greedy=0.0, historical=1.0),
        seed=1,
    )
    assert isinstance(pool.sample(), RandomPlayer)
    assert pool.last_kind == 'random'


def test_pool_historical_factory_receives_ring_snapshot():
    seen = []

    def factory(sd):
        seen.append(sd)
        return object()

    pool = FixedOpponentPool(
        FixedOpponentCfg(depth=1, random=0.0, greedy=0.0, historical=1.0),
        agent_factory=factory,
        seed=1,
    )
    pool.add_snapshot({'net.w': 1.0})
    player = pool.sample()
    assert player is not None
    assert seen == [{'net.w': 1.0}]


def test_pool_state_dict_roundtrip_and_capacity_guard():
    pool = FixedOpponentPool(FixedOpponentCfg(depth=1), seed=5)
    pool.add_snapshot({'net.w': 1.0})
    sd = pool.state_dict()
    pool2 = FixedOpponentPool(FixedOpponentCfg(depth=1), seed=6)
    pool2.load_state_dict(sd)
    assert list(pool2._ring) == [{'net.w': 1.0}]
    with pytest.raises(ValueError, match='capacity mismatch'):
        FixedOpponentPool(FixedOpponentCfg(depth=1, ring_size=1), seed=6).load_state_dict(sd)


# ---------- play_vs_opponent_game smoke ---------- #


class TestPlayVsOpponentGame:
    def test_full_game_rows_schema_and_value_perspective(self):
        env = _make_env(seed=11)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=4, profile=False)
            result = play_vs_opponent_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(0),
                cfg,
                _greedy_f1d1(),
                max_game_steps=400,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            assert result.n_steps > 0
            assert result.winner in (0, 1, 2)
            expected_z = _agent_perspective_z(result.winner)
            for step in result.steps:
                # Row schema identical to the mirror path.
                assert set(step.keys()) == EXPECTED_STEP_KEYS
                assert '_acting_player' not in step
                # Value target from the AGENT seat's perspective on every row.
                assert step['z_target'] == expected_z
                # Agent policy target is a proper distribution.
                assert step['pi_target'].sum() == pytest.approx(1.0, abs=1e-5)
                assert step['legal_mask'].any()
        finally:
            env.close()

    def test_only_agent_rows_recorded(self):
        """Opponent turns must not produce buffer rows: every recorded row
        carries a real MCTS policy (non-degenerate) and the row count is
        strictly below the total number of env advances when the opponent
        acted (winner != agent in a lost game ⇒ opponent had turns)."""
        env = _make_env(seed=13)
        try:
            agent = _make_agent()
            pool = _pool_refs(env)
            cfg = MCTSConfig(n_rollouts=2, profile=False)
            result = play_vs_opponent_game(
                agent,
                env,
                SharedFixedPool(pool),
                random.Random(1),
                cfg,
                _greedy_f1d1(),
                max_game_steps=400,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            assert result.n_steps > 0
            # MCTS rows always carry counter targets except the final step.
            n_with_counter = sum(1 for s in result.steps if s['has_counter_target'])
            assert n_with_counter >= result.n_steps - 1
        finally:
            env.close()


# ---------- Collector + paradigm wiring ---------- #


def _build_full_az_cfg(paradigm_dict: dict | None = None):
    """TrainingConfig with the FULL obs shape so collect() can parse
    dynamic obs (tiny-shape cfgs are fine for make_collector only)."""
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    paradigm = {
        'lr': 1e-3,
        'batch_size': 8,
        'buffer_cap': 500,
        'agent': {
            'n_counter_slots': N_COUNTER_SLOTS,
            'n_hooks': N_HOOKS,
            'max_ops_per_hook': MAX_TOK,
            'max_actions': MAX_ACTIONS,
            'd_model': D_MODEL,
            'n_cross_layers': 1,
        },
        'mcts': {'n_rollouts': 4, 'profile': False},
    }
    if paradigm_dict:
        paradigm.update(paradigm_dict)
    return TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='test_az_fixed', device='cpu'),
        pipeline=PipelineCfg(mode='serial', num_actors=1),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['赤蝶'],
            pool=['v_legacy', 'test_basic'],
            max_rounds=10,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir=DATA_DIR,
            deck_0=SELFPLAY_DECK,
            deck_1=SELFPLAY_DECK,
        ),
        paradigm=paradigm,
        checkpoint=CheckpointCfg(save_every=1000, keep_last_n=3, artifacts_root='artifacts'),
    )


def _tiny_env_factory(seed: int = 0):
    def factory(_game_idx: int) -> GicgEnv:
        return _make_env(seed=seed)

    return factory


class TestCollectorFixedOpponent:
    def test_serial_collector_with_pool_collects_nonmirror_game(self):
        cfg = _build_full_az_cfg({'fixed_opponent': {'depth': 1, 'dice_greedy': True}})
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        pool = FixedOpponentPool(pcfg.fixed_opponent, seed=cfg.meta.seed + 1)
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=3), opponent_pool=pool)
        try:
            out = collector.collect(1, provider=None)
            assert out.n_units > 0
            trajectories = out.runtime_metrics['az_trajectories']
            assert len(trajectories) == 1
            game_static, steps = trajectories[0]
            assert len(steps) > 0
            winner = out.episode_stats[0]['winner']
            expected_z = _agent_perspective_z(winner)
            for step in steps:
                assert set(step.keys()) == EXPECTED_STEP_KEYS
                assert step['z_target'] == expected_z
            # state_dict carries the opponent pool section for resume.
            sd = collector.state_dict()
            assert 'opponent_pool' in sd
            collector.load_state_dict(sd)
        finally:
            collector.close()

    def test_serial_collector_default_is_mirror(self):
        cfg = _build_full_az_cfg()
        pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        collector = AZSelfPlayCollector(cfg, pcfg, network, _make_env(seed=3))
        try:
            assert collector._opponent_pool is None
            sd = collector.state_dict()
            assert 'opponent_pool' not in sd
        finally:
            collector.close()


class TestMakeCollectorBranches:
    def test_make_collector_mirror_branch_unchanged(self):
        cfg = _build_full_az_cfg()
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        collector = paradigm.make_collector(cfg, _tiny_env_factory(), network, opp_pool=None)
        try:
            assert isinstance(collector, AZSelfPlayCollector)
            assert collector._opponent_pool is None
        finally:
            collector.close()

    def test_make_collector_fixed_branch_builds_pool(self):
        cfg = _build_full_az_cfg({'fixed_opponent': {'depth': 1}})
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        collector = paradigm.make_collector(cfg, _tiny_env_factory(), network, opp_pool=None)
        try:
            assert isinstance(collector, AZSelfPlayCollector)
            assert isinstance(collector._opponent_pool, FixedOpponentPool)
        finally:
            collector.close()

    def test_make_collector_fixed_branch_uses_passed_pool(self):
        cfg = _build_full_az_cfg({'fixed_opponent': {'depth': 1}})
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        passed = FixedOpponentPool(FixedOpponentCfg(depth=1), seed=9)
        collector = paradigm.make_collector(cfg, _tiny_env_factory(), network, opp_pool=passed)
        try:
            assert collector._opponent_pool is passed
        finally:
            collector.close()

    def test_make_collector_async_fixed_opponent_wires_pool(self):
        """async + fixed_opponent: AZAsyncCollector with the parent pool
        (actors rebuild their own pools locally; ring rides the broadcast).
        Construction only — no processes until first collect."""
        from training.paradigms.az._async import AZAsyncCollector

        cfg = _build_full_az_cfg({'fixed_opponent': {'depth': 1}})
        object.__setattr__(cfg.pipeline, 'mode', 'async')
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        collector = paradigm.make_collector(cfg, None, network, opp_pool=None)
        try:
            assert isinstance(collector, AZAsyncCollector)
            assert isinstance(collector._opponent_pool, FixedOpponentPool)
            assert not collector._spawned
        finally:
            collector.close()


class TestMakeOpponentPool:
    def test_make_network_reuses_cached_instance(self):
        cfg = _build_full_az_cfg()
        paradigm = AZParadigm()
        first = paradigm.make_network(cfg)
        assert paradigm.make_network(cfg) is first

    def test_returns_none_for_mirror(self):
        cfg = _build_full_az_cfg()
        paradigm = AZParadigm()
        paradigm.make_network(cfg)
        assert paradigm.make_opponent_pool(cfg, None) is None

    def test_historical_snapshot_player_end_to_end(self):
        """Ring → snapshot player → full non-mirror game: the AZSnapshotPlayer
        must satisfy the select_action contract (game_start/eval_state/game_end
        bracketing) and the game must terminate with agent-perspective z."""
        cfg = _build_full_az_cfg(
            {
                'fixed_opponent': {'depth': 1, 'random': 0.0, 'greedy': 0.0, 'historical': 1.0},
                'mcts': {'n_rollouts': 2, 'profile': False},
            }
        )
        paradigm = AZParadigm()
        network = paradigm.make_network(cfg)
        pool = paradigm.make_opponent_pool(cfg, network)
        assert isinstance(pool, FixedOpponentPool)
        pool.add_snapshot(network.state_dict())  # pipeline ckpt shape (AZNetwork keys)
        opponent = pool.sample()
        assert isinstance(opponent, AZSnapshotPlayer)

        env = _make_env(seed=17)
        try:
            agent = _make_agent()
            card_pool = _pool_refs(env)
            mcts_cfg = MCTSConfig(n_rollouts=2, profile=False)
            result = play_vs_opponent_game(
                agent,
                env,
                SharedFixedPool(card_pool),
                random.Random(2),
                mcts_cfg,
                opponent,
                max_game_steps=400,
                n_counter_slots=N_COUNTER_SLOTS,
                max_actions=MAX_ACTIONS,
            )
            assert result.n_steps > 0
            expected_z = _agent_perspective_z(result.winner)
            for step in result.steps:
                assert step['z_target'] == expected_z
        finally:
            env.close()
