from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from tools.runs import list as list_runs
from tools.runs._helpers.resolver import resolve_nnn_to_dir
from tools.runs._helpers.sync_scan import scan_local_timestamps
from tools.runs._train.setup import phase_a_setup


def _cfg(path: Path, *, label: str = 'seed_1', tag: str = 'd2') -> Path:
    path.write_text(
        f'[meta]\nrun_label = "{label}"\nexperiment_tag = "{tag}"\nparadigm = "dmc"\n',
        encoding='utf-8',
    )
    return path


def test_setup_places_runs_under_experiment_tag(tmp_path, monkeypatch):
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    state = phase_a_setup(Namespace(cfg=str(_cfg(tmp_path / 'cfg.toml')), override=[], resume=None))
    assert state.experiment_tag == 'd2'
    assert state.artifacts_dir.parent == tmp_path / 'artifacts' / 'd2'
    assert state.artifacts_dir.name.endswith(f'_{state.nnn:06d}')


def test_resolver_and_scanners_accept_tagged_runs(tmp_path):
    run = tmp_path / 'artifacts' / 'd2' / '202609220800_000007'
    run.mkdir(parents=True)
    (run / 'metadata.toml').write_text(
        'run_id = "000007"\n timestamp = "2026-09-22T08:00:00+00:00"\n'
        'cfg_file = "cfg.toml"\n cfg_resolved_version = 1\n git_commit = "x"\n'
        'host = "h"\n status = "done"\n artifacts_dir = "artifacts/d2/202609220800_000007"\n'
        'wall_seconds = 1.0\n exit_code = 0\n notes = ""\n experiment_tag = "d2"\n run_label = "seed_1"\n',
        encoding='utf-8',
    )
    assert resolve_nnn_to_dir(tmp_path, '7') == run
    assert scan_local_timestamps(tmp_path) == {'000007': '2026-09-22T08:00:00+00:00'}
    assert list_runs.list_runs(tmp_path)[0].run_label == 'seed_1'


def test_allocator_counts_legacy_and_tagged_runs(tmp_path, monkeypatch):
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    (tmp_path / 'artifacts' / 'legacy').mkdir(parents=True)
    (tmp_path / 'artifacts' / '202609220800_000003_old').mkdir()
    (tmp_path / 'artifacts' / 'legacy' / '202609220801_000008').mkdir()
    monkeypatch.chdir(tmp_path)
    state = phase_a_setup(Namespace(cfg=str(_cfg(tmp_path / 'cfg.toml')), override=[], resume=None))
    assert state.nnn == 9
