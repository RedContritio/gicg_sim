"""Cross-platform TCP smoke for tools.eval.eval_service socket layer.

Verifies AF_INET bind/accept/status-RPC roundtrip works on the current
platform. Designed to be lightweight (no DSL preload, no gauntlet job)
so it runs quickly on the Windows GPU box for migration certification:

    # Mac dev
    .venv/bin/python -m pytest tools/eval/tests/test_socket_cross_platform.py -q

    # Windows remote (cross-platform verification gate)
    .venv/bin/python -m tools.runs.exec <cfg.toml> -- .venv/Scripts/python.exe -m pytest tools/eval/tests/test_socket_cross_platform.py -q

If this test PASSes on both Mac and Windows, the AF_UNIX -> AF_INET
migration is platform-certified at the socket layer. Full eval_service
behavior (gauntlet, schema endpoints) is exercised by the heavyweight
suite at training/tests/test_eval_service_*.py.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest


def _alloc_port() -> int:
    """Allocate an OS-assigned localhost port (xdist-safe).

    Uses the bind-to-0 trick: bind to port 0, read the kernel-assigned
    port, close. Has a TOCTOU window between close and the server's
    bind, but that race is acceptable for tests (per pytest -n 4
    convention in AGENTS.md).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('localhost', 0))
        return s.getsockname()[1]


def _start_server(port: int):
    """Start EvalServer on localhost:port in a daemon thread.

    Returns (server, thread). Caller must call server.stop() and
    thread.join() to clean up.
    """
    from tools.eval.eval_service_server import EvalServer

    server = EvalServer(host='localhost', port=port, max_workers=1)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()
    # server.start() returns after bind() but before accept loop is live; brief wait avoids ConnectionRefusedError race
    time.sleep(0.5)
    return server, thread


def _send_request(host: str, port: int, payload: bytes) -> dict:
    """Send raw bytes, return decoded JSON response.

    Drains until EOF — schema responses exceed a single recv() packet.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5.0)
    sock.connect((host, port))
    sock.sendall(payload)
    buf = b''
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    sock.close()
    return json.loads(buf.decode('utf-8'))


@pytest.fixture
def server_port():
    """Allocate port + start server; tear down on test exit."""
    port = _alloc_port()
    server, thread = _start_server(port)
    try:
        yield 'localhost', port
    finally:
        server.stop()
        thread.join(timeout=5)


def test_status_roundtrip(server_port):
    host, port = server_port
    resp = _send_request(host, port, json.dumps({'kind': 'status'}).encode('utf-8'))
    assert resp['status'] == 'ok'
    for field in ('active', 'completed', 'errors', 'queued', 'uptime_s'):
        assert field in resp, f'missing status field: {field}'
    assert resp['active'] == 0
    assert resp['completed'] == 0
    assert resp['errors'] == 0
    assert resp['queued'] == 0


def test_two_sequential_connections(server_port):
    """Accept loop must not get stuck after the first connection."""
    host, port = server_port

    resp1 = _send_request(host, port, json.dumps({'kind': 'status'}).encode('utf-8'))
    assert resp1['status'] == 'ok'

    resp2 = _send_request(host, port, json.dumps({'kind': 'schema'}).encode('utf-8'))
    assert resp2['status'] == 'ok'
    assert 'schema' in resp2


def test_invalid_json_returns_error(server_port):
    """Malformed JSON triggers error response, not server crash."""
    host, port = server_port

    resp = _send_request(host, port, b'this is not valid json {[')
    assert resp['status'] == 'error'
    assert 'message' in resp

    followup = _send_request(host, port, json.dumps({'kind': 'status'}).encode('utf-8'))
    assert followup['status'] == 'ok'
