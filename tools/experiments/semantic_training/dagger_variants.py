"""One-shot variant DAgger with aggregated learner states and frozen recheck."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import json
from pathlib import Path
import time
import traceback

from tools.experiments.semantic_training.train import run
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.compare import compare
from tools.rule_validation.verify_panel import verify_variants
from training.core.config.loader import load_cfg
from training.core.artifact_io import fingerprint


def train(
    config,
    checkpoint,
    catalog,
    output,
    rounds=3,
    episodes=256,
    steps=1000,
    workers=8,
    learning_rate=0.0003,
    tie_objective='uniform',
    anchor_beta=0.0,
    recheck_seed=94290,
    seed_base=94120,
):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    initial, replay = checkpoint, []
    selection_seed = seed_base - 130
    status = dict(
        status='running',
        stage='initial_evaluation',
        algorithm='D2 DAgger, not RL',
        rounds=rounds,
        episodes=episodes,
        steps=steps,
        workers=workers,
        training_seeds=list(range(seed_base + 1, seed_base + 1 + rounds)),
        selection_seed=selection_seed,
        recheck_seed=recheck_seed,
        learning_rate=learning_rate,
        tie_objective=tie_objective,
        anchor_beta=anchor_beta,
        source_sha256=fingerprint(),
        candidates=[],
    )

    status['tool_sha256'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in ('tools/rule_validation', 'tools/experiments/semantic_training')
        for p in sorted(Path(directory).glob('*.py'))
    }

    def save():
        status['wall_s'] = time.monotonic() - tick
        tmp = root / 'status.tmp'
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
                status['candidates'].append(panel(checkpoint, 'dev_0', selection_seed, 55))
                for index in range(1, rounds + 1):
                    status.update(stage='dagger', round=index)
                    save()
                    out = root / f'round_{index}'
                    run(
                        config,
                        str(out),
                        episodes,
                        steps,
                        workers,
                        seed=seed_base + index,
                        initial=checkpoint,
                        variants=catalog,
                        learner=checkpoint,
                        replay_dirs=replay,
                        learning_rate=learning_rate,
                        tie_objective=tie_objective,
                        anchor_beta=anchor_beta,
                    )
                    result = json.loads((out / 'result.json').read_text())
                    checkpoint = result['checkpoint']
                    replay.append(str(Path(result['run']) / 'teacher'))
                    status['candidates'].append(panel(checkpoint, f'dev_{index}', selection_seed, 55))
                    save()
                chosen = max(status['candidates'], key=lambda x: x['score'])['checkpoint']
                status.update(stage='independent_development_recheck', selected=chosen)
                save()
                status['baseline_recheck'] = panel(initial, 'baseline_recheck', recheck_seed, 110)
                status['selected_recheck'] = panel(chosen, 'selected_recheck', recheck_seed, 110)
                status['paired'] = compare(
                    root / 'baseline_recheck/result.json', root / 'selected_recheck/result.json', root / 'paired.json'
                )
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
    p.add_argument('checkpoint')
    p.add_argument('catalog')
    p.add_argument('output')
    p.add_argument('--rounds', type=int, default=3)
    p.add_argument('--episodes', type=int, default=256)
    p.add_argument('--steps', type=int, default=1000)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--seed-base', type=int, default=94120)
    p.add_argument('--recheck-seed', type=int, default=94290)
    p.add_argument('--tie-objective', choices=('uniform', 'set', 'executed'), default='uniform')
    a = p.parse_args()
    train(
        a.config,
        a.checkpoint,
        a.catalog,
        a.output,
        a.rounds,
        a.episodes,
        a.steps,
        a.workers,
        tie_objective=a.tie_objective,
        recheck_seed=a.recheck_seed,
        seed_base=a.seed_base,
    )
