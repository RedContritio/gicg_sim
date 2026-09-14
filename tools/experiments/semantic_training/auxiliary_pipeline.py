"""Matched-budget rule-supervised RL versus RL-only, followed by independent variant evaluation."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import json
from pathlib import Path
import time
import traceback

from tools.experiments.semantic_training.rl import run
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.compare import compare
from tools.rule_validation.verify_panel import verify_variants
from training.core.config.loader import load_cfg
from training.core.artifact_io import fingerprint


def train(config, checkpoint, catalog, output, iterations=4, episodes=256, workers=8):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    status = dict(
        status='running',
        stage='initial_evaluation',
        iterations=iterations,
        episodes=episodes,
        training_seed=94700,
        selection_seed=93990,
        recheck_seed=94890,
        source_sha256=fingerprint(),
        arms={},
        scope='development comparison, not final repeated-seed acceptance',
    )
    status['tool_sha256'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in ('tools/rule_validation', 'tools/experiments/semantic_training')
        for p in sorted(Path(directory).glob('*.py'))
    }

    def save():
        status['wall_s'] = time.monotonic() - tick
        tmp = root / 'status.tmp'
        tmp.write_text(json.dumps(status, indent=2), encoding='utf-8')
        tmp.replace(root / 'status.json')

    def panel(ckpt, name, seed, scenarios):
        status['panel'] = name
        save()
        out = root / name
        evaluate(
            config,
            ckpt,
            out,
            scenarios=scenarios,
            layouts=2,
            workers=workers,
            seed=seed,
            opponent_depth=2,
            variants=catalog,
        )
        report = json.loads((out / 'result.json').read_text())
        verified = verify_variants(
            report,
            load_cfg(config),
            catalog,
            seed=seed,
            scenarios=scenarios,
            checkpoint_sha256=hashlib.sha256(Path(ckpt).read_bytes()).hexdigest(),
            source_sha256=fingerprint(),
        )
        (out / 'verified.json').write_text(json.dumps(verified, indent=2), encoding='utf-8')
        return dict(checkpoint=ckpt, **verified)

    save()
    with (root / 'console.log').open('w', encoding='utf-8', buffering=1) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                initial = panel(checkpoint, 'dev_0', 93990, 55)
                for arm, beta in (('auxiliary', 0.5), ('control', 0.0)):
                    status.update(stage='rl', arm=arm)
                    save()
                    run(
                        config,
                        checkpoint,
                        str(root / arm),
                        iterations=iterations,
                        episodes=episodes,
                        workers=workers,
                        seed=94700,
                        dev_seed=93100,
                        dev_scenarios=55,
                        dev_depth=2,
                        opponent_depth=2,
                        value_baseline=True,
                        temperature=0.5,
                        variants=catalog,
                        rule_beta=beta,
                        rule_stride=4,
                    )
                    result = json.loads((root / arm / 'result.json').read_text())
                    if result['status'] != 'complete':
                        raise ValueError('training incomplete')
                    status.update(stage='variant_selection')
                    candidates = [initial]
                    for item in result['iterations']:
                        candidates.append(panel(item['checkpoint'], f'{arm}_dev_{item["iteration"]}', 93990, 55))
                    status['arms'][arm] = dict(
                        beta=beta,
                        candidates=candidates,
                        selected=max(candidates, key=lambda x: x['score'])['checkpoint'],
                    )
                    save()
                status.update(stage='independent_development_recheck')
                status['baseline_recheck'] = panel(checkpoint, 'baseline_recheck', 94890, 110)
                for arm in ('auxiliary', 'control'):
                    chosen = status['arms'][arm]['selected']
                    status['arms'][arm]['recheck'] = panel(chosen, f'{arm}_recheck', 94890, 110)
                    compare(
                        root / 'baseline_recheck/result.json',
                        root / f'{arm}_recheck/result.json',
                        root / f'{arm}_vs_baseline.json',
                    )
                status['comparison'] = compare(
                    root / 'control_recheck/result.json', root / 'auxiliary_recheck/result.json', root / 'paired.json'
                )
                status.update(status='complete', stage='finished')
        except BaseException as error:
            traceback.print_exc(file=log)
            status.update(status='failed', error=repr(error))
            raise
        finally:
            save()
            (root / 'completion.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    print(json.dumps(status), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('catalog')
    parser.add_argument('output')
    a = parser.parse_args()
    train(a.config, a.checkpoint, a.catalog, a.output)
