"""Reusable historical Kaeya 3v3 response probe; immediate damage is not match optimality."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.player_loader import FORMAT, load_semantic_agent
from tools.experiments.semantic_training.consequence_policy import FORMAT as CONSEQUENCE_FORMAT
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.rule_lessons import damage_oracle, trio_case
from tools.experiments.semantic_training.rule_probe import variant
from training.core.artifact_io import load_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_agent(checkpoint, readout=None, device='cpu'):
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    if payload.get('format') == CONSEQUENCE_FORMAT:
        if readout is not None:
            raise ValueError('consequence policy embeds its frozen readout; external replacement is forbidden')
        agent = load_semantic_agent(checkpoint, device=device)
        agent.rule_head = agent.net.rule_head
        return agent, dict(
            checkpoint_sha256=digest(checkpoint),
            readout_checkpoint_sha256=digest(checkpoint),
            readout_external=False,
            use_consequences=agent.net.use_consequences,
            training_provenance=payload['_training_provenance'],
        )
    if payload.get('format') != FORMAT and not (
        payload.get('format') == 'paired-consequence/1.0.0' and payload.get('parent_format') == FORMAT
    ):
        raise ValueError('incompatible policy format')
    agent = SemanticAgent(AgentConfig(**payload['shape']), device)
    agent.net.load_state_dict(payload['net'], strict=True)
    source = checkpoint
    head = payload.get('rule_head')
    if head is None:
        if readout is None:
            raise ValueError('policy has no rule head; provide an explicit frozen readout checkpoint')
        other = load_checkpoint(readout, map_location='cpu', weights_only=False)
        if other['shape'] != payload['shape']:
            raise ValueError('readout shape differs')
        head, source = other['rule_head'], readout
    attach(agent).load_state_dict(head, strict=True)
    agent.rule_head.eval()
    return agent, dict(
        checkpoint_sha256=digest(checkpoint),
        readout_checkpoint_sha256=digest(source),
        readout_external=str(source) != str(checkpoint),
        training_provenance=payload['_training_provenance'],
    )


def collect(agent, cfg, seeds=(94510, 94511), layouts=(7, 19)):
    rows, previous = [], {}
    with tempfile.TemporaryDirectory(prefix='gicg-transfer-') as temp:
        for damages in ((2, 6), (6, 2), (4, 8), (8, 4)):
            data = Path(temp) / '_'.join(map(str, damages))
            data_hash = variant(cfg.scenario.data_dir, data, damages)
            for seed in seeds:
                for layout in layouts:
                    env, groups = trio_case(cfg, data, seed, layout)
                    try:
                        before = env.export_view()
                        expected, observed = damage_oracle(env, groups)
                        if env.export_view() != before:
                            raise AssertionError('oracle changed probe state')
                        agent.game_start(env.static_obs)
                        obs = agent.observation(env)
                        key = (min(damages), seed, layout)
                        if key in previous:
                            old = previous.pop(key)
                            if old.keys() != obs.keys():
                                raise AssertionError('counterfactual schema mismatch')
                            for name in obs.keys() - {'hook_ir'}:
                                if not np.array_equal(old[name], obs[name]):
                                    raise AssertionError(f'counterfactual changed {name}')
                            if np.array_equal(old['hook_ir'], obs['hook_ir']):
                                raise AssertionError('damage swap invisible in rule IR')
                        else:
                            previous[key] = obs
                        batch = batch_observations([obs], agent.cfg, agent.device)
                        with torch.no_grad():
                            logits, state, actions = agent.net(batch, return_actions=True)
                            predictions = agent.rule_head(state, actions)
                        count = len(env.get_action_labels())
                        scores = [float(logits[0, group].max()) for group in groups]
                        estimated = [float(-predictions[0, group[0], 1] * 10) for group in groups]
                        if not np.isfinite(scores + estimated).all():
                            raise ValueError('nonfinite probe prediction')
                        # Match deployed deterministic policy's tie rounding.
                        chosen = int((logits[0, :count] * 1e5).round().argmax())
                        rows.append(
                            dict(
                                damages=damages,
                                seed=seed,
                                layout=layout,
                                expected=expected,
                                observed=observed,
                                predicted=estimated,
                                scores=scores,
                                prediction_correct=estimated[expected] > estimated[1 - expected],
                                policy_correct=scores[expected] > scores[1 - expected],
                                chooses_damage_leader=chosen in groups[expected],
                                chosen_label=env.get_action_labels()[chosen],
                                data_sha256=data_hash,
                            )
                        )
                    finally:
                        env.close()
    if previous:
        raise AssertionError('unpaired probe cases')
    return dict(
        cases=rows,
        **{
            name: sum(r[name] for r in rows)
            for name in ('prediction_correct', 'policy_correct', 'chooses_damage_leader')
        },
    )


def run(config, checkpoint, output, readout=None, device='cpu'):
    torch.set_num_threads(1)
    agent, provenance = load_agent(checkpoint, readout, device)
    result = dict(
        protocol='kaeya-transfer/1.0.0',
        scope='diagnostic 3v3, natural initial energy, omnidice; damage ranking is not full-game optimality',
        config_sha256=digest(config),
        **provenance,
        **collect(agent, load_cfg(config)),
    )
    with Path(output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print({name: result[name] for name in ('prediction_correct', 'policy_correct', 'chooses_damage_leader')})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--readout', help='explicit frozen readout for a policy without a trained rule head')
    parser.add_argument('--device', default='cpu', choices=('cpu', 'cuda'))
    args = parser.parse_args()
    run(args.config, args.checkpoint, args.output, args.readout, args.device)
