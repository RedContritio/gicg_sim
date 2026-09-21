from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import torch
from fastapi.testclient import TestClient

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training import evaluate as semantic_evaluate
from tools.experiments.semantic_training.player_loader import FORMAT
from training.core.artifact_io import provenance, save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from web.backend.app import create_app
from web.backend import live_session, semantic_live


@pytest.fixture
def live_model(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    cfg_path = root / 'configs/dmc/native_starter.toml'
    ckpt_path = root / 'artifacts/model/semantic.pt'
    report_path = root / 'artifacts/eval/result.json'
    service_path = root / 'configs/web/semantic_live.toml'
    for path in (cfg_path, ckpt_path, report_path, service_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path('configs/dmc/native_starter.toml'), cfg_path)
    cfg = load_cfg(cfg_path)
    shape = AgentConfig(
        n_counter_slots=1832,
        n_hooks=900,
        max_ops_per_hook=128,
        max_actions=2048,
        d_model=8,
        n_cross_layers=1,
    )
    agent = SemanticAgent(shape)
    save_checkpoint({'format': FORMAT, 'shape': vars(shape), 'net': agent.net.state_dict()}, ckpt_path)
    report_path.write_text(
        json.dumps(
            {
                'status': 'complete',
                'checkpoint_sha256': hashlib.sha256(ckpt_path.read_bytes()).hexdigest(),
                'scenario': asdict(cfg.scenario),
                'provenance': provenance(),
                'score': 0.5,
                'opponent_depth': 2,
                'scenarios': 1,
                'layouts': 1,
            }
        ),
        encoding='utf-8',
    )
    service_path.write_text(
        '\n'.join(
            [
                'name = "test semantic model"',
                'type = "semantic_rl"',
                'cfg = "configs/dmc/native_starter.toml"',
                'ckpt = "artifacts/model/semantic.pt"',
                'report = "artifacts/eval/result.json"',
            ]
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(semantic_live, 'ROOT', root)
    monkeypatch.setattr(semantic_live, 'SERVICE_CONFIG', service_path)
    return root, ckpt_path, report_path


@pytest.mark.parametrize('side', [0, 1])
def test_semantic_websocket_uses_configured_profile(live_model, side):
    client = TestClient(create_app())
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json(
            {
                'type': 'new',
                'team_0': ['凯亚', '迪卢克', '芭芭拉'],
                'team_1': ['砂糖', '菲谢尔', '芭芭拉'],
                'human_player': side,
                'opponent': {'type': 'semantic_rl'},
                'seed': 146002,
            }
        )
        frame = ws.receive_json()
        assert frame['type'] == 'state', frame
        assert len(frame['view']['players'][side]['chars']) == 3
        assert all(char['name'] == '暗牌' for char in frame['view']['players'][1 - side]['hand'])
        assert frame['done'] or frame['current_player'] == side


def test_semantic_rules_report_and_independent_players(live_model):
    _, ckpt_path, _ = live_model
    profile = semantic_live.profile()
    assert profile['available'] is True
    assert profile['team_size'] == 3
    assert profile['allow_overlap'] is True
    with pytest.raises(ValueError, match='3 名'):
        semantic_live.build_session({'team_0': ['凯亚'], 'team_1': ['砂糖']}, 44, 0)
    with pytest.raises(ValueError, match='固定牌组'):
        semantic_live.build_session({'card_pool': []}, 44, 0)
    first = semantic_live.build_session({}, 44, 0)
    second = semantic_live.build_session({}, 45, 1)
    try:
        assert first.player is not second.player
        assert first.player.net is not second.player.net
        assert first.env.export_view()['round'] == 1
        assert first.player.select_action(first.env) >= 0
    finally:
        first.env.close()
        second.env.close()
    semantic_evaluate.initialize(str(semantic_live.load_service_definition()[0].cfg_path), str(ckpt_path))
    assert isinstance(semantic_evaluate._AGENT, SemanticAgent)
    assert semantic_evaluate._AGENT is not first.player

    web_session = semantic_live.build_session({}, 0, 0)
    eval_session = semantic_live.build_session({}, 0, 0)
    try:
        semantic_evaluate._AGENT.game_start(eval_session.env.static_obs)
        assert web_session.player.select_action(web_session.env) == semantic_evaluate._AGENT.select_action(
            eval_session.env
        )
    finally:
        web_session.env.close()
        eval_session.env.close()


def test_semantic_stale_report_does_not_block_model(live_model):
    root, _, report_path = live_model
    report = json.loads(report_path.read_text())
    report['checkpoint_sha256'] = '0' * 64
    report_path.write_text(json.dumps(report))
    current = semantic_live.profile()
    assert current['available'] is True
    assert current['evaluation'] == {}
    session = semantic_live.build_session({}, 1, 0)
    session.env.close()

    service = root / 'configs/web/semantic_live.toml'
    service.write_text(service.read_text().replace('artifacts/model/semantic.pt', '../outside.pt'))
    with pytest.raises(ValueError, match='artifacts'):
        semantic_live.load_service_definition()


def test_semantic_profile_handles_missing_model(live_model):
    _, ckpt_path, _ = live_model
    ckpt_path.unlink()
    missing = semantic_live.profile()
    assert missing['available'] is False
    assert missing['unavailable_reason'] == 'configured checkpoint is not installed'


def test_semantic_profile_allows_missing_report(live_model):
    root, _, report_path = live_model
    report_path.unlink()
    service_path = root / 'configs/web/semantic_live.toml'
    service_path.write_text(
        '\n'.join(line for line in service_path.read_text().splitlines() if not line.startswith('report ='))
    )

    current = semantic_live.profile()
    assert current['available'] is True
    assert current['evaluation'] == {}


def test_semantic_profile_hides_evaluation_with_wrong_fingerprint(live_model):
    _, _, report_path = live_model
    report = json.loads(report_path.read_text())
    report['provenance']['source_observation_sha256'] = '0' * 64
    report_path.write_text(json.dumps(report))
    current = semantic_live.profile()
    assert current['available'] is True
    assert current['unavailable_reason'] is None
    assert current['evaluation'] == {}


def test_profile_hides_evaluation_for_different_inference_behavior(live_model):
    _, _, report_path = live_model
    report = json.loads(report_path.read_text())
    report['player_spec'] = {'type': 'az', 'ckpt': '/evaluated/model.pt', 'n_simulations': 0}
    report_path.write_text(json.dumps(report))

    current = semantic_live.profile()
    assert current['available'] is True
    assert current['unavailable_reason'] is None
    assert current['evaluation'] == {}


def test_configured_inference_behavior_is_forwarded_to_player_loader(live_model, monkeypatch):
    root, _, report_path = live_model
    service_path = root / 'configs/web/semantic_live.toml'
    service_path.write_text(
        service_path.read_text().replace('type = "semantic_rl"', 'type = "az"')
        + '\nn_simulations = 16\nmax_rollout_depth = 77\n'
    )
    report = json.loads(report_path.read_text())
    report['player_spec'] = {
        'type': 'az',
        'ckpt': '/evaluated/model.pt',
        'n_simulations': 16,
        'max_rollout_depth': 77,
    }
    report_path.write_text(json.dumps(report))
    captured = {}

    class Player:
        def select_action(self, env):
            return 0

    def build_player(spec, seed, **kwargs):
        captured.update(spec=spec, seed=seed, kwargs=kwargs)
        return Player()

    monkeypatch.setattr(semantic_live, 'build_opponent_player', build_player)
    session = semantic_live.build_session({}, 51, 0)
    try:
        assert captured['spec'] == {
            'type': 'az',
            'ckpt': str((root / 'artifacts/model/semantic.pt').resolve()),
            'n_simulations': 16,
            'max_rollout_depth': 77,
        }
        assert semantic_live.profile()['inference'] == {
            'type': 'az',
            'n_simulations': 16,
            'max_rollout_depth': 77,
        }
    finally:
        session.env.close()


def test_player_cache_distinguishes_search_depth(tmp_path, monkeypatch):
    ckpt = tmp_path / 'artifacts/model.pt'
    ckpt.parent.mkdir(parents=True)
    ckpt.write_bytes(b'checkpoint')
    calls = []

    def load(spec):
        calls.append(spec)
        return lambda seed: object()

    live_session._builder_cache.clear()
    monkeypatch.setattr(live_session, 'load_player', load)
    base = {'type': 'az', 'ckpt': str(ckpt), 'n_simulations': 16}
    live_session.build_opponent_player({**base, 'max_rollout_depth': 50}, 1, ckpt_allow_root=ckpt.parents[1])
    live_session.build_opponent_player({**base, 'max_rollout_depth': 100}, 1, ckpt_allow_root=ckpt.parents[1])
    assert len(calls) == 2


def test_old_semantic_checkpoint_format_is_unavailable(live_model):
    _, ckpt_path, report_path = live_model
    payload = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    payload.pop('_training_provenance')
    payload['format'] = 'semantic-q/1.0.0'
    save_checkpoint(payload, ckpt_path)
    report = json.loads(report_path.read_text())
    report['checkpoint_sha256'] = hashlib.sha256(ckpt_path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report))

    current = semantic_live.profile()
    assert current['available'] is False
    assert 'semantic-q/2.0.0' in current['unavailable_reason']
