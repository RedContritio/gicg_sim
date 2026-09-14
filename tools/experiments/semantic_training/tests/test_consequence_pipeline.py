"""Selection/recheck isolation at the orchestration boundary (no strength claim)."""

import json
from pathlib import Path
import socket
from types import SimpleNamespace

from tools.experiments.semantic_training import consequence_rl as pipeline


def test_selection_uses_development_only_and_keeps_initial_on_tie(tmp_path, monkeypatch):
    paths = {arm: str(tmp_path / f'{arm}.pt') for arm in ('candidate', 'control')}
    for path in paths.values():
        Path(path).write_bytes(b'initial')
    monkeypatch.setattr(pipeline, 'matched_initials', lambda _: paths)
    monkeypatch.setattr(pipeline, 'load_remote_from_cfg', lambda _: SimpleNamespace(hostname=socket.gethostname()))
    monkeypatch.setattr(pipeline, 'load_cfg', lambda _: None)
    calls, verified, probes = [], [], []

    def train(config, checkpoint, output, **kwargs):
        assert kwargs['learning_rate'] == 0.001
        root = Path(output)
        root.mkdir()
        final = root / 'final.pt'
        final.write_bytes(root.name.encode())
        (root / 'result.json').write_text(
            json.dumps(
                dict(status='complete', checkpoint=str(final), iterations=[dict(iteration=1, checkpoint=str(final))])
            )
        )

    def evaluate(config, checkpoint, output, **kwargs):
        output.mkdir()
        calls.append((checkpoint, kwargs['seed'], kwargs['scenarios']))
        # Make the independent test favor the opposite policy. Selection must stay fixed.
        trained_candidate = 'candidate/final.pt' in checkpoint
        score = (0.8 if trained_candidate else 0.3) if kwargs['seed'] == 95900 else 0.1
        (output / 'result.json').write_text(json.dumps(dict(score=score, checkpoint=checkpoint)))

    def verify(report, cfg, catalog, **kwargs):
        verified.append(kwargs)
        assert kwargs['checkpoint_sha256'] == pipeline.digest(report['checkpoint'])
        return dict(score=report['score'])

    monkeypatch.setattr(pipeline.rl, 'run', train)
    monkeypatch.setattr(pipeline, 'evaluate', evaluate)
    monkeypatch.setattr(pipeline, 'verify_variants', verify)
    monkeypatch.setattr(pipeline, 'probe', lambda config, checkpoint, output, **kwargs: probes.append(checkpoint))
    monkeypatch.setattr(pipeline, 'compare', lambda a, b, output: output.write_text('{}'))
    root = tmp_path / 'run'
    pipeline.run(
        SimpleNamespace(
            config='config',
            initial='initial',
            output=str(root),
            catalog='catalog',
            workers=1,
            episodes=4,
            iterations=1,
            seed=95800,
            learning_rate=0.001,
        )
    )
    result = json.loads((root / 'completion.json').read_text())
    assert result['status'] == 'complete'
    assert result['arms']['candidate']['selected'] == str(root / 'candidate/final.pt')
    assert result['arms']['control']['selected'] == paths['control']
    assert len(verified) == len(calls) == 7
    assert [seed for _, seed, _ in calls] == [95900] * 4 + [96000] * 3
    assert [n for _, _, n in calls] == [55] * 4 + [110] * 3
    assert calls[-1][0] == paths['control']
    assert len(probes) == 3
