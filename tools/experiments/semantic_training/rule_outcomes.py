"""Snapshot-labelled public consequences for an auxiliary rule model, not policy targets."""

from tools.rule_validation.outcomes import measure


FIELDS = (
    'own_hp_delta',
    'enemy_hp_delta',
    'own_energy_delta',
    'enemy_energy_delta',
    'own_alive_delta',
    'enemy_alive_delta',
    'terminal',
    'terminal_result',
    'pending',
)


def target(env, action):
    """Actor-relative changes after one env.step; pending resolution is explicitly labelled."""
    side = env.acting_player
    result = measure(env, action)
    before, after = result['before']['players'], result['after']['players']
    values = []
    for field in ('hp', 'energy'):
        for player in (side, 1 - side):
            values.append(
                sum(c[field] for c in after[player]['chars']) - sum(c[field] for c in before[player]['chars'])
            )
    values.extend(after[p]['alive_count'] - before[p]['alive_count'] for p in (side, 1 - side))
    terminal_result = 0
    if result['done'] and result['winner'] in (0, 1):
        terminal_result = 1 if result['winner'] == side else -1
    values.extend((int(result['done']), terminal_result, int(result['pending'])))
    return values


def capture(env, actions):
    """Labels share the caller's pre-action observation and leave game state untouched."""
    actions = list(dict.fromkeys(actions))
    count = len(env.get_legal_actions()[0])
    if not actions or any(a < 0 or a >= count for a in actions):
        raise ValueError('nonempty legal action indices required')
    return {'fields': FIELDS, 'actions': actions, 'targets': [target(env, a) for a in actions]}
