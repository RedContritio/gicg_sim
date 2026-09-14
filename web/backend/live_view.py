"""Player-facing live view with public zone data and hidden opponent resources."""


def live_view(env, human_player):
    if human_player not in (0, 1):
        raise ValueError('invalid human player')
    view = env.export_view()
    view['acting_player'] = env.acting_player
    for pi, player in enumerate(view['players']):
        hand = player.get('hand') or []
        player['hand_count'] = len(hand)
        dice = env.dice_counts(pi).tolist()
        player['dice_count'] = sum(dice)
        if pi == human_player:
            player['dice'] = dice
        else:
            player.pop('dice', None)
            player['hand'] = [{'ref': -1, 'name': '暗牌'} for _ in hand]
    return view
