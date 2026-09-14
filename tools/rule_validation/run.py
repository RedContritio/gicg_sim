"""Run a TOML rule-patch case with checked engine outcomes."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib

from gicg_env import GicgEnv
from tools.rule_validation.patches import Patch, apply
from tools.rule_validation.outcomes import check, measure, seek


def run(config, output, checkpoint=None):
    path = Path(config)
    spec = tomllib.loads(path.read_text(encoding='utf-8'))
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    report = dict(
        case=spec['name'],
        status='running',
        scope='engine rule verification, not model strength',
        config_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        outcomes=[],
    )
    try:
        with tempfile.TemporaryDirectory(prefix='gicg-rule-case-') as temp:
            pool = spec.get('pool', 'native_latest')
            report['patch'] = apply(spec.get('data', 'data'), temp, [Patch(**p) for p in spec.get('patches', [])], pool)
            scene = spec['scene']
            with GicgEnv(
                scene['team_0'],
                scene['team_1'],
                pool=pool,
                data_dir=temp,
                card_pool=scene.get('card_pool', []),
                fix_dice=scene.get('fix_dice'),
                seed=scene.get('layout', 7),
                max_rounds=10,
            ) as env:
                env.reset(seed=scene.get('seed', 93700))
                groups = seek(env, spec['actions'], player=scene.get('player'), budget=scene.get('prepare_budget', 32))
                if checkpoint:
                    import torch
                    from training.core.artifact_io import load_checkpoint
                    from training.core.network import AgentConfig
                    from tools.experiments.semantic_training.agent import SemanticAgent
                    from tools.rule_validation.policy import rank

                    torch.set_num_threads(1)
                    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
                    agent = SemanticAgent(AgentConfig(**payload['shape']))
                    agent.net.load_state_dict(payload['net'])
                    report['model'] = dict(
                        checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
                        **rank(agent, env, groups),
                    )
                for group in groups:
                    for action in group:
                        outcome = measure(env, action)
                        report['outcomes'].append(dict(action=env.get_action_labels()[action], **outcome))
                        check(outcome, spec['expected'])
            report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', error=repr(error))
        raise
    finally:
        (root / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--checkpoint')
    a = p.parse_args()
    result = run(a.config, a.output, a.checkpoint)
    print(result['case'], result['status'])
