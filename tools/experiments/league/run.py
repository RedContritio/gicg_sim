"""Registered DMC run with a frozen league plan and exact pool-state resume."""

import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import torch
from tools.runs import train
from tools.experiments.league.pool import LeaguePool
from training.core.artifact_io import fingerprint, load_checkpoint
from training.paradigms.dmc.paradigm import DMCParadigm
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._opponent import RandomPlayer, GreedyPlayer
from training.core.network import AgentConfig


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def run(plan_path, role, resume=None, budget=None):
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text())
    assert fingerprint() == plan['source'], 'training source mismatch'
    for filename, expected in plan.get('tool_sha256', {}).items():
        if digest(filename) != expected:
            raise ValueError(f'league tool changed: {filename}')
    spec = plan['roles'][role]
    identity = digest(plan_path)
    original_network = DMCParadigm.make_network
    phase_c = train._phase_c_run_train_and_close
    output = Path(plan['output'])
    output.mkdir(parents=True, exist_ok=True)
    record_path = output / f'{role}.json'
    if not resume and record_path.exists():
        raise ValueError('existing role run: resume explicitly')
    record = {
        'role': role,
        'plan_sha256': identity,
        'status': 'validating',
        'warm_start': spec['initial'],
        'fresh_optimizer_and_buffer': not bool(resume),
    }
    states = {}
    for member in plan['members']:
        if digest(member['checkpoint']) != member['sha256']:
            raise ValueError(f'checkpoint changed: {member["id"]}')
        blob = load_checkpoint(member['checkpoint'], map_location='cpu', weights_only=False)
        states[member['id']] = {k.removeprefix('net.'): v for k, v in blob['net'].items()}
        del blob

    def network(paradigm, cfg):
        fresh = paradigm._network is None
        net = original_network(paradigm, cfg)
        if fresh and not resume and spec['initial'] is not None:
            net._agent.net.load_state_dict(states[spec['initial']])
        return net

    def pool(paradigm, cfg, net):
        pcfg = paradigm._resolve_pcfg(cfg)
        shape = AgentConfig.from_obs_shape(pcfg.agent)
        builders = {}
        for entry in spec['opponents']:
            name = entry['id']
            if name == 'random':
                builders[name] = RandomPlayer
            elif name == 'F1-D2':
                builders[name] = lambda seed: GreedyPlayer(features='F1', depth=2, dice_greedy=True, seed=seed)
            else:
                opponent = DmcAgent(shape, device=cfg.meta.device, epsilon=0)
                opponent.net.load_state_dict(states[name])
                opponent.net.eval()

                def build(seed, agent=opponent):
                    agent.rng.seed(seed)
                    return agent

                builders[name] = build
        return LeaguePool(spec['opponents'], builders, cfg.meta.seed + 1, identity + ':' + role)

    def save():
        temporary = record_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2))
        temporary.replace(record_path)

    def execute(state):
        record.update(status='training', run=str(state.artifacts_dir))
        save()
        (state.artifacts_dir / 'league_plan.json').write_text(json.dumps(plan, indent=2))
        return phase_c(state)

    torch.set_num_threads(1)
    args = [
        plan['config'],
        '--override',
        f'meta.seed={spec["seed"]}',
        '--override',
        f'meta.device={plan["device"]}',
        '--override',
        f'meta.run_label=league_{role}',
        '--override',
        f'paradigm.dmc.total_frames={budget or plan["budget"]}',
        '--override',
        f'paradigm.dmc.epsilon={spec["epsilon"]}',
    ]
    if resume:
        args += ['--resume', str(resume)]
    try:
        with (
            patch.object(DMCParadigm, 'make_network', network),
            patch.object(DMCParadigm, 'make_opponent_pool', pool),
            patch.object(train, '_phase_c_run_train_and_close', execute),
        ):
            result = train.main(args)
        if result:
            raise RuntimeError(f'training exit {result}')
        checkpoint = Path(record['run']) / 'ckpts/latest.pt'
        record.update(status='complete', checkpoint=str(checkpoint), sha256=digest(checkpoint))
        save()
    except BaseException as error:
        record.update(status='failed', error=repr(error))
        save()
        raise
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('plan')
    parser.add_argument('role')
    parser.add_argument('--resume')
    parser.add_argument('--budget', type=int)
    args = parser.parse_args()
    run(args.plan, args.role, args.resume, args.budget)
