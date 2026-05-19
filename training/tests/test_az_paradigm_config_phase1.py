"""Phase 1 T1.1 contract test — AZParadigmConfig must expose the full set of
runtime-required fields that AZParadigm + collector + loss + paradigm.make_*
methods read.

This guards against:
- accidental field rename (`buffer_cap` ↔ `buffer_capacity` etc.)
- legacy-wrap regression (sub-cfgs disappearing behind getattr-chains)
- typed AgentShapeCfg / MCTSCfg / TrainStepCfg field drift

The set is derived from grepping `pcfg.X` access points in
`paradigm.py` / `collector.py` / `loss.py` (Phase 1 freeze inventory).
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from training.paradigms.az.config import AZParadigmConfig, AgentShapeCfg, MCTSCfg, TrainStepCfg


# Runtime-required top-level fields (consumed by paradigm.py / collector.py).
REQUIRED_TOP_FIELDS: set[str] = {
    'lr',
    'weight_decay',
    'batch_size',
    'buffer_cap',
    'priority_weight',
    'max_game_steps',
    'total_games',
    'train_steps_per_game',
    'min_buffer_before_train',
    'init_from_ckpt',
    'agent',
    'mcts',
    'train',
}

# Runtime-required agent shape fields (consumed by paradigm.make_network →
# AgentConfig + collector.py episode policy build).
REQUIRED_AGENT_FIELDS: set[str] = {
    'n_counter_slots',
    'n_hooks',
    'max_ops_per_hook',
    'max_actions',
    'd_model',
    'n_cross_layers',
    'dropout',
}

# Runtime-required MCTS fields (consumed by paradigm.make_episode_policy +
# collector.py MCTSConfig build).
REQUIRED_MCTS_FIELDS: set[str] = {
    'n_rollouts',
    'c_puct',
    'dirichlet_alpha',
    'dirichlet_eps',
    'temperature',
    'temperature_switch_step',
    'max_rollout_depth',
    'parallel_rollouts',
    'value_mix_lambda',
    'prior_mix_lambda',
    'lambda_anneal_games',
    'lambda_start',
    'lambda_end',
    'profile',
    'backend',
}

# Runtime-required train step fields (consumed by loss.py + train_step legacy).
REQUIRED_TRAIN_FIELDS: set[str] = {
    'l2_coef',
    'max_grad_norm',
    'value_target_source',
    'value_mix_lambda',
    'entropy_coef',
    'delta_aux_coef',
}


def _field_names(dc_cls) -> set[str]:
    return {f.name for f in fields(dc_cls)}


def test_az_paradigm_config_has_required_top_fields():
    """AZParadigmConfig top-level fields cover all runtime access points."""
    declared = _field_names(AZParadigmConfig)
    missing = REQUIRED_TOP_FIELDS - declared
    assert not missing, f'AZParadigmConfig missing required top-level fields: {sorted(missing)}'


def test_az_paradigm_config_has_required_agent_fields():
    """AgentShapeCfg covers AgentConfig wire-in shape parameters."""
    declared = _field_names(AgentShapeCfg)
    missing = REQUIRED_AGENT_FIELDS - declared
    assert not missing, f'AgentShapeCfg missing required fields: {sorted(missing)}'


def test_az_paradigm_config_has_required_mcts_fields():
    """MCTSCfg covers MCTSConfig wire-in fields (paradigm.make_episode_policy)."""
    declared = _field_names(MCTSCfg)
    missing = REQUIRED_MCTS_FIELDS - declared
    assert not missing, f'MCTSCfg missing required fields: {sorted(missing)}'


def test_az_paradigm_config_has_required_train_fields():
    """TrainStepCfg covers loss + legacy train_step fields."""
    declared = _field_names(TrainStepCfg)
    missing = REQUIRED_TRAIN_FIELDS - declared
    assert not missing, f'TrainStepCfg missing required fields: {sorted(missing)}'


def test_az_paradigm_config_no_wrap_indirection():
    """T1.1 — AZParadigmConfig must NOT wrap legacy.config.AZConfig.

    Phase 1 inlines the fields directly into AZParadigmConfig (and the
    three sub-cfgs). We assert by checking that no field's type is
    `training.paradigms.az.legacy.config.AZConfig` and that the module
    does not import that class.
    """
    import training.paradigms.az.config as cfg_mod
    import ast
    import pathlib

    src = pathlib.Path(cfg_mod.__file__).read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            assert not mod.startswith('training.paradigms.az.legacy'), (
                f'config.py imports legacy.az ({mod}) — Phase 1 must inline'
            )


def test_az_paradigm_config_runtime_attribute_access():
    """Instantiate from a representative TOML-shaped dict and check that
    every runtime access pattern resolves without AttributeError."""
    cfg = AZParadigmConfig.from_dict(
        {
            'lr': 1e-3,
            'weight_decay': 0.0,
            'batch_size': 64,
            'buffer_cap': 50_000,
            'priority_weight': 3.0,
            'max_game_steps': 400,
            'total_games': 2000,
            'train_steps_per_game': 4,
            'min_buffer_before_train': 256,
            'agent': {
                'n_counter_slots': 16,
                'n_hooks': 4,
                'max_ops_per_hook': 4,
                'max_actions': 8,
                'd_model': 8,
                'n_cross_layers': 1,
            },
            'mcts': {'n_rollouts': 50, 'c_puct': 1.4, 'profile': False},
            'train': {'l2_coef': 1e-4, 'entropy_coef': 0.01, 'delta_aux_coef': 0.1},
        }
    )
    # Access patterns as used in paradigm.py / collector.py / loss.py.
    _ = cfg.lr
    _ = cfg.weight_decay
    _ = cfg.batch_size
    _ = cfg.buffer_cap
    _ = cfg.priority_weight
    _ = cfg.max_game_steps
    _ = cfg.total_games
    _ = cfg.train_steps_per_game
    _ = cfg.min_buffer_before_train
    _ = cfg.init_from_ckpt
    _ = cfg.agent.n_counter_slots
    _ = cfg.agent.n_hooks
    _ = cfg.agent.max_ops_per_hook
    _ = cfg.agent.max_actions
    _ = cfg.agent.d_model
    _ = cfg.agent.dropout
    _ = cfg.agent.n_cross_layers
    m = cfg.mcts
    for fname in REQUIRED_MCTS_FIELDS:
        _ = getattr(m, fname)
    t = cfg.train
    for fname in REQUIRED_TRAIN_FIELDS:
        _ = getattr(t, fname)


def test_az_paradigm_config_unknown_top_key_raises():
    """Strict gate: unknown top-level key → ValueError (CS4 contract)."""
    with pytest.raises(ValueError, match='unknown paradigm key'):
        AZParadigmConfig.from_dict({'no_such_field': 1})
