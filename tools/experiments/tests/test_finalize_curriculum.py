"""Finalization rejects wrong evidence and never audits an unfinished course."""

import json

import pytest

from tools.experiments.semantic_training import finalize_curriculum as final


def test_failed_and_running_course_do_not_start_audits(tmp_path, monkeypatch):
    def unexpected(*args):
        pytest.fail('verification started before course completion')

    monkeypatch.setattr(final, 'verify', unexpected)
    (tmp_path / 'result.json').write_text(json.dumps({'status': 'failed', 'error': 'example'}))
    with pytest.raises(RuntimeError, match='example'):
        final.run(tmp_path)
    (tmp_path / 'result.json').write_text(json.dumps({'status': 'running'}))
    with pytest.raises(TimeoutError):
        final.run(tmp_path, wait_seconds=0)


def test_coverage_rejects_invalid_decks_and_missing_cards(monkeypatch):
    monkeypatch.setattr(final, 'card_grades', lambda: {'card0': 1})
    rows = [
        dict(index=i, side=s, starting={f'card{k}': 2 for k in range(15)}, seen=['card0'], legal=[], used={})
        for i in range(240)
        for s in (0, 1)
    ]
    result = dict(
        status='complete', checkpoint_sha256='frozen', provenance={'source_observation_sha256': 'src'}, games=rows
    )
    assert final.checked_coverage(result, {'sha256': 'frozen'}, 'src')['unplayed_cards'] == ['card0']
    rows[0]['starting']['card0'] = 3
    with pytest.raises(ValueError, match='starting deck'):
        final.checked_coverage(result, {'sha256': 'frozen'}, 'src')
    rows[0]['starting']['card0'] = 2
    monkeypatch.setattr(final, 'card_grades', lambda: {'unseen': 1})
    with pytest.raises(ValueError, match='never seen'):
        final.checked_coverage(result, {'sha256': 'frozen'}, 'src')
    with pytest.raises(ValueError, match='wrong candidate'):
        final.checked_coverage(result, {'sha256': 'wrong'}, 'src')
