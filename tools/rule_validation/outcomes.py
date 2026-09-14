"""Snapshot-backed measurements; labels describe observed effects, not strategy."""


def measure(env, action):
    before = env.export_view()
    snap = env.snapshot()
    try:
        env.step(action)
        after = env.export_view()
        loss = [
            sum(c['hp'] for c in a['chars']) - sum(c['hp'] for c in b['chars'])
            for a, b in zip(before['players'], after['players'])
        ]
        return dict(
            before=before, after=after, hp_loss=loss, done=env.done, winner=env.winner, pending=bool(env.has_pending)
        )
    finally:
        env.restore(snap)
        env.snapshot_free(snap)


def choose(env, groups, metric):
    side = env.acting_player
    scores = []
    for group in groups:
        if not group:
            raise ValueError('empty action group')
        values = []
        for action in group:
            result = measure(env, action)
            if metric == 'immediate_win':
                value = int(result['done'] and result['winner'] == side)
            elif metric == 'enemy_hp_loss':
                value = result['hp_loss'][1 - side]
            else:
                raise ValueError(f'unknown metric: {metric}')
            values.append(value)
        if len(set(values)) != 1:
            raise ValueError('action alternatives disagree on oracle metric')
        scores.append(values[0])
    if scores.count(max(scores)) != 1:
        raise ValueError('oracle has no unique preferred group')
    return scores.index(max(scores)), scores


def seek(env, selectors, player=None, budget=32):
    for _ in range(budget):
        labels = env.get_action_labels()
        groups = [
            [i for i, label in enumerate(labels) if tuple(label[: len(selector)]) == tuple(selector)]
            for selector in selectors
        ]
        if all(groups) and (player is None or env.acting_player == player):
            return groups
        if env.done:
            break
        end = [i for i, (kind, _, _) in enumerate(labels) if kind == 'EndTurn']
        env.step(end[0] if end else 0)
    raise ValueError('case did not reach requested decision within preparation budget')


def check(result, expected):
    for path, wanted in expected.items():
        actual = result
        for key in path.split('.'):
            actual = actual[int(key)] if isinstance(actual, list) else actual[key]
        if actual != wanted:
            raise AssertionError(f'{path}: got {actual!r}, expected {wanted!r}')
