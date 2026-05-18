"""Integration test for tools/remote/eval_service.py.

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

from training.paradigms.az.config import smoke_config

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

    cfg = smoke_config(data_dir=DATA_DIR)
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
    from tools.remote.eval_service import EvalServer

    server = EvalServer(host=host, port=port, max_workers=1)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()
    time.sleep(0.5)
    return server, t


class TestSendMatchupCLI:
    """Parser-level tests for the CLI. These don't need a live socket —
    just feed a schema + argv and check the built request."""

    def _schema(self):
        from tools.remote.eval_service import REQUEST_SCHEMA

        return REQUEST_SCHEMA

    def test_dotted_path_to_list_of_dicts(self):
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        argv = [
            '--kind',
            'gauntlet',
            '--mode',
            'fixed',
            '--team-0',
            '赤蝶',
            '墨客',
            '--team-1',
            '猫咪',
            '刻师傅',
            '--players.0.type',
            'cfr',
            '--players.0.ckpt',
            '/tmp/fake.pt',
            '--players.0.n-simulations',
            '0',
            '--players.1.type',
            'mcts_pure',
            '--players.1.n-simulations',
            '100',
            '--games-per-cell',
            '10',
            '--swap-sides',
            'false',
            '--result-path',
            '/tmp/out.jsonl',
        ]
        req = _build_request(schema, argv)
        assert req['kind'] == 'gauntlet'
        assert req['mode'] == 'fixed'
        assert req['team_0'] == ['赤蝶', '墨客']
        assert req['team_1'] == ['猫咪', '刻师傅']
        assert req['players'] == [
            {'type': 'cfr', 'ckpt': '/tmp/fake.pt', 'n_simulations': 0},
            {'type': 'mcts_pure', 'n_simulations': 100},
        ]
        assert req['games_per_cell'] == 10
        assert req['swap_sides'] is False
        assert req['result_path'] == '/tmp/out.jsonl'

    def test_boolean_coercion_via_schema(self):
        """``--swap-sides false`` must coerce to a bool, not the string
        'false'. Auto-detect would happen to do the right thing, but
        we want the schema path to also work."""
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        req = _build_request(
            schema,
            [
                '--kind',
                'gauntlet',
                '--swap-sides',
                'true',
                '--mode',
                'fixed',
                '--team-0',
                'X',
                '--team-1',
                'Y',
                '--players.0.type',
                'random',
                '--players.1.type',
                'random',
                '--result-path',
                '/t.jsonl',
            ],
        )
        assert req['swap_sides'] is True

    def test_array_of_strings_preserved(self):
        """``--team-0 赤蝶`` (single token) on an array field should
        still be a list — schema type is array."""
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        req = _build_request(
            schema,
            [
                '--kind',
                'gauntlet',
                '--mode',
                'fixed',
                '--team-0',
                '赤蝶',
                '--team-1',
                '墨客',
                '--players.0.type',
                'random',
                '--players.1.type',
                'random',
                '--result-path',
                '/t.jsonl',
            ],
        )
        assert req['team_0'] == ['赤蝶']
        assert req['team_1'] == ['墨客']

    def test_unknown_flag_accepted_in_dotted_form(self):
        """CLI doesn't reject flags the schema doesn't know — the
        server-side schema check will. This keeps the CLI from having
        to re-validate the whole schema client-side."""
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        req = _build_request(
            schema,
            [
                '--kind',
                'gauntlet',
                '--mode',
                'fixed',
                '--team-0',
                'X',
                '--team-1',
                'Y',
                '--players.0.type',
                'random',
                '--players.1.type',
                'random',
                '--result-path',
                '/t.jsonl',
                '--nonexistent-field',
                'value',
            ],
        )
        assert req['nonexistent_field'] == 'value'

    def test_out_of_bounds_player_index_does_not_crash(self):
        """Pathological CLI input ``--players.2.type random`` (index
        past the schema's maxItems=2) must not crash the parser. The
        resulting request WILL be rejected by server-side schema
        validation — which is desired — but we don't lock in a
        specific client-side shape (should the parser ever learn to
        reject such inputs up-front, this test stays valid)."""
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        req = _build_request(
            schema,
            [
                '--kind',
                'gauntlet',
                '--mode',
                'fixed',
                '--team-0',
                'X',
                '--team-1',
                'Y',
                '--players.2.type',
                'random',
                '--result-path',
                '/t.jsonl',
            ],
        )
        # Contract: parser didn't crash + produced a dict. Specific
        # ``players`` shape intentionally unspecified.
        assert isinstance(req, dict)

    def test_out_of_bounds_player_index_rejected_by_server(self, tmp_path):
        """Server-side complement: whatever the parser produces for
        ``--players.2.type``, the server's schema check must reject
        it (maxItems=2 enforced end-to-end)."""
        import threading

        host = 'localhost'
        port = _alloc_port()
        from tools.remote.eval_service import EvalServer

        server = EvalServer(host=host, port=port, max_workers=1)
        t = threading.Thread(target=server.start, daemon=True)
        t.start()
        time.sleep(0.5)
        try:
            from tools._meta.send_matchup_parser import build_request as _build_request
            from tools.remote.eval_service import REQUEST_SCHEMA

            req = _build_request(
                REQUEST_SCHEMA,
                [
                    '--kind',
                    'gauntlet',
                    '--mode',
                    'fixed',
                    '--team-0',
                    'X',
                    '--team-1',
                    'Y',
                    '--players.2.type',
                    'random',
                    '--result-path',
                    '/tmp/x.jsonl',
                ],
            )
            resp = _send_request(host, port, req)
            assert resp['status'] == 'error'
            assert resp['message'].startswith('schema:')
        finally:
            server.stop()
            t.join(timeout=5)

    def test_empty_argv_returns_empty_dict(self):
        """Parser on empty argv should not crash — returns ``{}``.
        Server will reject (missing required 'kind'); the CLI
        shouldn't crash before it sends."""
        from tools._meta.send_matchup_parser import build_request as _build_request

        schema = self._schema()
        req = _build_request(schema, [])
        assert req == {}
