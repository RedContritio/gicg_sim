"""The pretraining gate must exercise the real environment without learning."""

import json

import pytest

from tools.experiments.prepare_training import DEFAULT_CONFIGS, prepare
from training.core.config.loader import load_cfg


def test_exact_configs_restore_and_infer_without_learning(tmp_path):
    report = prepare(DEFAULT_CONFIGS, [41], tmp_path / 'ready.json')
    assert report['status'] == 'passed' and report['training_started'] is False
    assert len(report['engine_sha256']) == 64
    for row in report['configs']:
        assert row['parameters'] > 0
        assert row['episodes'][0]['steps'] > 0
        assert row['episodes'][0]['multi_choice_pending'] == 0
    assert report['configs'][1]['episodes'][0]['cards']


def test_preflight_preserves_failure_seed_and_action_prefix(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError('injected transition divergence')

    monkeypatch.setattr('tools.experiments.prepare_training.transition', fail)
    output = tmp_path / 'failed.json'
    output.write_text('{"status": "passed"}')
    with pytest.raises(RuntimeError, match='injected'):
        prepare(DEFAULT_CONFIGS[:1], [41], output)
    trace = json.loads(output.with_suffix('.failure.json').read_text())
    assert trace['seed'] == 41 and trace['inputs'][0]['index'] >= 0
    assert trace['resolved_config']['scenario']['team_0'] == ['赤蝶']
    assert json.loads(output.read_text())['status'] == 'failed'


def test_adaptation_cards_are_excluded_from_training_pools():
    train = [load_cfg(path) for path in DEFAULT_CONFIGS]
    held = load_cfg('configs/dmc/readiness_holdout.toml')
    for cfg in train:
        assert not set(cfg.scenario.card_pool) & set(held.scenario.card_pool)
        assert cfg.paradigm['max_game_steps'] >= 512
        assert cfg.paradigm['eval_interval_episodes'] == 0
