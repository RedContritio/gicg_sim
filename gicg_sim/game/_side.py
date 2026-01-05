from typing import List, Optional

from ..constants.element import DiceElement, element2dice
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
        self.backup_characters: List[List[Character]] = []
        self.summons: List[SummonToken] = []
        self.supporters: List[SupporterToken] = []
        self.dices: DiceState = DiceState()
        self.active_character_id: CharacterID | None = None
        self.has_ended_round: bool = False

    def _add_character(self, character: Character):
        self.characters.append(character)

        if self.active_character_id is None:
            self.active_character_id = character.id

    def get_active_character(self) -> Character:
        if self.active_character_id is None:
            raise ValueError("No active character")
        for character in self.characters:
            if character.id == self.active_character_id:
                return character
        raise ValueError("No active character")

    @property
    def active_character(self) -> Character:
        return self.get_active_character()

    def _set_dice(self, dices: DiceState):
        self.dices = dices

    def draw_cards(self, count: int) -> List[Card]:
        """从牌堆抽牌到手牌"""
        drawn: List[Card] = []
        for _ in range(count):
            if self.cards_tile:
                card = self.cards_tile.pop(0)
                self.cards_hand.append(card)
                drawn.append(card)
        return drawn

    def discard_card(self, card: Optional[Card] = None) -> Optional[Card]:
        """弃掉一张手牌，如果不指定则弃掉第一张"""
        if not self.cards_hand:
            return None
        if card is None:
            return self.cards_hand.pop(0)
        if card in self.cards_hand:
            self.cards_hand.remove(card)
            return card
        return None

    def elemental_tuning(self) -> bool:
        """元素调和: 弃一张牌，将一个骰子转为当前角色元素"""
        if not self.cards_hand:
            return False
        if self.dices.total() == 0:
            return False

        # 弃掉一张牌
        self.discard_card()

        # 获取当前角色元素对应的骰子元素
        character = self.get_active_character()
        target_dice = element2dice(character.element)

        # 添加一个对应元素的骰子
        self.dices.add(target_dice, 1)

        return True

    def is_all_defeated(self) -> bool:
        """检查是否所有角色都被击败"""
        return all(c.is_defeated() for c in self.characters)

    def end_round(self):
        """宣布结束回合"""
        self.has_ended_round = True

    def reset_round_state(self):
        """重置回合状态"""
        self.has_ended_round = False
