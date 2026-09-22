"""train_value: noise-fit sanity, learnable-signal fit, artifact reload, reward validation."""

import json
import math
from dataclasses import replace
import random

import pytest
import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.player_loader import (
    FORMAT,
    load_semantic_agent,
    load_semantic_payload,
)
from tools.experiments.semantic_training.teams import with_teams
from tools.experiments.semantic_training.train_value import (
    SIGNED_OUTCOME,
    _load_episode,
    _resolve_reward_encoding,
    _to_target,
    run,
)
from tools.experiments.semantic_training.value_baseline import (
    EXPECTED_SCORE,
    SIGNED_OUTCOME as VALUE_SIGNED,
    WIN_PROBABILITY,
    attach,
    convert_value_head_state,
    make_optimizer,
    predict,
)
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def _make_agent(tmp_path):
    """Untrained semantic-Q checkpoint with a zero-init value head."""
    torch.set_num_threads(1)
    cfg = load_cfg('configs/dmc/native_starter.toml')
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    agent = SemanticAgent(shape)
    value_head = attach(agent)
    ckpt = tmp_path / 'agent.pt'
    save_checkpoint(
        {
            'format': FORMAT,
            'shape': vars(shape),
            'net': agent.net.state_dict(),
            'value_head': value_head.state_dict(),
        },
        ckpt,
    )
    return ckpt


def _collect_obs(agent, n_envs, rows_per_env, seed):
    """Real obs dicts from small random-play envs; one episode per ``rows_per_env`` obs."""
    rng = random.Random(seed)
    obs_list = []
    cfg = load_cfg('configs/dmc/native_starter.toml')
    others = [n for n in cfg.scenario.char_pool if n != '凯亚']
    for i in range(n_envs):
        dice = [rng.randrange(9) for _ in range(8)]
        cfg_i = with_teams(cfg, ['凯亚'] + others[:2], others[3:6])
        cfg_i = replace(cfg_i, scenario=replace(cfg_i.scenario, fix_dice=dice))
        env = make_env_factory(cfg_i, None, seed + i)(0, layout_seed=seed + 1000 + i)
        env.reset(seed=seed + 2000 + i)
        agent.game_start(env.static_obs)
        while env.phase == 1 and not env.done:
            env.step(0)
        taken = 0
        while not env.done and taken < rows_per_env:
            if env.acting_player == 0:
                obs = agent.observation(env)
                if obs:
                    obs_list.append(obs)
                    taken += 1
            kinds, _ = env.get_legal_actions()
            env.step(rng.randrange(len(kinds)))
        env.close()
    return obs_list


def _write_episodes(directory, obs_list, rows_per_env, reward_fn):
    """Mimic rl_rollout files: rows plus terminal ``reward``/``side``, constant per episode."""
    directory.mkdir(parents=True, exist_ok=True)
    n_episodes = len(obs_list) // rows_per_env
    for ep in range(n_episodes):
        chunk = obs_list[ep * rows_per_env : (ep + 1) * rows_per_env]
        rows = [{'obs': obs, 'action': 0, 'old_logp': 0.0, 'old_value': 0.5} for obs in chunk]
        for row in rows:
            row.update(reward=reward_fn(ep, chunk[0]), reward_encoding='win_probability', side=0)
        torch.save(rows, directory / f'episode_{ep:05d}.pt')
    return n_episodes


def _finite_metrics(metrics):
    return all(not isinstance(value, float) or math.isfinite(value) for value in metrics.values())


def test_noise_rewards_fit_nothing(tmp_path):
    ckpt = _make_agent(tmp_path)
    agent = load_semantic_agent(ckpt)
    rows_per_env = 4
    obs_list = _collect_obs(agent, 24, rows_per_env, seed=74001)
    rollouts = tmp_path / 'rollouts'
    rng = random.Random(5)
    rewards = {ep: float(rng.randrange(2)) for ep in range(len(obs_list) // rows_per_env)}
    n_episodes = _write_episodes(rollouts, obs_list, rows_per_env, lambda ep, _o: rewards[ep])
    output = tmp_path / 'out'
    report = run(
        'configs/dmc/native_starter.toml',
        str(ckpt),
        [str(rollouts)],
        str(output),
        episodes=n_episodes,
        steps=150,
        batch_size=32,
        device='cpu',
    )
    new = report['heldout']['new_head']
    assert _finite_metrics(new)
    assert new['r2'] is not None and abs(new['r2']) < 0.5
    old = report['heldout']['old_head']
    assert old is not None and old['n'] == new['n'] and math.isfinite(old['mse'])
    assert report['heldout']['mse_ratio_new_over_old'] is not None
    saved = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert saved['heldout']['new_head']['n'] == new['n']
    assert saved['train_rows'] == report['train_rows']
    assert saved['train_rows'] > 0 and saved['heldout_rows'] > 0
    assert (output / 'value_head.pt').exists()
    assert (output / 'agent_with_value.pt').exists()


def test_signal_rewards_learn_and_artifacts_load(tmp_path):
    ckpt = _make_agent(tmp_path)
    agent = load_semantic_agent(ckpt)
    rows_per_env = 4
    obs_list = _collect_obs(agent, 30, rows_per_env, seed=74000)
    n_episodes = len(obs_list) // rows_per_env
    low = min(obs_list, key=lambda obs: float(obs['meta'].sum()))
    high = max(obs_list, key=lambda obs: float(obs['meta'].sum()))
    obs_list = [high if ep % 2 else low for ep in range(n_episodes) for _ in range(rows_per_env)]
    rollouts = tmp_path / 'rollouts'
    _write_episodes(
        rollouts,
        obs_list,
        rows_per_env,
        lambda ep, _o: float(ep % 2),
    )
    output = tmp_path / 'out'
    report = run(
        'configs/dmc/native_starter.toml',
        str(ckpt),
        [str(rollouts)],
        str(output),
        episodes=n_episodes,
        steps=600,
        batch_size=32,
        device='cpu',
    )
    new = report['heldout']['new_head']
    assert new['pearson'] is not None and new['pearson'] > 0.6
    assert new['spearman'] is not None and new['spearman'] > 0.5
    assert new['r2'] is not None and new['r2'] > 0.3
    assert 0 < len(new['calibration_deciles']) <= 10

    # value_head.pt loads into a fresh head of the same architecture.
    fresh = load_semantic_agent(ckpt)
    head_state = torch.load(output / 'value_head.pt', map_location='cpu', weights_only=False)
    attach(fresh).load_state_dict(head_state)

    # agent_with_value.pt preserves the original envelope and swaps only value_head.
    payload = load_semantic_payload(output / 'agent_with_value.pt')
    assert payload['value_encoding'] == EXPECTED_SCORE
    assert payload['value_perspective'] == 'acting_player'
    assert payload['return_definition'] == 'terminal_expected_score'
    original = load_semantic_payload(ckpt)
    assert payload['format'] == original['format']
    assert payload['shape'] == original['shape']
    for key, tensor in original['net'].items():
        assert torch.equal(payload['net'][key], tensor)
    assert any(
        not torch.equal(payload['value_head'][key], original['value_head'][key]) for key in original['value_head']
    )
    reloaded = load_semantic_agent(str(output / 'agent_with_value.pt'))
    _logits, value = predict(reloaded, obs_list[0])
    assert math.isfinite(value)


def test_value_optimizer_restores_checkpoint_head(tmp_path):
    ckpt = _make_agent(tmp_path)
    payload = load_semantic_payload(ckpt)
    expected = {key: value.clone() for key, value in payload['value_head'].items()}
    agent = load_semantic_agent(ckpt)
    make_optimizer(agent, expected)
    for key, value in agent.value_head.state_dict().items():
        assert torch.equal(value, expected[key])


def test_value_encoding_conversion_and_probability_checkpoint_loader(tmp_path):
    ckpt = _make_agent(tmp_path)
    payload = load_semantic_payload(ckpt, verify_provenance=False)
    probability = {key: value.clone() for key, value in payload['value_head'].items()}
    probability['layers.2.bias'].fill_(0.25)
    signed = convert_value_head_state(probability, WIN_PROBABILITY, VALUE_SIGNED)
    assert torch.equal(signed['layers.2.bias'], torch.tensor([-0.5]))
    restored = convert_value_head_state(signed, VALUE_SIGNED, WIN_PROBABILITY)
    torch.testing.assert_close(restored['layers.2.bias'], probability['layers.2.bias'])
    canonical = convert_value_head_state(probability, WIN_PROBABILITY, EXPECTED_SCORE)
    torch.testing.assert_close(canonical['layers.2.bias'], probability['layers.2.bias'])
    canonical_signed = convert_value_head_state(canonical, EXPECTED_SCORE, VALUE_SIGNED)
    torch.testing.assert_close(canonical_signed['layers.2.bias'], signed['layers.2.bias'])
    payload['value_head'] = probability
    payload['value_encoding'] = WIN_PROBABILITY
    path = tmp_path / 'probability.pt'
    save_checkpoint(payload, path)
    loaded = load_semantic_agent(path)
    assert loaded.value_encoding == VALUE_SIGNED
    torch.testing.assert_close(loaded.value_head.layers[-1].bias, torch.tensor([-0.5]))


def test_invalid_reward_rejected(tmp_path):
    torch.save([{'obs': {}, 'reward': 0.7}], tmp_path / 'episode_00000.pt')
    with pytest.raises(AssertionError, match='unexpected reward'):
        _load_episode(tmp_path / 'episode_00000.pt')


def test_signed_draw_maps_to_half():
    assert _to_target(0.0, SIGNED_OUTCOME) == 0.5


def test_unmarked_zero_reward_requires_explicit_encoding(tmp_path):
    path = tmp_path / 'episode_00000.pt'
    torch.save([{'obs': {}, 'reward': 0.0}], path)
    with pytest.raises(ValueError, match='ambiguous'):
        _resolve_reward_encoding([path], 'auto')


def test_allow_unverified_checkpoint_is_forwarded_to_value_training(monkeypatch):
    calls = []

    def load_agent(path, *, device, verify_provenance):
        calls.append(('agent', verify_provenance))
        raise RuntimeError('stop after flag forwarding')

    monkeypatch.setattr('tools.experiments.semantic_training.train_value.load_semantic_agent', load_agent)
    monkeypatch.setattr('tools.experiments.semantic_training.train_value.plan_episodes', lambda *_args: [])
    with pytest.raises(RuntimeError, match='stop after flag forwarding'):
        run(
            'configs/dmc/native_starter.toml',
            'missing.pt',
            [],
            str(monkeypatch),
            episodes=1,
            device='cpu',
            allow_unverified_checkpoint=True,
        )
    assert calls == [('agent', False)]
