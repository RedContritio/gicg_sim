import gicg_sim
import gicg_sim.constants


def test_game_side_count():
    game = gicg_sim.Game()
    assert gicg_sim.constants.GAME_SIDE_COUNT == len(game.sides)


def test_game_side_members():
    members = ['cards_tile', 'cards_hand', 'summons',
               'supporters', 'characters', 'dices']
    game = gicg_sim.Game()
    for side in game.sides:
        for member in members:
            assert hasattr(side, member)
