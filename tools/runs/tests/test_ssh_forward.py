"""Unit tests for ``tools.runs._ssh.ssh_forward`` — quoting + composition。

P2 left ssh_forward 0-tested (no callers yet); P3 ``tools.runs.train``
remote dispatch path is the first caller, so we need explicit coverage
of (a) the PS payload composed for the remote process, (b) shell-meta /
whitespace-injection resistance via ``ps_quote``, and (c) the local
return-code passthrough.

All-mock — ``discover_remote_python`` returns a fixed venv path,
``ssh_encoded_argv`` is patched to *capture* the inner PS payload so
assertions read the actual quoted string, and ``run_argv_capture`` is
patched to bypass real ssh execution.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.runs._host import RemoteCfg
from tools.runs._ssh import ssh_forward


REMOTE = RemoteCfg(ssh='dev@host', root='D:/gicg_dev', os='windows', hostname='DEV-PC')
REMOTE_POSIX = RemoteCfg(ssh='dev@host', root='/srv/gicg dev', os='linux', hostname='boxlin')


def _capture_payload():
    """Helper: stash composed PS payload on a list so tests can assert it.

    Returns ``(argv_builder, captured_list)`` — ``argv_builder`` is the
    side_effect for the ``ssh_encoded_argv`` patch and writes the
    received PS script into ``captured_list[0]``.
    """
    captured: list[str] = []

    def builder(remote, ps_script):  # noqa: ARG001
        captured.append(ps_script)
        return ['ssh', remote.ssh, 'echo', 'stubbed']

    return builder, captured


def _ok(rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout='', stderr='')


# ---------------------------------------------------------------------------
# Happy paths — basic composition.
# ---------------------------------------------------------------------------


def test_ssh_forward_happy_path_no_extra():
    """No extra args → PS payload = ``cd <root>; <py> -X utf8 -u -m <mod> <cfg>``。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/gicg_dev/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        rc = ssh_forward(REMOTE, 'tools.runs.list', Path('cfg.toml'), [])
    assert rc == 0
    payload = captured[0]
    # cd root present, no trailing whitespace before semicolon.
    assert payload.startswith("cd 'D:\\gicg_dev'; ")
    # Cfg path quoted via PS single-quote.
    assert "-m tools.runs.list 'cfg.toml'" in payload
    # No trailing space when extra_args is empty.
    assert not payload.endswith(' ')


def test_ssh_forward_extra_args_quoted():
    """Each extra_arg gets independently ps_quote'd → ``'--all' '--dry-run'``。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.kill', Path('c.toml'), ['--all', '--dry-run'])
    payload = captured[0]
    assert "'--all'" in payload
    assert "'--dry-run'" in payload
    # Ordering preserved.
    assert payload.index("'--all'") < payload.index("'--dry-run'")


# ---------------------------------------------------------------------------
# Quoting safety — spaces, shell metachars, embedded single quotes.
# ---------------------------------------------------------------------------


def test_ssh_forward_arg_with_space_quoted():
    """``--match 'foo bar'`` survives — PS reads it as one token。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.kill', Path('c.toml'), ['--match', 'foo bar'])
    payload = captured[0]
    assert "'foo bar'" in payload


def test_ssh_forward_arg_with_semicolon_safe():
    """Injection attempt via ``;rm -rf /`` is fully wrapped → PS sees it as
    one quoted token, NOT a command separator。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.kill', Path('c.toml'), ['--match', 'a;rm -rf /'])
    payload = captured[0]
    assert "'a;rm -rf /'" in payload
    # The dangerous semicolon must NOT appear outside the quoted span as a
    # command separator. Easiest invariant: the literal ``; rm`` (post-cd
    # script separator pattern) should not show up.
    assert '; rm -rf /' not in payload


def test_ssh_forward_arg_with_pipe_and_amp_safe():
    """``|`` / ``&`` / ``>`` inside an arg stay inside the quote → PS does
    not parse them as redirect / background / pipeline。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.tail', Path('c.toml'), ['--match', 'a|b&c>d'])
    payload = captured[0]
    assert "'a|b&c>d'" in payload


def test_ssh_forward_arg_with_embedded_single_quote():
    """PS single-quote literal escape doubles the inner quote: ``a'b`` →
    ``'a''b'``。``ps_quote`` is the source of truth — we just assert
    ssh_forward routes through it。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.kill', Path('c.toml'), ["a'b"])
    payload = captured[0]
    assert "'a''b'" in payload


def test_ssh_forward_cfg_with_space_quoted():
    """Cfg path with space is quoted as well — protects ``cd ...; py -m
    ... 'a b/cfg.toml'`` tokenization。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(REMOTE, 'tools.runs.list', Path('a b/cfg.toml'), [])
    payload = captured[0]
    assert "'a b/cfg.toml'" in payload


def test_ssh_forward_cfg_path_backslash_normalized_to_forward():
    """Backslashes from local Path on Windows test runners → forward
    slashes; quoting still applies on top of the normalized form。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        # Force backslashes by passing a string Path that contains them.
        ssh_forward(REMOTE, 'tools.runs.list', Path('configs\\dmc\\smoke.toml'), [])
    payload = captured[0]
    assert "'configs/dmc/smoke.toml'" in payload
    # Cfg path region must be fully forward-slashed (no leftover backslashes).
    assert 'configs\\dmc' not in payload


# ---------------------------------------------------------------------------
# Return-code + stream branch passthrough.
# ---------------------------------------------------------------------------


def test_ssh_forward_returns_remote_exit_code():
    """Whatever ``run_argv_capture`` returns flows back unchanged。"""
    builder, _captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(42)),
    ):
        rc = ssh_forward(REMOTE, 'tools.runs.train', Path('cfg.toml'), [])
    assert rc == 42


def test_ssh_forward_stream_branch_uses_run_stream():
    """``stream=True`` → bypass ``run_argv_capture``, route through
    ``_run_stream`` (Popen-based realtime pump)。"""
    builder, _captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh._run_stream', return_value=7) as m_stream,
        patch('tools.runs._ssh.run_argv_capture') as m_run,
    ):
        rc = ssh_forward(REMOTE, 'tools.runs.train', Path('cfg.toml'), ['--resume', '/x'], stream=True)
    assert rc == 7
    m_stream.assert_called_once()
    m_run.assert_not_called()


def test_ssh_forward_propagates_resume_flag():
    """User passes ``--resume <path>`` → payload contains both tokens,
    each separately quoted。"""
    builder, captured = _capture_payload()
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='D:/.venv/Scripts/python.exe'),
        patch('tools.runs._ssh.ssh_encoded_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=_ok(0)),
    ):
        ssh_forward(
            REMOTE,
            'tools.runs.train',
            Path('cfg.toml'),
            ['--override', 'a.b=1', '--override', 'c.d=2', '--resume', 'artifacts/x/ckpts/latest.pt'],
        )
    payload = captured[0]
    assert "'--override'" in payload
    assert "'a.b=1'" in payload
    assert "'c.d=2'" in payload
    assert "'--resume'" in payload
    assert "'artifacts/x/ckpts/latest.pt'" in payload


# ---------------------------------------------------------------------------
# Probe failure surfaces (no caller-side swallow).
# ---------------------------------------------------------------------------


def test_ssh_forward_probe_failure_propagates():
    """``discover_remote_python`` raises → ssh_forward doesn't catch it,
    caller sees ``FileNotFoundError`` with setup hint。"""
    with patch('tools.runs._ssh.discover_remote_python', side_effect=FileNotFoundError('no venv')):
        with pytest.raises(FileNotFoundError, match='no venv'):
            ssh_forward(REMOTE, 'tools.runs.list', Path('cfg.toml'), [])


# ---------------------------------------------------------------------------
# POSIX ssh branch.
# ---------------------------------------------------------------------------


def test_ssh_forward_posix_uses_bash_and_quotes_args():
    captured: list[str] = []

    def builder(remote, script):  # noqa: ARG001
        captured.append(script)
        return ['ssh', remote.ssh, 'stubbed']

    fake = _ok(0)
    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='/srv/gicg dev/.venv/bin/python'),
        patch('tools.runs._ssh.ssh_bash_argv', side_effect=builder),
        patch('tools.runs._ssh.run_argv_capture', return_value=fake) as run,
    ):
        rc = ssh_forward(
            REMOTE_POSIX,
            'tools.runs.kill',
            Path('configs/a b.toml'),
            ['--match', "a'b; rm -rf /"],
        )
    assert rc == 0
    script = captured[0]
    assert script.startswith("cd '/srv/gicg dev' && ")
    assert shlex.quote('/srv/gicg dev/.venv/bin/python') in script
    assert shlex.quote('configs/a b.toml') in script
    assert shlex.quote("a'b; rm -rf /") in script
    run.assert_called_once_with(['ssh', REMOTE_POSIX.ssh, 'stubbed'], timeout=86400)


def test_ssh_forward_posix_stream_uses_built_argv():
    captured: list[str] = []

    def builder(remote, script):  # noqa: ARG001
        captured.append(script)
        return ['ssh', remote.ssh, 'stubbed']

    with (
        patch('tools.runs._ssh.discover_remote_python', return_value='/srv/gicg/.venv/bin/python'),
        patch('tools.runs._ssh.ssh_bash_argv', side_effect=builder),
        patch('tools.runs._ssh._run_stream', return_value=7) as stream,
        patch('tools.runs._ssh.ssh_run_bash') as bash,
    ):
        rc = ssh_forward(REMOTE_POSIX, 'tools.runs.train', Path('cfg.toml'), [], stream=True)
    assert rc == 7
    stream.assert_called_once()
    bash.assert_not_called()
