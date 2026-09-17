"""Integration test for tools/eval/eval_service.py.

Starts an EvalServer in a background thread, sends a status request
and a small matchup (kind=gauntlet) request via TCP localhost,
verifies the protocol round-trip and result file output.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

import pytest

from training.tests._az_fixtures import az_smoke_cfg

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _alloc_port() -> int:
    """Allocate a free TCP port on localhost via bind-to-0. TOCTOU race
    is acceptable for tests (collision statistically rare; xdist-safe
    enough for the -n 4 concurrency the suite runs at)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('localhost', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _TestEnv:
    def __init__(self, run_path: Path, host: str, port: int, cfg):
        self.path = run_path
        self.host = host
        self.port = port
        self.cfg = cfg


@pytest.fixture
def test_env(tmp_path):
    """Set up a minimal test environment with a saved checkpoint."""
    from training.paradigms.az.network import Agent

    cfg = az_smoke_cfg(data_dir=DATA_DIR)
    agent = Agent(cfg.agent)
    ckpt_path = tmp_path / 'ckpt_test.pt'
    agent.save(str(ckpt_path))
    return _TestEnv(tmp_path, 'localhost', _alloc_port(), cfg)


def _send_request(host: str, port: int, req: dict) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect((host, port))
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


def _start_server(host: str, port: int):
    from tools.eval.eval_service import EvalServer

    server = EvalServer(host=host, port=port, max_workers=1)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.5)
    return server, t


class TestSchemaEndpoint:
    """Schema is the authoritative contract for the request body.
    ``send_matchup`` fetches it at startup to drive CLI + help; these
    tests guard the round-trip."""

    def test_schema_request_returns_schema(self, test_env):
        server, t = _start_server(test_env.host, test_env.port)
        try:
            resp = _send_request(
                test_env.host,
                test_env.port,
                {'kind': 'schema'},
            )
            assert resp['status'] == 'ok'
            assert 'schema' in resp
            schema = resp['schema']
            # Sanity — this is the schema we ship.
            assert schema['$id'] == 'gicg/eval_service/v1'
            # oneOf branches present for each request kind.
            titles = {b.get('title') for b in schema['oneOf']}
            assert titles == {'gauntlet', 'status', 'stop', 'schema'}
        finally:
            server.stop()
            t.join(timeout=5)

    def test_invalid_player_type_rejected(self, test_env):
        """Schema validation should reject a player type not in the
        oneOf union with an error pointing at the offending path."""
        server, t = _start_server(test_env.host, test_env.port)
        try:
            resp = _send_request(
                test_env.host,
                test_env.port,
                {
                    'kind': 'gauntlet',
                    'mode': 'fixed',
                    'team_0': ['X'],
                    'team_1': ['Y'],
                    'players': [
                        {'type': 'bogus_player', 'ckpt': '/x'},
                        {'type': 'random'},
                    ],
                    'result_path': '/tmp/x.jsonl',
                },
            )
            assert resp['status'] == 'error'
            # Must be a schema error, not a runtime (ckpt) error.
            assert resp['message'].startswith('schema:')
        finally:
            server.stop()
            t.join(timeout=5)


def test_greedy_depth_four_schema_accepts():
    from tools.eval.eval_service import REQUEST_SCHEMA, _VALIDATOR

    assert REQUEST_SCHEMA['$defs']['player_spec_greedy']['properties']['depth']['enum'] == [1, 2, 3, 4]
    _VALIDATOR.validate(
        {
            'kind': 'gauntlet',
            'mode': 'fixed',
            'team_0': ['赤蝶'],
            'team_1': ['墨客'],
            'players': [
                {'type': 'greedy', 'depth': 4},
                {'type': 'random'},
            ],
            'result_path': '/tmp/depth4.jsonl',
        }
    )

    def test_enumerate_disjoint_missing_char_pool_rejected(self, test_env):
        """Conditional-required: mode=enumerate_disjoint needs
        char_pool + team_size. Guards the schema's ``allOf if/then``
        branch — the most fragile non-trivial piece of the schema."""
        server, t = _start_server(test_env.host, test_env.port)
        try:
            resp = _send_request(
                test_env.host,
                test_env.port,
                {
                    'kind': 'gauntlet',
                    'mode': 'enumerate_disjoint',
                    # intentionally omit char_pool + team_size
                    'players': [
                        {'type': 'random'},
                        {'type': 'random'},
                    ],
                    'result_path': '/tmp/x.jsonl',
                },
            )
            assert resp['status'] == 'error'
            assert resp['message'].startswith('schema:')
        finally:
            server.stop()
            t.join(timeout=5)

    def test_mcts_pure_without_n_simulations_rejected(self, test_env):
        """mcts_pure requires n_simulations >= 1; schema guards it."""
        server, t = _start_server(test_env.host, test_env.port)
        try:
            resp = _send_request(
                test_env.host,
                test_env.port,
                {
                    'kind': 'gauntlet',
                    'mode': 'fixed',
                    'team_0': ['赤蝶'],
                    'team_1': ['墨客'],
                    'players': [
                        {'type': 'random'},
                        {'type': 'mcts_pure'},
                    ],
                    'result_path': '/tmp/x.jsonl',
                },
            )
            assert resp['status'] == 'error'
        finally:
            server.stop()
            t.join(timeout=5)

    def test_cfr_ckpt_missing_file_rejected(self, test_env):
        """Runtime-only invariant: ckpt path must exist on disk.
        Schema can't express 'file exists', so ``_validate_request``
        does this as an extra check."""
        server, t = _start_server(test_env.host, test_env.port)
        try:
            resp = _send_request(
                test_env.host,
                test_env.port,
                {
                    'kind': 'gauntlet',
                    'mode': 'fixed',
                    'team_0': ['赤蝶'],
                    'team_1': ['墨客'],
                    'players': [
                        {'type': 'cfr', 'ckpt': '/does/not/exist.pt'},
                        {'type': 'random'},
                    ],
                    'result_path': '/tmp/x.jsonl',
                },
            )
            assert resp['status'] == 'error'
            assert 'ckpt not found' in resp['message']
        finally:
            server.stop()
            t.join(timeout=5)
