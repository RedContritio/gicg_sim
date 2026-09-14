"""Fresh-source D2 imitation and paired prediction preparation on the training host."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import time

from tools.experiments.semantic_training import paired_training, train
from tools.experiments.semantic_training.consequence_export import export
from tools.runs._host import load_remote_from_cfg
from training.core.artifact_io import fingerprint


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('bootstrap must run on the configured training host')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    status = dict(status='running', stage='warmup', settings=vars(args), source_sha256=fingerprint())
    status['tool_sha256'] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))
    }

    def save(final=False):
        status['wall_s'] = time.monotonic() - tick
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / ('completion.json' if final else 'status.json'))

    save()
    try:
        train.run(
            args.config,
            str(root / 'warmup'),
            episodes=args.episodes,
            steps=args.steps,
            workers=args.workers,
            seed=args.seed,
            variants=args.catalog,
        )
        warmup = json.loads((root / 'warmup/result.json').read_text())
        if warmup['status'] != 'complete':
            raise ValueError('warmup incomplete')
        status.update(stage='paired', warmup_checkpoint=warmup['checkpoint'])
        save()
        paired_training.run(
            argparse.Namespace(
                config=args.config,
                checkpoint=warmup['checkpoint'],
                output=str(root / 'paired'),
                catalog=args.catalog,
                steps=args.paired_steps,
                contexts=6,
                workers=args.workers,
                seed=args.seed + 100,
            )
        )
        paired = json.loads((root / 'paired/completion.json').read_text())
        if paired['status'] != 'complete':
            raise ValueError('paired training incomplete')
        export(root / 'paired/paired.pt', root / 'initial', args.seed + 200)
        status.update(status='complete', stage='ready_for_residual_rl', initial=str(root / 'initial'))
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save(final=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('output')
    parser.add_argument('--episodes', type=int, default=256)
    parser.add_argument('--steps', type=int, default=2000)
    parser.add_argument('--paired-steps', type=int, default=1500)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--seed', type=int, default=95500)
    parser.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    run(parser.parse_args())
