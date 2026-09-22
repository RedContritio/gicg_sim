"""Extract compatible RL16 tensors into an AZ warm-start checkpoint.

This is a lossy parameter transplant, not a behavior-preserving conversion.
SemanticQNet's relation layers and semantic forward path are not represented by
the generic AZ network. Use the output only for controlled historical studies.

Mapping (verified shape-exact 09-19):
- 'base.X' -> 'X'                      : 149 shared trunk/encoder keys
- 'base.heads.q.state_proj.*' ->
  'heads.policy.state_proj.*'          : RL16's Q head becomes AZ policy head
- 'heads.value.head.*'                 : fresh init (RL16 value MLP is
                                         32->32->1, AZ needs 224->64->1;
                                         ExIt retrains value from z anyway)
- 'heads.delta.head.*'                 : fresh init (delta aux head)

Usage: .venv/bin/python -m tools.ckpt.convert_rl16_to_az <rl16.pt> <out.pt>
"""

import sys


def convert(src_path: str, out_path: str) -> None:
    import os

    from training.core.artifact_io import load_checkpoint, save_checkpoint
    from training.core.network import make_actor_critic
    from training.core.network import AgentConfig
    from training.paradigms.az.network import AZ_HEAD_KINDS

    previous_skip = os.environ.get('GICG_SKIP_PROVENANCE')
    os.environ['GICG_SKIP_PROVENANCE'] = '1'
    try:
        src = load_checkpoint(src_path, map_location='cpu', weights_only=False)
    finally:
        if previous_skip is None:
            os.environ.pop('GICG_SKIP_PROVENANCE', None)
        else:
            os.environ['GICG_SKIP_PROVENANCE'] = previous_skip
    rl_net = src['net']

    cfg = AgentConfig(
        n_counter_slots=1832,
        n_hooks=900,
        max_ops_per_hook=128,
        max_actions=2048,
        d_model=32,
        n_cross_layers=1,
        dropout=0.0,
    )
    net = make_actor_critic(cfg, head_kinds=AZ_HEAD_KINDS, use_typed_damage=True)
    az_sd = net.state_dict()

    out = {}
    n_shared = n_policy = n_fresh = 0
    for k in az_sd:
        rk = 'base.' + k
        if rk in rl_net and rl_net[rk].shape == az_sd[k].shape:
            out[k] = rl_net[rk].clone()
            n_shared += 1
        elif k.startswith('heads.policy.'):
            qk = rk.replace('heads.policy.', 'heads.q.')
            if qk in rl_net and rl_net[qk].shape == az_sd[k].shape:
                out[k] = rl_net[qk].clone()
                n_policy += 1
                continue
            out[k] = az_sd[k].clone()
            n_fresh += 1
        else:
            out[k] = az_sd[k].clone()
            n_fresh += 1
    print(f'shared={n_shared} policy_from_q={n_policy} kept_fresh_init={n_fresh}')
    print('warning: semantic RL and AZ forward paths are not behaviorally equivalent')

    blob = {
        'net_state_dict': out,
        'cfg': {
            'n_counter_slots': cfg.n_counter_slots,
            'n_hooks': cfg.n_hooks,
            'max_ops_per_hook': cfg.max_ops_per_hook,
            'max_actions': cfg.max_actions,
            'fields_per_op': 5,
            'd_model': cfg.d_model,
            'dropout': cfg.dropout,
            'n_cross_layers': cfg.n_cross_layers,
        },
        'cfg_run_label': 'rl16_warmstart',
        'behaviorally_equivalent_to_source': False,
        'conversion_kind': 'lossy_parameter_transplant',
    }
    save_checkpoint(blob, out_path)
    print(f'-> {out_path}')


if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2])
