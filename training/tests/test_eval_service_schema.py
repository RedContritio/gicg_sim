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


class TestSchemaEndpoint:
    """Schema is the authoritative contract for the request body.
    ``send_matchup`` fetches it at startup to drive CLI + help; these
    tests guard the round-trip."""

    def test_schema_request_returns_schema(self, test_env):
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
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
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
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

    def test_enumerate_disjoint_missing_char_pool_rejected(self, test_env):
        """Conditional-required: mode=enumerate_disjoint needs
        char_pool + team_size. Guards the schema's ``allOf if/then``
        branch — the most fragile non-trivial piece of the schema."""
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
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
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
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
        server, t = _start_server(test_env.socket_path)
        try:
            resp = _send_request(
                str(test_env.socket_path),
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
