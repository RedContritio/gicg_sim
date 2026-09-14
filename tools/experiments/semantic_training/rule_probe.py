"""Isolated counterfactual IR diagnostic; never a native strength evaluation."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import torch

from gicg_env import GicgEnv
from tools.experiments.semantic_training.agent import SemanticAgent
from training.core.artifact_io import load_checkpoint
from training.core.network import AgentConfig
from tools.rule_validation.patches import Patch, apply
from tools.rule_validation.outcomes import choose, seek
from tools.rule_validation.policy import rank


SKILLS = ('仪典剑术', '霜袭')


class ProbeAgent(SemanticAgent):
    def observation(self, env):
        obs = super().observation(env)
        # An empty diagnostic card pool yields [] from the engine. Preserve the
        # graph's two-dimensional schema without changing the running trainer.
        for name, width in [('counter_links', 4), ('card_links', 2)]:
            obs[name] = obs[name].reshape(-1, width)
        return obs


def variant(source, destination, damages, indirect=False):
    """Copy only executable native data, leaving all training sources untouched."""
    patches = []
    for name, element, original, damage in zip(SKILLS, ('Physical', 'Ice'), (2, 3), damages):
        old = f'deal_damage(Target.EnemyActive, Element.{element}, {original})'
        expr = f'deal_damage(Target.EnemyActive, Element.{element}, {damage})'
        if indirect:
            expr = f'local probe_damage = {damage}\n  deal_damage(Target.EnemyActive, Element.{element}, probe_damage)'
        patches.append(Patch(f'pools/native_latest/characters/凯亚/凯亚_{name}.lua', old, expr))
    return apply(source, destination, patches)['data_sha256']


def case(data, seed, layout):
    # Deliberate 1v1/empty-hand diagnostic: one action has engine-proven immediate
    # victory. Its score is NOT a claim about native 3v3 or unseen full matches.
    env = GicgEnv(
        ['凯亚'],
        ['凯亚'],
        pool='native_latest',
        data_dir=str(data),
        card_pool=[],
        seed=layout,
        fix_dice=[0] * 7 + [8],
        max_rounds=10,
    )
    try:
        env.reset(seed=seed)
        return env, seek(env, [('Skill', name) for name in SKILLS])
    except BaseException:
        env.close()
        raise


def oracle(env, indices):
    return choose(env, indices, 'immediate_win')[0]


def run(checkpoint, output, data='data', seeds=4):
    torch.set_num_threads(1)
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    agent = ProbeAgent(AgentConfig(**payload['shape']))
    agent.net.load_state_dict(payload['net'])
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    report = dict(
        scope='diagnostic only: synthetic 1v1, empty hands, omnidice, no training',
        checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        training_provenance=payload['_training_provenance'],
        cases=[],
    )
    with tempfile.TemporaryDirectory(prefix='gicg-rule-probe-') as tmp:
        for label, amounts, indirect in [
            ('attack', (10, 1), False),
            ('skill', (1, 10), False),
            ('attack_indirect', (10, 1), True),
            ('skill_indirect', (1, 10), True),
        ]:
            path = Path(tmp) / label
            digest = variant(data, path, amounts, indirect)
            for seed in range(93700, 93700 + seeds):
                for layout in (7, 19):
                    env, indices = case(path, seed, layout)
                    try:
                        expected = oracle(env, indices)
                        ranking = rank(agent, env, indices)
                        scores = ranking['group_scores']
                        chosen = ranking['chosen']
                        # Both full-policy success and restricted skill ranking matter.
                        report['cases'].append(
                            dict(
                                variant=label,
                                damages=amounts,
                                data_sha256=digest,
                                seed=seed,
                                layout=layout,
                                expected=SKILLS[expected],
                                skill_scores=scores,
                                winning_skill_margin=scores[expected] - scores[1 - expected],
                                picks_immediate_win=chosen in indices[expected],
                                chosen_label=env.get_action_labels()[chosen],
                                hook_ir_sha256=hashlib.sha256(agent.observation(env)['hook_ir'].tobytes()).hexdigest(),
                            )
                        )
                    finally:
                        env.close()
    report['summary'] = {
        name: dict(
            cases=len(rows),
            wins=sum(r['picks_immediate_win'] for r in rows),
            correct_skill_ranking=sum(r['winning_skill_margin'] > 0 for r in rows),
        )
        for name in ('attack', 'skill', 'attack_indirect', 'skill_indirect')
        if (rows := [r for r in report['cases'] if r['variant'] == name])
    }
    (root / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(report['summary'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--seeds', type=int, default=4)
    args = p.parse_args()
    run(args.checkpoint, args.output, seeds=args.seeds)
