from pathlib import Path

import pytest

from web.backend import live_api


@pytest.fixture(autouse=True)
def live_log_root(tmp_path: Path, monkeypatch):
    root = tmp_path / 'live_logs'
    monkeypatch.setattr(live_api, 'LIVE_LOG_ROOT', root)
    return root
