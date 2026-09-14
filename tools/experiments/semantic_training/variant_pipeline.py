"""One-shot variant BC, RL and evaluation; one terminal result, no progress polling."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import json
from pathlib import Path
import socket
import time
import traceback

from tools.runs._host import load_remote_from_cfg, ssh_run, ps_quote


def local_run(config, output, variants, episodes, steps, iterations, rl_episodes, workers):
    from tools.experiments.semantic_training.train import run as train
    from tools.experiments.semantic_training.rl import run as reinforce
    from tools.experiments.semantic_training.evaluate import evaluate
    from tools.experiments.semantic_training.verify_native_panel import verify
    from training.core.config.loader import load_cfg
    from training.core.artifact_io import fingerprint

    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'variants.toml').write_bytes(Path(variants).read_bytes())
    variants = str(root / 'variants.toml')
    status = dict(
        status='running',
        stage='bc',
        scope='development, not three-seed final acceptance',
        episodes=episodes,
        steps=steps,
        iterations=iterations,
        rl_episodes=rl_episodes,
        workers=workers,
        source_sha256=fingerprint(),
        seed=93900,
    )
    status['tool_sha256'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in ('tools/rule_validation', 'tools/experiments/semantic_training')
        for p in sorted(Path(directory).glob('*.py'))
    }
    tick = time.monotonic()

    def save():
        status['wall_s'] = time.monotonic() - tick
        temp = root / 'pipeline.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / 'pipeline.json')

    def panel(ckpt, name, depth, heldout=False):
        destination = root / name
        evaluate(
            config,
            ckpt,
            destination,
            scenarios=55,
            layouts=2,
            workers=workers,
            seed=93990 if heldout else 93100,
            opponent_depth=depth,
            variants=variants if heldout else None,
        )
        report = json.loads((destination / 'result.json').read_text())
        if not heldout:
            result = verify(
                report,
                load_cfg(config),
                seed=93100,
                depth=depth,
                scenarios=55,
                checkpoint_sha256=hashlib.sha256(Path(ckpt).read_bytes()).hexdigest(),
                source_sha256=fingerprint(),
            )
            (destination / 'verified.json').write_text(json.dumps(result, indent=2))
        return report['score']

    save()
    with (root / 'console.log').open('w', encoding='utf-8', buffering=1) as log:
        try:
            with redirect_stdout(log), redirect_stderr(log):
                train(config, str(root / 'bc'), episodes, steps, workers, seed=93900, variants=variants)
                ckpt = json.loads((root / 'bc/result.json').read_text())['checkpoint']
                status.update(stage='bc_evaluation', bc_checkpoint=ckpt)
                save()
                status['bc_d1'] = panel(ckpt, 'bc_d1', 1)
                status['bc_d2'] = panel(ckpt, 'bc_d2', 2)
                status['bc_heldout_d2'] = panel(ckpt, 'bc_heldout_d2', 2, True)
                status.update(stage='rl')
                save()
                reinforce(
                    config,
                    ckpt,
                    str(root / 'rl'),
                    iterations=iterations,
                    episodes=rl_episodes,
                    workers=workers,
                    seed=93910,
                    dev_seed=93100,
                    dev_scenarios=55,
                    dev_depth=2,
                    opponent_depth=2,
                    value_baseline=True,
                    temperature=0.5,
                    variants=variants,
                )
                rl = json.loads((root / 'rl/result.json').read_text())
                choices = [(status['bc_d2'], ckpt)] + [(r['dev_score'], r['checkpoint']) for r in rl['iterations']]
                best = max(choices, key=lambda item: item[0])[1]  # Earliest wins ties, including BC.
                status.update(stage='selected_evaluation', selected_checkpoint=best)
                save()
                status['selected_d1'] = panel(best, 'selected_d1', 1)
                status['selected_d2'] = panel(best, 'selected_d2', 2)
                status['selected_heldout_d2'] = panel(best, 'selected_heldout_d2', 2, True)
                status.update(status='complete', stage='finished')
        except BaseException as error:
            traceback.print_exc(file=log)
            status.update(status='failed', error=repr(error))
            raise
        finally:
            save()
            (root / 'completion.json').write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in status.items() if k != 'tool_sha256'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--variants', default='configs/rule_validation/native_variants.toml')
    p.add_argument('--episodes', type=int, default=512)
    p.add_argument('--steps', type=int, default=4000)
    p.add_argument('--iterations', type=int, default=4)
    p.add_argument('--rl-episodes', type=int, default=256)
    p.add_argument('--workers', type=int, default=8)
    a = p.parse_args()
    remote = load_remote_from_cfg(Path(a.config))
    if remote and socket.gethostname().lower() != remote.hostname.lower():
        args = [
            a.config,
            a.output,
            '--variants',
            a.variants,
            '--episodes',
            str(a.episodes),
            '--steps',
            str(a.steps),
            '--iterations',
            str(a.iterations),
            '--rl-episodes',
            str(a.rl_episodes),
            '--workers',
            str(a.workers),
        ]
        # This project uses the known native venv. Source sync/build is a separate preflight step.
        command = (
            f'Set-Location {ps_quote(remote.root)}; & {ps_quote(remote.root + "/venv/Scripts/python.exe")} '
            '-X utf8 -u -m tools.experiments.semantic_training.variant_pipeline ' + ' '.join(map(ps_quote, args))
        )
        result = ssh_run(remote, command, timeout=86400)
        print(result.stdout)
        if result.returncode:
            print(result.stderr)
        raise SystemExit(result.returncode)
    local_run(a.config, a.output, a.variants, a.episodes, a.steps, a.iterations, a.rl_episodes, a.workers)
