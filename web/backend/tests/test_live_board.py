"""Public board information and explicitly labelled native practice games."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from web.backend.app import create_app
from web.backend.live_view import live_view


@pytest.mark.parametrize('human', [0, 1])
def test_live_view_redacts_opponent_resources(human):
    class Env:
        acting_player = human

        def export_view(self):
            return {'players': [{'hand': [{'ref': p, 'name': f'secret-{p}'}]} for p in range(2)]}

        def dice_counts(self, player):
            return np.array([player + 1, 2, 0, 0, 0, 0, 0, 1])

    view = live_view(Env(), human)
    own, other = view['players'][human], view['players'][1 - human]
    assert own['hand'][0]['name'] == f'secret-{human}'
    assert own['dice'] == [human + 1, 2, 0, 0, 0, 0, 0, 1]
    assert other['hand'] == [{'ref': -1, 'name': '暗牌'}]
    assert 'dice' not in other
    assert other['hand_count'] == 1
    assert other['dice_count'] == 5 - human


@pytest.mark.parametrize('human', [0, 1])
def test_random_practice_uses_native_profile_and_public_view(human):
    client = TestClient(create_app())
    profile = client.get('/api/live/profile').json()
    with client.websocket_connect('/ws/live') as ws:
        ws.send_json(
            {
                'type': 'new',
                'opponent': {'type': 'random'},
                'profile_rules': True,
                'human_player': human,
                'team_0': profile['team_0'],
                'team_1': profile['team_1'],
                'seed': 16160,
            }
        )
        frame = ws.receive_json()
        for _ in range(15):
            assert frame['type'] == 'state', frame
            for player in frame['view']['players']:
                assert len(player['chars']) == profile['team_size']
                assert all(isinstance(player[key], list) for key in ('supports', 'summons', 'statuses'))
            other = frame['view']['players'][1 - human]
            assert 'dice' not in other
            assert all(card['name'] == '暗牌' and card['ref'] == -1 for card in other['hand'])
            if frame['done']:
                break
            actions = frame['legal_actions']
            assert actions
            action = next((a for a in actions if a['kind_name'] == 'Skill'), actions[0])
            ws.send_json({'type': 'action', 'index': action['index']})
            frame = ws.receive_json()
