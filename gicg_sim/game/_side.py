from typing import List

from ..constants.id import CharacterID
from .card import Card
from .character import Character
from .dice import DiceState
from .summon import SummonToken
from .supporter import SupporterToken


class _GameSide:
    def __init__(self) -> None:
        self.cards_tile: List[Card] = []
        self.cards_hand: List[Card] = []
        self.characters: List[Character] = []
        self.summons: List[SummonToken] = []
        self.supporters: List[SupporterToken] = []
        self.dices: DiceState = DiceState()
        self.active_character: CharacterID | None = None

    def get_active_character(self) -> Character:
        if self.active_character is None:
            raise ValueError("No active character")
        return self.characters[self.active_character]
