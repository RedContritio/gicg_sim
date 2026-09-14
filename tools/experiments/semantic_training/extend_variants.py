"""Resume the variant run, then select and recheck on variant development panels."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import json
from pathlib import Path
import time
import traceback

from tools.experiments.semantic_training.rl import run
from tools.experiments.semantic_training.evaluate import evaluate
from tools.rule_validation.verify_panel import verify_variants
from training.core.config.loader import load_cfg
from training.core.artifact_io import fingerprint


def extend(config, previous, output, iterations=12, workers=8):
    previous, root = Path(previous), Path(output)
    old = json.loads((previous / 'rl/result.json').read_text())
    if old['status'] != 'complete':
        raise ValueError('previous training has not completed')
    settings = old['settings']
    root.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    status = dict(
        status='running',
        stage='rl',
        previous=str(previous),
        iterations=iterations,
        selection_seed=93990,
        recheck_seed=94090,
        scope='development only',
        panels=[],
    )

    def save():
        status['wall_s'] = time.monotonic() - tick
        tmp = root / 'completion.tmp'
        tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(root / 'status.json')

    def panel(ckpt, name, seed, scenarios):
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
            variants=settings['variants'],
        )
        report = json.loads((out / 'result.json').read_text())
        result = verify_variants(
            report,
            load_cfg(config),
            settings['variants'],
            seed=seed,
            scenarios=scenarios,
            checkpoint_sha256=hashlib.sha256(Path(ckpt).read_bytes()).hexdigest(),
            source_sha256=fingerprint(),
        )
        (out / 'verified.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return dict(checkpoint=ckpt, **result)

    save()
    with (root / 'console.log').open('w', encoding='utf-8', buffering=1) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                run(
                    config,
                    old['anchor'],
                    str(root / 'rl'),
                    iterations=iterations,
                    episodes=settings['episodes'],
                    workers=workers,
                    resume=old['checkpoint'],
                    seed=settings['master_seed'],
                    dev_seed=settings['dev_seed'],
                    dev_scenarios=settings['dev_scenarios'],
                    batch_size=settings['batch_size'],
                    dev_depth=settings['dev_depth'],
                    opponent_depth=settings['opponent_depth'],
                    value_baseline=settings['value_baseline'],
                    temperature=settings['temperature'],
                    variants=settings['variants'],
                )
                new = json.loads((root / 'rl/result.json').read_text())
                candidates = [old['checkpoint']] + [r['checkpoint'] for r in new['iterations']]
                status.update(stage='variant_selection')
                save()
                for index, ckpt in enumerate(candidates):
                    status['panels'].append(panel(ckpt, f'variant_{index}', 93990, 55))
                    save()
                best = max(status['panels'], key=lambda p: p['score'])
                status.update(stage='independent_development_recheck', selected=best['checkpoint'])
                save()
                status['baseline_recheck'] = panel(candidates[0], 'baseline_recheck', 94090, 110)
                status['selected_recheck'] = panel(best['checkpoint'], 'selected_recheck', 94090, 110)
                status.update(status='complete', stage='finished')
        except BaseException as error:
            traceback.print_exc(file=log)
            status.update(status='failed', error=repr(error))
            raise
        finally:
            save()
            (root / 'completion.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('previous')
    p.add_argument('output')
    p.add_argument('--iterations', type=int, default=12)
    p.add_argument('--workers', type=int, default=8)
    a = p.parse_args()
    extend(a.config, a.previous, a.output, a.iterations, a.workers)
