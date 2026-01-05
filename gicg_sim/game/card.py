from typing import Optional

from .cost import Cost


class Card:
    """Card (Drawable) class for the game.
    """

    def __init__(self, name: str, cost: Optional[Cost] = None):
        self.name = name
        self.cost = cost


class DummyCard(Card):
    """无效牌，用于测试
    """

    def __init__(self):
        super().__init__("DummyCard", None)
