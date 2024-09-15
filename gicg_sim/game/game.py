from typing import List

from .card import Card
from .character import Character
from .dice import DiceState
from .summon import SummonToken
from .supporter import SupporterToken

GAME_SIDE_COUNT = 2


class _GameSide:
    def __init__(self) -> None:
        self.cards_tile: List[Card] = []
        self.cards_hand: List[Card] = []
        self.characters: List[Character] = []
        self.summons: List[SummonToken] = []
        self.supporters: List[SupporterToken] = []
        self.dices: DiceState = DiceState()


class Game:
    def __init__(self) -> None:
        self.sides = [_GameSide(), _GameSide()]
        self.current_side = 0

    def get_current_side(self):
        return self.sides[self.current_side]
