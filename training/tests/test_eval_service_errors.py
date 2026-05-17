"""Integration test for tools/remote/eval_service.py.

Starts an EvalServer in a background thread, sends a status request
and a small matchup (kind=gauntlet) request via Unix socket, verifies
the protocol round-trip and result file output.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from training.paradigms.az.config import smoke_config

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


class _TestEnv:
    def __init__(self, run_path: Path, socket_path: Path, cfg):
        self.path = run_path
        self.socket_path = socket_path
        self.cfg = cfg


@pytest.fixture
def test_env(tmp_path):
    """Set up a minimal test environment with a saved checkpoint."""
    from training.paradigms.az.network import Agent

    cfg = smoke_config(data_dir=DATA_DIR)
    agent = Agent(cfg.agent)
    ckpt_path = tmp_path / 'ckpt_test.pt'
    agent.save(str(ckpt_path))
    sock_path = Path(tempfile.mkdtemp(prefix='eval_')) / 'eval.sock'
    return _TestEnv(tmp_path, sock_path, cfg)


def _send_request(socket_path: str, req: dict) -> dict:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect(socket_path)
    sock.sendall(json.dumps(req).encode('utf-8'))
    # Schema responses exceed a single 4K packet; drain until EOF.
    buf = b''
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    sock.close()
    return json.loads(buf.decode('utf-8'))


def _start_server(socket_path: Path):
    from tools.remote.eval_service import EvalServer

    server = EvalServer(socket_path=socket_path, max_workers=1)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.5)
    return server, t


class TestEvalService:
    def test_status_endpoint(self, test_env):
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(str(test_env.socket_path), {'kind': 'status'})
            assert resp['status'] == 'ok'
            assert resp['active'] == 0
            assert resp['completed'] == 0
        finally:
            server.stop()
            t.join(timeout=5)

    def test_matchup_az_vs_random(self, test_env):
        """Smoke: az challenger argmax vs random opponent, 2 games."""
        server, t = _start_server(test_env.socket_path)
        try:
            ckpt_path = str(test_env.path / 'ckpt_test.pt')
            result_path = test_env.path / 'gauntlet_results.jsonl'
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 100,
                    'seed': 42,
                    'players': [
                        {'type': 'az', 'ckpt': ckpt_path, 'n_simulations': 0},
                        {'type': 'random'},
                    ],
                    'mode': 'fixed',
                    'team_0': test_env.cfg.scenario.team_0,
                    'team_1': test_env.cfg.scenario.team_1,
                    'card_pool': test_env.cfg.scenario.card_pool,
                    'games_per_cell': 1,  # 1 per side = 2 games total
                    'max_game_steps': 400,
                    'data_dir': DATA_DIR,
                    'result_path': str(result_path),
                },
            )
            assert resp['status'] == 'accepted'
            assert resp['id'] == 'g00100'

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if result_path.exists() and result_path.stat().st_size > 0:
                    break
                time.sleep(0.5)

            assert result_path.exists(), 'gauntlet_results.jsonl not created'
            lines = result_path.read_text().strip().splitlines()
            assert len(lines) >= 1
            entry = json.loads(lines[0])
            assert entry['game_marker'] == 100
            assert entry['id'] == 'g00100'
            assert 'aggregate' in entry
            assert entry['aggregate']['n_games'] == 2
            assert 0.0 <= entry['aggregate']['win_rate'] <= 1.0
            assert len(entry['per_cell']) == 1
            assert entry['per_cell'][0]['team_0'] == test_env.cfg.scenario.team_0
        finally:
            server.stop()
            t.join(timeout=5)

    def test_missing_players_returns_error(self, test_env):
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 999,
                    'mode': 'fixed',
                    'team_0': ['赤蝶'],
                    'team_1': ['墨客'],
                    'result_path': str(test_env.path / 'results.jsonl'),
                },
            )
            assert resp['status'] == 'error'
            assert 'players' in resp['message']
        finally:
            server.stop()
            t.join(timeout=5)

    def test_missing_az_ckpt_returns_error(self, test_env):
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 999,
                    'players': [
                        {'type': 'az', 'ckpt': '/nonexistent/ckpt.pt'},
                        {'type': 'random'},
                    ],
                    'mode': 'fixed',
                    'team_0': ['赤蝶'],
                    'team_1': ['墨客'],
                    'result_path': str(test_env.path / 'results.jsonl'),
                },
            )
            assert resp['status'] == 'error'
            assert 'not found' in resp['message']
        finally:
            server.stop()
            t.join(timeout=5)

    def test_matchup_cfr_vs_random(self, test_env):
        """End-to-end: save a CFR ckpt, fire a gauntlet request with
        type=cfr as players[0], verify the socket path + loader +
        matchup produces a valid result file."""
        import torch
        from training.paradigms.cfr import CFRNetConfig, CFRStrategyNet

        # Save a small CFR ckpt
        cfr_cfg = CFRNetConfig(
            n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
            n_hooks=900,
            max_tokens_per_hook=120,
            max_actions=2048,
            d_model=16,
            n_cross_layers=1,
            dropout=0.0,
        )
        torch.manual_seed(0)
        cfr_net = CFRStrategyNet(cfr_cfg)
        cfr_ckpt = test_env.path / 'cfr_test.pt'
        cfr_net.save(str(cfr_ckpt))

        server, t = _start_server(test_env.socket_path)
        try:
            result_path = test_env.path / 'gauntlet_results.jsonl'
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 42,
                    'seed': 42,
                    'players': [
                        {'type': 'cfr', 'ckpt': str(cfr_ckpt), 'n_simulations': 0},
                        {'type': 'random'},
                    ],
                    'mode': 'fixed',
                    'team_0': test_env.cfg.scenario.team_0,
                    'team_1': test_env.cfg.scenario.team_1,
                    'card_pool': test_env.cfg.scenario.card_pool,
                    'games_per_cell': 1,  # 2 games total (side-swap)
                    'max_game_steps': 400,
                    'data_dir': DATA_DIR,
                    'result_path': str(result_path),
                },
            )
            assert resp['status'] == 'accepted'

            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if result_path.exists() and result_path.stat().st_size > 0:
                    break
                time.sleep(0.5)

            assert result_path.exists(), 'gauntlet_results.jsonl not created'
            entry = json.loads(result_path.read_text().strip().splitlines()[0])
            assert entry['game_marker'] == 42
            assert entry['aggregate']['n_games'] == 2
            assert 0.0 <= entry['aggregate']['win_rate'] <= 1.0
            assert entry['players'][0]['type'] == 'cfr'
            assert entry['players'][1]['type'] == 'random'
        finally:
            server.stop()
            t.join(timeout=5)

    def test_missing_cfr_ckpt_returns_error(self, test_env):
        """CFR ckpt absence is caught at accept time (not deferred
        to job execution)."""
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 1,
                    'players': [
                        {'type': 'cfr', 'ckpt': '/nonexistent/cfr.pt'},
                        {'type': 'random'},
                    ],
                    'mode': 'fixed',
                    'team_0': ['赤蝶'],
                    'team_1': ['墨客'],
                    'result_path': str(test_env.path / 'results.jsonl'),
                },
            )
            assert resp['status'] == 'error'
            assert 'cfr ckpt' in resp['message']
            assert 'not found' in resp['message']
        finally:
            server.stop()
            t.join(timeout=5)

    def test_missing_mode_returns_error(self, test_env):
        server, t = _start_server(test_env.socket_path)
        try:
            ckpt_path = str(test_env.path / 'ckpt_test.pt')
            resp = _send_request(
                str(test_env.socket_path),
                {
                    'kind': 'gauntlet',
                    'game_marker': 999,
                    'players': [
                        {'type': 'az', 'ckpt': ckpt_path},
                        {'type': 'random'},
                    ],
                    # no mode
                    'result_path': str(test_env.path / 'results.jsonl'),
                },
            )
            assert resp['status'] == 'error'
            assert 'mode' in resp['message']
        finally:
            server.stop()
            t.join(timeout=5)
